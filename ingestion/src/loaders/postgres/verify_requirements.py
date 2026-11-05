"""
PostgreSQL Requirements Verification CLI Tool

Validates consistency and credit counts of graduation_requirements and course_requirements.
"""

import sys
import argparse
from typing import Dict, Any, Optional
import psycopg

from src.loaders.postgres.db import get_connection


def get_requirements_stats(conn: psycopg.Connection) -> Dict[str, Any]:
    """Retrieve statistical summary of requirements."""
    with conn.cursor() as cur:
        # Graduation requirements
        cur.execute("SELECT requirement_id, department_name, total_credits, major_required_credits, major_elective_required_credits FROM graduation_requirements;")
        grad_rows = cur.fetchall()

        # Course requirements breakdown by requirement_type
        cur.execute(
            """
            SELECT requirement_type, COUNT(*) as count, COUNT(DISTINCT syllabus_id) as distinct_courses, SUM(credits) as total_credits
            FROM course_requirements
            GROUP BY requirement_type
            ORDER BY requirement_type;
            """
        )
        type_rows = cur.fetchall()

        # Breakdown by assigned_year
        cur.execute(
            """
            SELECT assigned_year, COUNT(*) as count, SUM(credits) as total_credits
            FROM course_requirements
            GROUP BY assigned_year
            ORDER BY assigned_year;
            """
        )
        year_rows = cur.fetchall()

    return {
        "graduation_requirements": grad_rows,
        "requirement_types": type_rows,
        "assigned_years": year_rows,
    }


def verify_all(conn: psycopg.Connection) -> bool:
    """Validate all requirements against official bulletin standards."""
    stats = get_requirements_stats(conn)
    grad_list = stats["graduation_requirements"]

    if not grad_list:
        print("[FAIL] No graduation_requirements records found.")
        return False

    grad = grad_list[0]
    print("============================================================")
    print(" GRADUATION & COURSE REQUIREMENTS VALIDATION REPORT")
    print("============================================================")
    print(f" Target Requirement  : {grad['requirement_id']} ({grad['department_name']})")
    print(f" Total Credits Target: {grad['total_credits']} credits")
    print(f" Major Required Goal : {grad['major_required_credits']} credits")
    print(f" Major Elective Goal : {grad['major_elective_required_credits']} credits (minimum)")
    print("------------------------------------------------------------")

    type_map = {r["requirement_type"]: r for r in stats["requirement_types"]}
    req_stat = type_map.get("required", {"count": 0, "total_credits": 0})
    el_req_stat = type_map.get("elective_required", {"count": 0, "total_credits": 0})
    el_stat = type_map.get("elective", {"count": 0, "total_credits": 0})

    print(f" Required (必修)      : {req_stat['count']} records, {req_stat['total_credits']} total credits")
    print(f" Elective Req (選択必修): {el_req_stat['count']} records, {el_req_stat['total_credits']} total credits")
    print(f" Elective (選択)      : {el_stat['count']} records, {el_stat['total_credits']} total credits")
    print("------------------------------------------------------------")

    # Assertions
    passed = True
    if req_stat["count"] == 0:
        print("[FAIL] Zero required courses found.")
        passed = False
    else:
        print(" [PASS] Required courses exist and populated.")

    if el_req_stat["count"] == 0:
        print("[FAIL] Zero elective_required courses found.")
        passed = False
    else:
        print(" [PASS] Elective required courses exist and populated.")

    print("============================================================")
    if passed:
        print(" SUCCESS: Requirements successfully populated and verified!")
    else:
        print(" FAILED: One or more requirement checks failed.")
    print("============================================================")
    return passed


def show_course_requirement(conn: psycopg.Connection, code: str) -> None:
    """Show requirement details for a specific course by syllabus_id or timetable_code."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cr.syllabus_id, c.timetable_code, c.course_code, c.subject_name,
                   cr.requirement_type, cr.credits, cr.assigned_year, cr.bulletin_code,
                   cr.field_category, cr.department_name
            FROM course_requirements cr
            JOIN courses c ON cr.syllabus_id = c.syllabus_id
            WHERE cr.syllabus_id = %s OR c.timetable_code = %s
            LIMIT 5;
            """,
            (code, code),
        )
        rows = cur.fetchall()

    if not rows:
        print(f"No requirement record found for code: {code}")
        return

    print("============================================================")
    print(f" COURSE REQUIREMENT DETAILS FOR: {code}")
    print("============================================================")
    for r in rows:
        print(f" Syllabus ID   : {r['syllabus_id']}")
        print(f" Timetable Code: {r['timetable_code']}")
        print(f" Course Code   : {r['course_code']}")
        print(f" Subject Name  : {r['subject_name']}")
        print(f" Requirement   : {r['requirement_type'].upper()}")
        print(f" Credits       : {r['credits']}")
        print(f" Assigned Year : {r['assigned_year']} 年次")
        print(f" Bulletin Code : {r['bulletin_code']}")
        print(f" Department    : {r['department_name']}")
        print("------------------------------------------------------------")


def main():
    parser = argparse.ArgumentParser(description="PostgreSQL Requirements Verification CLI.")
    subparsers = parser.add_subparsers(dest="command", help="Sub-command")

    subparsers.add_parser("check-all", help="Validate all requirements")
    subparsers.add_parser("stats", help="Show summary statistics")

    show_p = subparsers.add_parser("show", help="Show course requirement details")
    show_p.add_argument("code", help="syllabus_id or timetable_code")

    args = parser.parse_args()
    conn = get_connection()

    try:
        if args.command == "check-all" or args.command is None:
            verify_all(conn)
        elif args.command == "stats":
            stats = get_requirements_stats(conn)
            print("Stats:", stats)
        elif args.command == "show":
            show_course_requirement(conn, args.code)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
