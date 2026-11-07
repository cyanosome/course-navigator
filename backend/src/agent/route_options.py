"""画面の AI の口（POST /api/assist/ask）の型と、変種の因子に合わせた振り分け（api-contract.md 4.2）。

関西のデータで答える（E1）: 指示文は kansai_answer.md、ツールは courses を読む get_course_details、
出典の照合は syllabus_id と courses（nodes.course_sources_node）。/test/agent/mcp のシードの経路は変えない。
- route: mcp_grounded は runner.run_grounded。static は関西の静的経路が入るまで未実装（UnsupportedLevelError）。
- style: standard は関西の指示文そのまま（instruction を渡さない）。brief・detailed は同じ文に追補ファイルを足して渡す。
- verify・citations: 生成は変えない（照合は常にかかる）。画面の出し方と記録のために options に残すだけ。
- plan_context: 今のプラン（診断の結果）があれば、科目名などを courses で引いて相談の後ろに付け、
  足す・外すの提案を出させて照合する。
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
from pydantic import BaseModel, Field, StringConstraints

from agent import deps, nodes, runner
from agent.grounding import normalize_codes
from agent.schemas import CourseGroundedAnswer, PlanSuggestions
from course_core.catalog.mapping import to_float_credits
from course_core.repositories import postgres_courses_repo

__all__ = [
    "AssistIn",
    "AssistOptions",
    "AssistOut",
    "AssistRun",
    "PlanContext",
    "PlanTerm",
    "UnsupportedLevelError",
    "UnverifiedItem",
    "build_agent",
    "compose_message",
    "instruction_for",
    "plan_context_sha256",
    "plan_syllabus_ids",
    "render_plan_block",
    "run_with_options",
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

SyllabusId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class PlanTerm(BaseModel):
    """今のプランの1学期分。"""

    year: int = Field(..., ge=1, le=PLAN_YEAR_MAX)  # 学年
    term: str = Field(..., min_length=1, max_length=20)  # 学期（例 "春"・"秋"）
    syllabus_ids: list[SyllabusId] = Field(default_factory=list, max_length=PLAN_IDS_PER_TERM_MAX)


class PlanContext(BaseModel):
    """診断のプラン（A1 の任意の入力）。あれば AI は利用者の頼みに沿って足す・外すを提案する。"""

    answers_summary: str = Field("", max_length=PLAN_SUMMARY_MAX_CHARS)  # 診断の答えの短いまとめ
    terms: list[PlanTerm] = Field(default_factory=list, max_length=PLAN_TERMS_MAX)


class AssistOptions(BaseModel):
    route: Literal["mcp_grounded", "static"] = "mcp_grounded"
    style: Literal["standard", "brief", "detailed"] = "standard"
    verify: Literal["on", "off"] = "on"
    citations: Literal["cards", "text"] = "cards"


class AssistIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)  # composeQuestion の後の文
    raw_input: str | None = Field(None, max_length=2000)  # 利用者が打った文（記録用）
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
    # plan_context があり、mcp の経路で照合まで通ったときだけ埋まる（無ければ None）。
    plan_suggestions: PlanSuggestions | None = None


class UnsupportedLevelError(Exception):
    """この口でまだ動かせない水準（例 route=static は関西の静的経路が入るまで）。501 にする。"""


@dataclass(frozen=True)
class AssistRun:
    result: runner.McpAgentRunResult
    prompt_sha256: str | None  # 使った指示文の SHA-256（指示文が文字列でなければ None）
    plan_suggestions: PlanSuggestions | None = None
    toolset_reused: bool = False  # lifespan で作った McpToolset を使い回したか（偽なら1問ごとに作って閉じた）


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
    """記録（chat_response）に残す plan_context の指紋。本文（診断のまとめ）は記録に書かない。"""
    canonical = json.dumps(plan.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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


async def run_with_options(
    question: str, options: AssistOptions, plan_context: PlanContext | None = None
) -> AssistRun:
    """options に合わせて AI を1回動かす。例外は握りつぶさない（呼ぶ側が記録してから共通ハンドラへ）。"""
    if options.route == "static":
        raise UnsupportedLevelError("route=static は未実装の水準です（関西の静的経路が入るまで使えません）。")

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
    )
