"""画面の AI の口（POST /api/assist/ask）の型と、変種の因子に合わせた振り分け（api-contract.md 4.2）。

関西のデータで答える（E1）: 指示文は kansai_answer.md、ツールは courses を読む get_course_details、
出典の照合は syllabus_id と courses（nodes.course_sources_node）。/test/agent/mcp のシードの経路は変えない。
- 経路（select_path）: plan_context に診断の答え（config_version と answers）があれば静的の経路（static）。
  道具なしの LLM を1回だけ動かす（runner.run_single_generation、指示文は kansai_refine.md）。サーバーが診断のエンジンで
  プランの学期ごとの「選べる科目」（agent.plan_candidates。点の上位・プランの科目の別クラス・頼みに名前が出た科目）を作り、
  プランの系統図の科目に「外さない（別クラスへ移すのはよい）」の印を付けて渡す。
  答えが無ければ、route=mcp_grounded は MCP の経路（runner.run_grounded）、route=static は未実装（UnsupportedLevelError）。
- style: standard は関西の指示文そのまま（instruction を渡さない）。brief・detailed は同じ文に追補ファイルを足して渡す。
- verify・citations: 生成は変えない（照合は常にかかる）。画面の出し方と記録のために options に残すだけ。
- plan_context: 今のプラン（診断の結果）があれば、科目名などを DB で引いて相談の後ろに付け、
  足す・外すの提案を出させて照合する。静的の経路では、足す科目は選べる科目の中のもの（外れたら not_candidate）、
  外す科目は系統図に載らないもの（載るものは locked）だけを残す。ただし同じ学期の同じ名前の別クラスを足す組は「移す」として残す。
- 履修の状況（plan_context の start・completed・registered。任意で、診断の答えといっしょのときだけ）: 静的の経路の
  候補づくりと照合に使う（agent.plan_candidates のとおり。履修済みと同じ名前は足す案にしない、登録済みの科目を外す案は
  status=registered で残す）。誤り（course_core.diagnose.history の検査、registered が terms の同じ学期に無い）は 422
- McpToolset: lifespan で作った1つ（deps.mcp_toolset）があれば使い回し、閉じない。無ければ1問ごとに作って閉じる。
型を course_core でなくここに置くのは、AssistOut が runner.McpAgentRunResult を継ぐため
（course_core から agent を import すると向きが逆になる）。
"""

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from google.adk.agents.llm_agent import LlmAgent
from pydantic import BaseModel, Field, StrictInt, StrictStr, StringConstraints, model_validator

from agent import deps, nodes, plan_candidates, runner
from agent.grounding import normalize_codes
from agent.schemas import CourseGroundedAnswer, PlanSuggestions
from course_core.catalog.mapping import to_float_credits
from course_core.catalog.registry import load_departments
from course_core.diagnose.answers import validate_answers
from course_core.diagnose.config import DiagnoseConfig, load_config
from course_core.diagnose.engine import DiagnoseEngine
from course_core.diagnose.history import PlanHistory, validate_history
from course_core.diagnose.model import Catalog
from course_core.diagnose.source import load_catalog
from course_core.repositories import postgres_courses_repo
from course_core.schemas.diagnose import (
    COMPLETED_MAX,
    REGISTERED_TERMS_MAX,
    HistorySyllabusId,
    RegisteredTermIn,
    TermIn,
)

__all__ = [
    "REFINE_DEPARTMENT_ID",
    "AssistIn",
    "AssistOptions",
    "AssistOut",
    "AssistPath",
    "AssistRun",
    "PlanAnswersError",
    "PlanContext",
    "PlanTerm",
    "UnsupportedLevelError",
    "UnverifiedItem",
    "build_agent",
    "build_refine_agent",
    "compose_message",
    "instruction_for",
    "load_refine_catalog",
    "load_refine_config",
    "plan_context_sha256",
    "plan_syllabus_ids",
    "refine_instruction_for",
    "render_plan_block",
    "run_with_options",
    "select_path",
]

logger = logging.getLogger(__name__)

_PROMPTS_DIR: Final = Path(__file__).resolve().parent / "prompts"
_STYLE_ADDENDUM_FILES: Final = {
    "brief": _PROMPTS_DIR / "style_brief.md",
    "detailed": _PROMPTS_DIR / "style_detailed.md",
}
_PROMPT_SEPARATOR: Final = "\n\n"

