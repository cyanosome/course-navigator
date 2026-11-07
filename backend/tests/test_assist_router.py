"""AI の口（POST /assist/ask）のテスト。実 LLM・実 DB を使わず CI で回る。

- LLM は台本どおりに function_call を返す偽モデルの LlmAgent を route_options.build_agent に差し込み、
  runner.run_grounded（ADK の Workflow・ツール実行・出典の照合）は本物を通す（test_mcp_grounded.py と同じやり方）。
- PostgreSQL は架空の courses の行（tests/catalog_rows.py）を返す偽プール、研究のログは記録する偽の口
  （dependency_overrides）。
"""

import asyncio
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

import diagnose_fixtures
from agent import courses_tools, deps, grounding, plan_candidates, route_options, runner
from agent.route_options import AssistOptions
from agent.schemas import PlanAnswerPayload, PlanChange
from api.routers import assist as assist_router
from catalog_rows import course_row
from fake_toolset import RecordingToolset
from course_core import config
from course_core.research.sink import SessionVariant, get_research_sink
from course_core.research.variants import VARIANTS

_KNOWN_CODE = "900001"  # 架空の courses にある
_UNKNOWN_CODE = "999999"  # courses に無い（照合で外れる役）
_PLAN_CODE = "900002"  # 今のプランにある（courses にもある）
_EXTRA_CODE = "900003"  # courses にあり、今のプランに無い（足す役）
_QUESTION = "架空の質問: 反応工学の次に取れる科目は?"
_EVENT_ID = "6f1c2b9e-0000-4000-8000-000000000001"
_ROWS = [
    course_row(),
    course_row(syllabus_id=_PLAN_CODE, subject_name="架空の月曜の科目", term_schedule="月2"),
    course_row(syllabus_id=_EXTRA_CODE, subject_name="架空の水曜の科目", term_schedule="水2"),
]
_PLAN = {
    "answers_summary": "架空の診断のまとめ",
    "terms": [{"year": 2, "term": "春", "syllabus_ids": [_PLAN_CODE, _UNKNOWN_CODE]}],
}


# --- 代役 -------------------------------------------------------------------------------


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetch(self, query: str, syllabus_ids: list[str]) -> list[dict[str, Any]]:
        return [row for row in self._rows if row["syllabus_id"] in syllabus_ids]


class _FakePool:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.connection = _FakeConnection(rows)

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[_FakeConnection, None]:
        yield self.connection


def _user_text(llm_request: LlmRequest) -> str:
    return "".join(
        part.text or ""
        for content in llm_request.contents
        if content.role == "user"
        for part in (content.parts or [])
    )


class _ScriptedLlm(BaseLlm):
    """1ターン目は get_course_details、2ターン目は set_model_response を呼ぶ偽モデル。

    入力に今のプランがあれば、足す・外すの提案も出す（照合で残るもの・外れるものを混ぜる）。
    受け取った利用者の文は received に残す。
    """

    model: str = "scripted-fake-llm"
    received: list[str] = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        answered = {
            part.function_response.name
            for content in llm_request.contents
            for part in (content.parts or [])
            if part.function_response
        }
        text = _user_text(llm_request)
        self.received.append(text)
        if "get_course_details" not in answered:
            call = types.FunctionCall(
                name="get_course_details", args={"syllabus_ids": [_KNOWN_CODE, _UNKNOWN_CODE]}
            )
        else:
            args: dict[str, Any] = {
                "answer": f"架空の反応工学１ [{_KNOWN_CODE}] です。",
                "cited_codes": [_KNOWN_CODE, _UNKNOWN_CODE],
            }
            if "## 今のプラン" in text:
                args["add"] = [
                    {"syllabus_id": _EXTRA_CODE, "reason": "水曜"},
                    {"syllabus_id": _UNKNOWN_CODE, "reason": "架空"},
                    {"syllabus_id": _PLAN_CODE, "reason": "もうある"},
                ]
                args["remove"] = [
                    {"syllabus_id": _PLAN_CODE, "reason": "月曜"},
                    {"syllabus_id": _KNOWN_CODE, "reason": "プランに無い"},
                ]
            call = types.FunctionCall(name="set_model_response", args=args)
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))


class _FailingLlm(BaseLlm):
    model: str = "failing-fake-llm"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        raise RuntimeError("架空の LLM の障害")
        yield  # 非同期ジェネレータにするための到達しない yield


def _agent(llm: BaseLlm, extra_tools: list[Any] | None = None) -> LlmAgent:
    return LlmAgent(
        name="mcp_agent",
        model=llm,
        instruction="テスト用",
        tools=[*(extra_tools or []), courses_tools.get_course_details],
        output_schema=PlanAnswerPayload,
    )


class FakeSink:
    """研究のログの口の代役。セッション → 今のブロックの変種と、書いたイベントを持つ。"""

    def __init__(self) -> None:
        self.sessions: dict[str, SessionVariant] = {}
        self.events: list[tuple[str, str, Mapping[str, Any]]] = []

    def add(self, session_id: str, variant_id: str | None, block: int | None = 1) -> None:
        self.sessions[session_id] = SessionVariant(
            session_id=session_id,
            block=block,
            condition_id="M" if variant_id else None,
            variant_id=variant_id,
            flags=VARIANTS[variant_id] if variant_id else None,
        )

    async def current_variant(self, session_id: str) -> SessionVariant | None:
        return self.sessions.get(session_id)

    async def append_server_event(self, session_id, event_type, payload) -> None:
        self.events.append((session_id, event_type, dict(payload)))


@pytest.fixture
def scripted_llm() -> _ScriptedLlm:
    return _ScriptedLlm(received=[])


