"""卒業要件（graduation_requirements）と区分（course_requirements）を読む SQL（読み取り専用）。

表の定義は ingestion/src/loaders/postgres/schema_requirements.py。表や列の名前が変わったら、
このファイルの関数と course_core/schemas/catalog.py の型だけを直す（api-contract.md 2.6）。
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 実行時は asyncpg を読まない（型だけ）
    import asyncpg

__all__ = [
    "RequirementsTables",
    "count_course_kinds",
    "fetch_graduation_requirements",
    "requirements_tables_exist",
]


@dataclass(frozen=True)
class RequirementsTables:
    graduation: bool  # graduation_requirements があるか
    course: bool  # course_requirements があるか


async def requirements_tables_exist(conn: asyncpg.Connection) -> RequirementsTables:
    """要件の表が DB にあるか。表の無い DB（要件を取り込んでいない）でも 500 にしないために先に確かめる。"""
    row = await conn.fetchrow(
        "SELECT to_regclass('public.graduation_requirements') IS NOT NULL AS graduation, "
        "to_regclass('public.course_requirements') IS NOT NULL AS course"
    )
    return RequirementsTables(graduation=bool(row["graduation"]), course=bool(row["course"]))


async def fetch_graduation_requirements(
    conn: asyncpg.Connection, academic_year: int, faculty_code: str, department_code: str
) -> asyncpg.Record | None:
    """学科の卒業要件の1行。無ければ None。同じ学科に2行以上あればデータの誤りとして止める（どちらかを黙って選ばない）。"""
    rows = await conn.fetch(
        "SELECT * FROM graduation_requirements "
        "WHERE academic_year = $1 AND faculty_code = $2 AND department_code = $3 "
        "ORDER BY requirement_id LIMIT 2",
        academic_year,
        faculty_code,
        department_code,
    )
    if len(rows) > 1:
        raise ValueError(
            "graduation_requirements に同じ学科の行が複数あります: "
            + ", ".join(row["requirement_id"] for row in rows)
        )
    return rows[0] if rows else None


async def count_course_kinds(conn: asyncpg.Connection, department_code: str) -> dict[str, int]:
    """学科の区分ごとの科目数（requirement_type → 件数）。"""
    rows = await conn.fetch(
        "SELECT requirement_type, count(*) AS n FROM course_requirements "
        "WHERE department_code = $1 GROUP BY requirement_type",
        department_code,
    )
    return {row["requirement_type"]: int(row["n"]) for row in rows}
