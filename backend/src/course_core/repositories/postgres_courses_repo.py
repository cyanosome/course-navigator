"""courses（関西の取り込み）を読む SQL を集約するリポジトリ（読み取り専用）。

区分（course_requirements.requirement_type）は LEFT JOIN で `kind` 列として付ける。表の無い DB でも
動くよう、呼ぶ側が kinds_department_code=None を渡せば JOIN せず kind は NULL になる。
AI の出典の照合（E1）もここの fetch_courses_by_ids を使い、API と AI で同じ行の読み方にする。
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # 実行時は asyncpg を読まない（型だけ）
    import asyncpg

__all__ = [
    "count_courses",
    "fetch_course_detail",
    "fetch_courses_by_ids",
    "search_courses",
]

# 一覧の項目（CourseSummary）に要る列。description は先頭の抜き出し（lead）と AI の出典の抜粋に使う。
_SUMMARY_COLUMNS: Final = (
    "c.syllabus_id, c.academic_year, c.course_code, c.subject_name, c.subtitle, c.credits, "
    "c.year_range, c.semester, c.term_schedule, c.faculties, c.instructors, c.description, c.detail_url"
)
# 詳細（CourseDetail）で足す列。
_DETAIL_COLUMNS: Final = (
    "c.objectives, c.schedule_sessions, c.work_outside_class, c.grading_policy, c.evaluation_criteria, "
    'c.textbooks, c.textbook_notes, c."references", c.notes, c.language, c.teaching_type'
)
_KIND_JOIN: Final = (
    "LEFT JOIN course_requirements cr "
    "ON cr.syllabus_id = c.syllabus_id AND cr.department_code = $1"
)
_BULLETIN_COLUMNS: Final = (
    "cr.subject_name_bulletin AS cr_subject_name_bulletin, cr.credits AS cr_credits, "
    "cr.assigned_year AS cr_assigned_year, cr.bulletin_code AS cr_bulletin_code, "
    "cr.field_category AS cr_field_category"
)
_NO_BULLETIN_COLUMNS: Final = (
    "NULL::text AS cr_subject_name_bulletin, NULL::numeric AS cr_credits, "
    "NULL::integer AS cr_assigned_year, NULL::text AS cr_bulletin_code, "
    "NULL::text AS cr_field_category"
)


def _kind_parts(kinds_department_code: str | None) -> tuple[str, str, list[Any]]:
    """(kind の列, JOIN 句, 先頭の引数)。JOIN するときは $1 が学科コード。"""
    if kinds_department_code is None:
        return "NULL::text AS kind", "", []
    return "cr.requirement_type AS kind", _KIND_JOIN, [kinds_department_code]


async def count_courses(conn: asyncpg.Connection, academic_year: int) -> int:
    """学科の科目数（今は1学科分の取り込みなので年度で数える。api-contract.md 2.0）。"""
    return await conn.fetchval("SELECT count(*) FROM courses WHERE academic_year = $1", academic_year)


async def fetch_courses_by_ids(
    conn: asyncpg.Connection, syllabus_ids: Sequence[str], *, kinds_department_code: str | None = None
) -> list[asyncpg.Record]:
    """指定の科目の一覧の項目を1回で読む（N+1 回避）。無い ID は結果に含まれない。並びは syllabus_id の昇順。"""
    if not syllabus_ids:
        return []
    kind_col, join, args = _kind_parts(kinds_department_code)
    ids_param = f"${len(args) + 1}"
    sql = (
        f"SELECT {_SUMMARY_COLUMNS}, {kind_col} FROM courses c {join} "
        f"WHERE c.syllabus_id = ANY({ids_param}::text[]) ORDER BY c.syllabus_id"
    )
    return await conn.fetch(sql, *args, list(syllabus_ids))


async def search_courses(
    conn: asyncpg.Connection,
    *,
    academic_year: int,
    patterns: Sequence[str],
    kinds_department_code: str | None,
) -> list[asyncpg.Record]:
    """年度の科目のうち、各語の型（ilike_pattern 済み）が科目名・概要・到達目標のどれかに当たるものを全部読む。

    語どうしは AND。並べ方とほかの絞り込みは呼ぶ側（course_core.catalog.search）。
    """
    kind_col, join, args = _kind_parts(kinds_department_code)
    params: list[Any] = [*args, academic_year]
    conditions = [f"c.academic_year = ${len(params)}"]
    for pattern in patterns:
        params.append(pattern)
        placeholder = f"${len(params)}"
        conditions.append(
            "("
            + " OR ".join(
                f"c.{column} ILIKE {placeholder} ESCAPE '\\'"
                for column in ("subject_name", "description", "objectives")
            )
            + ")"
        )
    sql = (
        f"SELECT {_SUMMARY_COLUMNS}, {kind_col} FROM courses c {join} "
        f"WHERE {' AND '.join(conditions)} ORDER BY c.syllabus_id"
    )
    return await conn.fetch(sql, *params)


async def fetch_course_detail(
    conn: asyncpg.Connection, syllabus_id: str, *, kinds_department_code: str | None
) -> asyncpg.Record | None:
    """科目の詳細の1行（区分の表があれば要覧の行の列 cr_* も）。無ければ None。"""
    kind_col, join, args = _kind_parts(kinds_department_code)
    bulletin = _BULLETIN_COLUMNS if kinds_department_code is not None else _NO_BULLETIN_COLUMNS
    sql = (
        f"SELECT {_SUMMARY_COLUMNS}, {_DETAIL_COLUMNS}, {kind_col}, {bulletin} "
        f"FROM courses c {join} WHERE c.syllabus_id = ${len(args) + 1}"
    )
    return await conn.fetchrow(sql, *args, syllabus_id)
