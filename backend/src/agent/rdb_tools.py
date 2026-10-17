"""MCP Agent に持たせる RDB（PostgreSQL）読み取りツール（test3-2）。

Neo4j（MCP）で見つけた候補科目について、担当教員・開講時期・単位数・シラバス概要を
`test_postgres_syllabus` から読む。SELECT のみで書き込みは行わない。
ADK は関数の docstring と型ヒントからツール宣言を作るので、docstring は LLM 向けの説明を兼ねる。
"""

from typing import Any

from pydantic import BaseModel, Field

from agent import deps
from agent.grounding import normalize_codes, truncate_text
from course_core.repositories import postgres_repo

__all__ = [
    "MAX_CODES_PER_CALL",
    "SYLLABUS_TEXT_MAX_CHARS",
    "CourseDetail",
    "CourseDetailsResult",
    "get_course_details",
]

# 1回の呼び出しで LLM に返す量の上限（暴走した呼び出しで応答が膨らむのを防ぐ）。
MAX_CODES_PER_CALL = 20
SYLLABUS_TEXT_MAX_CHARS = 400
_UNSET_POOL_MESSAGE = (
    "PostgreSQL 接続プールが未設定のため、シラバス詳細を取得できません。"
)


class CourseDetail(BaseModel):
    code: str
    title: str
    instructor: str | None = None
    schedule: str | None = None
    credits: int | None = None
    syllabus_text: str = ""


class CourseDetailsResult(BaseModel):
    courses: list[CourseDetail] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)  # DB に存在しなかったコード
    skipped_codes: list[str] = Field(default_factory=list)  # 上限超過で問い合わせなかったコード
    error: str | None = None


async def get_course_details(codes: list[str]) -> dict[str, Any]:
    """科目コードの一覧を受け取り、PostgreSQL に登録されたシラバス詳細を返す。

    Neo4j で見つけた候補科目のコード（例: ["GMS-301", "GMS-303"]）をまとめて1回で渡すこと。
    1回に問い合わせるのは先頭20件まで（超過分は skipped_codes に入る）。

    Args:
        codes: 科目コードの一覧。

    Returns:
        courses: 見つかった科目の code / title / instructor / schedule / credits / syllabus_text。
        not_found: DB に存在しなかったコード（その科目の詳細を推測で補ってはならない）。
        skipped_codes: 上限超過で問い合わせなかったコード。
        error: 取得できなかった場合の理由。
    """
    requested = normalize_codes(codes)
    queried = requested[:MAX_CODES_PER_CALL]
    skipped = requested[MAX_CODES_PER_CALL:]

    pool = deps.db_pool()
    if pool is None:
        return CourseDetailsResult(
            skipped_codes=skipped, error=_UNSET_POOL_MESSAGE
        ).model_dump()

    async with pool.acquire() as conn:
        rows = await postgres_repo.get_syllabi_by_codes(conn, queried)

    found_codes = {row["code"] for row in rows}
    return CourseDetailsResult(
        courses=[
            CourseDetail(
                code=row["code"],
                title=row["title"],
                instructor=row["instructor"],
                schedule=row["schedule"],
                credits=row["credits"],
                syllabus_text=truncate_text(row["syllabus_text"], SYLLABUS_TEXT_MAX_CHARS),
            )
            for row in rows
        ],
        not_found=[code for code in queried if code not in found_codes],
        skipped_codes=skipped,
    ).model_dump()