@pytest.fixture
def built_options(monkeypatch, scripted_llm) -> list[AssistOptions]:
    """build_agent を偽モデルの LlmAgent に差し替え、渡された options を記録する。"""
    received: list[AssistOptions] = []

    def _build(options: AssistOptions) -> LlmAgent:
        received.append(options)
        return _agent(scripted_llm)

    monkeypatch.setattr(route_options, "build_agent", _build)
    monkeypatch.setattr(config, "AGENT_ENABLE_MCP", True)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key-for-routing")
    deps.set_backends(_FakePool(_ROWS), None)
    yield received
    deps.set_backends(None, None)


@pytest.fixture
def sink() -> FakeSink:
    return FakeSink()


@pytest.fixture
def client(sink, monkeypatch) -> TestClient:
    monkeypatch.delenv("RESEARCH_DEV", raising=False)
    monkeypatch.delenv("NAVI_DEFAULT_VARIANT", raising=False)
    app = FastAPI()
    app.include_router(assist_router.router)
    app.dependency_overrides[get_research_sink] = lambda: sink
    return TestClient(app, raise_server_exceptions=False)


def _ask(client: TestClient, session: str | None = None, **body: Any):
    headers = {"X-Navi-Session": session} if session else {}
    return client.post("/assist/ask", json={"question": _QUESTION, **body}, headers=headers)


# --- 因子の決め方 -------------------------------------------------------------------------


def test_study_session_uses_block_flags_and_ignores_options(client, sink, built_options):
    sink.add("sess-1", "V00")
    response = _ask(
        client,
        session="sess-1",
        options={"route": "mcp_grounded", "style": "brief", "verify": "off", "citations": "text"},
        client_event_id=_EVENT_ID,
    )
    assert response.status_code == 200
    assert response.headers["X-Navi-Contract"] == "navi-v1"
    body = response.json()
    assert body["options_ignored"] is True
    assert body["options_applied"] == {"route": "mcp_grounded", "style": "standard", "verify": "on", "citations": "cards"}
    assert body["variant_id"] == "V00"
    assert body["route"] == "mcp"
    assert body["route_requested"] == "mcp_grounded"
    assert [s["code"] for s in body["sources"]] == [_KNOWN_CODE]
    source = body["sources"][0]
    assert source["origin"] == "postgres:courses"
    assert source["url"] == "https://example.invalid/900001"
    assert source["credits"] == 2.0
    assert body["unverified_codes"] == [_UNKNOWN_CODE]
    assert body["unverified_items"] == []  # verify=on のときは埋めない
    assert body["plan_suggestions"] is None  # plan_context が無い
    assert built_options == [AssistOptions()]

    assert len(sink.events) == 1
    session_id, event_type, payload = sink.events[0]
    assert (session_id, event_type) == ("sess-1", "chat_response")
    assert payload["request_id"] == body["request_id"]
    assert payload["client_event_id"] == _EVENT_ID
    assert payload["route_requested"] == "mcp_grounded"
    assert payload["route_actual"] == "mcp"
    assert payload["options_ignored"] is True
    assert payload["model"] == "scripted-fake-llm"
    assert len(payload["prompt_sha256"]) == 64
    assert payload["cited_codes"] == [_KNOWN_CODE, _UNKNOWN_CODE]
    assert payload["source_codes"] == [_KNOWN_CODE]
    assert payload["unverified_codes"] == [_UNKNOWN_CODE]
    assert [call["name"] for call in payload["tool_calls"]] == ["get_course_details", "set_model_response"]
    assert "result_summary" not in payload["tool_calls"][0]
    assert payload["plan_context_sha256"] is None
    assert payload["plan_suggestions"] is None
    assert payload["plan_delivery"] is None  # plan_context の無い問い
    assert payload["toolset"] == "per_request"  # lifespan の McpToolset が無い
    assert payload["error"] is None
    assert payload["latency_ms"] >= 0


def test_cookie_session_is_used_too(client, sink, built_options):
    sink.add("sess-cookie", "V00")
    client.cookies.set("navi_sid", "sess-cookie")
    assert _ask(client).status_code == 200
    assert [event[0] for event in sink.events] == ["sess-cookie"]


def test_no_session_production_uses_default_variant(client, sink, built_options, monkeypatch):
    monkeypatch.setenv("NAVI_DEFAULT_VARIANT", "V00")
    response = _ask(client, options={"style": "detailed"})
    assert response.status_code == 200
    body = response.json()
    assert body["variant_id"] == "V00"
    assert body["options_ignored"] is True
    assert body["options_applied"]["style"] == "standard"
    assert sink.events == []  # セッションが無ければ記録しない


def test_no_session_default_variant_without_ai_is_409(client, sink, built_options):
    """既定の変種 V01（AI なし）のままなら、AI の口は断る。"""
    response = _ask(client)
    assert response.status_code == 409
    assert built_options == []
    assert sink.events == []


def test_research_dev_applies_options(client, sink, built_options, monkeypatch):
    monkeypatch.setenv("RESEARCH_DEV", "true")
    response = _ask(client, options={"route": "mcp_grounded", "style": "brief", "verify": "off", "citations": "text"})
    assert response.status_code == 200
    body = response.json()
    assert body["options_ignored"] is False
    assert body["variant_id"] is None
    assert body["options_applied"] == {"route": "mcp_grounded", "style": "brief", "verify": "off", "citations": "text"}
    assert body["unverified_items"] == [{"code": _UNKNOWN_CODE, "reason": "not_in_db"}]
    assert built_options == [AssistOptions(style="brief", verify="off", citations="text")]


