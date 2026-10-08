"""test3-2（MCP Agent + RDB ツール + 出典付与）の検証テスト。

ADR-0010 に従い、実 LLM / 実 DB を呼ばずに CI で回る形にしている。
- PostgreSQL は `acquire()` / `fetch()` だけを持つ偽プールで代役させる（行は seed/courses.json 由来）。
- LLM は台本どおりに function_call を返す偽モデル（BaseLlm のサブクラス）で代役させ、
  ADK の Workflow / LlmAgent / ツール実行 / set_model_response の経路は本物を通す。
"""

import asyncio
import json
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.adk import Event, Workflow
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.genai import types

import fake_graph
from agent import deps, grounding, nodes, rdb_tools, runner
from agent.compose_agent import build_compose_agent
from agent.mcp_agent import build_grounded_mcp_agent, build_mcp_agent
from agent.schemas import AnswerPayload, GroundedAnswer
from agent.workflow import build_mcp_grounded_workflow
from api.routers import agent as agent_router
from course_core import config

_KNOWN_CODE = "GMS-303"  # 機械学習（seed に存在）
_UNKNOWN_CODE = "GMS-999"  # seed に存在しない（ハルシネーション役）
_QUESTION = "データサイエンス入門の次に取れる科目は?"


# --- PostgreSQL の代役 ---------------------------------------------------------


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.queried_codes: list[list[str]] = []

    async def fetch(self, query: str, codes: list[str]) -> list[dict[str, Any]]:
        self.queried_codes.append(list(codes))
        return [row for row in self._rows if row["code"] in codes]


class _FakePool:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.connection = _FakeConnection(rows)

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[_FakeConnection, None]:
        yield self.connection


@pytest.fixture
def fake_pool():
    """seed/courses.json の20科目を持つ偽プールを deps に注入する。"""
    pool = _FakePool(fake_graph.courses())
    deps.set_backends(pool, None)
    yield pool
    deps.set_backends(None, None)


@pytest.fixture
def no_backends():
    deps.set_backends(None, None)
    yield
    deps.set_backends(None, None)


def _seed_row(code: str) -> dict[str, Any]:
    return next(course for course in fake_graph.courses() if course["code"] == code)


# --- LLM の代役 ----------------------------------------------------------------


class _ScriptedLlm(BaseLlm):
    """1ターン目は get_course_details、2ターン目は set_model_response を呼ぶ偽モデル。

    Gemini API（非 Vertex）では output_schema + tools の組で ADK が set_model_response を
    差し込むので、本番と同じ「ツール → set_model_response」の経路を通す。
    """

    model: str = "scripted-fake-llm"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        answered = {
            part.function_response.name
            for content in llm_request.contents
            for part in (content.parts or [])
            if part.function_response
        }
        if "get_course_details" not in answered:
            call = types.FunctionCall(
                name="get_course_details",
                args={"codes": [_KNOWN_CODE, _UNKNOWN_CODE]},
            )
        else:
            call = types.FunctionCall(
                name="set_model_response",
                args={
                    "answer": f"機械学習 [{_KNOWN_CODE}] と 架空科目 [{_UNKNOWN_CODE}] です。",
                    "cited_codes": [_KNOWN_CODE, _UNKNOWN_CODE],
                },
            )
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(function_call=call)])
        )


def _scripted_agent() -> LlmAgent:
    return LlmAgent(
        name="mcp_agent",
        model=_ScriptedLlm(),
        instruction="テスト用",
        tools=[rdb_tools.get_course_details],
        output_schema=AnswerPayload,
    )


# --- grounding（純関数） --------------------------------------------------------


def test_truncate_text():
    assert grounding.truncate_text(None, 5) == ""
    assert grounding.truncate_text("abc", 5) == "abc"
    assert grounding.truncate_text("abcdefg", 5) == "abcde…"