# plan_context の大きさの上限（4年分のプランが入り、LLM への入力が膨らみすぎない程度）。
PLAN_SUMMARY_MAX_CHARS: Final = 1000
PLAN_TERMS_MAX: Final = 16
PLAN_IDS_PER_TERM_MAX: Final = 40
PLAN_YEAR_MAX: Final = 8
_PLAN_HEADING: Final = "## 今のプラン（利用者の診断から作ったもの。科目名・学期・曜限・単位はサーバーが DB で引いた値）"
_PLAN_SUMMARY_PREFIX: Final = "診断のまとめ: "
_PLAN_NOT_IN_DB: Final = "（DB に無い syllabus_id）"
_PLAN_LOOKUP_FAILED: Final = "（DB を引けず確かめられませんでした）"
_PLAN_EMPTY_TERM: Final = "- （科目なし）"
# 診断の答え（plan_context.answers）の質問の数の上限（設定の質問は8問まで。知らない質問は答えの検査で断る）。
PLAN_ANSWERS_MAX: Final = 16
PLAN_CONFIG_VERSION_MAX_CHARS: Final = 64
# A1 は関西の1学科のデータで答える（指示文も関西のもの）。微修正の候補はこの学科の診断の設定と科目で作る。
REFINE_DEPARTMENT_ID: Final = "kansai-enechem-2026"

SyllabusId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
AssistPath = Literal["mcp", "static"]


class PlanTerm(BaseModel):
    """今のプランの1学期分。"""

    year: int = Field(..., ge=1, le=PLAN_YEAR_MAX)  # 学年
    term: str = Field(..., min_length=1, max_length=20)  # 学期（例 "春"・"秋"）
    syllabus_ids: list[SyllabusId] = Field(default_factory=list, max_length=PLAN_IDS_PER_TERM_MAX)


class PlanContext(BaseModel):
    """診断のプラン（A1 の任意の入力）。あれば AI は利用者の頼みに沿って足す・外すを提案する。

    config_version と answers（POST /diagnose/plan と同じ形の診断の答え）は任意で、送るなら両方とも送る。
    あれば静的の経路（道具なしの1回の生成）で、診断のエンジンの候補から選ばせる。
    start・completed・registered（POST /diagnose/plan と同じ形の履修の状況）も任意で、静的の経路だけが使う
    （診断の答えといっしょでなければ断る）。registered の科目は terms の同じ学期にも入れる。
    """

    answers_summary: str = Field("", max_length=PLAN_SUMMARY_MAX_CHARS)  # 診断の答えの短いまとめ
    terms: list[PlanTerm] = Field(default_factory=list, max_length=PLAN_TERMS_MAX)
    config_version: str | None = Field(None, min_length=1, max_length=PLAN_CONFIG_VERSION_MAX_CHARS)
    # single・multi は選択肢の id の配列、scale5 は 1〜5（schemas.diagnose.DiagnosePlanIn.answers と同じ形）
    answers: dict[str, list[StrictStr] | StrictInt] | None = Field(None, max_length=PLAN_ANSWERS_MAX)
    start: TermIn | None = None
    completed: list[HistorySyllabusId] | None = Field(None, max_length=COMPLETED_MAX)
    registered: list[RegisteredTermIn] | None = Field(None, max_length=REGISTERED_TERMS_MAX)

    @model_validator(mode="after")
    def _version_and_answers_together(self) -> "PlanContext":
        if (self.config_version is None) != (self.answers is None):
            raise ValueError("config_version と answers は両方とも送るか、両方とも送らないでください。")
        if self.answers is None and (self.start is not None or self.completed or self.registered):
            raise ValueError(
                "start・completed・registered は、診断の答え（config_version と answers）といっしょに送ってください。"
            )
        return self

    @property
    def has_answers(self) -> bool:
        return self.answers is not None


class AssistOptions(BaseModel):
    route: Literal["mcp_grounded", "static"] = "mcp_grounded"
    style: Literal["standard", "brief", "detailed"] = "standard"
    verify: Literal["on", "off"] = "on"
    citations: Literal["cards", "text"] = "cards"


class AssistIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)  # composeQuestion の後の文
    raw_input: str | None = Field(None, max_length=2000)  # 利用者が打った文（記録用。静的の経路では頼みに名前が出た科目を探す）
    client_event_id: UUID | None = None  # 対応する chat_send の event_id
    options: AssistOptions | None = None  # 開発のときだけ効く
    plan_context: PlanContext | None = None  # 今のプラン（診断の結果）。あれば足す・外すを提案する