def test_research_dev_without_options_uses_defaults(client, built_options, monkeypatch):
    monkeypatch.setenv("RESEARCH_DEV", "true")
    body = _ask(client).json()
    assert body["options_applied"] == AssistOptions().model_dump()


def test_research_dev_does_not_override_study_session(client, sink, built_options, monkeypatch):
    monkeypatch.setenv("RESEARCH_DEV", "true")
    sink.add("sess-1", "V00")
    body = _ask(client, session="sess-1", options={"style": "brief"}).json()
    assert body["options_ignored"] is True
    assert body["options_applied"]["style"] == "standard"


# --- 断る場合 -----------------------------------------------------------------------------


def test_static_route_is_501_before_e1(client, sink, built_options, monkeypatch):
    monkeypatch.setenv("RESEARCH_DEV", "true")
    response = _ask(client, options={"route": "static"})
    assert response.status_code == 501
    assert built_options == []


def test_static_route_in_study_is_501_and_recorded(client, sink, built_options):
    sink.add("sess-static", "V09")  # ai_route=static
    response = _ask(client, session="sess-static")
    assert response.status_code == 501
    assert [(e[1], e[2]["error"], e[2]["route_actual"]) for e in sink.events] == [("chat_response", "other", None)]


def test_harness_only_route_is_501(client, sink, built_options):
    sink.add("sess-free", "V07")  # ai_route=mcp_free は評価ハーネスだけ
    assert _ask(client, session="sess-free").status_code == 501
    assert sink.events == []


def test_unknown_session_is_401(client, sink, built_options):
    response = _ask(client, session="no-such-session")
    assert response.status_code == 401
    assert built_options == []
    assert sink.events == []


def test_session_outside_block_is_409(client, sink, built_options):
    sink.add("sess-idle", None, block=None)
    assert _ask(client, session="sess-idle").status_code == 409


def test_session_in_no_ai_block_is_409(client, sink, built_options):
    sink.add("sess-noai", "V01")
    assert _ask(client, session="sess-noai").status_code == 409
    assert sink.events == []


@pytest.mark.parametrize("question", ["", "   ", "あ" * 2001])
def test_bad_question_is_422(client, built_options, question, monkeypatch):
    monkeypatch.setenv("RESEARCH_DEV", "true")
    assert client.post("/assist/ask", json={"question": question}).status_code == 422
    assert built_options == []


# --- 失敗も記録する -------------------------------------------------------------------------


def test_timeout_is_504_and_recorded(client, sink, monkeypatch):
    async def _slow(question: str, options: AssistOptions, plan_context=None, request_text=None):
        await asyncio.sleep(5)

    monkeypatch.setattr(route_options, "run_with_options", _slow)
    monkeypatch.setattr(assist_router, "ASSIST_TIMEOUT_SECONDS", 0.05)
    sink.add("sess-1", "V00")
    response = _ask(client, session="sess-1", client_event_id=_EVENT_ID)
    assert response.status_code == 504
    assert len(sink.events) == 1
    payload = sink.events[0][2]
    assert payload["error"] == "timeout"
    assert payload["client_event_id"] == _EVENT_ID
    assert payload["route_actual"] is None


def test_llm_failure_is_recorded_and_not_swallowed(client, sink, monkeypatch):
    monkeypatch.setattr(route_options, "build_agent", lambda options: _agent(_FailingLlm()))
    monkeypatch.setattr(config, "AGENT_ENABLE_MCP", True)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key-for-routing")
    sink.add("sess-1", "V00")
    response = _ask(client, session="sess-1")
    assert response.status_code == 500
    assert len(sink.events) == 1
    payload = sink.events[0][2]
    assert payload["error"] == "other"
    assert "架空の LLM の障害" in payload["error_detail"]


def test_mcp_fallback_is_recorded_as_mcp_unavailable(client, sink, monkeypatch):
    async def _fallback(question: str, options: AssistOptions, plan_context=None, request_text=None):
        result = runner.McpAgentRunResult(route="static", answer="静的", notes=["MCP なし"], latency_ms=3)
        return route_options.AssistRun(result=result, prompt_sha256=None)

    monkeypatch.setattr(route_options, "run_with_options", _fallback)
    sink.add("sess-1", "V00")
    response = _ask(client, session="sess-1")
    assert response.status_code == 200
    assert response.json()["route"] == "static"
    payload = sink.events[0][2]
    assert (payload["route_actual"], payload["error"], payload["error_detail"]) == ("static", "mcp_unavailable", "MCP なし")


class _UnwritableSink(FakeSink):
    """chat_response を書けない研究のログの口（ディスクの障害などの代役）。"""

    async def append_server_event(self, session_id, event_type, payload) -> None:
        raise OSError("架空の書き込みの障害")


def test_unwritable_sink_fails_loudly_for_sessions(built_options):
    """研究のログに書けないときは、セッション付きの要求を記録したふりで通さない（200 にしない）。

    研究のログの口の実装（get_research_sink の中身）に依らないよう、書けない口を差し込んで確かめる。
    """
    sink = _UnwritableSink()
    sink.add("sess-1", "V00")
    app = FastAPI()
    app.include_router(assist_router.router)
    app.dependency_overrides[get_research_sink] = lambda: sink
    client = TestClient(app, raise_server_exceptions=False)
    assert _ask(client, session="sess-1").status_code == 500


