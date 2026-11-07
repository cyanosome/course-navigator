"""MCP Agent に持たせる RDB（PostgreSQL）読み取りツール（関西の courses、A1 用）。

Neo4j（MCP）で見つけた候補科目について、担当教員・学期・曜限・単位数・授業の概要を
`courses` から読む（B1 の postgres_courses_repo.fetch_courses_by_ids を使い、データの API と同じ行の読み方にする）。
SELECT のみで書き込みは行わない。シードの表を読む rdb_tools.get_course_details（/test/agent/mcp 用）とは別物で、
LLM に見せる名前は同じ get_course_details、引数は syllabus_id の一覧。
ADK は関数の docstring と型ヒントからツール宣言を作るので、docstring は LLM 向けの説明を兼ねる。
"""

from collections.abc import Mapping
from typing import Any, Final

from pydantic import BaseModel, Field

from agent import deps
from agent.grounding import normalize_codes, truncate_text
from course_core.catalog.mapping import parse_instructors, primary_teacher, to_float_credits
from course_core.repositories import postgres_courses_repo

__all__ = [
    "MAX_IDS_PER_CALL",
    "SYLLABUS_TEXT_MAX_CHARS",
    "CourseDetail",
    "CourseDetailsResult",
    "get_course_details",
]

# 1回の呼び出しで LLM に返す量の上限（暴走した呼び出しで応答が膨らむのを防ぐ）。rdb_tools と同じ値。
MAX_IDS_PER_CALL: Final = 20
SYLLABUS_TEXT_MAX_CHARS: Final = 400
_UNSET_POOL_MESSAGE: Final = "PostgreSQL 接続プールが未設定のため、シラバス詳細を取得できません。"


class CourseDetail(BaseModel):
    syllabus_id: str
    title: str
    instructor: str | None = None
    year_range: str | None = None
    semester: str | None = None
    term_schedule: str | None = None
    credits: float | None = None
    syllabus_text: str = ""  # 授業の概要（description）の先頭


class CourseDetailsResult(BaseModel):
    courses: list[CourseDetail] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)  # courses に無かった syllabus_id
    skipped_ids: list[str] = Field(default_factory=list)  # 上限超過で問い合わせなかった syllabus_id
    error: str | None = None


def _detail_from_row(row: Mapping[str, Any]) -> CourseDetail:
    syllabus_id = row["syllabus_id"]
    return CourseDetail(
        syllabus_id=syllabus_id,
        title=row["subject_name"],
        instructor=primary_teacher(parse_instructors(row["instructors"], syllabus_id)),
        year_range=row["year_range"],
        semester=row["semester"],
        term_schedule=row["term_schedule"],
        credits=to_float_credits(row["credits"]),
        syllabus_text=truncate_text(row["description"], SYLLABUS_TEXT_MAX_CHARS),
    )


async def get_course_details(syllabus_ids: list[str]) -> dict[str, Any]:
    """syllabus_id の一覧を受け取り、PostgreSQL の courses にあるシラバスの詳細を返す。

    Neo4j で見つけた候補科目の syllabus_id（例: ["162246", "162249"]）をまとめて1回で渡すこと。
    course_code ではなく syllabus_id を渡す。1回に問い合わせるのは先頭20件まで（超過分は skipped_ids に入る）。

    Args:
        syllabus_ids: 科目の syllabus_id の一覧。

    Returns:
        courses: 見つかった科目の syllabus_id / title / instructor / year_range / semester /
            term_schedule / credits / syllabus_text。
        not_found: courses に無かった syllabus_id（その科目の詳細を推測で補ってはならない）。
        skipped_ids: 上限超過で問い合わせなかった syllabus_id。
        error: 取得できなかった場合の理由。
    """
    requested = normalize_codes(syllabus_ids)
    queried = requested[:MAX_IDS_PER_CALL]
    skipped = requested[MAX_IDS_PER_CALL:]

    pool = deps.db_pool()
    if pool is None:
        return CourseDetailsResult(skipped_ids=skipped, error=_UNSET_POOL_MESSAGE).model_dump()

    async with pool.acquire() as conn:
        rows = await postgres_courses_repo.fetch_courses_by_ids(conn, queried)

    found_ids = {row["syllabus_id"] for row in rows}
    return CourseDetailsResult(
        courses=[_detail_from_row(row) for row in rows],
        not_found=[syllabus_id for syllabus_id in queried if syllabus_id not in found_ids],
        skipped_ids=skipped,
    ).model_dump()
