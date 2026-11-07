"""DB の行から診断の科目と系統図（Catalog）を作る。

科目の項目は B1 の写像（mapping.course_summary_from_row）で作り、画面と同じ読み方にする
（学期・曜限・配当年次の読めない値は推測で埋めない）。まとまりの線は D3 の既定の edge_types（3種すべて）。
自学部の判定（is_own_department）とまとまりの呼び名（group_name）は、画面（D3 の name・otherFaculty）と違う
（変更記録 2026-11-07 (1) と、表記の崩れの直し）。
build_catalog は I/O を持たない。load_catalog は PostgreSQL と Neo4j を読むだけ（書かない）。
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final, get_args

from course_core.catalog import mapping
from course_core.catalog.registry import DepartmentEntry, GroupMeta, GroupMetaEntry, load_group_meta
from course_core.diagnose.model import Catalog, DiagCourse, GroupInfo, normalize_text
from course_core.repositories import neo4j_curriculum_repo, postgres_diagnose_repo
from course_core.repositories.neo4j_curriculum_repo import GroupRecord
from course_core.schemas.catalog import EdgeType

if TYPE_CHECKING:  # 実行時の型は asyncpg の Connection と neo4j の AsyncSession（テストは偽物を渡す）
    import asyncpg
    from neo4j import AsyncSession

__all__ = [
    "DEFAULT_EDGE_TYPES",
    "build_catalog",
    "course_from_row",
    "group_name",
    "is_own_department",
    "load_catalog",
    "membership",
]

DEFAULT_EDGE_TYPES: Final[tuple[EdgeType, ...]] = get_args(EdgeType)
_NO_GROUP_META: Final = GroupMetaEntry()
_LABEL_BRACKET_RE: Final = re.compile(r"【([^】]+)】")
_GROUP_SUFFIX: Final = "グループ"


def is_own_department(faculties: Sequence[str], own_faculty: str) -> bool:
    """科目の対象学部（faculties の略号）が自学部だけなら真（変更記録 2026-11-07 (1)。関西のデータで 104 件）。

    略号は学部名の頭の文字（例 環 → 環境都市工学部）。全 1,029 件の対象に「環」が入るので「含む」では区別できない。
    対象が空の科目は自学部と言えないので偽。画面の otherFaculty（「含む」で判定）とは決め方が違う。
    """
    named = [faculty for faculty in faculties if faculty]
    return bool(named) and all(own_faculty.startswith(faculty) for faculty in named)


def group_name(label: str, meta_name: str | None) -> str:
    """理由の文で使うまとまりの呼び名。補足ファイルの name が先。無ければ、表記の【】の中を取り、末尾の「グループ」を外す。

    例 "【物理化学系グループ】" → "物理化学系"、"【共通教養科目グループ】（全学共通プラットフォーム）" → "共通教養科目"、
    "【特別研究Ⅰ】（4年春）" → "特別研究Ⅰ"、"フレッシュマンゼミナール" → そのまま。
    D3 の name（mapping.group_display_name）は【】の外の補足が残る3つ（G_Common・G_Research1・G_Research2）で崩れる。
    """
    if meta_name:
        return meta_name
    match = _LABEL_BRACKET_RE.search(label)
    name = (match.group(1) if match else label).strip()
    if name.endswith(_GROUP_SUFFIX) and len(name) > len(_GROUP_SUFFIX):
        name = name[: -len(_GROUP_SUFFIX)]
    return name or label


def membership(groups: Iterable[GroupRecord]) -> dict[str, str]:
    """syllabus_id → まとまり。2つ以上に属する科目は先のまとまり（学年 → group_id の順。D3 と同じ）。"""
    result: dict[str, str] = {}
    for group in groups:
        for syllabus_id in group.members:
            result.setdefault(syllabus_id, group.group_id)
    return result


def course_from_row(row: Mapping[str, Any], *, group_id: str | None, own_faculty: str) -> DiagCourse:
    """courses の1行（一覧の列＋ objectives）から診断の科目を作る。"""
    summary = mapping.course_summary_from_row(row, group_id=group_id)
    return DiagCourse(
        syllabus_id=summary.syllabus_id,
        name=summary.name,
        credits=summary.credits,
        year_min=summary.year_min,
        year_max=summary.year_max,
        term=summary.term,
        slots=tuple(summary.slots),
        slot_note=summary.slot_note,
        group_id=group_id,
        own_department=is_own_department(summary.faculties, own_faculty),
        texts={
            "name": normalize_text(summary.name),
            "summary": normalize_text(row["description"] or ""),
            "goals": normalize_text(row["objectives"] or ""),
        },
    )


def build_catalog(
    *,
    department: DepartmentEntry,
    rows: Iterable[Mapping[str, Any]],
    groups: Sequence[GroupRecord],
    edges: Iterable[Mapping[str, Any]],
    meta: GroupMeta,
) -> Catalog:
    member_of = membership(groups)
    return Catalog.build(
        department_id=department.id,
        data_version=department.data_version,
        courses=[
            course_from_row(row, group_id=member_of.get(row["syllabus_id"]), own_faculty=department.faculty)
            for row in rows
        ],
        groups=[
            GroupInfo(
                group_id=group.group_id,
                name=group_name(group.label, meta.groups.get(group.group_id, _NO_GROUP_META).name),
                academic_year=group.academic_year,
            )
            for group in groups
        ],
        edges=[(edge["source"], edge["target"]) for edge in edges],
    )


async def load_catalog(conn: asyncpg.Connection, session: AsyncSession, department: DepartmentEntry) -> Catalog:
    """学科の全科目と系統図を読む（読み取りだけ）。"""
    groups = await neo4j_curriculum_repo.fetch_groups(session, department.neo4j.faculty, department.neo4j.department)
    edges = await neo4j_curriculum_repo.fetch_group_edges(
        session, department.neo4j.faculty, department.neo4j.department, DEFAULT_EDGE_TYPES
    )
    rows = await postgres_diagnose_repo.fetch_courses_for_diagnose(conn, department.pg.academic_year)
    return build_catalog(department=department, rows=rows, groups=groups, edges=edges, meta=load_group_meta(department.id))