def test_classify_error():
    class _Db(Exception):
        pass

    _Db.__module__ = "asyncpg.exceptions"
    assert assist_router.classify_error(_Db()) == "db"
    _Db.__module__ = "neo4j.exceptions"
    assert assist_router.classify_error(_Db()) == "db"
    _Db.__module__ = "google.genai.errors"
    assert assist_router.classify_error(_Db()) == "llm"
    assert assist_router.classify_error(RuntimeError()) == "other"


# --- 今のプラン（plan_context） --------------------------------------------------------------


def test_plan_context_grounds_suggestions_and_is_recorded(client, sink, built_options, scripted_llm):
    sink.add("sess-1", "V00")
    response = _ask(client, session="sess-1", plan_context=_PLAN)
    assert response.status_code == 200
    body = response.json()

    # LLM には相談の後ろに今のプランが付き、科目名はサーバーが courses で引いた値
    first_text = scripted_llm.received[0]
    assert first_text.startswith(_QUESTION)
    assert "## 今のプラン" in first_text
    assert "架空の診断のまとめ" in first_text
    assert f"- {_PLAN_CODE} 架空の月曜の科目（春 月2 2単位）" in first_text
    assert f"- {_UNKNOWN_CODE}（DB に無い syllabus_id）" in first_text

    # 足す科目は DB にありプランに無いものだけ、外す科目はプランにあるものだけが残る
    assert body["plan_suggestions"] == {
        "add": [{"syllabus_id": _EXTRA_CODE, "title": "架空の水曜の科目", "reason": "水曜", "status": "planned"}],
        "remove": [{"syllabus_id": _PLAN_CODE, "title": "架空の月曜の科目", "reason": "月曜", "status": "planned"}],
        "dropped": [
            {"action": "add", "syllabus_id": _UNKNOWN_CODE, "reason": "not_in_db"},
            {"action": "add", "syllabus_id": _PLAN_CODE, "reason": "already_in_plan"},
            {"action": "remove", "syllabus_id": _KNOWN_CODE, "reason": "not_in_plan"},
        ],
    }

    payload = sink.events[0][2]
    expected_digest = route_options.plan_context_sha256(route_options.PlanContext.model_validate(_PLAN))
    assert payload["plan_context_sha256"] == expected_digest
    assert len(expected_digest) == 64
    assert "架空の診断のまとめ" not in str(payload)  # 診断のまとめの本文は記録に書かない
    assert payload["plan_suggestions"] == {
        "add": [_EXTRA_CODE],
        "remove": [_PLAN_CODE],
        "dropped": body["plan_suggestions"]["dropped"],
    }
    assert payload["plan_delivery"] == "delivered"


def test_plan_context_on_the_static_fallback_is_recorded(client, sink, monkeypatch):
    async def _fallback(question: str, options: AssistOptions, plan_context=None, request_text=None):
        result = runner.McpAgentRunResult(route="static", answer="静的", notes=["MCP なし"], latency_ms=3)
        return route_options.AssistRun(result=result, prompt_sha256=None)

    monkeypatch.setattr(route_options, "run_with_options", _fallback)
    sink.add("sess-1", "V00")
    assert _ask(client, session="sess-1", plan_context=_PLAN).status_code == 200
    payload = sink.events[0][2]
    assert (payload["plan_delivery"], payload["plan_suggestions"], payload["error"]) == (
        "static_fallback",
        None,
        "mcp_unavailable",
    )


def test_plan_context_without_an_answer_is_not_delivered(client, sink, monkeypatch):
    async def _slow(question: str, options: AssistOptions, plan_context=None, request_text=None):
        await asyncio.sleep(5)

    monkeypatch.setattr(route_options, "run_with_options", _slow)
    monkeypatch.setattr(assist_router, "ASSIST_TIMEOUT_SECONDS", 0.05)
    sink.add("sess-1", "V00")
    assert _ask(client, session="sess-1", plan_context=_PLAN).status_code == 504
    payload = sink.events[0][2]
    assert (payload["plan_delivery"], payload["error"]) == ("not_delivered", "timeout")
    assert payload["plan_context_sha256"] is not None


def test_plan_context_digest_changes_with_the_plan():
    plan = route_options.PlanContext.model_validate(_PLAN)
    other = plan.model_copy(update={"answers_summary": "別のまとめ"})
    assert route_options.plan_context_sha256(plan) == route_options.plan_context_sha256(
        route_options.PlanContext.model_validate(_PLAN)
    )
    assert route_options.plan_context_sha256(plan) != route_options.plan_context_sha256(other)


@pytest.mark.parametrize(
    "plan",
    [
        {"answers_summary": "", "terms": [{"year": 0, "term": "春", "syllabus_ids": []}]},
        {"answers_summary": "", "terms": [{"year": 1, "term": "", "syllabus_ids": []}]},
        {"answers_summary": "あ" * 1001, "terms": []},
        {"answers_summary": "", "terms": [{"year": 1, "term": "春", "syllabus_ids": [""]}]},
        {"answers_summary": "", "terms": [{"year": 1, "term": "春", "syllabus_ids": ["1"] * 41}]},
        {"answers_summary": "", "terms": [{"year": 1, "term": "春", "syllabus_ids": []}] * 17},
    ],
)
def test_bad_plan_context_is_422(client, built_options, monkeypatch, plan):
    monkeypatch.setenv("RESEARCH_DEV", "true")
    assert _ask(client, plan_context=plan).status_code == 422
    assert built_options == []