class UnverifiedItem(BaseModel):
    code: str
    reason: Literal["not_in_db", "lookup_failed"]


class AssistOut(runner.McpAgentRunResult):
    """既存の応答（McpAgentRunResult）の全項目に、因子の当て方と照合の結果を足したもの。"""

    request_id: str
    variant_id: str | None
    options_applied: AssistOptions
    options_ignored: bool  # 送られた options を使わなかったか（調査中・開発でないとき）
    route_requested: Literal["mcp_grounded", "static"]
    unverified_items: list[UnverifiedItem]  # verify=off のときだけ埋める
    # plan_context があり、照合まで通ったときだけ埋まる（無ければ None。MCP の経路で静的 DAG に倒れたときも None）。
    plan_suggestions: PlanSuggestions | None = None


class UnsupportedLevelError(Exception):
    """この口でまだ動かせない水準（例 診断の答えの無い route=static）。501 にする。"""


class PlanAnswersError(Exception):
    """plan_context の診断の答えを使えない（版が違う 409、答えの誤り 422）。status_code で返す。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class AssistRun:
    result: runner.McpAgentRunResult
    prompt_sha256: str | None  # 使った指示文の SHA-256（指示文が文字列でなければ None）
    plan_suggestions: PlanSuggestions | None = None
    toolset_reused: bool = False  # lifespan で作った McpToolset を使い回したか（偽なら1問ごとに作って閉じた）
    path: AssistPath = "mcp"  # サーバーが選んだ経路（select_path）
    candidate_count: int | None = None  # 静的の経路で渡した選べる科目の syllabus_id の数（mcp では None）
    # candidate_count の内訳（plan_candidates.RefineContext.source_counts。top・same_name・named。mcp では None）
    candidate_sources: dict[str, int] | None = None
    llm_calls: int | None = None  # LLM の呼び出しの回数（runner.GroundedRun.llm_calls）


def _style_addendum(style: str) -> str:
    path = _STYLE_ADDENDUM_FILES[style]
    if not path.is_file():
        raise FileNotFoundError(f"文体の追補プロンプトが見つかりません: {path}")
    return path.read_text(encoding="utf-8")


def instruction_for(style: str) -> str | None:
    """style ごとの指示文。standard は None（build_kansai_mcp_agent の既定の文をそのまま使う）。"""
    if style == "standard":
        return None
    # 既定の文は mcp_agent の読み込み関数をそのまま使う（遅延 import は build_agent と同じ理由）。
    from agent.mcp_agent import load_kansai_instruction

    return _PROMPT_SEPARATOR.join((load_kansai_instruction(), _style_addendum(style)))


def build_agent(options: AssistOptions) -> LlmAgent:
    """options の style に合わせた関西向けの mcp_agent。テストはここを偽モデルの LlmAgent に差し替える。

    lifespan で作った McpToolset（deps.mcp_toolset）があればそれを持たせる。
    """
    # mcp_agent は mcp パッケージを読み込むので遅延 import にする（runner と同じ方針）。
    from agent.mcp_agent import build_kansai_mcp_agent

    return build_kansai_mcp_agent(instruction=instruction_for(options.style), toolset=deps.mcp_toolset())


def refine_instruction_for(style: str) -> str | None:
    """静的の経路の style ごとの指示文。standard は None（build_kansai_refine_agent の既定の文 kansai_refine.md）。"""
    if style == "standard":
        return None
    from agent.mcp_agent import load_kansai_refine_instruction

    return _PROMPT_SEPARATOR.join((load_kansai_refine_instruction(), _style_addendum(style)))


def build_refine_agent(options: AssistOptions) -> LlmAgent:
    """静的の経路（診断の答えがある微修正）の、道具を持たない関西向けのエージェント。テストは偽モデルに差し替える。"""
    from agent.mcp_agent import build_kansai_refine_agent

    return build_kansai_refine_agent(instruction=refine_instruction_for(options.style))


def select_path(options: AssistOptions, plan_context: PlanContext | None) -> AssistPath | None:
    """サーバーが選ぶ経路。plan_context に診断の答えがあれば static（options.route によらない）。

    答えが無ければ route=mcp_grounded は mcp。route=static は候補を作れないので None（この口では動かせない）。
    """
    if plan_context is not None and plan_context.has_answers:
        return "static"
    if options.route == "mcp_grounded":
        return "mcp"
    return None


def _prompt_sha256(agent: LlmAgent) -> str | None:
    instruction = agent.instruction
    if not isinstance(instruction, str):
        return None
    return hashlib.sha256(instruction.encode("utf-8")).hexdigest()


# --- 今のプラン（plan_context） -------------------------------------------------------------


def plan_syllabus_ids(plan: PlanContext) -> list[str]:
    """プランの全学期の syllabus_id（正規化して出現順、重複なし）。"""
    return normalize_codes(syllabus_id for term in plan.terms for syllabus_id in term.syllabus_ids)


def plan_context_sha256(plan: PlanContext) -> str:
    """記録（chat_response）に残す plan_context の指紋。本文（診断のまとめ）は記録に書かない。

    送られなかった任意の項目（config_version・answers）は指紋に入れない（診断の答えを足す前の指紋と同じになる）。
    """
    canonical = json.dumps(
        plan.model_dump(exclude_none=True), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _course_line(syllabus_id: str, row: Mapping[str, Any] | None, lookup_ok: bool) -> str:
    if not lookup_ok:
        return f"- {syllabus_id}{_PLAN_LOOKUP_FAILED}"
    if row is None:
        return f"- {syllabus_id}{_PLAN_NOT_IN_DB}"
    details = [part for part in (row["semester"], row["term_schedule"]) if part]
    credits = to_float_credits(row["credits"])
    if credits is not None:
        details.append(f"{credits:g}単位")
    suffix = f"（{' '.join(details)}）" if details else ""
    return f"- {syllabus_id} {row['subject_name']}{suffix}"


def render_plan_block(plan: PlanContext, rows: Sequence[Mapping[str, Any]] | None) -> str:
    """今のプランを LLM に渡す文にする。rows は courses の行（DB を引けなかったときは None）。"""
    rows_by_id = {row["syllabus_id"]: row for row in rows or ()}
    lines = [_PLAN_HEADING]
    if plan.answers_summary.strip():
        lines.append(_PLAN_SUMMARY_PREFIX + plan.answers_summary.strip())
    for term in plan.terms:
        lines.append(f"### {term.year}年 {term.term}")
        term_ids = normalize_codes(term.syllabus_ids)
        if not term_ids:
            lines.append(_PLAN_EMPTY_TERM)
        lines.extend(_course_line(sid, rows_by_id.get(sid), rows is not None) for sid in term_ids)
    return "\n".join(lines)


def compose_message(question: str, plan_block: str | None) -> str:
    """LLM への入力。プランがあれば相談の後ろに付ける（指示文は変えないので prompt_sha256 は変わらない）。"""
    if plan_block is None:
        return question
    return question + _PROMPT_SEPARATOR + plan_block


async def _fetch_plan_rows(syllabus_ids: Sequence[str]) -> list[Mapping[str, Any]] | None:
    """プランの科目の行を courses から1回で読む。プールが無ければ None（プランの文に「確かめられなかった」と出す）。"""
    pool = deps.db_pool()
    if pool is None:
        logger.warning("PostgreSQL 接続プールが未設定のため、プランの科目名を引けませんでした。")
        return None
    async with pool.acquire() as conn:
        return list(await postgres_courses_repo.fetch_courses_by_ids(conn, syllabus_ids))


def load_refine_config(department_id: str) -> DiagnoseConfig:
    """静的の経路で使う、いま有効な診断の設定。テストは架空の設定に差し替える。"""
    return load_config(department_id).config


async def load_refine_catalog(department_id: str) -> Catalog:
    """静的の経路で使う学科の科目と系統図（POST /diagnose/plan と同じ読み方。読み取りだけ）。テストは差し替える。"""
    pool, driver = deps.db_pool(), deps.neo4j_driver()
    if pool is None or driver is None:
        raise RuntimeError("PostgreSQL か Neo4j が未設定のため、微修正の候補を作れません（deps.set_backends）。")
    department = load_departments()[department_id]
    async with pool.acquire() as conn, driver.session() as session:
        return await load_catalog(conn, session, department)


def _registered_outside_the_plan(plan_context: PlanContext, history: PlanHistory) -> list[str]:
    """登録済みの科目のうち、plan_context.terms の同じ学期に無いもの（出現順）。"""
    in_plan = {
        (term.year, term.term, syllabus_id)
        for term in plan_context.terms
        for syllabus_id in normalize_codes(term.syllabus_ids)
    }
    return [
        course.syllabus_id
        for term, courses in history.registered.items()
        for course in courses
        if (term.year, term.term, course.syllabus_id) not in in_plan
    ]


async def _refine_context(plan_context: PlanContext, request_text: str) -> plan_candidates.RefineContext:
    """診断の答えと履修の状況を検査し、診断のエンジンで選べる科目と系統図の科目の印を作る。使えない答えは PlanAnswersError。"""
    config = load_refine_config(REFINE_DEPARTMENT_ID)
    if plan_context.config_version != config.version:
        raise PlanAnswersError(
            409,
            f"診断の設定の版が違います（送られた版 {plan_context.config_version}、いまの版 {config.version}）。",
        )
    answers, errors = validate_answers(config, plan_context.answers or {})
    if errors:
        raise PlanAnswersError(422, "診断の答えに誤りがあります: " + "; ".join(errors))
    catalog = await load_refine_catalog(REFINE_DEPARTMENT_ID)
    history, history_errors = validate_history(
        config,
        catalog,
        start=plan_context.start,
        completed=plan_context.completed,
        registered=plan_context.registered,
    )
    if not history_errors and (outside := _registered_outside_the_plan(plan_context, history)):
        history_errors = [f"registered の科目が terms の同じ学期にありません: {', '.join(outside)}"]
    if history_errors:
        raise PlanAnswersError(422, "履修の状況に誤りがあります: " + "; ".join(history_errors))
    return plan_candidates.build_refine_context(
        engine=DiagnoseEngine(config, catalog),
        catalog=catalog,
        answers=answers,
        answers_summary=plan_context.answers_summary,
        terms=plan_context.terms,
        request_text=request_text,
        history=history,
    )


async def _run_static(question: str, options: AssistOptions, plan_context: PlanContext, request_text: str) -> AssistRun:
    """静的の経路: 道具なしの LLM を1回動かし、選べる科目と系統図の科目の印（と移す組）で照合する。"""
    context = await _refine_context(plan_context, request_text)
    candidate_ids = context.candidate_ids
    agent = build_refine_agent(options)
    run = await runner.run_single_generation(
        compose_message(question, context.block),
        agent=agent,
        grounding_node=nodes.course_sources_node(
            context.plan_ids,
            candidate_ids=candidate_ids,
            locked_ids=context.locked_ids,
            move_pairs=context.move_pairs,
            completed_ids=context.completed_ids,
            registered_ids=context.registered_ids,
        ),
    )
    grounded = run.grounded
    return AssistRun(
        result=run.result,
        prompt_sha256=_prompt_sha256(agent),
        plan_suggestions=grounded.plan_suggestions if isinstance(grounded, CourseGroundedAnswer) else None,
        path="static",
        candidate_count=len(candidate_ids),
        candidate_sources=context.source_counts,
        llm_calls=run.llm_calls,
    )


async def run_with_options(
    question: str,
    options: AssistOptions,
    plan_context: PlanContext | None = None,
    request_text: str | None = None,
) -> AssistRun:
    """options と plan_context に合わせて AI を1回動かす。例外は握りつぶさない（呼ぶ側が記録してから共通ハンドラへ）。

    request_text は頼みに名前が出た科目を探す文（利用者が打った文。無ければ question）。静的の経路だけが使う。
    """
    path = select_path(options, plan_context)
    if path is None:
        raise UnsupportedLevelError(
            "route=static は、plan_context に診断の答え（config_version と answers）があるときだけ使えます。"
        )
    if path == "static" and plan_context is not None:
        return await _run_static(question, options, plan_context, request_text or question)

    plan_ids: list[str] | None = None
    plan_block: str | None = None
    if plan_context is not None:
        plan_ids = plan_syllabus_ids(plan_context)
        plan_block = render_plan_block(plan_context, await _fetch_plan_rows(plan_ids))

    agent = build_agent(options)
    shared = deps.mcp_toolset()
    reused = shared is not None and any(tool is shared for tool in agent.tools)
    run = await runner.run_grounded(
        compose_message(question, plan_block),
        agent=agent,
        grounding_node=nodes.course_sources_node(plan_ids),
        keep_toolsets=(shared,) if reused else (),
    )
    grounded = run.grounded
    plan_suggestions = grounded.plan_suggestions if isinstance(grounded, CourseGroundedAnswer) else None
    return AssistRun(
        result=run.result,
        prompt_sha256=_prompt_sha256(agent),
        plan_suggestions=plan_suggestions,
        toolset_reused=reused,
        path="mcp",
        llm_calls=run.llm_calls,
    )
