"""LLM 回答の出典を DB の行から組み立てる純関数群（test3-2、関西の courses）。

出典（Source）は LLM の生成テキストではなく、cited_codes を PostgreSQL で引き直した
行だけから作る。LLM が引用したが DB に存在しないコードは unverified_codes に回し、
出典としては出さない（ハルシネーション検出）。I/O を持たないので DB 無しでテストできる。
シードの表（test_postgres_syllabus、キーは科目コード）と関西の courses（キーは syllabus_id）で
関数を分ける。courses ではプランの微修正の提案（足す・外す）も同じ行で照合する。
"""

import string
import unicodedata
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

from agent.schemas import (
    AnswerPayload,
    CourseGroundedAnswer,
    DroppedSuggestion,
    GroundedAnswer,
    PlanAnswerPayload,
    PlanSuggestion,
    PlanSuggestions,
    Source,
)
from course_core.catalog.mapping import parse_instructors, primary_teacher, to_float_credits

__all__ = [
    "COURSES_SOURCE_ORIGIN",
    "EXCERPT_MAX_CHARS",
    "SOURCE_ORIGIN",
    "build_course_grounded_answer",
    "build_grounded_answer",
    "course_lookup_ids",
    "ground_plan_suggestions",
    "normalize_codes",
    "source_from_course_row",
    "source_from_row",
    "truncate_text",
    "ungrounded_answer",
]

SOURCE_ORIGIN = "postgres:test_postgres_syllabus"
COURSES_SOURCE_ORIGIN = "postgres:courses"
EXCERPT_MAX_CHARS = 120
_SCHEDULE_SEPARATOR = " "
_NO_PLAN_NOTE = "プランが渡されていないため、LLM が出した足す・外すの提案 {count} 件を使いませんでした。"
_ELLIPSIS = "…"
# LLM が回答文の書式（例 "[GMS-303]" / "【GMS-303】"）のまま cited_codes に入れてくる括弧。
# NFKC 後に外すので全角の［］や全角空白もここで落ちる。
_CODE_STRIP_CHARS = string.whitespace + "[]【】"


def truncate_text(text: str | None, max_chars: int) -> str:
    """max_chars を超える部分を切り、切ったときだけ省略記号を付ける。"""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + _ELLIPSIS


def _normalize_code(code: str) -> str:
    """NFKC で全角英数・記号を半角に寄せ、前後の空白と括弧を外す。大文字小文字は変えない。"""
    return unicodedata.normalize("NFKC", code).strip(_CODE_STRIP_CHARS)


def normalize_codes(codes: Iterable[str]) -> list[str]:
    """各コードを正規化して空文字を捨て、出現順を保ったまま重複を除く。

    例: "[GMS-303]" / "ＧＭＳ－３０３" / " GMS-303 " はすべて "GMS-303" になる。
    """
    normalized = (_normalize_code(code) for code in codes)
    return list(dict.fromkeys(code for code in normalized if code))


def source_from_row(row: Mapping[str, Any]) -> Source:
    """test_postgres_syllabus の1行（asyncpg.Record / dict）を Source に変換する。"""
    return Source(
        code=row["code"],
        title=row["title"],
        instructor=row["instructor"],
        schedule=row["schedule"],
        credits=row["credits"],
        excerpt=truncate_text(row["syllabus_text"], EXCERPT_MAX_CHARS),
        origin=SOURCE_ORIGIN,
    )


def build_grounded_answer(
    payload: AnswerPayload, rows: Iterable[Mapping[str, Any]]
) -> GroundedAnswer:
    """cited_codes を DB の行と突き合わせ、出典と未検証コードに振り分ける。

    sources / unverified_codes はどちらも cited_codes の出現順に並ぶ。
    """
    cited = normalize_codes(payload.cited_codes)
    rows_by_code = {row["code"]: row for row in rows}
    return GroundedAnswer(
        answer=payload.answer,
        cited_codes=cited,
        sources=[source_from_row(rows_by_code[code]) for code in cited if code in rows_by_code],
        unverified_codes=[code for code in cited if code not in rows_by_code],
    )