def test_render_plan_block():
    plan = route_options.PlanContext.model_validate(
        {
            "answers_summary": "  ",
            "terms": [
                {"year": 1, "term": "秋", "syllabus_ids": [" 900001 ", "900001", _UNKNOWN_CODE]},
                {"year": 2, "term": "春", "syllabus_ids": []},
            ],
        }
    )
    assert route_options.plan_syllabus_ids(plan) == ["900001", _UNKNOWN_CODE]
    block = route_options.render_plan_block(plan, [course_row(credits=None, term_schedule=None)])
    assert block.splitlines() == [
        block.splitlines()[0],  # 見出し
        "### 1年 秋",
        "- 900001 架空の反応工学１（春）",
        f"- {_UNKNOWN_CODE}（DB に無い syllabus_id）",
        "### 2年 春",
        "- （科目なし）",
    ]
    assert "診断のまとめ" not in block  # 空のまとめは書かない
    failed = route_options.render_plan_block(plan, None)
    assert "- 900001（DB を引けず確かめられませんでした）" in failed.splitlines()
    assert route_options.compose_message("相談", None) == "相談"
    assert route_options.compose_message("相談", "## 今のプラン") == "相談\n\n## 今のプラン"


# --- McpToolset の使い回し --------------------------------------------------------------------


def test_run_with_options_reuses_lifespan_toolset(monkeypatch, scripted_llm):
    shared = RecordingToolset()
    monkeypatch.setattr(route_options, "build_agent", lambda options: _agent(scripted_llm, [shared]))
    monkeypatch.setattr(config, "AGENT_ENABLE_MCP", True)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key-for-routing")
    deps.set_backends(_FakePool(_ROWS), None)
    deps.set_mcp_toolset(shared)
    try:
        for _ in range(2):
            run = asyncio.run(route_options.run_with_options(_QUESTION, AssistOptions()))
            assert run.toolset_reused is True
            assert run.result.route == "mcp"
    finally:
        deps.set_mcp_toolset(None)
        deps.set_backends(None, None)
    assert shared.get_tools_calls >= 2  # 事前確認は毎回する（死んだセッションは ADK がつなぎ直す）
    assert shared.close_calls == 0  # 閉じるのは lifespan


def test_build_agent_uses_lifespan_toolset(monkeypatch):
    shared = RecordingToolset()
    monkeypatch.setattr(config, "AGENT_ENABLE_MCP", True)
    deps.set_mcp_toolset(shared)
    try:
        agent = route_options.build_agent(AssistOptions())
    finally:
        deps.set_mcp_toolset(None)
    assert agent.tools[0] is shared
    assert agent.tools[1] is courses_tools.get_course_details
    assert agent.output_schema is PlanAnswerPayload


# --- 文体の追補 -----------------------------------------------------------------------------


def test_instruction_for_styles():
    from agent.mcp_agent import build_kansai_mcp_agent

    assert route_options.instruction_for("standard") is None
    default_instruction = build_kansai_mcp_agent().instruction
    for style, marker in (("brief", "回答の長さ"), ("detailed", "回答の詳しさ")):
        text = route_options.instruction_for(style)
        assert text is not None
        assert text.startswith(default_instruction)  # 今の文は書き換えず、後ろに足すだけ
        assert marker in text[len(default_instruction):]


def test_build_agent_passes_style_instruction():
    agent = route_options.build_agent(AssistOptions(style="detailed"))
    assert agent.instruction == route_options.instruction_for("detailed")
    standard = route_options.build_agent(AssistOptions())
    assert "回答の長さ" not in standard.instruction and "回答の詳しさ" not in standard.instruction


def test_refine_instruction_for_styles():
    from agent.mcp_agent import load_kansai_refine_instruction

    assert route_options.refine_instruction_for("standard") is None
    brief = route_options.refine_instruction_for("brief")
    assert brief is not None and brief.startswith(load_kansai_refine_instruction())
    assert route_options.build_refine_agent(AssistOptions(style="brief")).instruction == brief
    assert route_options.build_refine_agent(AssistOptions()).tools == []


# --- 診断の答えがある微修正（静的の経路） ------------------------------------------------------

_LOCKED_CODE = _PLAN_CODE  # 今のプランにある系統図の科目（外さないが、別クラスへ移すのはよい）
_FREE_CODE = "900004"  # 今のプランにある系統図に載らない科目（外せる）
_SAME_NAME_CODE = "900005"  # 今のプランの系統図の科目と同じ名前の別クラス（移す組のときだけ足せる）
_NAMED_CODE = "900006"  # 点が低く上位に入らないが、頼みに名前が出れば選べる科目
_STATIC_ROWS = [
    *_ROWS,
    course_row(syllabus_id=_FREE_CODE, subject_name="架空の教養", term_schedule="月3"),
    course_row(syllabus_id=_SAME_NAME_CODE, subject_name="架空の月曜の科目", term_schedule="金2"),
    course_row(syllabus_id=_NAMED_CODE, subject_name="架空の珍しい科目", term_schedule="木5"),
]
_STATIC_PLAN = {
    "answers_summary": "架空の診断のまとめ",
    "terms": [{"year": 1, "term": "春", "syllabus_ids": [_LOCKED_CODE, _FREE_CODE]}],
    "config_version": "test-1",
    "answers": {"interest": ["adv"], "morning": ["ok"], "scale": 3},
}


def _static_catalog(fillers: int = 0):
    """静的の経路の架空の科目。fillers 件の点の高い科目を足すと、点の低い科目は上位（30 件）に入らなくなる。"""
    course = diagnose_fixtures.course
    high = [course(f"95{index:04d}", name=f"架空の上位{index}", group_id="G_B", slots=("土1",)) for index in range(fillers)]
    return diagnose_fixtures.catalog(
        [
            course(_LOCKED_CODE, name="架空の月曜の科目", group_id="G_A", slots=("月2",)),
            course(_FREE_CODE, name="架空の教養", slots=("月3",)),
            course(_EXTRA_CODE, name="架空の水曜の科目", group_id="G_C", slots=("水2",)),  # 上位の選べる科目
            course(_SAME_NAME_CODE, name="架空の月曜の科目", slots=("金2",)),  # 別クラス（移す先）
            course(_KNOWN_CODE, name="架空の反応工学１", year_min=3),  # 1年は取れないので選べない
            course(_NAMED_CODE, name="架空の珍しい科目", slots=("木5",)),
            *high,
        ]
    )


