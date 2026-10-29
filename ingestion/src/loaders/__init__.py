"""Data Loaders for Course Navigator.

Responsible for ingesting structured course and curriculum data into target databases
(e.g., Neo4j Graph Database, PostgreSQL Relational Database).
"""

from src.loaders.graph.loader import (
    get_driver,
    ensure_constraints,
    load_courses_batch,
    load_from_file,
)

__all__ = [
    "get_driver",
    "ensure_constraints",
    "load_courses_batch",
    "load_from_file",
]