def ungrounded_answer(payload: AnswerPayload, note: str) -> GroundedAnswer:
    """DB を引けなかったとき用。全コードを未検証に回し、理由を notes に残す。"""
    cited = normalize_codes(payload.cited_codes)
    return GroundedAnswer(
        answer=payload.answer,
        cited_codes=cited,
        unverified_codes=cited,
        notes=[note],
    )


# --- 関西の courses（キーは syllabus_id） ------------------------------------------------


def _schedule_text(semester: str | None, term_schedule: str | None) -> str | None:
    """"春" と "火2" → "春 火2"。どちらも無ければ None。"""
    parts = [part for part in (semester, term_schedule) if part]
    return _SCHEDULE_SEPARATOR.join(parts) if parts else None


def source_from_course_row(row: Mapping[str, Any]) -> Source:
    """courses の1行（postgres_courses_repo.fetch_courses_by_ids の列）を Source に変換する。

    instructors の JSON が壊れていれば ValueError（握りつぶさない。syllabus_id がメッセージに残る）。
    """
    syllabus_id = row["syllabus_id"]
    return Source(
        code=syllabus_id,
        title=row["subject_name"],
        instructor=primary_teacher(parse_instructors(row["instructors"], syllabus_id)),
        schedule=_schedule_text(row["semester"], row["term_schedule"]),
        credits=to_float_credits(row["credits"]),
        excerpt=truncate_text(row["description"], EXCERPT_MAX_CHARS),
        origin=COURSES_SOURCE_ORIGIN,
        url=row["detail_url"],
    )


def course_lookup_ids(payload: PlanAnswerPayload) -> list[str]:
    """照合のために courses で引く syllabus_id（引用・足す・外すの和。正規化して出現順）。"""
    return normalize_codes(
        [
            *payload.cited_codes,
            *(change.syllabus_id for change in payload.add),
            *(change.syllabus_id for change in payload.remove),
        ]
    )


def ground_plan_suggestions(
    payload: PlanAnswerPayload,
    rows_by_id: Mapping[str, Mapping[str, Any]],
    plan_ids: Sequence[str],
    *,
    candidate_ids: Collection[str] | None = None,
    locked_ids: Collection[str] | None = None,
    move_pairs: Mapping[str, Collection[str]] | None = None,
    completed_ids: Collection[str] | None = None,
    registered_ids: Collection[str] | None = None,
) -> PlanSuggestions:
    """足す・外すの提案を DB の行と今のプランで照合する。

    足す科目は DB に実在しプランに無いものだけ、外す科目はプランにあるものだけを残し、
    外したものは理由つきで dropped に回す。同じ科目の2回目の提案は数えない。
    診断の答えのある微修正（静的の経路）だけで使う集合（None なら見ない。MCP の経路）:
    - candidate_ids（サーバーが渡した「選べる科目」）: 足す科目はその中のものだけ（外れたら not_candidate）
    - move_pairs（プランの科目 → 同じ学期の同じ名前の別クラス）: 別クラスを足す案は、元の科目を外す案と組のときだけ
      「移す」として残す（組でなければ、同じ名前の科目がもうプランにあるので already_in_plan）
    - locked_ids（系統図に載るプランの科目）: 外す案は locked で外す。ただし移す組（別クラスを足す案が残ったもの）は残す
    - completed_ids（履修済みと同じ名前の科目）: 足す案は completed で外す（not_candidate より先に見る）
    - registered_ids（登録済みの科目）: 外す案は locked でも外さず、status を registered にして残す
    """
    plan = set(normalize_codes(plan_ids))
    pairs = move_pairs or {}
    requested_removals = {_normalize_code(change.syllabus_id) for change in payload.remove} & plan
    move_sources: dict[str, set[str]] = {}  # 別クラス → 移す元になれるプランの科目
    for plan_id, targets in pairs.items():
        for target in targets:
            move_sources.setdefault(target, set()).add(plan_id)
    add: list[PlanSuggestion] = []
    remove: list[PlanSuggestion] = []
    dropped: list[DroppedSuggestion] = []

    seen_add: set[str] = set()
    for change in payload.add:
        syllabus_id = _normalize_code(change.syllabus_id)
        if not syllabus_id or syllabus_id in seen_add:
            continue
        seen_add.add(syllabus_id)
        if syllabus_id not in rows_by_id:
            dropped.append(DroppedSuggestion(action="add", syllabus_id=syllabus_id, reason="not_in_db"))
            continue
        if syllabus_id in plan:
            dropped.append(DroppedSuggestion(action="add", syllabus_id=syllabus_id, reason="already_in_plan"))
            continue
        if completed_ids is not None and syllabus_id in completed_ids:
            dropped.append(DroppedSuggestion(action="add", syllabus_id=syllabus_id, reason="completed"))
            continue
        if candidate_ids is not None and syllabus_id not in candidate_ids:
            dropped.append(DroppedSuggestion(action="add", syllabus_id=syllabus_id, reason="not_candidate"))
            continue
        if syllabus_id in move_sources and not move_sources[syllabus_id] & requested_removals:
            dropped.append(DroppedSuggestion(action="add", syllabus_id=syllabus_id, reason="already_in_plan"))
            continue
        title = rows_by_id[syllabus_id]["subject_name"]
        add.append(PlanSuggestion(syllabus_id=syllabus_id, title=title, reason=change.reason))

    accepted_adds = {suggestion.syllabus_id for suggestion in add}
    seen_remove: set[str] = set()
    for change in payload.remove:
        syllabus_id = _normalize_code(change.syllabus_id)
        if not syllabus_id or syllabus_id in seen_remove:
            continue
        seen_remove.add(syllabus_id)
        if syllabus_id not in plan:
            dropped.append(DroppedSuggestion(action="remove", syllabus_id=syllabus_id, reason="not_in_plan"))
            continue
        moved = any(target in accepted_adds for target in pairs.get(syllabus_id, ()))
        registered = registered_ids is not None and syllabus_id in registered_ids
        if locked_ids is not None and syllabus_id in locked_ids and not moved and not registered:
            dropped.append(DroppedSuggestion(action="remove", syllabus_id=syllabus_id, reason="locked"))
            continue
        row = rows_by_id.get(syllabus_id)
        title = row["subject_name"] if row is not None else None
        remove.append(
            PlanSuggestion(
                syllabus_id=syllabus_id,
                title=title,
                reason=change.reason,
                status="registered" if registered else "planned",
            )
        )

    return PlanSuggestions(add=add, remove=remove, dropped=dropped)


