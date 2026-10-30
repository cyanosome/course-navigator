"""
PostgreSQL Course Data Verification and Inspection CLI Tool.

Enables inspecting table statistics, displaying individual course details,
running custom queries, and deterministically verifying 100% data fidelity
against parsed JSON source data.
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import psycopg

from src.loaders.postgres.db import get_connection, get_db_config
from src.loaders.postgres.schema import create_courses_table

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


def get_table_stats(conn: psycopg.Connection) -> Dict[str, Any]:
    """Retrieve row counts, column coverage, and distribution statistics for the courses table."""
    stats: Dict[str, Any] = {}

    with conn.cursor() as cur:
        # Check table existence
        cur.execute(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'courses'
            );
            """
        )
        exists = cur.fetchone()["exists"]
        stats["table_exists"] = exists
        if not exists:
            stats["total_rows"] = 0
            return stats

        # Total rows
        cur.execute("SELECT COUNT(*) AS total FROM courses;")
        total = cur.fetchone()["total"]
        stats["total_rows"] = total

        if total == 0:
            return stats

        # Column NULL coverage
        cur.execute(
            """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'courses' 
            ORDER BY ordinal_position;
            """
        )
        columns = cur.fetchall()

        col_coverage: Dict[str, Dict[str, Any]] = {}
        for col in columns:
            cname = col["column_name"]
            quoted_col = f'"{cname}"' if cname == "references" else cname
            cur.execute(
                f"""
                SELECT 
                    COUNT(*) FILTER (WHERE {quoted_col} IS NOT NULL) AS non_null_count,
                    COUNT(*) FILTER (WHERE {quoted_col} IS NULL) AS null_count
                FROM courses;
                """
            )
            cnt = cur.fetchone()
            non_null = cnt["non_null_count"]
            col_coverage[cname] = {
                "type": col["data_type"],
                "non_null_count": non_null,
                "null_count": cnt["null_count"],
                "coverage_pct": round(non_null / total * 100, 1),
            }
        stats["columns"] = col_coverage

        # Semester distribution
        cur.execute(
            """
            SELECT COALESCE(semester, '(None)') AS sem, COUNT(*) AS cnt 
            FROM courses GROUP BY semester ORDER BY cnt DESC;
            """
        )
        stats["semesters"] = {r["sem"]: r["cnt"] for r in cur.fetchall()}

        # Credits distribution
        cur.execute(
            """
            SELECT COALESCE(credits::text, '(None)') AS cred, COUNT(*) AS cnt 
            FROM courses GROUP BY credits ORDER BY cnt DESC;
            """
        )
        stats["credits"] = {r["cred"]: r["cnt"] for r in cur.fetchall()}

    return stats


def get_course_record(conn: psycopg.Connection, key: str) -> Optional[Dict[str, Any]]:
    """Fetch a single course by syllabus_id or timetable_code."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM courses 
            WHERE syllabus_id = %s OR timetable_code = %s 
            LIMIT 1;
            """,
            (key, key),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def format_course_display(course: Dict[str, Any]) -> str:
    """Format a course record into a clean, human-readable terminal output."""
    lines = [
        "=" * 60,
        f" [Course] {course.get('subject_name')} ({course.get('timetable_code', 'N/A')})",
        "=" * 60,
        f" Syllabus ID   : {course.get('syllabus_id')}",
        f" Course Code   : {course.get('course_code')}",
        f" Academic Year : {course.get('academic_year')}",
        f" Year Range    : {course.get('year_range')}",
        f" Semester      : {course.get('semester')}",
        f" Schedule      : {course.get('term_schedule')}",
        f" Credits       : {course.get('credits')} ({course.get('credits_raw')} tani)",
        f" Class         : {course.get('class_name')}",
        f" Faculties     : {', '.join(course.get('faculties') or [])}",
        f" Departments   : {', '.join(course.get('department_codes') or [])}",
        f" Language      : {course.get('language')}",
        f" Teaching Type : {course.get('teaching_type')}",
        "-" * 60,
        " [Instructors]",
    ]

    instructors = course.get("instructors") or []
    if isinstance(instructors, list) and instructors:
        for inst in instructors:
            primary_tag = " (担任)" if inst.get("is_primary") else ""
            lines.append(f"   * {inst.get('name')} [Code: {inst.get('code', 'N/A')}]{primary_tag}")
    else:
        lines.append(f"   Raw tantou: {', '.join(course.get('instructors_tantou_raw') or [])}")

    lines.extend([
        "-" * 60,
        " [Description / 授業概要]",
        f"   {course.get('description', '')[:300]}...",
        "-" * 60,
        " [Objectives / 到達目標]",
        f"   {course.get('objectives', '')[:300]}...",
        "-" * 60,
        " [Grading Policy / 評価方法]",
        f"   {course.get('grading_policy', '')}",
        "-" * 60,
        " [Schedule Sessions / 授業計画 (抜粋)]",
    ])

    sessions = course.get("schedule_sessions") or []
    if isinstance(sessions, list) and sessions:
        for s in sessions[:5]:
            lines.append(f"   * {s.get('raw_line')}")
        if len(sessions) > 5:
            lines.append(f"   ... ({len(sessions) - 5} more sessions)")
    else:
        sched_preview = (course.get("schedule_raw") or "")[:200]
        lines.append(f"   {sched_preview}...")

    textbooks = course.get("textbooks") or []
    refs = course.get("references") or []
    lines.extend([
        "-" * 60,
        f" Textbooks  ({len(textbooks)}): {', '.join(textbooks[:2])}",
        f" References ({len(refs)}): {', '.join(refs[:2])}",
        f" Detail URL : {course.get('detail_url')}",
        "=" * 60,
    ])

    return "\n".join(lines)


