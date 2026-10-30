"""
Neo4j Curriculum & Course Graph Loader.

Ingests the Curriculum Tree DAG (CourseGroups, DiplomaPolicies, prerequisite relationships)
and detailed Course nodes with instructor/department/faculty relationships into Neo4j.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase, Driver, Session

from src.loaders.graph.schema import (
    CONSTRAINTS,
    INGEST_COURSE_GROUPS_QUERY,
    INGEST_DIPLOMA_POLICIES_QUERY,
    INGEST_GROUP_PREREQUISITES_QUERY,
    INGEST_DP_CONTRIBUTIONS_QUERY,
    INGEST_COURSE_MEMBERSHIPS_QUERY,
    INGEST_COURSES_QUERY,
    INGEST_COURSE_PROFESSORS_QUERY,
    INGEST_COURSE_DEPARTMENTS_QUERY,
    INGEST_COURSE_FACULTIES_QUERY,
)

logger = logging.getLogger(__name__)

# Base directory paths (points to ingestion/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_TREE_FILE = (
    BASE_DIR
    / "data"
    / "parsed"
    / "university"
    / "kansai"
    / "2026"
    / "curriculum_group_graph.json"
)
DEFAULT_COURSES_FILE = (
    BASE_DIR
    / "data"
    / "parsed"
    / "university"
    / "kansai"
    / "2026"
    / "courses_detail.json"
)


@dataclass
class GraphLoadReport:
    """Detailed summary of the Neo4j graph loading process."""
    courses_total: int = 0
    courses_loaded: int = 0
    groups_loaded: int = 0
    dp_loaded: int = 0
    prerequisites_loaded: int = 0
    dp_contributions_loaded: int = 0
    memberships_loaded: int = 0
    elapsed_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "courses_total": self.courses_total,
            "courses_loaded": self.courses_loaded,
            "groups_loaded": self.groups_loaded,
            "dp_loaded": self.dp_loaded,
            "prerequisites_loaded": self.prerequisites_loaded,
            "dp_contributions_loaded": self.dp_contributions_loaded,
            "memberships_loaded": self.memberships_loaded,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "errors": self.errors,
        }


class Neo4jCurriculumLoader:
    """Loader for Curriculum Tree DAG and Course Nodes in Neo4j."""

    def __init__(
        self,
        driver: Optional[Driver] = None,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        if driver is not None:
            self._driver = driver
            self._owns_driver = False
        else:
            self._uri = uri or os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
            self._user = user or os.getenv("NEO4J_USER", "neo4j")
            self._password = password or os.getenv(
                "NEO4J_PASSWORD", "secure_password_please_change"
            )
            self._driver = GraphDatabase.driver(
                self._uri, auth=(self._user, self._password)
            )
            self._owns_driver = True

    def close(self) -> None:
        """Close driver connection if created internally."""
        if self._owns_driver and self._driver is not None:
            self._driver.close()

    def __enter__(self) -> Neo4jCurriculumLoader:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def ensure_constraints(self, session: Session) -> None:
        """Ensure all required uniqueness constraints and indexes exist in Neo4j."""
        logger.info("Applying Neo4j schema constraints and indexes...")
        for query in CONSTRAINTS:
            logger.debug("Executing constraint: %s", query)
            session.run(query).consume()
        logger.info("Schema constraints successfully verified/applied.")

    def clear_kansai_graph(
        self,
        session: Session,
        faculty: str = "環境都市工学部",
        department: str = "エネルギー環境・化学工学科",
    ) -> Dict[str, int]:
        """Delete CourseGroup, DiplomaPolicy, and Course nodes for a specific department."""
        logger.warning(
            "Clearing graph data for faculty='%s', department='%s'...",
            faculty,
            department,
        )
        delete_groups_query = """
        MATCH (cg:CourseGroup)
        WHERE cg.faculty = $faculty OR cg.department = $department
        DETACH DELETE cg
        """
        delete_dp_query = """
        MATCH (dp:DiplomaPolicy)
        WHERE dp.faculty = $faculty OR dp.department = $department
        DETACH DELETE dp
        """
        res_groups = session.run(
            delete_groups_query, faculty=faculty, department=department
        ).consume()
        res_dp = session.run(
            delete_dp_query, faculty=faculty, department=department
        ).consume()

        logger.info(
            "Cleared nodes: CourseGroup deleted=%d, DiplomaPolicy deleted=%d",
            res_groups.counters.nodes_deleted,
            res_dp.counters.nodes_deleted,
        )
        return {
            "groups_deleted": res_groups.counters.nodes_deleted,
            "dp_deleted": res_dp.counters.nodes_deleted,
        }

    def load_courses(
        self,
        session: Session,
        courses_path: Path,
        batch_size: int = 500,
    ) -> Dict[str, int]:
        """Load detailed course records from JSON into Neo4j in batches."""
        if not courses_path.exists():
            raise FileNotFoundError(f"Courses JSON file not found: {courses_path}")

        logger.info("Reading courses JSON from %s", courses_path)
        with open(courses_path, "r", encoding="utf-8") as f:
            courses_data: List[Dict[str, Any]] = json.load(f)

        total_courses = len(courses_data)
        logger.info(
            "Ingesting %d courses in batches of %d...", total_courses, batch_size
        )

        loaded_courses = 0
        for i in range(0, total_courses, batch_size):
            batch = courses_data[i : i + batch_size]
            # 1. Upsert course core nodes
            session.run(INGEST_COURSES_QUERY, batch=batch).consume()
            # 2. Link instructors
            session.run(INGEST_COURSE_PROFESSORS_QUERY, batch=batch).consume()
            # 3. Link departments
            session.run(INGEST_COURSE_DEPARTMENTS_QUERY, batch=batch).consume()
            # 4. Link faculties
            session.run(INGEST_COURSE_FACULTIES_QUERY, batch=batch).consume()

            loaded_courses += len(batch)
            logger.info("Loaded courses batch: %d / %d", loaded_courses, total_courses)

        return {"courses_total": total_courses, "courses_loaded": loaded_courses}

    def load_curriculum_groups(
        self,
        session: Session,
        tree_path: Path,
        faculty: Optional[str] = None,
        department: Optional[str] = None,
    ) -> Dict[str, int]:
        """Load curriculum DAG (groups, DPs, edges, memberships) from JSON into Neo4j."""
        if not tree_path.exists():
            raise FileNotFoundError(f"Curriculum tree JSON not found: {tree_path}")

        logger.info("Reading curriculum group graph JSON from %s", tree_path)
        with open(tree_path, "r", encoding="utf-8") as f:
            tree_data: Dict[str, Any] = json.load(f)

        univ_faculty = faculty or tree_data.get("faculty", "環境都市工学部")
        univ_dept = department or tree_data.get("department", "エネルギー環境・化学工学科")

        raw_groups = tree_data.get("groups", [])
        raw_edges = tree_data.get("edges", [])

        # Separate CourseGroups and DiplomaPolicies
        course_groups: List[Dict[str, Any]] = []
        diploma_policies: List[Dict[str, Any]] = []
        memberships: List[Dict[str, Any]] = []

        for g in raw_groups:
            gid = g.get("group_id", "")
            if gid.startswith("DP"):
                diploma_policies.append({"code": gid, "name": g.get("label", gid)})
            else:
                course_groups.append(
                    {
                        "group_id": gid,
                        "label": g.get("label", ""),
                        "academic_year": g.get("academic_year", 0),
                        "semester": g.get("semester"),
                    }
                )
                for member in g.get("member_courses", []):
                    sid = member.get("syllabus_id")
                    if sid:
                        memberships.append(
                            {
                                "group_id": gid,
                                "syllabus_id": str(sid),
                                "course_code": member.get("course_code"),
                                "subject_name": member.get("normalized_name")
                                or member.get("raw_name"),
                            }
                        )

        # Separate group prerequisite edges and DP contribution edges
        prereq_edges: List[Dict[str, Any]] = []
        dp_edges: List[Dict[str, Any]] = []

        for e in raw_edges:
            target_id = e.get("target_group_id", "")
            edge_type = e.get("edge_type", "")
            if target_id.startswith("DP") or edge_type == "dp_contribution":
                dp_edges.append(
                    {
                        "source_group_id": e.get("source_group_id"),
                        "target_group_id": target_id,
                        "edge_type": edge_type or "dp_contribution",
                    }
                )
            else:
                prereq_edges.append(
                    {
                        "source_group_id": e.get("source_group_id"),
                        "target_group_id": target_id,
                        "edge_type": edge_type or "prerequisite",
                        "is_major_connection": bool(e.get("is_major_connection", True)),
                    }
                )

        logger.info(
            "Ingesting %d CourseGroups, %d DiplomaPolicies, %d Prerequisite edges, "
            "%d DP Contribution edges, and %d Memberships...",
            len(course_groups),
            len(diploma_policies),
            len(prereq_edges),
            len(dp_edges),
            len(memberships),
        )

        # 1. Upsert CourseGroups
        session.run(
            INGEST_COURSE_GROUPS_QUERY,
            groups=course_groups,
            faculty=univ_faculty,
            department=univ_dept,
        ).consume()

        # 2. Upsert DiplomaPolicies
        session.run(
            INGEST_DIPLOMA_POLICIES_QUERY,
            dps=diploma_policies,
            faculty=univ_faculty,
            department=univ_dept,
        ).consume()

        # 3. Create PREREQUISITE_FOR edges between groups
        session.run(
            INGEST_GROUP_PREREQUISITES_QUERY,
            edges=prereq_edges,
        ).consume()

        # 4. Create CONTRIBUTES_TO edges between groups and DPs
        session.run(
            INGEST_DP_CONTRIBUTIONS_QUERY,
            dp_edges=dp_edges,
        ).consume()

        # 5. Create BELONGS_TO_GROUP edges between courses and groups
        session.run(
            INGEST_COURSE_MEMBERSHIPS_QUERY,
            memberships=memberships,
        ).consume()

        return {
            "groups_loaded": len(course_groups),
            "dp_loaded": len(diploma_policies),
            "prerequisites_loaded": len(prereq_edges),
            "dp_contributions_loaded": len(dp_edges),
            "memberships_loaded": len(memberships),
        }

    def load_all(
        self,
        tree_path: Path,
        courses_path: Path,
        batch_size: int = 500,
        clear_first: bool = False,
        faculty: Optional[str] = None,
        department: Optional[str] = None,
    ) -> GraphLoadReport:
        """Run the full ingestion pipeline: constraints, courses, and curriculum groups."""
        start_time = time.time()
        report = GraphLoadReport()

        with self._driver.session() as session:
            # Step 1: Ensure constraints
            self.ensure_constraints(session)

            # Step 2: Clear if requested
            if clear_first:
                self.clear_kansai_graph(
                    session,
                    faculty=faculty or "環境都市工学部",
                    department=department or "エネルギー環境・化学工学科",
                )

            # Step 3: Load courses first so course nodes exist
            courses_summary = self.load_courses(
                session, courses_path=courses_path, batch_size=batch_size
            )
            report.courses_total = courses_summary["courses_total"]
            report.courses_loaded = courses_summary["courses_loaded"]

            # Step 4: Load curriculum groups, edges, and memberships
            groups_summary = self.load_curriculum_groups(
                session,
                tree_path=tree_path,
                faculty=faculty,
                department=department,
            )
            report.groups_loaded = groups_summary["groups_loaded"]
            report.dp_loaded = groups_summary["dp_loaded"]
            report.prerequisites_loaded = groups_summary["prerequisites_loaded"]
            report.dp_contributions_loaded = groups_summary["dp_contributions_loaded"]
            report.memberships_loaded = groups_summary["memberships_loaded"]

        report.elapsed_seconds = time.time() - start_time
        logger.info("Neo4j graph ingestion completed successfully: %s", report.to_dict())
        return report


def main() -> None:
    """CLI entry point for loading Kansai University curriculum & courses into Neo4j."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Load Kansai University curriculum tree DAG and courses into Neo4j."
    )
    parser.add_argument(
        "--tree",
        type=Path,
        default=DEFAULT_TREE_FILE,
        help=f"Path to curriculum_group_graph.json (default: {DEFAULT_TREE_FILE})",
    )
    parser.add_argument(
        "--courses",
        type=Path,
        default=DEFAULT_COURSES_FILE,
        help=f"Path to courses_detail.json (default: {DEFAULT_COURSES_FILE})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for course nodes ingestion (default: 500)",
    )
    parser.add_argument(
        "--clear-first",
        action="store_true",
        help="Clear existing department curriculum graph before loading",
    )
    parser.add_argument(
        "--faculty",
        type=str,
        default="環境都市工学部",
        help="Target faculty name (default: 環境都市工学部)",
    )
    parser.add_argument(
        "--department",
        type=str,
        default="エネルギー環境・化学工学科",
        help="Target department name (default: エネルギー環境・化学工学科)",
    )

    args = parser.parse_args()

    with Neo4jCurriculumLoader() as loader:
        report = loader.load_all(
            tree_path=args.tree,
            courses_path=args.courses,
            batch_size=args.batch_size,
            clear_first=args.clear_first,
            faculty=args.faculty,
            department=args.department,
        )
        print("\n=== Neo4j Curriculum & Course Ingestion Summary ===")
        print(f"Courses Loaded:          {report.courses_loaded} / {report.courses_total}")
        print(f"Course Groups Loaded:    {report.groups_loaded}")
        print(f"Diploma Policies Loaded: {report.dp_loaded}")
        print(f"Prerequisite Edges:      {report.prerequisites_loaded}")
        print(f"DP Contribution Edges:   {report.dp_contributions_loaded}")
        print(f"Course Memberships:      {report.memberships_loaded}")
        print(f"Elapsed Time:            {report.elapsed_seconds:.2f}s")


if __name__ == "__main__":
    main()