def build_course_grounded_answer(
    payload: PlanAnswerPayload,
    rows: Iterable[Mapping[str, Any]],
    *,
    plan_ids: Sequence[str] | None,
    candidate_ids: Collection[str] | None = None,
    locked_ids: Collection[str] | None = None,
    move_pairs: Mapping[str, Collection[str]] | None = None,
    completed_ids: Collection[str] | None = None,
    registered_ids: Collection[str] | None = None,
) -> CourseGroundedAnswer:
    """cited_codes（syllabus_id）を courses の行と突き合わせ、出典と未検証に振り分ける。

    plan_ids（今のプランの syllabus_id）があれば、足す・外すの提案も照合して plan_suggestions に入れる
    （candidate_ids・locked_ids・move_pairs・completed_ids・registered_ids は ground_plan_suggestions のとおり）。
    無ければ plan_suggestions は None で、LLM が提案を出していたら使わなかったことを notes に残す。
    """
    cited = normalize_codes(payload.cited_codes)
    rows_by_id = {row["syllabus_id"]: row for row in rows}
    notes: list[str] = []
    plan_suggestions: PlanSuggestions | None = None
    if plan_ids is not None:
        plan_suggestions = ground_plan_suggestions(
            payload,
            rows_by_id,
            plan_ids,
            candidate_ids=candidate_ids,
            locked_ids=locked_ids,
            move_pairs=move_pairs,
            completed_ids=completed_ids,
            registered_ids=registered_ids,
        )
    elif payload.add or payload.remove:
        notes.append(_NO_PLAN_NOTE.format(count=len(payload.add) + len(payload.remove)))
    return CourseGroundedAnswer(
        answer=payload.answer,
        cited_codes=cited,
        sources=[source_from_course_row(rows_by_id[code]) for code in cited if code in rows_by_id],
        unverified_codes=[code for code in cited if code not in rows_by_id],
        notes=notes,
        plan_suggestions=plan_suggestions,
    )
