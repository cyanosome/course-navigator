"""
PostgreSQL Course Loader for Course Navigator.

Loads transformed syllabus JSON records into the PostgreSQL courses table
with idempotent upsert (ON CONFLICT DO UPDATE), transaction safety, and
automated post-load diff verification.
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

import psycopg
from psycopg.types.json import Jsonb

from src.loaders.postgres.db import get_connection
from src.loaders.postgres.schema import create_courses_table
from src.loaders.postgres.verify_data import diff_with_json

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_JSON_PATH = (
    PROJECT_ROOT
    / "data"
    / "parsed"
    / "university"
    / "kansai"
    / "2026"
    / "courses_detail.json"
)

UPSERT_COURSE_SQL = """
INSERT INTO courses (
    syllabus_id,
    academic_year,
    course_code,
    timetable_code,
    subject_name,
    subtitle,
    credits,
    credits_raw,
    year_range,
    class_name,
    semester,
    term_schedule,
    faculties,
    department_codes,
    subject_type_code,
    category_code,
    language,
    teaching_type,
    teaching_methods,
    instructors,
    instructors_tantou_raw,
    instructors_tannin_raw,
    instructor_codes,
    contact_method,
    description,
    objectives,
    schedule_raw,
    schedule_sessions,
    work_outside_class,
    grading_policy,
    evaluation_criteria,
    feedback_method,
    textbooks,
    textbook_notes,
    "references",
    reference_notes,
    notes,
    detail_url,
    relative_ref_path
) VALUES (
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s
)
ON CONFLICT (syllabus_id) DO UPDATE SET
    academic_year = EXCLUDED.academic_year,
    course_code = EXCLUDED.course_code,
    timetable_code = EXCLUDED.timetable_code,
    subject_name = EXCLUDED.subject_name,
    subtitle = EXCLUDED.subtitle,
    credits = EXCLUDED.credits,
    credits_raw = EXCLUDED.credits_raw,
    year_range = EXCLUDED.year_range,
    class_name = EXCLUDED.class_name,
    semester = EXCLUDED.semester,
    term_schedule = EXCLUDED.term_schedule,
    faculties = EXCLUDED.faculties,
    department_codes = EXCLUDED.department_codes,
    subject_type_code = EXCLUDED.subject_type_code,
    category_code = EXCLUDED.category_code,
    language = EXCLUDED.language,
    teaching_type = EXCLUDED.teaching_type,
    teaching_methods = EXCLUDED.teaching_methods,
    instructors = EXCLUDED.instructors,
    instructors_tantou_raw = EXCLUDED.instructors_tantou_raw,
    instructors_tannin_raw = EXCLUDED.instructors_tannin_raw,
    instructor_codes = EXCLUDED.instructor_codes,
    contact_method = EXCLUDED.contact_method,
    description = EXCLUDED.description,
    objectives = EXCLUDED.objectives,
    schedule_raw = EXCLUDED.schedule_raw,
    schedule_sessions = EXCLUDED.schedule_sessions,
    work_outside_class = EXCLUDED.work_outside_class,
    grading_policy = EXCLUDED.grading_policy,
    evaluation_criteria = EXCLUDED.evaluation_criteria,
    feedback_method = EXCLUDED.feedback_method,
    textbooks = EXCLUDED.textbooks,
    textbook_notes = EXCLUDED.textbook_notes,
    "references" = EXCLUDED."references",
    reference_notes = EXCLUDED.reference_notes,
    notes = EXCLUDED.notes,
    detail_url = EXCLUDED.detail_url,
    relative_ref_path = EXCLUDED.relative_ref_path,
    updated_at = CURRENT_TIMESTAMP;