def test_normalize_codes_strips_brackets_and_full_width():
    """回答文の書式のまま入った括弧・全角は外して照合する。大文字小文字は変えない。"""
    codes = [
        "[GMS-303]",
        "ＧＭＳ－３０３",
        "【GMS-401】",
        "［GMS-302］",
        "　GMS-301 ",
        "",
        " [] ",
        "gms-303",
    ]

    assert grounding.normalize_codes(codes) == [
        "GMS-303",
        "GMS-401",
        "GMS-302",
        "GMS-301",
        "gms-303",
    ]


def test_build_grounded_answer_matches_bracketed_and_full_width_codes():
    payload = AnswerPayload(answer="回答", cited_codes=["[GMS-303]", "ＧＭＳ－３０３"])

    grounded = grounding.build_grounded_answer(payload, [_seed_row(_KNOWN_CODE)])

    assert grounded.cited_codes == [_KNOWN_CODE]
    assert [source.code for source in grounded.sources] == [_KNOWN_CODE]
    assert grounded.unverified_codes == []


def test_build_grounded_answer_splits_known_and_unknown_codes():
    """出典は DB の行から作り、DB に無いコードは unverified_codes に回る。"""
    payload = AnswerPayload(
        answer="回答",
        cited_codes=[_UNKNOWN_CODE, f" {_KNOWN_CODE} ", _KNOWN_CODE, ""],
    )
    row = _seed_row(_KNOWN_CODE)

    grounded = grounding.build_grounded_answer(payload, [row])

    assert grounded.answer == "回答"
    assert grounded.cited_codes == [_UNKNOWN_CODE, _KNOWN_CODE]
    assert grounded.unverified_codes == [_UNKNOWN_CODE]
    assert [source.code for source in grounded.sources] == [_KNOWN_CODE]
    source = grounded.sources[0]
    assert source.title == row["title"]
    assert source.instructor == row["instructor"]
    assert source.schedule == row["schedule"]
    assert source.credits == row["credits"]
    assert source.excerpt == grounding.truncate_text(
        row["syllabus_text"], grounding.EXCERPT_MAX_CHARS
    )
    assert source.origin == grounding.SOURCE_ORIGIN
    assert source.url is None


# --- attach_sources ノード -----------------------------------------------------


def test_attach_sources_grounds_codes_against_db(fake_pool):
    payload = AnswerPayload(answer="回答", cited_codes=[_KNOWN_CODE, _UNKNOWN_CODE])

    event = asyncio.run(nodes.attach_sources(payload, None))

    assert isinstance(event.output, GroundedAnswer)
    assert [source.code for source in event.output.sources] == [_KNOWN_CODE]
    assert event.output.unverified_codes == [_UNKNOWN_CODE]
    assert event.output.notes == []
    assert fake_pool.connection.queried_codes == [[_KNOWN_CODE, _UNKNOWN_CODE]]


def test_attach_sources_without_pool_marks_all_unverified(no_backends):
    """プール未設定は黙って素通りさせず、全コード未検証 + 理由を notes に残す。"""
    payload = AnswerPayload(answer="回答", cited_codes=[_KNOWN_CODE])

    event = asyncio.run(nodes.attach_sources(payload, None))

    assert event.output.sources == []
    assert event.output.unverified_codes == [_KNOWN_CODE]
    assert len(event.output.notes) == 1


# --- get_course_details ツール -------------------------------------------------


def test_get_course_details_returns_rows_and_not_found(fake_pool):
    result = asyncio.run(rdb_tools.get_course_details([_KNOWN_CODE, _UNKNOWN_CODE, _KNOWN_CODE]))

    row = _seed_row(_KNOWN_CODE)
    assert result["error"] is None
    assert result["not_found"] == [_UNKNOWN_CODE]
    assert result["skipped_codes"] == []
    assert result["courses"] == [
        {
            "code": _KNOWN_CODE,
            "title": row["title"],
            "instructor": row["instructor"],
            "schedule": row["schedule"],
            "credits": row["credits"],
            "syllabus_text": row["syllabus_text"],
        }
    ]