def diff_with_json(
    conn: psycopg.Connection,
    json_path: Path,
    max_mismatches: int = 10,
) -> Dict[str, Any]:
    """Deterministically compare database records against parsed JSON source data.

    Returns:
        Report dictionary detailing total counts, missing records, and field mismatches.
    """
    if not json_path.exists():
        raise FileNotFoundError(f"JSON source file not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        json_entries = json.load(f)

    json_map = {e["syllabus_id"]: e for e in json_entries}
    total_json = len(json_map)

    with conn.cursor() as cur:
        cur.execute("SELECT * FROM courses;")
        db_rows = cur.fetchall()

    db_map = {r["syllabus_id"]: dict(r) for r in db_rows}
    total_db = len(db_map)

    missing_in_db = [sid for sid in json_map if sid not in db_map]
    extra_in_db = [sid for sid in db_map if sid not in json_map]

    fields_to_check = [
        "subject_name",
        "course_code",
        "timetable_code",
        "academic_year",
        "semester",
        "term_schedule",
        "credits_raw",
        "description",
        "objectives",
        "grading_policy",
    ]

    mismatches: List[Dict[str, Any]] = []

    for sid, json_item in json_map.items():
        if sid not in db_map:
            continue
        db_item = db_map[sid]

        item_diffs: Dict[str, Tuple[Any, Any]] = {}
        for field in fields_to_check:
            j_val = json_item.get(field)
            d_val = db_item.get(field)

            # Normalize None and empty string
            j_norm = None if j_val == "" else j_val
            d_norm = None if d_val == "" else d_val

            if j_norm != d_norm:
                item_diffs[field] = (j_val, d_val)

        # Check numeric credits
        j_cred = json_item.get("credits")
        d_cred = float(db_item["credits"]) if db_item.get("credits") is not None else None
        if j_cred != d_cred:
            item_diffs["credits"] = (j_cred, d_cred)

        if item_diffs:
            mismatches.append({
                "syllabus_id": sid,
                "subject_name": json_item.get("subject_name"),
                "diffs": item_diffs,
            })
            if len(mismatches) >= max_mismatches:
                break

    return {
        "total_json": total_json,
        "total_db": total_db,
        "matched_count": len(json_map.keys() & db_map.keys()) - len(mismatches),
        "missing_in_db_count": len(missing_in_db),
        "missing_in_db_samples": missing_in_db[:5],
        "extra_in_db_count": len(extra_in_db),
        "mismatches_count": len(mismatches),
        "mismatch_samples": mismatches,
        "is_perfect_match": len(missing_in_db) == 0 and len(extra_in_db) == 0 and len(mismatches) == 0,
    }


def execute_read_query(conn: psycopg.Connection, query: str) -> None:
    """Execute a read-only query and display tabular output."""
    clean_q = query.strip()
    forbidden = ["drop ", "delete ", "truncate ", "update ", "insert ", "alter "]
    if any(clean_q.lower().startswith(f) for f in forbidden):
        print("ERROR: Only read queries (SELECT / EXPLAIN) are permitted with 'query'.")
        return

    with conn.cursor() as cur:
        cur.execute(clean_q)
        rows = cur.fetchall()
        if not rows:
            print("Query returned 0 rows.")
            return

        headers = list(rows[0].keys())
        print(f"\n--- Result ({len(rows)} rows) ---")
        # Compute column widths
        col_widths = {h: max(len(h), 8) for h in headers}
        for r in rows[:20]:
            for h in headers:
                val_str = str(r.get(h) if r.get(h) is not None else "")
                val_str = val_str.replace("\n", " ")[:30]
                col_widths[h] = max(col_widths[h], len(val_str))

        # Print header
        header_line = " | ".join(h.ljust(col_widths[h]) for h in headers)
        sep_line = "-+-".join("-" * col_widths[h] for h in headers)
        print(header_line)
        print(sep_line)

        # Print rows
        for r in rows[:30]:
            row_vals = []
            for h in headers:
                val = r.get(h)
                val_str = str(val if val is not None else "")
                val_str = val_str.replace("\n", " ")[:30]
                row_vals.append(val_str.ljust(col_widths[h]))
            print(" | ".join(row_vals))

        if len(rows) > 30:
            print(f"... and {len(rows) - 30} more rows.")


def main():
    """CLI entry point for PostgreSQL verification tool."""
    parser = argparse.ArgumentParser(
        description="Verify and inspect Kansai University syllabus data in PostgreSQL."
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Verification command to execute")

    # init-db
    subparsers.add_parser("init-db", help="Create courses table and indexes in PostgreSQL")

    # stats
    subparsers.add_parser("stats", help="Show table row count and column coverage stats")

    # show
    show_parser = subparsers.add_parser("show", help="Display full details of a specific course")
    show_parser.add_argument("key", help="Syllabus ID (e.g. 162242) or Timetable Code (e.g. 64214)")

    # diff
    diff_parser = subparsers.add_parser("diff", help="Compare database rows against courses_detail.json")
    diff_parser.add_argument(
        "--json",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help=f"Path to parsed courses_detail.json (default: {DEFAULT_JSON_PATH})",
    )

    # query
    query_parser = subparsers.add_parser("query", help="Execute read-only SQL query and print table")
    query_parser.add_argument("sql", help="SELECT SQL query to execute")

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    cfg = get_db_config()
    try:
        conn = get_connection(cfg)
    except Exception as e:
        print(f"ERROR: Could not connect to PostgreSQL at {cfg['host']}:{cfg['port']}/{cfg['dbname']}")
        print(f"Details: {e}")
        sys.exit(1)

    with conn:
        if args.subcommand == "init-db":
            print(f"Creating 'courses' table on {cfg['host']}:{cfg['port']}/{cfg['dbname']} ...")
            create_courses_table(conn)
            print("Table 'courses' and indexes created successfully.")

        elif args.subcommand == "stats":
            stats = get_table_stats(conn)
            if not stats["table_exists"]:
                print("Table 'courses' does not exist yet. Run 'init-db' to create it.")
                return

            print("=" * 60)
            print(f" POSTGRESQL COURSES TABLE STATS ({cfg['host']}:{cfg['port']}/{cfg['dbname']})")
            print("=" * 60)
            print(f" Total Rows: {stats['total_rows']}")
            print("\n [Column Population Rates]")
            for col, data in stats.get("columns", {}).items():
                print(f"   {col:24s} : {data['non_null_count']:4d}/{stats['total_rows']} ({data['coverage_pct']:5.1f}%) [{data['type']}]")

            print("\n [Semester Distribution]")
            for sem, count in stats.get("semesters", {}).items():
                print(f"   {sem:10s} : {count:4d}")

            print("\n [Credits Distribution]")
            for cred, count in stats.get("credits", {}).items():
                print(f"   {cred:10s} : {count:4d}")
            print("=" * 60)

        elif args.subcommand == "show":
            course = get_course_record(conn, args.key)
            if not course:
                print(f"Course not found for key: '{args.key}'")
                sys.exit(1)
            print(format_course_display(course))

        elif args.subcommand == "diff":
            print(f"Diffing PostgreSQL table 'courses' against: {args.json} ...")
            report = diff_with_json(conn, args.json)
            print("=" * 60)
            print(" DIFF VALIDATION REPORT")
            print("=" * 60)
            print(f" JSON Source Count  : {report['total_json']}")
            print(f" DB Table Count     : {report['total_db']}")
            print(f" Missing in DB      : {report['missing_in_db_count']}")
            print(f" Extra in DB        : {report['extra_in_db_count']}")
            print(f" Field Mismatches   : {report['mismatches_count']}")

            if report["is_perfect_match"]:
                print("\n SUCCESS: 100% Perfect Match! Zero discrepancies detected.")
            else:
                print("\n WARNING: Discrepancies found:")
                if report["missing_in_db_samples"]:
                    print(f"   Missing IDs: {report['missing_in_db_samples']}")
                if report["mismatch_samples"]:
                    for m in report["mismatch_samples"]:
                        print(f"   ID {m['syllabus_id']} ({m['subject_name']}):")
                        for fld, (j, d) in m["diffs"].items():
                            print(f"     - {fld}: JSON='{j}' vs DB='{d}'")
            print("=" * 60)

        elif args.subcommand == "query":
            execute_read_query(conn, args.sql)


if __name__ == "__main__":
    main()
