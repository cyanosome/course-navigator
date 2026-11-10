"""エージェントの関西対応（E1）のテスト。実 LLM・実 DB を使わず CI で回る。

- 出典の照合（syllabus_id と courses）、足す・外すの提案の照合、courses を読む get_course_details、
  関西の出典付与ノード、関西向けのエージェントの組み立てと指示文、McpToolset の使い回し。
- PostgreSQL は架空の courses の行（tests/catalog_rows.py）を返す偽プール。シードの経路のテストは
  test_mcp_grounded.py のまま変えない。
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from agent import courses_tools, deps, grounding, mcp_agent, nodes, runner
from agent.schemas import CourseGroundedAnswer, PlanAnswerPayload, PlanChange
from catalog_rows import course_row
from course_core import config
from fake_toolset import RecordingToolset

_KNOWN = "900001"
_OTHER = "900002"
_UNKNOWN = "999999"
_ROWS = [course_row(), course_row(syllabus_id=_OTHER, subject_name="架空の科目２")]


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.queried: list[list[str]] = []

    async def fetch(self, query: str, syllabus_ids: list[str]) -> list[dict[str, Any]]:
        self.queried.append(list(syllabus_ids))
        return [row for row in self._rows if row["syllabus_id"] in syllabus_ids]


class _FakePool:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.connection = _FakeConnection(rows)

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[_FakeConnection, None]:
        yield self.connection


@pytest.fixture
def fake_pool():
    pool = _FakePool(_ROWS)
    deps.set_backends(pool, None)
    yield pool
    deps.set_backends(None, None)


@pytest.fixture
def no_backends():
    deps.set_backends(None, None)
    yield
    deps.set_backends(None, None)


# --- 出典の照合（純関数） ------------------------------------------------------------------


def test_source_from_course_row():
    source = grounding.source_from_course_row(course_row())

    assert source.code == _KNOWN
    assert source.title == "架空の反応工学１"
    assert source.instructor == "架空 花子"  # is_primary の人
    assert source.schedule == "春 火2"
    assert source.credits == 2.0
    assert source.excerpt == "あ" * grounding.EXCERPT_MAX_CHARS + "…"
    assert source.origin == grounding.COURSES_SOURCE_ORIGIN == "postgres:courses"
    assert source.url == "https://example.invalid/900001"


def test_source_from_course_row_without_schedule_and_teacher():
    source = grounding.source_from_course_row(
        course_row(semester=None, term_schedule=None, instructors=None, credits=None, description=None)
    )
    assert source.schedule is None
    assert source.instructor is None
    assert source.credits is None
    assert source.excerpt == ""


def test_build_course_grounded_answer_splits_known_and_unknown():
    payload = PlanAnswerPayload(answer="回答", cited_codes=[f"[{_KNOWN}]", _UNKNOWN, "１６２２４６", _KNOWN])

    grounded = grounding.build_course_grounded_answer(payload, _ROWS, plan_ids=None)

    assert isinstance(grounded, CourseGroundedAnswer)
    assert grounded.cited_codes == [_KNOWN, _UNKNOWN, "162246"]  # 括弧と全角は外す
    assert [source.code for source in grounded.sources] == [_KNOWN]
    assert grounded.unverified_codes == [_UNKNOWN, "162246"]
    assert grounded.plan_suggestions is None
    assert grounded.notes == []


def test_build_course_grounded_answer_notes_unused_suggestions_without_plan():
    payload = PlanAnswerPayload(answer="回答", add=[PlanChange(syllabus_id=_KNOWN)])

    grounded = grounding.build_course_grounded_answer(payload, _ROWS, plan_ids=None)

    assert grounded.plan_suggestions is None
    assert len(grounded.notes) == 1
    assert "1 件" in grounded.notes[0]


def test_ground_plan_suggestions():
    payload = PlanAnswerPayload(
        answer="回答",
        add=[
            PlanChange(syllabus_id=f" {_OTHER} ", reason="足す"),
            PlanChange(syllabus_id=_OTHER, reason="2回目"),  # 数えない
            PlanChange(syllabus_id=_UNKNOWN),
            PlanChange(syllabus_id=_KNOWN),
            PlanChange(syllabus_id=""),  # 空は数えない
        ],
        remove=[
            PlanChange(syllabus_id=_KNOWN, reason="外す"),
            PlanChange(syllabus_id="888888", reason="プランにだけある"),
            PlanChange(syllabus_id=_OTHER),
        ],
    )
    rows_by_id = {row["syllabus_id"]: row for row in _ROWS}

    suggestions = grounding.ground_plan_suggestions(payload, rows_by_id, [_KNOWN, "888888"])

    assert [(s.syllabus_id, s.title, s.reason) for s in suggestions.add] == [(_OTHER, "架空の科目２", "足す")]
    assert [(s.syllabus_id, s.title, s.reason) for s in suggestions.remove] == [
        (_KNOWN, "架空の反応工学１", "外す"),
        ("888888", None, "プランにだけある"),  # DB に無くてもプランにあれば外せる
    ]
    assert [(d.action, d.syllabus_id, d.reason) for d in suggestions.dropped] == [
        ("add", _UNKNOWN, "not_in_db"),
        ("add", _KNOWN, "already_in_plan"),
        ("remove", _OTHER, "not_in_plan"),
    ]


def test_course_lookup_ids_unions_cited_and_suggestions():
    payload = PlanAnswerPayload(
        answer="回答",
        cited_codes=[_KNOWN],
        add=[PlanChange(syllabus_id=_OTHER)],
        remove=[PlanChange(syllabus_id=_KNOWN), PlanChange(syllabus_id=_UNKNOWN)],
    )
    assert grounding.course_lookup_ids(payload) == [_KNOWN, _OTHER, _UNKNOWN]


# --- get_course_details（courses） ---------------------------------------------------------


def test_courses_get_course_details_returns_rows_and_not_found(fake_pool):
    result = asyncio.run(courses_tools.get_course_details([_KNOWN, _UNKNOWN, _KNOWN]))

    assert result["error"] is None
    assert result["not_found"] == [_UNKNOWN]
    assert result["skipped_ids"] == []
    assert result["courses"] == [
        {
            "syllabus_id": _KNOWN,
            "title": "架空の反応工学１",
            "instructor": "架空 花子",
            "year_range": "１〜４年次",
            "semester": "春",
            "term_schedule": "火2",
            "credits": 2.0,
            "syllabus_text": "あ" * 130,
        }
    ]
    assert fake_pool.connection.queried == [[_KNOWN, _UNKNOWN]]


def test_courses_get_course_details_caps_ids_and_truncates():
    rows = [course_row(syllabus_id=f"{index:06d}", description="い" * 1000) for index in range(22)]
    deps.set_backends(_FakePool(rows), None)
    try:
        result = asyncio.run(courses_tools.get_course_details([row["syllabus_id"] for row in rows]))
    finally:
        deps.set_backends(None, None)

    assert len(result["courses"]) == courses_tools.MAX_IDS_PER_CALL
    assert result["skipped_ids"] == ["000020", "000021"]
    assert result["courses"][0]["syllabus_text"] == "い" * courses_tools.SYLLABUS_TEXT_MAX_CHARS + "…"


def test_courses_get_course_details_without_pool_returns_error(no_backends):
    result = asyncio.run(courses_tools.get_course_details([_KNOWN]))
    assert result["courses"] == []
    assert result["error"]


# --- 関西の出典付与ノード --------------------------------------------------------------------


def test_course_sources_node_grounds_against_courses(fake_pool):
    node = nodes.course_sources_node([_KNOWN])
    payload = PlanAnswerPayload(
        answer="回答",
        cited_codes=[_KNOWN, _UNKNOWN],
        add=[PlanChange(syllabus_id=_OTHER)],
        remove=[PlanChange(syllabus_id=_KNOWN)],
    )

    event = asyncio.run(node(payload, None))

    assert node.__name__ == "attach_sources"  # node_sequence はシードの経路と同じ名前
    assert isinstance(event.output, CourseGroundedAnswer)
    assert [source.code for source in event.output.sources] == [_KNOWN]
    assert event.output.unverified_codes == [_UNKNOWN]
    assert [s.syllabus_id for s in event.output.plan_suggestions.add] == [_OTHER]
    assert [s.syllabus_id for s in event.output.plan_suggestions.remove] == [_KNOWN]
    assert fake_pool.connection.queried == [[_KNOWN, _UNKNOWN, _OTHER]]  # 1回で引く


def test_course_sources_node_without_pool_marks_all_unverified(no_backends):
    payload = PlanAnswerPayload(answer="回答", cited_codes=[_KNOWN])

    event = asyncio.run(nodes.course_sources_node([_KNOWN])(payload, None))

    assert isinstance(event.output, CourseGroundedAnswer)
    assert event.output.sources == []
    assert event.output.unverified_codes == [_KNOWN]
    assert event.output.plan_suggestions is None
    assert len(event.output.notes) == 1


# --- 関西向けのエージェントと指示文 ------------------------------------------------------------


def test_build_kansai_mcp_agent_tools_and_schema():
    shared = RecordingToolset()
    with_shared = mcp_agent.build_kansai_mcp_agent(toolset=shared, enable_mcp=True)
    fresh = mcp_agent.build_kansai_mcp_agent(enable_mcp=True)
    without_mcp = mcp_agent.build_kansai_mcp_agent(enable_mcp=False)

    assert with_shared.tools[0] is shared
    assert with_shared.tools[1] is courses_tools.get_course_details
    assert fresh.tools[0] is not shared
    assert without_mcp.tools == [courses_tools.get_course_details]
    assert with_shared.output_schema is PlanAnswerPayload
    assert with_shared.instruction == mcp_agent.load_kansai_instruction()


def test_kansai_instruction_matches_the_kansai_schema():
    text = mcp_agent.load_kansai_instruction()

    for needed in (
        "syllabus_id",
        "CourseGroup",
        "PREREQUISITE_FOR",
        "BELONGS_TO_GROUP",
        "read-cypher",
        "get_course_details(syllabus_ids=",
        "## 今のプラン",
        "準備中",
    ):
        assert needed in text
    # シードの形と、実験の DB に無い類似度の線は出さない
    for absent in ("SIMILAR_TO", "GMS-", "REQUIRES_PREREQUISITE", "COVERS_TOPIC", "Topic"):
        assert absent not in text


def test_seed_prompts_are_unchanged_for_test_endpoints():
    """/test/agent/mcp の指示文はシードの形のまま（関西の指示文は A1 だけが使う）。"""
    seed = mcp_agent.build_grounded_mcp_agent(enable_mcp=False).instruction
    assert "GMS-301" in seed
    assert "syllabus_id" not in seed


# --- McpToolset の使い回し --------------------------------------------------------------------


class _ScriptedLlm(BaseLlm):
    model: str = "scripted-fake-llm"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        call = types.FunctionCall(name="set_model_response", args={"answer": "回答", "cited_codes": [_KNOWN]})
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))


def _agent_with(toolset: RecordingToolset) -> LlmAgent:
    return LlmAgent(
        name="mcp_agent",
        model=_ScriptedLlm(),
        instruction="テスト用",
        tools=[toolset, courses_tools.get_course_details],
        output_schema=PlanAnswerPayload,
    )


@pytest.fixture
def mcp_on(monkeypatch, fake_pool):
    monkeypatch.setattr(config, "AGENT_ENABLE_MCP", True)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "dummy-key-for-routing")


def test_run_grounded_keeps_shared_toolset_open(mcp_on):
    shared = RecordingToolset()

    run = asyncio.run(
        runner.run_grounded(
            "質問",
            agent=_agent_with(shared),
            grounding_node=nodes.course_sources_node(None),
            keep_toolsets=(shared,),
        )
    )

    assert run.result.route == "mcp"
    assert run.result.node_sequence == ["route_initial", "mcp_agent", "attach_sources"]
    assert [source.code for source in run.result.sources] == [_KNOWN]
    assert isinstance(run.grounded, CourseGroundedAnswer)
    assert shared.get_tools_calls >= 1
    assert shared.close_calls == 0


def test_run_grounded_closes_per_request_toolset(mcp_on):
    fresh = RecordingToolset()

    asyncio.run(runner.run_grounded("質問", agent=_agent_with(fresh), grounding_node=nodes.course_sources_node(None)))

    assert fresh.close_calls == 1


def test_open_shared_mcp_toolset_connects_once(monkeypatch):
    toolset = RecordingToolset()
    monkeypatch.setattr(mcp_agent, "build_neo4j_toolset", lambda: toolset)

    opened = asyncio.run(mcp_agent.open_shared_mcp_toolset())

    assert opened is toolset
    assert toolset.get_tools_calls == 1
    assert toolset.close_calls == 0


def test_open_shared_mcp_toolset_does_not_stop_startup(monkeypatch, caplog):
    toolset = RecordingToolset(error=ConnectionError("架空の接続の失敗"))
    monkeypatch.setattr(mcp_agent, "build_neo4j_toolset", lambda: toolset)
    caplog.set_level(logging.WARNING, logger=mcp_agent.__name__)

    opened = asyncio.run(mcp_agent.open_shared_mcp_toolset())

    assert opened is toolset  # 起動は続け、リクエストのときに繋ぎ直す
    assert any("架空の接続の失敗" in record.getMessage() for record in caplog.records)


# --- 微修正の静的の経路（診断の答えがあるとき） -------------------------------------------------


def test_ground_plan_suggestions_with_candidates_and_locks():
    """足す科目は選べる科目の中のもの、外す科目は系統図に載らないものだけ（それ以外は理由つきで dropped）。"""
    payload = PlanAnswerPayload(
        answer="回答",
        add=[PlanChange(syllabus_id=_OTHER, reason="候補"), PlanChange(syllabus_id=_KNOWN), PlanChange(syllabus_id=_UNKNOWN)],
        remove=[PlanChange(syllabus_id="888888", reason="系統図"), PlanChange(syllabus_id="777777", reason="教養")],
    )
    rows_by_id = {row["syllabus_id"]: row for row in _ROWS}

    suggestions = grounding.ground_plan_suggestions(
        payload, rows_by_id, ["888888", "777777"], candidate_ids={_OTHER}, locked_ids={"888888"}
    )

    assert [s.syllabus_id for s in suggestions.add] == [_OTHER]
    assert [s.syllabus_id for s in suggestions.remove] == ["777777"]
    assert [(d.action, d.syllabus_id, d.reason) for d in suggestions.dropped] == [
        ("add", _KNOWN, "not_candidate"),
        ("add", _UNKNOWN, "not_in_db"),  # DB に無いものは先に not_in_db
        ("remove", "888888", "locked"),
    ]
    # 集合を渡さなければ今の照合のまま（MCP の経路）
    plain = grounding.ground_plan_suggestions(payload, rows_by_id, ["888888", "777777"])
    assert [s.syllabus_id for s in plain.add] == [_OTHER, _KNOWN]
    assert [s.syllabus_id for s in plain.remove] == ["888888", "777777"]


def test_ground_plan_suggestions_allows_moving_to_another_class():
    """系統図の科目 888888 を外す案は、同じ学期の同じ名前の別クラスを足す案が残る組なら「移す」として残す。"""
    rows_by_id = {row["syllabus_id"]: row for row in _ROWS}
    plan = ["888888", "777777"]
    pairs = {"888888": {_OTHER}, "777777": {_KNOWN}}
    kwargs = {"candidate_ids": {_OTHER, _KNOWN}, "locked_ids": {"888888"}, "move_pairs": pairs}

    moved = grounding.ground_plan_suggestions(
        PlanAnswerPayload(answer="回答", add=[PlanChange(syllabus_id=_OTHER)], remove=[PlanChange(syllabus_id="888888")]),
        rows_by_id,
        plan,
        **kwargs,
    )
    assert [s.syllabus_id for s in moved.add] == [_OTHER]
    assert [s.syllabus_id for s in moved.remove] == ["888888"]
    assert moved.dropped == []

    # 別クラスだけを足す案（元を外さない）は already_in_plan、別の科目の別クラスとの組では locked のまま
    unpaired = grounding.ground_plan_suggestions(
        PlanAnswerPayload(answer="回答", add=[PlanChange(syllabus_id=_OTHER), PlanChange(syllabus_id=_KNOWN)], remove=[PlanChange(syllabus_id="777777")]),
        rows_by_id,
        plan,
        **kwargs,
    )
    assert [s.syllabus_id for s in unpaired.add] == [_KNOWN]  # 777777 を外す組の別クラス
    assert [(d.action, d.syllabus_id, d.reason) for d in unpaired.dropped] == [("add", _OTHER, "already_in_plan")]
    wrong_pair = grounding.ground_plan_suggestions(
        PlanAnswerPayload(answer="回答", add=[PlanChange(syllabus_id=_KNOWN)], remove=[PlanChange(syllabus_id="888888"), PlanChange(syllabus_id="777777")]),
        rows_by_id,
        plan,
        **kwargs,
    )
    assert [(d.action, d.syllabus_id, d.reason) for d in wrong_pair.dropped] == [("remove", "888888", "locked")]


def test_course_sources_node_passes_candidates_and_locks(fake_pool):
    node = nodes.course_sources_node([_KNOWN], candidate_ids=set(), locked_ids={_KNOWN})
    payload = PlanAnswerPayload(
        answer="回答", add=[PlanChange(syllabus_id=_OTHER)], remove=[PlanChange(syllabus_id=_KNOWN)]
    )

    event = asyncio.run(node(payload, None))

    assert [(d.syllabus_id, d.reason) for d in event.output.plan_suggestions.dropped] == [
        (_OTHER, "not_candidate"),
        (_KNOWN, "locked"),
    ]


def test_ground_plan_suggestions_with_completed_and_registered():
    """履修済みと同じ名前の科目を足す案は completed で外す（not_candidate より先）。
    登録済みの科目を外す案は、系統図の科目でも locked にせず status=registered で残す。"""
    rows_by_id = {row["syllabus_id"]: row for row in _ROWS}
    payload = PlanAnswerPayload(
        answer="回答",
        add=[PlanChange(syllabus_id=_OTHER), PlanChange(syllabus_id=_KNOWN)],
        remove=[PlanChange(syllabus_id="888888"), PlanChange(syllabus_id="777777")],
    )

    suggestions = grounding.ground_plan_suggestions(
        payload,
        rows_by_id,
        ["888888", "777777"],
        candidate_ids={_KNOWN},
        locked_ids={"888888"},
        completed_ids={_OTHER},
        registered_ids={"888888"},
    )

    assert [s.syllabus_id for s in suggestions.add] == [_KNOWN]
    assert [(s.syllabus_id, s.status) for s in suggestions.remove] == [("888888", "registered"), ("777777", "planned")]
    assert [(d.action, d.syllabus_id, d.reason) for d in suggestions.dropped] == [("add", _OTHER, "completed")]


def test_course_sources_node_passes_completed_and_registered(fake_pool):
    node = nodes.course_sources_node([_KNOWN], candidate_ids=set(), locked_ids={_KNOWN}, completed_ids={_OTHER}, registered_ids={_KNOWN})
    payload = PlanAnswerPayload(
        answer="回答", add=[PlanChange(syllabus_id=_OTHER)], remove=[PlanChange(syllabus_id=_KNOWN)]
    )

    event = asyncio.run(node(payload, None))

    assert [(d.syllabus_id, d.reason) for d in event.output.plan_suggestions.dropped] == [(_OTHER, "completed")]
    assert [(s.syllabus_id, s.status) for s in event.output.plan_suggestions.remove] == [(_KNOWN, "registered")]


def test_build_kansai_refine_agent_has_no_tools():
    agent = mcp_agent.build_kansai_refine_agent()

    assert agent.tools == []
    assert agent.name == mcp_agent.REFINE_AGENT_NAME
    assert agent.output_schema is PlanAnswerPayload
    assert agent.instruction == mcp_agent.load_kansai_refine_instruction()


def test_kansai_refine_instruction_matches_the_block():
    from agent import plan_candidates

    text = mcp_agent.load_kansai_refine_instruction()
    for needed in ("## 今のプラン", "## 選べる科目", plan_candidates.LOCK_MARK, "合計", "準備中", "cited_codes"):
        assert needed in text
    assert plan_candidates.PLAN_HEADING.startswith("## 今のプラン")
    assert plan_candidates.CANDIDATES_HEADING.startswith("## 選べる科目")
    # 道具を持たないので、道具の名前は書かない
    for absent in ("read-cypher", "get_course_details(", "get-schema"):
        assert absent not in text


class _JsonLlm(BaseLlm):
    """道具なしの生成の偽モデル。応答の形の指定（response_schema）に合わせ、JSON の文を1回だけ返す。"""

    model: str = "json-fake-llm"
    requests: list[LlmRequest] = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        text = PlanAnswerPayload(answer="回答", cited_codes=[_KNOWN]).model_dump_json()
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=text)]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=10, candidates_token_count=5),
        )


def test_run_single_generation_calls_the_llm_once_without_tools(fake_pool):
    llm = _JsonLlm(requests=[])
    agent = LlmAgent(name="refine_agent", model=llm, instruction="テスト用", tools=[], output_schema=PlanAnswerPayload)

    run = asyncio.run(
        runner.run_single_generation("質問", agent=agent, grounding_node=nodes.course_sources_node([_KNOWN]))
    )

    assert run.result.route == "static"
    assert run.result.model == "json-fake-llm"
    assert run.result.node_sequence == ["refine_agent", "attach_sources"]
    assert run.result.tool_calls == []
    assert [source.code for source in run.result.sources] == [_KNOWN]
    assert isinstance(run.grounded, CourseGroundedAnswer)
    assert run.llm_calls == 1
    assert len(llm.requests) == 1
    assert not llm.requests[0].config.tools  # 道具を渡していない


def test_run_single_generation_refuses_agents_with_tools(fake_pool):
    agent = _agent_with(RecordingToolset())
    with pytest.raises(ValueError):
        asyncio.run(runner.run_single_generation("質問", agent=agent, grounding_node=nodes.course_sources_node(None)))