def test_get_course_details_caps_codes_per_call(fake_pool):
    codes = [course["code"] for course in fake_graph.courses()]
    extra = [f"XXX-{index:03d}" for index in range(3)]

    result = asyncio.run(rdb_tools.get_course_details(codes + extra))

    assert len(codes) == rdb_tools.MAX_CODES_PER_CALL  # seed は20科目
    assert len(result["courses"]) == rdb_tools.MAX_CODES_PER_CALL
    assert result["skipped_codes"] == extra
    assert fake_pool.connection.queried_codes == [codes]


def test_get_course_details_truncates_long_syllabus():
    long_row = {**_seed_row(_KNOWN_CODE), "syllabus_text": "あ" * 1000}
    deps.set_backends(_FakePool([long_row]), None)
    try:
        result = asyncio.run(rdb_tools.get_course_details([_KNOWN_CODE]))
    finally:
        deps.set_backends(None, None)

    text = result["courses"][0]["syllabus_text"]
    assert text == "あ" * rdb_tools.SYLLABUS_TEXT_MAX_CHARS + "…"


def test_get_course_details_without_pool_returns_error(no_backends):
    result = asyncio.run(rdb_tools.get_course_details([_KNOWN_CODE]))

    assert result["courses"] == []
    assert result["error"]


# --- tool_calls の抽出 ---------------------------------------------------------


def _call_event(call_id: str, name: str, args: dict[str, Any], *, partial: bool = False) -> Event:
    return Event(
        partial=partial,
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(id=call_id, name=name, args=args))],
        ),
    )


def _response_event(call_id: str, name: str, response: dict[str, Any]) -> Event:
    return Event(
        content=types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=call_id, name=name, response=response
                    )
                )
            ],
        ),
    )


def test_extract_tool_calls_pairs_calls_and_responses():
    cypher = "MATCH (c:Course) RETURN c.code"
    events = [
        _call_event("c1", "read-cypher", {"query": cypher}, partial=True),  # 途中断片は数えない
        _call_event("c1", "read-cypher", {"query": cypher}),
        _call_event("c2", "get_course_details", {"codes": [_KNOWN_CODE]}),
        _response_event("c2", "get_course_details", {"courses": [], "not_found": [_KNOWN_CODE]}),
        _response_event("c1", "read-cypher", {"result": "x" * 2000}),
        _response_event("orphan", "unknown-tool", {"ok": True}),
    ]

    calls = runner.extract_tool_calls(events)

    assert [call.name for call in calls] == ["read-cypher", "get_course_details", "unknown-tool"]
    assert calls[0].args == {"query": cypher}
    assert calls[0].result_summary is not None
    assert calls[0].result_summary.endswith("…")  # 長い応答は切り詰める
    assert json.loads(calls[1].result_summary) == {"courses": [], "not_found": [_KNOWN_CODE]}
    assert calls[2].args == {}
    assert calls[2].result_summary == json.dumps({"ok": True})


def test_extract_tool_calls_keeps_call_without_response():
    calls = runner.extract_tool_calls([_call_event("c1", "read-cypher", {"query": "RETURN 1"})])

    assert len(calls) == 1
    assert calls[0].result_summary is None


# --- ワークフロー構築 ----------------------------------------------------------


def test_build_mcp_grounded_workflow_structure():
    wf = build_mcp_grounded_workflow(enable_mcp=False)

    assert isinstance(wf, Workflow)
    assert wf.name == "course_navigator_mcp_grounded_workflow"
    # build_mcp_first_workflow の 8 本 + mcp_agent->attach_sources の 1 本
    assert len(wf.edges) == 9


def test_build_grounded_mcp_agent_adds_rdb_tool():
    without_mcp = build_grounded_mcp_agent(model="gemini-2.5-flash", enable_mcp=False)
    with_mcp = build_grounded_mcp_agent(model="gemini-2.5-flash", enable_mcp=True)

    assert without_mcp.name == "mcp_agent"
    assert without_mcp.tools == [rdb_tools.get_course_details]
    assert len(with_mcp.tools) == 2
    assert isinstance(with_mcp.tools[0], McpToolset)
    assert with_mcp.tools[1] is rdb_tools.get_course_details


