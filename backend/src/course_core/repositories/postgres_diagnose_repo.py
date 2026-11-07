"""診断のエンジンが使う科目の一覧を読む SQL（読み取り専用）。

一覧の項目（CourseSummary）と同じ列に、keyword の「到達目標」（objectives）を足して、学科の全科目を1回で読む。
列は postgres_courses_repo の一覧と同じものを使う（API と診断で同じ行の読み方にする）。区分は使わないので kind は NULL。
"""

from typing import TYPE_CHECKING, Final

from course_core.repositories.postgres_courses_repo import _SUMMARY_COLUMNS

if TYPE_CHECKING:  # 実行時は asyncpg を読まない（型だけ）
    import asyncpg

__all__ = ["fetch_courses_for_diagnose"]

_FETCH_COURSES: Final = (
    f"SELECT {_SUMMARY_COLUMNS}, c.objectives, NULL::text AS kind FROM courses c "
    "WHERE c.academic_year = $1 ORDER BY c.syllabus_id"
)


async def fetch_courses_for_diagnose(conn: asyncpg.Connection, academic_year: int) -> list[asyncpg.Record]:
    """学科の全科目（今は1学科分の取り込みなので年度で読む。api-contract.md 2.0）。並びは syllabus_id の昇順。"""
    return await conn.fetch(_FETCH_COURSES, academic_year)
