"""Kansai University Transformers (Parsers) package."""

from typing import TYPE_CHECKING
from src.transformers.kansai.schema import (
    KansaiCourseDetail,
    InstructorItem,
    ScheduleSession,
    ParseReport,
)
from src.transformers.kansai.tree_schema import (
    EdgeType,
    CourseItem,
    CourseGroupNode,
    CourseGroupEdge,
    CurriculumGroupGraph,
)

if TYPE_CHECKING:
    from src.transformers.kansai.syllabus_parser import KansaiSyllabusTransformer
    from src.transformers.kansai.curriculum_tree_parser import KansaiCurriculumTreeParser

__all__ = [
    "KansaiSyllabusTransformer",
    "KansaiCourseDetail",
    "InstructorItem",
    "ScheduleSession",
    "ParseReport",
    "KansaiCurriculumTreeParser",
    "EdgeType",
    "CourseItem",
    "CourseGroupNode",
    "CourseGroupEdge",
    "CurriculumGroupGraph",
]


def __getattr__(name: str):
    if name == "KansaiSyllabusTransformer":
        import src.transformers.kansai.syllabus_parser as sp
        return getattr(sp, name)
    if name == "KansaiCurriculumTreeParser":
        import src.transformers.kansai.curriculum_tree_parser as cp
        return getattr(cp, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