def _payload(add: list[str], remove: list[str]) -> PlanAnswerPayload:
    return PlanAnswerPayload(
        answer="架空の回答です。",
        cited_codes=[*add, *remove],
        add=[PlanChange(syllabus_id=code, reason=f"足す {code}") for code in add],
        remove=[PlanChange(syllabus_id=code, reason=f"外す {code}") for code in remove],
    )


class _RefineLlm(BaseLlm):
    """道具なしの生成の偽モデル。payload を JSON の文にして1回だけ返す（usage_metadata 付き）。"""

    model: str = "refine-fake-llm"
    payload: PlanAnswerPayload = PlanAnswerPayload(answer="架空の回答です。")
    received: list[str] = []
    tool_counts: list[int] = []
    catalog_loads: list[str] = []  # 候補を作るために読んだ学科（差し替えた load_refine_catalog が書く）
    fillers: int = 0  # _static_catalog の fillers

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.received.append(_user_text(llm_request))
        self.tool_counts.append(len(llm_request.config.tools or []))
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=self.payload.model_dump_json())]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=10, candidates_token_count=5),
        )


@pytest.fixture
def refine_llm(monkeypatch, built_options) -> _RefineLlm:
    """静的の経路の差し替え（偽モデル・架空の診断の設定と科目）。MCP の経路の build_agent は built_options が記録する。"""
    llm = _RefineLlm(received=[], tool_counts=[], catalog_loads=[])

    async def _catalog(department_id: str):
        llm.catalog_loads.append(department_id)
        return _static_catalog(llm.fillers)

    monkeypatch.setattr(
        route_options,
        "build_refine_agent",
        lambda options: LlmAgent(
            name="refine_agent", model=llm, instruction="テスト用", tools=[], output_schema=PlanAnswerPayload
        ),
    )
    monkeypatch.setattr(route_options, "load_refine_config", lambda department_id: diagnose_fixtures.make_config())
    monkeypatch.setattr(route_options, "load_refine_catalog", _catalog)
    deps.set_backends(_FakePool(_STATIC_ROWS), None)
    return llm


def test_plan_answers_use_the_static_path_with_candidates_and_locks(client, sink, built_options, refine_llm):
    refine_llm.payload = _payload(add=[_EXTRA_CODE, _KNOWN_CODE, _UNKNOWN_CODE], remove=[_LOCKED_CODE, _FREE_CODE])
    sink.add("sess-1", "V00")  # route=mcp_grounded の変種でも、診断の答えがあれば静的の経路
    response = _ask(client, session="sess-1", plan_context=_STATIC_PLAN)
    assert response.status_code == 200
    body = response.json()

    # LLM は1回だけ、道具なしで呼ばれ、選べる科目と系統図の科目の印が相談の後ろに付く
    assert len(refine_llm.received) == 1
    assert refine_llm.tool_counts == [0]
    assert built_options == []  # MCP の経路のエージェントは作らない
    assert refine_llm.catalog_loads == [route_options.REFINE_DEPARTMENT_ID]
    text = refine_llm.received[0]
    lines = text.splitlines()
    assert text.startswith(_QUESTION)
    assert f"- {_LOCKED_CODE} 架空の月曜の科目（月2、2単位、まとまり: 架空基礎系）{plan_candidates.LOCK_MARK}" in lines
    assert f"- {_FREE_CODE} 架空の教養（月3、2単位）" in lines
    assert any(line.startswith("## 選べる科目") for line in lines)
    assert f"- {_EXTRA_CODE} 架空の水曜の科目（水2、2単位、まとまり: 架空発展系、点 3）" in lines
    # 系統図の科目の別クラスは、移す先として印を付けて出す
    same_name = [line for line in lines if line.startswith(f"- {_SAME_NAME_CODE} ")]
    assert len(same_name) == 1 and f"今のプランの {_LOCKED_CODE} の別クラス" in same_name[0]

    assert body["route"] == "static"
    assert body["route_requested"] == "mcp_grounded"
    assert body["model"] == "refine-fake-llm"
    assert body["tool_calls"] == []
    assert body["plan_suggestions"] == {
        "add": [
            {"syllabus_id": _EXTRA_CODE, "title": "架空の水曜の科目", "reason": f"足す {_EXTRA_CODE}", "status": "planned"}
        ],
        "remove": [{"syllabus_id": _FREE_CODE, "title": "架空の教養", "reason": f"外す {_FREE_CODE}", "status": "planned"}],
        "dropped": [
            {"action": "add", "syllabus_id": _KNOWN_CODE, "reason": "not_candidate"},
            {"action": "add", "syllabus_id": _UNKNOWN_CODE, "reason": "not_in_db"},
            {"action": "remove", "syllabus_id": _LOCKED_CODE, "reason": "locked"},  # 別クラスを足す組が無い
        ],
    }

    payload = sink.events[0][2]
    assert (payload["path"], payload["candidate_count"], payload["llm_calls"]) == ("static", 3, 1)
    assert payload["candidate_sources"] == {"top": 2, "same_name": 1, "named": 0}  # top は 900003 と 900006
    assert (payload["route_actual"], payload["plan_delivery"], payload["error"]) == ("static", "delivered", None)
    assert payload["plan_suggestions"]["remove"] == [_FREE_CODE]
    assert "架空の診断のまとめ" not in str(payload)


