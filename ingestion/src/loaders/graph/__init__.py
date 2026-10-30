"""
Neo4j Graph loaders, schemas, and verification tools.
"""

from typing import TYPE_CHECKING
from src.loaders.graph.schema import (
    CONSTRAINTS,
    INGEST_COURSE_GROUPS_QUERY,
    INGEST_DIPLOMA_POLICIES_QUERY,
    INGEST_GROUP_PREREQUISITES_QUERY,
    INGEST_DP_CONTRIBUTIONS_QUERY,
    INGEST_COURSE_MEMBERSHIPS_QUERY,
    INGEST_COURSES_QUERY,
)

if TYPE_CHECKING:
    from src.loaders.graph.curriculum_loader import Neo4jCurriculumLoader, GraphLoadReport
    from src.loaders.graph.verify_graph import check_all, check_course, check_groups

__all__ = [
    "CONSTRAINTS",
    "INGEST_COURSE_GROUPS_QUERY",
    "INGEST_DIPLOMA_POLICIES_QUERY",
    "INGEST_GROUP_PREREQUISITES_QUERY",
    "INGEST_DP_CONTRIBUTIONS_QUERY",
    "INGEST_COURSE_MEMBERSHIPS_QUERY",
    "INGEST_COURSES_QUERY",
    "Neo4jCurriculumLoader",
    "GraphLoadReport",
    "check_all",
    "check_course",
    "check_groups",
]


def __getattr__(name: str):
    if name in ("Neo4jCurriculumLoader", "GraphLoadReport"):
        import src.loaders.graph.curriculum_loader as cl
        return getattr(cl, name)
    if name in ("check_all", "check_course", "check_groups"):
        import src.loaders.graph.verify_graph as vg
        return getattr(vg, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
