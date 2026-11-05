"""
Neo4j Requirements & Course Prerequisite Loader

Ingests GraduationRequirement, RequirementCategory nodes, [:CLASSIFIED_AS]
classification relationships, and individual course-level [:REQUIRES_PREREQUISITE]
edges into Neo4j GraphDB using pure deterministic Cypher batches.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from neo4j import GraphDatabase, Driver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_REQUIREMENTS_JSON = (
    PROJECT_ROOT / "data" / "parsed" / "university" / "kansai" / "2026" / "bulletin_cee_requirements.json"
)

DEFAULT_NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
DEFAULT_NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
DEFAULT_NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")


def get_driver(
    uri: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> Driver:
    """Create a Neo4j driver connection."""
    u = uri or os.getenv("NEO4J_URI", DEFAULT_NEO4J_URI)
    usr = user or os.getenv("NEO4J_USER", DEFAULT_NEO4J_USER)
    pwd = password or os.getenv("NEO4J_PASSWORD", DEFAULT_NEO4J_PASSWORD)
    return GraphDatabase.driver(u, auth=(usr, pwd))


class Neo4jRequirementsLoader:
    """Loads graduation requirements and course-level prerequisites into Neo4j."""

    def __init__(self, driver: Optional[Driver] = None):
        self._external_driver = driver is not None
        self.driver = driver or get_driver()

    def close(self) -> None:
        if not self._external_driver and self.driver:
            self.driver.close()

    def load_requirements(
        self,
        json_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Load graduation requirements and prerequisite edges into Neo4j."""
        target_path = json_path or DEFAULT_REQUIREMENTS_JSON
        if not target_path.exists():
            raise FileNotFoundError(f"Requirements JSON file not found: {target_path}")

        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        grad_data = data["graduation_requirement"]
        courses_data = data["courses"]

        stats = {
            "requirement_id": grad_data["requirement_id"],
            "categories_created": 3,
            "classified_edges_created": 0,
            "prerequisites_created": 0,
        }

        with self.driver.session() as session:
            # 1. Create constraints on GraduationRequirement and RequirementCategory
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (gr:GraduationRequirement) REQUIRE gr.requirement_id IS UNIQUE;")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (rc:RequirementCategory) REQUIRE rc.category_id IS UNIQUE;")

            # 2. Merge GraduationRequirement
            session.run(
                """
                MERGE (gr:GraduationRequirement {requirement_id: $req_id})
                SET gr.academic_year = $year,
                    gr.faculty_code = $faculty_code,
                    gr.faculty_name = $faculty_name,
                    gr.department_code = $dept_code,
                    gr.department_name = $dept_name,
                    gr.total_credits = $total_credits,
                    gr.major_required_credits = $major_req_credits,
                    gr.major_elective_required_credits = $major_el_req_credits;
                """,
                {
                    "req_id": grad_data["requirement_id"],
                    "year": grad_data["academic_year"],
                    "faculty_code": grad_data["faculty_code"],
                    "faculty_name": grad_data["faculty_name"],
                    "dept_code": grad_data["department_code"],
                    "dept_name": grad_data["department_name"],
                    "total_credits": grad_data["total_credits"],
                    "major_req_credits": grad_data["major_required_credits"],
                    "major_el_req_credits": grad_data["major_elective_required_credits"],
                },
            )

            # 3. Merge RequirementCategory nodes & connect to GraduationRequirement
            categories = [
                {
                    "category_id": f"{grad_data['requirement_id']}_required",
                    "name": "専門教育_必修",
                    "type": "required",
                    "required_credits": grad_data["major_required_credits"],
                },
                {
                    "category_id": f"{grad_data['requirement_id']}_elective_required",
                    "name": "専門教育_選択必修",
                    "type": "elective_required",
                    "required_credits": grad_data["major_elective_required_credits"],
                },
                {
                    "category_id": f"{grad_data['requirement_id']}_elective",
                    "name": "専門教育_選択",
                    "type": "elective",
                    "required_credits": 0.0,
                },
            ]
            session.run(
                """
                UNWIND $categories AS cat
                MERGE (rc:RequirementCategory {category_id: cat.category_id})
                SET rc.name = cat.name,
                    rc.requirement_type = cat.type,
                    rc.required_credits = cat.required_credits
                WITH rc, cat
                MATCH (gr:GraduationRequirement {requirement_id: $req_id})
                MERGE (gr)-[:HAS_CATEGORY]->(rc);
                """,
                {"categories": categories, "req_id": grad_data["requirement_id"]},
            )

            # 4. Connect Course nodes to RequirementCategory via [:CLASSIFIED_AS]
            classifications = []
            for item in courses_data:
                req_type = item["requirement_type"]
                cat_id = f"{grad_data['requirement_id']}_{req_type}"
                for s_id in item.get("matched_syllabus_ids", []):
                    classifications.append({
                        "syllabus_id": s_id,
                        "category_id": cat_id,
                        "req_type": req_type,
                        "dept_code": grad_data["department_code"],
                    })

            if classifications:
                session.run(
                    """
                    UNWIND $batch AS c
                    MATCH (course:Course {syllabus_id: c.syllabus_id})
                    MATCH (rc:RequirementCategory {category_id: c.category_id})
                    MERGE (course)-[r:CLASSIFIED_AS {department_code: c.dept_code}]->(rc)
                    SET r.requirement_type = c.req_type;
                    """,
                    {"batch": classifications},
                )
                stats["classified_edges_created"] = len(classifications)
                logger.info("Created/merged %d [:CLASSIFIED_AS] edges", len(classifications))

            # 5. Connect individual course-level [:REQUIRES_PREREQUISITE] edges
            prereq_rules = [
                {
                    "target_name": "特別研究２",
                    "prereq_name": "特別研究１",
                    "rule": "「特別研究Ⅱ」を履修するには、「特別研究Ⅰ」を修得していること。",
                },
                {
                    "target_name": "特別研究１",
                    "prereq_name": "化学工学実験",
                    "rule": "特別研究着手要件：「化学工学実験」を修得していること。",
                },
                {
                    "target_name": "特別研究１",
                    "prereq_name": "有機化学実験",
                    "rule": "特別研究着手要件：「有機化学実験」を修得していること。",
                },
            ]
            session.run(
                """
                UNWIND $rules AS r
                MATCH (target:Course)
                WHERE target.name STARTS WITH r.target_name
                MATCH (prereq:Course)
                WHERE prereq.name STARTS WITH r.prereq_name
                MERGE (target)-[rel:REQUIRES_PREREQUISITE]->(prereq)
                SET rel.rule = r.rule, rel.is_mandatory = true;
                """,
                {"rules": prereq_rules},
            )
            stats["prerequisites_created"] = len(prereq_rules)
            logger.info("Created/merged individual course-level prerequisite rules")

        return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Load bulletin requirements and prerequisite edges into Neo4j.")
    parser.add_argument("--json", type=Path, default=DEFAULT_REQUIREMENTS_JSON, help="Path to requirements JSON")

    args = parser.parse_args()
    loader = Neo4jRequirementsLoader()
    try:
        res = loader.load_requirements(json_path=args.json)
        print(f"[SUCCESS] Loaded Neo4j requirements: {res}")
    finally:
        loader.close()


if __name__ == "__main__":
    main()