def test_moving_a_locked_course_to_another_class_is_kept(client, sink, built_options, refine_llm):
    """系統図の科目を外す案も、同じ学期の同じ名前の別クラスを足す案と組なら「移す」として残す。"""
    refine_llm.payload = _payload(add=[_SAME_NAME_CODE], remove=[_LOCKED_CODE])
    sink.add("sess-1", "V00")
    suggestions = _ask(client, session="sess-1", plan_context=_STATIC_PLAN).json()["plan_suggestions"]
    assert [s["syllabus_id"] for s in suggestions["add"]] == [_SAME_NAME_CODE]
    assert [s["syllabus_id"] for s in suggestions["remove"]] == [_LOCKED_CODE]
    assert suggestions["dropped"] == []


def test_other_class_without_removing_the_original_is_dropped(client, sink, built_options, refine_llm):
    """別クラスだけを足す案は、同じ名前の科目がもうプランにあるので already_in_plan で外す（元の系統図の科目も残る）。"""
    refine_llm.payload = _payload(add=[_SAME_NAME_CODE], remove=[])
    sink.add("sess-1", "V00")
    suggestions = _ask(client, session="sess-1", plan_context=_STATIC_PLAN).json()["plan_suggestions"]
    assert suggestions["add"] == []
    assert suggestions["dropped"] == [{"action": "add", "syllabus_id": _SAME_NAME_CODE, "reason": "already_in_plan"}]


def test_course_named_in_the_request_is_a_candidate(client, sink, built_options, refine_llm):
    """点が低く上位 30 件に入らない科目も、利用者が打った文（raw_input）に名前が出れば選べる科目に入る。"""
    refine_llm.fillers = 30
    refine_llm.payload = _payload(add=[_NAMED_CODE], remove=[])
    sink.add("sess-1", "V00")

    unnamed = _ask(client, session="sess-1", plan_context=_STATIC_PLAN, raw_input="1年春に科目を足したい").json()
    assert [d["reason"] for d in unnamed["plan_suggestions"]["dropped"]] == ["not_candidate"]
    assert f"- {_NAMED_CODE} " not in refine_llm.received[0]

    named = _ask(client, session="sess-1", plan_context=_STATIC_PLAN, raw_input="1年春に「架空の珍しい科目」を入れたい").json()
    assert [s["syllabus_id"] for s in named["plan_suggestions"]["add"]] == [_NAMED_CODE]
    line = next(line for line in refine_llm.received[1].splitlines() if line.startswith(f"- {_NAMED_CODE} "))
    assert line.endswith("［頼みに名前が出た科目］")
    sources = [event[2]["candidate_sources"] for event in sink.events]
    assert sources == [{"top": 30, "same_name": 1, "named": 0}, {"top": 30, "same_name": 1, "named": 1}]


def test_static_route_option_with_plan_answers_is_served(client, sink, built_options, refine_llm, monkeypatch):
    """route=static（今まで 501）は、診断の答えがあれば静的の経路で答える。"""
    monkeypatch.setenv("RESEARCH_DEV", "true")
    response = _ask(client, options={"route": "static"}, plan_context=_STATIC_PLAN)
    assert response.status_code == 200
    assert response.json()["route"] == "static"
    assert len(refine_llm.received) == 1


def test_plan_without_answers_keeps_the_mcp_path(client, sink, built_options, refine_llm):
    sink.add("sess-1", "V00")
    assert _ask(client, session="sess-1", plan_context=_PLAN).status_code == 200
    assert refine_llm.received == []
    assert len(built_options) == 1
    payload = sink.events[0][2]
    assert (payload["path"], payload["candidate_count"], payload["route_actual"]) == ("mcp", None, "mcp")
    assert payload["llm_calls"] == 0  # 偽モデルは usage_metadata を返さない（実の Gemini は返す）


def test_plan_answers_with_another_config_version_are_409(client, sink, built_options, refine_llm):
    sink.add("sess-1", "V00")
    response = _ask(client, session="sess-1", plan_context={**_STATIC_PLAN, "config_version": "old-1"})
    assert response.status_code == 409
    assert "old-1" in response.json()["detail"]
    assert refine_llm.received == []
    payload = sink.events[0][2]
    assert (payload["path"], payload["plan_delivery"], payload["error"]) == ("static", "not_delivered", "other")


def test_wrong_plan_answers_are_422_and_recorded(client, sink, built_options, refine_llm):
    sink.add("sess-1", "V00")
    bad = {**_STATIC_PLAN, "answers": {"interest": ["no-such-option"], "morning": ["ok"], "scale": 3}}
    response = _ask(client, session="sess-1", plan_context=bad)
    assert response.status_code == 422
    assert "no-such-option" in response.json()["detail"]
    assert refine_llm.received == []
    assert sink.events[0][2]["error"] == "other"


@pytest.mark.parametrize("missing", ["config_version", "answers"])
def test_plan_answers_need_both_version_and_answers(client, sink, built_options, refine_llm, missing):
    sink.add("sess-1", "V00")
    plan = {key: value for key, value in _STATIC_PLAN.items() if key != missing}
    assert _ask(client, session="sess-1", plan_context=plan).status_code == 422
    assert refine_llm.received == []
    assert sink.events == []  # 形の誤りは FastAPI が断る（plan_context のほかの形の誤りと同じく記録しない）


