"""
PostgreSQL loaders, schemas, and data verification tools.
"""

from typing import TYPE_CHECKING
from src.loaders.postgres.db import get_connection, get_db_config
from src.loaders.postgres.schema import create_courses_table, drop_courses_table

if TYPE_CHECKING:
    from src.loaders.postgres.verify_data import (
        get_table_stats,
        get_course_record,
        diff_with_json,
        format_course_display,
    )
    from src.loaders.postgres.loader import PostgresCourseLoader, LoadReport

__all__ = [
    "get_connection",
    "get_db_config",
    "create_courses_table",
    "drop_courses_table",
    "get_table_stats",
    "get_course_record",
    "diff_with_json",
    "format_course_display",
    "PostgresCourseLoader",
    "LoadReport",
]


def __getattr__(name: str):
    if name in (
        "get_table_stats",
        "get_course_record",
        "diff_with_json",
        "format_course_display",
    ):
        import src.loaders.postgres.verify_data as vd
        return getattr(vd, name)
    if name in ("PostgresCourseLoader", "LoadReport"):
        import src.loaders.postgres.loader as ldr
        return getattr(ldr, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
