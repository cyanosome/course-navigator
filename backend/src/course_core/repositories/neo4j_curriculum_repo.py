"""系統図（CourseGroup・PREREQUISITE_FOR・BELONGS_TO_GROUP）と類似度の線を読む Cypher（読み取り専用）。

ノードと関係の定義は ingestion/src/loaders/graph/schema.py。DP は別のラベル DiplomaPolicy で、
DP への辺は CONTRIBUTES_TO なので、ここの PREREQUISITE_FOR には入らない。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # 実行時の型は neo4j の AsyncSession（テストは偽物を渡す）
    from neo4j import AsyncSession

__all__ = [
    "GroupRecord",
    "SimilarEdgeStats",
    "count_group_edges",
    "count_similar_edges",
    "fetch_course_group",
    "fetch_group_edges",
    "fetch_groups",
]

_FETCH_GROUPS: Final = """
MATCH (g:CourseGroup)
WHERE g.faculty = $faculty AND g.department = $department
OPTIONAL MATCH (c:Course)-[:BELONGS_TO_GROUP]->(g)
WITH g, collect(DISTINCT c.syllabus_id) AS members
RETURN g.group_id AS group_id, g.label AS label, g.academic_year AS academic_year,
       g.semester AS semester, members
ORDER BY g.academic_year, g.group_id
"""

_FETCH_GROUP_EDGES: Final = """
MATCH (a:CourseGroup)-[r:PREREQUISITE_FOR]->(b:CourseGroup)
WHERE a.faculty = $faculty AND a.department = $department AND r.edge_type IN $edge_types
RETURN a.group_id AS source, b.group_id AS target, r.edge_type AS edge_type, r.is_major AS is_major
ORDER BY source, target
"""

_COUNT_GROUP_EDGES: Final = """
MATCH (a:CourseGroup)-[r:PREREQUISITE_FOR]->(:CourseGroup)
WHERE a.faculty = $faculty AND a.department = $department
RETURN count(r) AS n
"""

_COUNT_SIMILAR_EDGES: Final = """
MATCH (:Course)-[r:SIMILAR_TO]->(:Course)
RETURN count(r) AS n, collect(DISTINCT r.model) AS models
"""

_FETCH_COURSE_GROUP: Final = """
MATCH (:Course {syllabus_id: $syllabus_id})-[:BELONGS_TO_GROUP]->(g:CourseGroup)
WHERE g.faculty = $faculty AND g.department = $department
RETURN g.group_id AS group_id
ORDER BY g.academic_year, g.group_id
"""


@dataclass(frozen=True)
class GroupRecord:
    group_id: str
    label: str
    academic_year: int
    semester: str | None
    members: tuple[str, ...]  # BELONGS_TO_GROUP の科目の syllabus_id（昇順）


@dataclass(frozen=True)
class SimilarEdgeStats:
    count: int
    models: tuple[str, ...]


async def _records(session: AsyncSession, query: str, **params: Any) -> list[dict[str, Any]]:
    result = await session.run(query, **params)
    return await result.data()


async def fetch_groups(session: AsyncSession, faculty: str, department: str) -> list[GroupRecord]:
    """学科のまとまり（学年 → group_id の順）と、そこに属する科目。"""
    rows = await _records(session, _FETCH_GROUPS, faculty=faculty, department=department)
    return [
        GroupRecord(
            group_id=row["group_id"],
            label=row["label"] or "",
            academic_year=int(row["academic_year"]),
            semester=row["semester"],
            members=tuple(sorted(sid for sid in row["members"] if sid)),
        )
        for row in rows
    ]


async def fetch_group_edges(
    session: AsyncSession, faculty: str, department: str, edge_types: Sequence[str]
) -> list[dict[str, Any]]:
    """まとまりどうしの線（source・target・edge_type・is_major）。edge_types の種類だけ。"""
    return await _records(
        session, _FETCH_GROUP_EDGES, faculty=faculty, department=department, edge_types=list(edge_types)
    )


async def count_group_edges(session: AsyncSession, faculty: str, department: str) -> int:
    rows = await _records(session, _COUNT_GROUP_EDGES, faculty=faculty, department=department)
    return int(rows[0]["n"]) if rows else 0


async def count_similar_edges(session: AsyncSession) -> SimilarEdgeStats:
    """DB 全体の SIMILAR_TO の本数と model の値（実験の DB に残っていないかを確かめる。制約 C8・C9）。"""
    rows = await _records(session, _COUNT_SIMILAR_EDGES)
    if not rows:
        return SimilarEdgeStats(count=0, models=())
    models = tuple(sorted(str(model) for model in rows[0]["models"] if model is not None))
    return SimilarEdgeStats(count=int(rows[0]["n"]), models=models)


async def fetch_course_group(
    session: AsyncSession, syllabus_id: str, faculty: str, department: str
) -> list[str]:
    """科目が属する学科のまとまり（学年 → group_id の順）。どこにも属さなければ []。"""
    rows = await _records(
        session, _FETCH_COURSE_GROUP, syllabus_id=syllabus_id, faculty=faculty, department=department
    )
    return [row["group_id"] for row in rows]