def test_static_path_needs_the_databases(client, sink, monkeypatch):
    """DB が無ければ候補を作れない。記録してから 500（握りつぶさない）。"""
    monkeypatch.setattr(route_options, "load_refine_config", lambda department_id: diagnose_fixtures.make_config())
    deps.set_backends(None, None)
    sink.add("sess-1", "V00")
    assert _ask(client, session="sess-1", plan_context=_STATIC_PLAN).status_code == 500
    payload = sink.events[0][2]
    assert payload["error"] == "other"
    assert "未設定" in payload["error_detail"]


def test_plan_context_digest_ignores_unsent_answers():
    """診断の答えを送らない plan_context の指紋は、項目を足す前と同じ（送られなかった項目を指紋に入れない）。"""
    plan = route_options.PlanContext.model_validate(_PLAN)
    with_answers = route_options.PlanContext.model_validate(_STATIC_PLAN)
    assert set(plan.model_dump(exclude_none=True)) == {"answers_summary", "terms"}
    assert route_options.plan_context_sha256(plan) != route_options.plan_context_sha256(with_answers)
    # 履修の状況（start・completed・registered）も、送らなければ指紋に入らない
    assert set(with_answers.model_dump(exclude_none=True)) == {"answers_summary", "terms", "config_version", "answers"}


# --- 履修の状況（start・completed・registered）がある微修正 ---------------------------------------


def test_history_on_the_static_path(client, sink, built_options, refine_llm):
    """履修済みと同じ名前の科目は選べる科目に出さず、足す案は completed で外す。
    登録済みの科目を外す案は、系統図の科目でも dropped にせず status=registered で残す。"""
    refine_llm.payload = _payload(add=[_EXTRA_CODE, _NAMED_CODE], remove=[_LOCKED_CODE])
    sink.add("sess-1", "V00")
    plan = {
        **_STATIC_PLAN,
        "start": {"year": 1, "term": "春"},
        "completed": [_EXTRA_CODE],
        "registered": [{"year": 1, "term": "春", "syllabus_ids": [_LOCKED_CODE]}],
    }
    response = _ask(client, session="sess-1", plan_context=plan)
    assert response.status_code == 200, response.text

    lines = refine_llm.received[0].splitlines()
    locked_line = f"- {_LOCKED_CODE} 架空の月曜の科目（月2、2単位、まとまり: 架空基礎系）"
    assert locked_line + plan_candidates.LOCK_MARK + plan_candidates.REGISTERED_MARK in lines
    assert not any(line.startswith(f"- {_EXTRA_CODE} ") for line in lines)
    suggestions = response.json()["plan_suggestions"]
    assert suggestions == {
        "add": [{"syllabus_id": _NAMED_CODE, "title": "架空の珍しい科目", "reason": f"足す {_NAMED_CODE}", "status": "planned"}],
        "remove": [
            {"syllabus_id": _LOCKED_CODE, "title": "架空の月曜の科目", "reason": f"外す {_LOCKED_CODE}", "status": "registered"}
        ],
        "dropped": [{"action": "add", "syllabus_id": _EXTRA_CODE, "reason": "completed"}],
    }
    payload = sink.events[0][2]
    assert payload["candidate_sources"] == {"top": 1, "same_name": 1, "named": 0}  # 履修済みの 900003 が top から抜ける
    expected =route_options.plan_context_sha256(route_options.PlanContext.model_validate(plan))
    assert payload["plan_context_sha256"] == expected != route_options.plan_context_sha256(
        route_options.PlanContext.model_validate(_STATIC_PLAN)
    )


@pytest.mark.parametrize(
    "history",
    [
        {"completed": [_KNOWN_CODE]},
        {"start": {"year": 1, "term": "春"}},
        {"registered": [{"year": 1, "term": "春", "syllabus_ids": [_PLAN_CODE]}]},
    ],
)
def test_history_without_plan_answers_is_422(client, sink, built_options, refine_llm, history):
    """履修の状況は静的の経路だけが使うので、診断の答えが無ければ形の誤り（FastAPI が断り、記録しない）。"""
    sink.add("sess-1", "V00")
    assert _ask(client, session="sess-1", plan_context={**_PLAN, **history}).status_code == 422
    assert built_options == [] and refine_llm.received == []
    assert sink.events == []


def test_empty_history_without_plan_answers_keeps_the_mcp_path(client, sink, built_options, refine_llm):
    sink.add("sess-1", "V00")
    assert _ask(client, session="sess-1", plan_context={**_PLAN, "completed": [], "registered": []}).status_code == 200
    assert len(built_options) == 1 and refine_llm.received == []


@pytest.mark.parametrize(
    ("history", "fragment"),
    [
        ({"completed": [_UNKNOWN_CODE]}, "知らない科目です"),
        ({"start": {"year": 2, "term": "春"}}, "start の 2年春"),
        ({"registered": [{"year": 1, "term": "秋", "syllabus_ids": [_FREE_CODE]}]}, "terms の同じ学期にありません"),
        ({"completed": [_FREE_CODE], "registered": [{"year": 1, "term": "春", "syllabus_ids": [_FREE_CODE]}]}, "両方"),
    ],
)
def test_wrong_history_is_422_and_recorded(client, sink, built_options, refine_llm, history, fragment):
    sink.add("sess-1", "V00")
    response = _ask(client, session="sess-1", plan_context={**_STATIC_PLAN, **history})
    assert response.status_code == 422
    assert fragment in response.json()["detail"]
    assert refine_llm.received == []
    payload = sink.events[0][2]
    assert (payload["path"], payload["plan_delivery"], payload["error"]) == ("static", "not_delivered", "other")