def test_build_mcp_agent_default_has_no_extra_tools():
    """adk web が使う既定の mcp_agent には RDB ツールが付かない（既存挙動の維持）。"""
    assert build_mcp_agent(model="gemini-2.5-flash", enable_mcp=False).tools == []


def test_rdb_instructions_only_in_grounded_agent():
    """RDB 手順は grounded 版だけに連結し、共有プロンプトには書かない。

    ツールを持たない mcp_agent / compose_agent が未宣言ツールを呼ぶと ADK が
    ValueError で実行を止めるため、共有プロンプトに get_course_details が出てはいけない。
    """
    grounded = build_grounded_mcp_agent(model="gemini-2.5-flash", enable_mcp=False)
    plain = build_mcp_agent(model="gemini-2.5-flash", enable_mcp=False)
    compose = build_compose_agent(model="gemini-2.5-flash", enable_mcp=False)

    assert "get_course_details" in grounded.instruction
    assert grounded.instruction.startswith(plain.instruction)
    assert "get_course_details" not in plain.instruction
    assert "get_course_details" not in compose.instruction


def test_grounded_agent_respects_explicit_instruction():
    agent = build_grounded_mcp_agent(
        model="gemini-2.5-flash", instruction="明示指定の指示", enable_mcp=False
    )

    assert agent.instruction == "明示指定の指示"
    assert agent.tools == [rdb_tools.get_course_details]


# --- run_mcp_grounded（偽 LLM / 偽 DB で通電） ----------------------------------


def test_run_mcp_grounded_mcp_route_with_scripted_llm(monkeypatch, fake_pool):
    """route_initial → mcp_agent（ツール2回）→ attach_sources を実 ADK で通す。"""
    monkeypatch.setattr(config, "AGENT_ENABLE_MCP", True)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key-for-routing")

    result = asyncio.run(runner.run_mcp_grounded(_QUESTION, agent=_scripted_agent()))

    assert result.route == "mcp"
    assert result.model == "scripted-fake-llm"
    assert result.node_sequence == ["route_initial", "mcp_agent", "attach_sources"]
    assert result.cited_codes == [_KNOWN_CODE, _UNKNOWN_CODE]
    assert [source.code for source in result.sources] == [_KNOWN_CODE]
    assert result.unverified_codes == [_UNKNOWN_CODE]
    assert [call.name for call in result.tool_calls] == ["get_course_details", "set_model_response"]
    assert result.tool_calls[0].args == {"codes": [_KNOWN_CODE, _UNKNOWN_CODE]}
    assert _KNOWN_CODE in (result.tool_calls[0].result_summary or "")
    assert result.latency_ms >= 0


class _RecordingToolset(BaseToolset):
    """close() の呼び出し回数だけを記録する McpToolset の代役（ツールは持たない）。"""

    def __init__(self) -> None:
        super().__init__()
        self.close_calls = 0

    async def get_tools(self, readonly_context: ReadonlyContext | None = None) -> list[BaseTool]:
        return []

    async def close(self) -> None:
        self.close_calls += 1


class _LlmFailure(RuntimeError):
    pass


class _FailingLlm(BaseLlm):
    """1ターン目で例外を投げる偽モデル（LLM API 障害の代役）。"""

    model: str = "failing-fake-llm"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        raise _LlmFailure("LLM API が応答しない")
        yield  # 非同期ジェネレータにするための到達しない yield


def test_run_mcp_grounded_closes_toolsets_after_success(monkeypatch, fake_pool):
    monkeypatch.setattr(config, "AGENT_ENABLE_MCP", True)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key-for-routing")
    toolset = _RecordingToolset()
    agent = _scripted_agent()
    agent.tools.append(toolset)

    result = asyncio.run(runner.run_mcp_grounded(_QUESTION, agent=agent))

    assert result.route == "mcp"
    assert toolset.close_calls == 1


