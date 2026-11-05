"""
PostgreSQL Requirements Loader

Loads graduation_requirements and course_requirements from structured JSON
into PostgreSQL tables with transactional integrity and idempotent Upsert.
"""

import sys
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
import psycopg
from psycopg.types.json import Jsonb

from src.loaders.postgres.db import get_connection
from src.loaders.postgres.schema_requirements import create_requirements_tables

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_REQUIREMENTS_JSON = (
    PROJECT_ROOT / "data" / "parsed" / "university" / "kansai" / "2026" / "bulletin_cee_requirements.json"
)


class PostgresRequirementsLoader:
    """Loads graduation requirements and course classifications into PostgreSQL."""

    def __init__(self, conn: Optional[psycopg.Connection] = None):
        self._external_conn = conn is not None
        self.conn = conn or get_connection()

    def close(self) -> None:
        if not self._external_conn and self.conn and not self.conn.closed:
            self.conn.close()

    def load_requirements(
        self,
        json_path: Optional[Path] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Load graduation and course requirements from JSON into DB."""
        target_path = json_path or DEFAULT_REQUIREMENTS_JSON
        if not target_path.exists():
            raise FileNotFoundError(f"Requirements JSON file not found: {target_path}")

        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        grad_data = data["graduation_requirement"]
        courses_data = data["courses"]

        # Ensure schema tables exist
        create_requirements_tables(self.conn)

        stats = {
            "graduation_requirement_id": grad_data["requirement_id"],
            "courses_total": len(courses_data),
            "course_requirements_inserted": 0,
            "dry_run": dry_run,
        }

        try:
            with self.conn.cursor() as cur:
                # 1. Upsert graduation_requirements
                cur.execute(
                    """
                    INSERT INTO graduation_requirements (
                        requirement_id, academic_year, faculty_code, faculty_name,
                        department_code, department_name, total_credits,
                        general_education_credits, general_designated_credits,
                        foreign_language_credits, foreign_lang_first_credits, foreign_lang_second_credits,
                        major_credits, major_required_credits, major_elective_required_credits,
                        thesis_requirements, rules_notes
                    ) VALUES (
                        %(requirement_id)s, %(academic_year)s, %(faculty_code)s, %(faculty_name)s,
                        %(department_code)s, %(department_name)s, %(total_credits)s,
                        %(general_education_credits)s, %(general_designated_credits)s,
                        %(foreign_language_credits)s, %(foreign_lang_first_credits)s, %(foreign_lang_second_credits)s,
                        %(major_credits)s, %(major_required_credits)s, %(major_elective_required_credits)s,
                        %(thesis_requirements)s, %(rules_notes)s
                    )
                    ON CONFLICT (requirement_id) DO UPDATE SET
                        total_credits = EXCLUDED.total_credits,
                        general_education_credits = EXCLUDED.general_education_credits,
                        general_designated_credits = EXCLUDED.general_designated_credits,
                        foreign_language_credits = EXCLUDED.foreign_language_credits,
                        foreign_lang_first_credits = EXCLUDED.foreign_lang_first_credits,
                        foreign_lang_second_credits = EXCLUDED.foreign_lang_second_credits,
                        major_credits = EXCLUDED.major_credits,
                        major_required_credits = EXCLUDED.major_required_credits,
                        major_elective_required_credits = EXCLUDED.major_elective_required_credits,
                        thesis_requirements = EXCLUDED.thesis_requirements,
                        rules_notes = EXCLUDED.rules_notes;
                    """,
                    {
                        "requirement_id": grad_data["requirement_id"],
                        "academic_year": grad_data["academic_year"],
                        "faculty_code": grad_data["faculty_code"],
                        "faculty_name": grad_data["faculty_name"],
                        "department_code": grad_data["department_code"],
                        "department_name": grad_data["department_name"],
                        "total_credits": grad_data["total_credits"],
                        "general_education_credits": grad_data["general_education_credits"],
                        "general_designated_credits": grad_data["general_designated_credits"],
                        "foreign_language_credits": grad_data["foreign_language_credits"],
                        "foreign_lang_first_credits": grad_data["foreign_lang_first_credits"],
                        "foreign_lang_second_credits": grad_data["foreign_lang_second_credits"],
                        "major_credits": grad_data["major_credits"],
                        "major_required_credits": grad_data["major_required_credits"],
                        "major_elective_required_credits": grad_data["major_elective_required_credits"],
                        "thesis_requirements": Jsonb(grad_data["thesis_requirements"]),
                        "rules_notes": grad_data.get("rules_notes", []),
                    },
                )
                logger.info("Upserted graduation requirement: %s", grad_data["requirement_id"])

                # 2. Upsert course_requirements
                # Flatten courses matching syllabus_ids
                records_to_insert = []
                for item in courses_data:
                    req_type = item["requirement_type"]
                    dept_code = grad_data["department_code"]
                    dept_name = grad_data["department_name"]
                    name_bulletin = item["subject_name_bulletin"]
                    credits_val = item["credits"]
                    assigned_year = item.get("assigned_year")
                    bulletin_code = item.get("bulletin_code")
                    field_cat = item.get("field_category")

                    for s_id in item.get("matched_syllabus_ids", []):
                        records_to_insert.append((
                            s_id,
                            dept_code,
                            dept_name,
                            name_bulletin,
                            req_type,
                            credits_val,
                            assigned_year,
                            bulletin_code,
                            field_cat,
                        ))

                if records_to_insert:
                    cur.executemany(
                        """
                        INSERT INTO course_requirements (
                            syllabus_id, department_code, department_name,
                            subject_name_bulletin, requirement_type, credits,
                            assigned_year, bulletin_code, field_category
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (syllabus_id, department_code) DO UPDATE SET
                            subject_name_bulletin = EXCLUDED.subject_name_bulletin,
                            requirement_type = EXCLUDED.requirement_type,
                            credits = EXCLUDED.credits,
                            assigned_year = EXCLUDED.assigned_year,
                            bulletin_code = EXCLUDED.bulletin_code,
                            field_category = EXCLUDED.field_category;
                        """,
                        records_to_insert,
                    )
                    stats["course_requirements_inserted"] = len(records_to_insert)
                    logger.info("Upserted %d course_requirements records", len(records_to_insert))

                if dry_run:
                    self.conn.rollback()
                    logger.info("Dry-run requested: all changes rolled back.")
                else:
                    self.conn.commit()
                    logger.info("Transaction successfully committed.")

        except Exception as e:
            self.conn.rollback()
            logger.error("Error during requirements load: %s", e)
            raise

        return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Load bulletin graduation and course requirements into PostgreSQL.")
    parser.add_argument("--json", type=Path, default=DEFAULT_REQUIREMENTS_JSON, help="Path to requirements JSON")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without committing")

    args = parser.parse_args()
    loader = PostgresRequirementsLoader()
    try:
        res = loader.load_requirements(json_path=args.json, dry_run=args.dry_run)
        print(f"[SUCCESS] Loaded requirements: {res}")
    finally:
        loader.close()


if __name__ == "__main__":
    main()