"""


@dataclass
class LoadReport:
    """Summary report for course loading process."""

    total_records: int
    loaded_records: int
    duration_seconds: float
    dry_run: bool
    is_verified: bool
    verification_diffs: int = 0
    error_message: Optional[str] = None


class PostgresCourseLoader:
    """Loads parsed course JSON data into PostgreSQL database."""

    def __init__(self, conn: Optional[psycopg.Connection] = None):
        self._conn = conn
        self._own_conn = conn is None

    def _get_connection(self) -> psycopg.Connection:
        if self._conn is None or getattr(self._conn, "closed", False) is True:
            self._conn = get_connection()
            self._own_conn = True
        return self._conn

    def close(self) -> None:
        """Close connection if owned by loader."""
        if self._own_conn and self._conn and not self._conn.closed:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def entry_to_row(entry: Dict[str, Any]) -> Tuple[Any, ...]:
        """Convert a single course dict to the 39-column tuple for UPSERT_COURSE_SQL."""
        instructors = entry.get("instructors") or []
        schedule_sessions = entry.get("schedule_sessions") or []

        return (
            entry.get("syllabus_id"),
            entry.get("academic_year"),
            entry.get("course_code"),
            entry.get("timetable_code"),
            entry.get("subject_name"),
            entry.get("subtitle"),
            entry.get("credits"),
            entry.get("credits_raw"),
            entry.get("year_range"),
            entry.get("class_name"),
            entry.get("semester"),
            entry.get("term_schedule"),
            entry.get("faculties") or [],
            entry.get("department_codes") or [],
            entry.get("subject_type_code"),
            entry.get("category_code"),
            entry.get("language"),
            entry.get("teaching_type"),
            entry.get("teaching_methods") or [],
            Jsonb(instructors),
            entry.get("instructors_tantou_raw") or [],
            entry.get("instructors_tannin_raw") or [],
            entry.get("instructor_codes") or [],
            entry.get("contact_method"),
            entry.get("description"),
            entry.get("objectives"),
            entry.get("schedule_raw"),
            Jsonb(schedule_sessions),
            entry.get("work_outside_class"),
            entry.get("grading_policy"),
            entry.get("evaluation_criteria"),
            entry.get("feedback_method"),
            entry.get("textbooks") or [],
            entry.get("textbook_notes"),
            entry.get("references") or [],
            entry.get("reference_notes"),
            entry.get("notes"),
            entry.get("detail_url"),
            entry.get("relative_ref_path"),
        )

    def load_from_json(
        self,
        json_path: Path = DEFAULT_JSON_PATH,
        batch_size: int = 500,
        dry_run: bool = False,
        skip_verify: bool = False,
        auto_create_table: bool = True,
    ) -> LoadReport:
        """Load courses from JSON into PostgreSQL.

        Args:
            json_path: Path to structured courses_detail.json.
            batch_size: Number of records to insert per executemany chunk.
            dry_run: If True, execute inside a transaction and roll back.
            skip_verify: If True, skip post-load diff verification.
            auto_create_table: If True, create table and indexes if not present.

        Returns:
            LoadReport containing counts, timing, and verification status.
        """
        start_time = time.time()
        conn = self._get_connection()

        if not json_path.exists():
            raise FileNotFoundError(f"JSON source file not found: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            entries = json.load(f)

        total_records = len(entries)
        if total_records == 0:
            return LoadReport(
                total_records=0,
                loaded_records=0,
                duration_seconds=round(time.time() - start_time, 2),
                dry_run=dry_run,
                is_verified=True,
                verification_diffs=0,
            )

        if auto_create_table:
            create_courses_table(conn)

        # Prepare tuples
        rows = [self.entry_to_row(e) for e in entries]

        # Process in batches within a transaction
        if dry_run:
            with conn.cursor() as cur:
                for i in range(0, total_records, batch_size):
                    chunk = rows[i : i + batch_size]
                    cur.executemany(UPSERT_COURSE_SQL, chunk)
            conn.rollback()
            duration = round(time.time() - start_time, 2)
            return LoadReport(
                total_records=total_records,
                loaded_records=total_records,
                duration_seconds=duration,
                dry_run=True,
                is_verified=False,
                verification_diffs=0,
            )

        # Live transaction
        with conn.transaction():
            with conn.cursor() as cur:
                for i in range(0, total_records, batch_size):
                    chunk = rows[i : i + batch_size]
                    cur.executemany(UPSERT_COURSE_SQL, chunk)

        # Automated post-load verification
        is_verified = False
        verification_diffs = 0
        if not skip_verify:
            diff_result = diff_with_json(conn, json_path=json_path)
            verification_diffs = diff_result["mismatches_count"] + diff_result["missing_in_db_count"]
            is_verified = diff_result["is_perfect_match"]
            if not is_verified:
                raise RuntimeError(
                    f"Post-load verification failed: {diff_result['missing_in_db_count']} missing, "
                    f"{diff_result['mismatches_count']} mismatches."
                )

        duration = round(time.time() - start_time, 2)
        return LoadReport(
            total_records=total_records,
            loaded_records=total_records,
            duration_seconds=duration,
            dry_run=False,
            is_verified=is_verified,
            verification_diffs=verification_diffs,
        )


def main():
    parser = argparse.ArgumentParser(
        description="Course Navigator - PostgreSQL Course Loader"
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help=f"Path to JSON file (default: {DEFAULT_JSON_PATH})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for executemany (default: 500)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution within a transaction and roll back",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip post-load automated diff verification",
    )

    args = parser.parse_args()

    print("==================================================")
    print("Course Navigator - PostgreSQL Course Loader")
    print(f"Source JSON: {args.json}")
    print(f"Batch Size:  {args.batch_size}")
    print(f"Dry Run:     {args.dry_run}")
    print(f"Skip Verify: {args.skip_verify}")
    print("==================================================")

    try:
        loader = PostgresCourseLoader()
        report = loader.load_from_json(
            json_path=args.json,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            skip_verify=args.skip_verify,
        )
        loader.close()

        print("\n[RESULT]")
        print(f"Total Source Records:  {report.total_records}")
        print(f"Loaded Records:        {report.loaded_records}")
        print(f"Execution Duration:    {report.duration_seconds}s")
        print(f"Dry Run Mode:          {report.dry_run}")
        if not args.dry_run:
            print(f"Verified (Zero Diff):  {report.is_verified}")
            print(f"Verification Diffs:    {report.verification_diffs}")

        if report.dry_run:
            print("\n[SUCCESS] Dry-run completed successfully (all changes rolled back).")
        elif report.is_verified or args.skip_verify:
            print("\n[SUCCESS] Course data successfully loaded into PostgreSQL!")
        else:
            print("\n[WARNING] Data loaded but verification detected discrepancies.")
            sys.exit(1)

    except Exception as e:
        print(f"\n[ERROR] Loading failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