def test_run_mcp_grounded_closes_toolsets_when_run_raises(monkeypatch, fake_pool):
    """実行中に例外が出てもツールセット（MCP サブプロセス）を閉じ、例外は握りつぶさない。"""
    monkeypatch.setattr(config, "AGENT_ENABLE_MCP", True)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key-for-routing")
    toolset = _RecordingToolset()
    agent = LlmAgent(
        name="mcp_agent",
        model=_FailingLlm(),
        instruction="テスト用",
        tools=[toolset, rdb_tools.get_course_details],
        output_schema=AnswerPayload,
    )

    with pytest.raises(_LlmFailure):
        asyncio.run(runner.run_mcp_grounded(_QUESTION, agent=agent))

    assert toolset.close_calls == 1


def test_run_mcp_grounded_falls_back_to_static(monkeypatch, no_backends):
    """MCP 無効 / キー無しでは静的 DAG の回答を route="static" で返す。"""
    monkeypatch.setattr(config, "AGENT_ENABLE_MCP", False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    fake_graph.install(monkeypatch)
    deps.set_backends(None, fake_graph.FakeDriver())

    result = asyncio.run(runner.run_mcp_grounded(_QUESTION))

    assert result.route == "static"
    assert result.model is None
    assert result.node_sequence[:2] == ["route_initial", "parse_intent"]
    assert _KNOWN_CODE in result.cited_codes
    assert result.sources == []
    assert result.tool_calls == []


# --- エンドポイント -------------------------------------------------------------


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(agent_router.router)
    return TestClient(app, raise_server_exceptions=False)


def _stub_result() -> runner.McpAgentRunResult:
    return runner.McpAgentRunResult(
        route="mcp",
        answer="回答",
        cited_codes=[_KNOWN_CODE, _UNKNOWN_CODE],
        sources=[grounding.source_from_row(_seed_row(_KNOWN_CODE))],
        unverified_codes=[_UNKNOWN_CODE],
        tool_calls=[
            runner.ToolCallRecord(
                name="get_course_details", args={"codes": [_KNOWN_CODE]}, result_summary="{}"
            )
        ],
        node_sequence=["route_initial", "mcp_agent", "attach_sources"],
        model="gemini-2.5-flash",
        latency_ms=12,
    )


def test_agent_mcp_endpoint_response_shape(monkeypatch):
    received: list[str] = []

    async def _stub(question: str) -> runner.McpAgentRunResult:
        received.append(question)
        return _stub_result()

    monkeypatch.setattr(runner, "run_mcp_grounded", _stub)

    response = _client().post("/test/agent/mcp", json={"question": f"  {_QUESTION} "})

    assert response.status_code == 200
    body = response.json()
    assert received == [_QUESTION]
    assert set(body) == {
        "route",
        "answer",
        "cited_codes",
        "sources",
        "unverified_codes",
        "notes",
        "tool_calls",
        "node_sequence",
        "model",
        "latency_ms",
    }
    assert body["route"] == "mcp"
    assert set(body["sources"][0]) == {
        "code",
        "title",
        "instructor",
        "schedule",
        "credits",
        "excerpt",
        "origin",
        "url",
    }
    assert body["unverified_codes"] == [_UNKNOWN_CODE]
    assert body["tool_calls"][0] == {
        "name": "get_course_details",
        "args": {"codes": [_KNOWN_CODE]},
        "result_summary": "{}",
    }


def test_agent_mcp_endpoint_empty_question_skips_runner(monkeypatch):
    async def _must_not_run(question: str) -> runner.McpAgentRunResult:
        raise AssertionError("空の質問で runner を呼んではいけない")

    monkeypatch.setattr(runner, "run_mcp_grounded", _must_not_run)

    response = _client().post("/test/agent/mcp", json={"question": "   "})

    assert response.status_code == 200
    assert response.json()["route"] == "static"
    assert response.json()["answer"] == "質問を入力してください。"


def test_agent_mcp_endpoint_does_not_swallow_errors(monkeypatch):
    async def _boom(question: str) -> runner.McpAgentRunResult:
        raise RuntimeError("MCP サーバーが起動できない")

    monkeypatch.setattr(runner, "run_mcp_grounded", _boom)

    response = _client().post("/test/agent/mcp", json={"question": _QUESTION})

    assert response.status_code == 500
