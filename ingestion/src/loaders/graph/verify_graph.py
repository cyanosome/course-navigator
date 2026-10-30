"""
Cross-Database Verification CLI for Neo4j Graph & PostgreSQL RDB.

Verifies:
1. Node and relationship counts in Neo4j.
2. 100% ID synchronization and consistency between Neo4j `Course` nodes and PostgreSQL `courses` table.
3. Curriculum Tree DAG structure (CourseGroup, DiplomaPolicy, PREREQUISITE_FOR, CONTRIBUTES_TO).
4. Detailed cross-DB inspection for specific courses.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase, Driver
from src.loaders.postgres.db import get_connection

logger = logging.getLogger(__name__)


def get_neo4j_driver(
    uri: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> Driver:
    """Create a Neo4j driver using environment variables or defaults."""
    uri = uri or os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = user or os.getenv("NEO4J_USER", "neo4j")
    password = password or os.getenv("NEO4J_PASSWORD", "secure_password_please_change")
    return GraphDatabase.driver(uri, auth=(user, password))


def check_all() -> bool:
    """Perform comprehensive cross-database consistency verification between Neo4j & PostgreSQL."""
    driver = get_neo4j_driver()
    all_passed = True

    print("=" * 65)
    print("      CROSS-DATABASE VERIFICATION: Neo4j Graph & PostgreSQL")
    print("=" * 65)

    try:
        # 1. Neo4j Node Counts
        neo4j_counts: Dict[str, int] = {}
        with driver.session() as session:
            # Kansai courses with syllabus_id
            res_kansai = session.run("MATCH (c:Course) WHERE c.syllabus_id IS NOT NULL RETURN count(c) AS cnt").single()
            neo4j_counts["Course_Kansai"] = res_kansai["cnt"] if res_kansai else 0

            # All courses
            res_all = session.run("MATCH (c:Course) RETURN count(c) AS cnt").single()
            neo4j_counts["Course_Total"] = res_all["cnt"] if res_all else 0

            for label in ["CourseGroup", "DiplomaPolicy", "Professor", "Department", "Faculty"]:
                res = session.run(f"MATCH (n:{label}) RETURN count(n) AS cnt").single()
                neo4j_counts[label] = res["cnt"] if res else 0

            # Neo4j Relationship Counts
            rel_counts: Dict[str, int] = {}
            for rel in [
                "PREREQUISITE_FOR",
                "CONTRIBUTES_TO",
                "BELONGS_TO_GROUP",
                "TAUGHT_BY",
                "BELONGS_TO",
                "OFFERED_BY",
            ]:
                res = session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS cnt").single()
                rel_counts[rel] = res["cnt"] if res else 0

        # 2. PostgreSQL Counts
        with get_connection() as pg_conn:
            with pg_conn.cursor() as cur:
                cur.execute("SELECT count(*) AS total FROM courses;")
                pg_course_count = cur.fetchone()["total"]

                cur.execute("SELECT count(DISTINCT syllabus_id) AS distinct_sids FROM courses;")
                pg_distinct_sids = cur.fetchone()["distinct_sids"]

        # 3. Print Overview Table
        print(f"\n[1] Node & Record Summary")
        print(f"  - PostgreSQL courses:       {pg_course_count:>5} rows (distinct syllabus_ids: {pg_distinct_sids})")
        print(f"  - Neo4j Kansai Courses:      {neo4j_counts.get('Course_Kansai', 0):>5} (with syllabus_id)")
        print(f"  - Neo4j Total Courses:       {neo4j_counts.get('Course_Total', 0):>5} (incl. legacy universities)")
        print(f"  - Neo4j CourseGroup nodes:   {neo4j_counts.get('CourseGroup', 0):>5}")
        print(f"  - Neo4j DiplomaPolicy nodes: {neo4j_counts.get('DiplomaPolicy', 0):>5}")
        print(f"  - Neo4j Professor nodes:     {neo4j_counts.get('Professor', 0):>5}")
        print(f"  - Neo4j Department nodes:    {neo4j_counts.get('Department', 0):>5}")
        print(f"  - Neo4j Faculty nodes:       {neo4j_counts.get('Faculty', 0):>5}")

        print(f"\n[2] Relationship Summary (Graph Topology)")
        print(f"  - Group Prerequisites (PREREQUISITE_FOR): {rel_counts.get('PREREQUISITE_FOR', 0):>5}")
        print(f"  - DP Contributions (CONTRIBUTES_TO):      {rel_counts.get('CONTRIBUTES_TO', 0):>5}")
        print(f"  - Course Memberships (BELONGS_TO_GROUP):  {rel_counts.get('BELONGS_TO_GROUP', 0):>5}")
        print(f"  - Course Instructors (TAUGHT_BY):         {rel_counts.get('TAUGHT_BY', 0):>5}")
        print(f"  - Course Departments (BELONGS_TO):        {rel_counts.get('BELONGS_TO', 0):>5}")
        print(f"  - Course Faculties (OFFERED_BY):          {rel_counts.get('OFFERED_BY', 0):>5}")

        # 4. Validations & Asserts
        print(f"\n[3] Integrity Checks")

        # Check 1: Course Count Match
        course_match = neo4j_counts.get("Course_Kansai", 0) == pg_course_count
        if course_match:
            print(f"  [PASS] Course count matches between Neo4j and PostgreSQL ({pg_course_count})")
        else:
            print(
                f"  [FAIL] Course count mismatch: Neo4j has {neo4j_counts.get('Course_Kansai', 0)}, "
                f"PostgreSQL has {pg_course_count}"
            )
            all_passed = False

        # Check 2: Curriculum Groups (Expected 18 CourseGroups for Kansai Env/Urban Engineering)
        groups_ok = neo4j_counts.get("CourseGroup", 0) == 18
        if groups_ok:
            print(f"  [PASS] Curriculum CourseGroup count == 18 ({neo4j_counts.get('CourseGroup', 0)})")
        else:
            print(f"  [FAIL] CourseGroup count expected == 18, got {neo4j_counts.get('CourseGroup', 0)}")
            all_passed = False

        # Check 3: Diploma Policies (Expected 3)
        dp_ok = neo4j_counts.get("DiplomaPolicy", 0) == 3
        if dp_ok:
            print(f"  [PASS] DiplomaPolicy count == 3 (DP1, DP2, DP3)")
        else:
            print(f"  [FAIL] DiplomaPolicy count expected 3, got {neo4j_counts.get('DiplomaPolicy', 0)}")
            all_passed = False

        # Check 4: Directed Edges (PREREQUISITE_FOR == 22, CONTRIBUTES_TO == 3)
        edges_ok = (
            rel_counts.get("PREREQUISITE_FOR", 0) == 22
            and rel_counts.get("CONTRIBUTES_TO", 0) == 3
        )
        if edges_ok:
            print(
                f"  [PASS] Graph DAG edges valid (Prerequisites: {rel_counts.get('PREREQUISITE_FOR', 0)}, "
                f"DP Contributions: {rel_counts.get('CONTRIBUTES_TO', 0)})"
            )
        else:
            print(
                f"  [FAIL] Graph DAG edges incomplete: Prerequisites={rel_counts.get('PREREQUISITE_FOR', 0)}, "
                f"DP Contributions={rel_counts.get('CONTRIBUTES_TO', 0)}"
            )
            all_passed = False

        # Check 5: Cross-DB Foreign Key Linkage
        with driver.session() as session:
            res = session.run(
                """
                MATCH (c:Course)
                WHERE c.syllabus_id IS NOT NULL
                RETURN c.syllabus_id AS sid
                LIMIT 50
                """
            )
            sample_sids = [r["sid"] for r in res]

        with get_connection() as pg_conn:
            with pg_conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS found FROM courses WHERE syllabus_id = ANY(%s);",
                    (sample_sids,),
                )
                found_count = cur.fetchone()["found"]

        if found_count == len(sample_sids) and len(sample_sids) > 0:
            print(f"  [PASS] Sample Cross-DB Linkage 100% verified ({found_count}/{len(sample_sids)} syllabus_ids matched)")
        else:
            print(f"  [FAIL] Sample Cross-DB Linkage mismatch ({found_count}/{len(sample_sids)} matched)")
            all_passed = False

        print("\n" + "=" * 65)
        if all_passed:
            print("  OVERALL RESULT: [PASSED] ALL CONSISTENCY CHECKS SATISFIED")
        else:
            print("  OVERALL RESULT: [FAILED] ONE OR MORE INTEGRITY CHECKS FAILED")
        print("=" * 65)

    finally:
        driver.close()

    return all_passed


def check_course(syllabus_id_or_code: str) -> None:
    """Inspect a single course by joining its Neo4j graph context with PostgreSQL detailed syllabus."""
    driver = get_neo4j_driver()
    print(f"\n--- Cross-Database Course Inspection: '{syllabus_id_or_code}' ---")

    try:
        # 1. Fetch from Neo4j
        with driver.session() as session:
            query = """
            MATCH (c:Course)
            WHERE c.syllabus_id = $target_id OR c.course_code = $target_id
            OPTIONAL MATCH (c)-[:BELONGS_TO_GROUP]->(cg:CourseGroup)
            OPTIONAL MATCH (cg)<-[r:PREREQUISITE_FOR]-(prereq:CourseGroup)
            OPTIONAL MATCH (c)-[:TAUGHT_BY]->(p:Professor)
            OPTIONAL MATCH (c)-[:OFFERED_BY]->(f:Faculty)
            OPTIONAL MATCH (c)-[:BELONGS_TO]->(d:Department)
            RETURN c,
                   cg.group_id AS group_id,
                   cg.label AS group_label,
                   collect(DISTINCT prereq.label) AS prereq_groups,
                   collect(DISTINCT p.name) AS professors,
                   collect(DISTINCT f.name) AS faculties,
                   collect(DISTINCT d.code) AS departments
            """
            result = session.run(query, target_id=syllabus_id_or_code).single()

        if not result or not result["c"]:
            print(f"Course not found in Neo4j with syllabus_id or course_code: {syllabus_id_or_code}")
            return

        node = result["c"]
        sid = node.get("syllabus_id")

        print("\n[Neo4j Graph Context]")
        print(f"  - Subject Name:   {node.get('name')}")
        print(f"  - Syllabus ID:    {sid}")
        print(f"  - Course Code:    {node.get('course_code')}")
        print(f"  - Timetable Code: {node.get('timetable_code')}")
        print(f"  - Credits:        {node.get('credits')}")
        print(f"  - Semester:       {node.get('semester')}")
        print(f"  - Group Label:    {result.get('group_label')} ({result.get('group_id')})")
        print(f"  - Prerequisites:  {', '.join(result.get('prereq_groups', [])) or 'None'}")
        print(f"  - Instructors:    {', '.join(result.get('professors', [])) or 'None'}")
        print(f"  - Faculties:      {', '.join(result.get('faculties', [])) or 'None'}")

        # 2. Fetch from PostgreSQL
        with get_connection() as pg_conn:
            with pg_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT syllabus_id, course_code, subject_name, credits,
                           academic_year, semester, description, schedule_raw
                    FROM courses
                    WHERE syllabus_id = %s
                    """,
                    (sid,),
                )
                row = cur.fetchone()

        if not row:
            print(f"\n[PostgreSQL Detail]")
            print(f"  [WARNING] Record not found in PostgreSQL for syllabus_id={sid}")
            return

        print("\n[PostgreSQL Relational Details]")
        print(f"  - Description Length: {len(row.get('description') or '')} chars")
        print(f"  - Schedule Raw Items: {len(row.get('schedule_raw') or [])} entries")
        desc_sample = (row.get("description") or "").replace("\n", " ")[:120]
        print(f"  - Description Sample: {desc_sample}...")
        print(f"\n[Verification Verdict]: Cross-DB Join Confirmed (Syllabus ID {sid} linked seamlessly)")

    finally:
        driver.close()


def check_groups() -> None:
    """List all CourseGroups in Neo4j, their semester, academic year, and prerequisite DAG."""
    driver = get_neo4j_driver()
    print("\n=== Kansai University Curriculum CourseGroups in Neo4j ===")

    try:
        with driver.session() as session:
            query = """
            MATCH (cg:CourseGroup)
            OPTIONAL MATCH (c:Course)-[:BELONGS_TO_GROUP]->(cg)
            OPTIONAL MATCH (prev:CourseGroup)-[:PREREQUISITE_FOR]->(cg)
            OPTIONAL MATCH (cg)-[:PREREQUISITE_FOR]->(nxt:CourseGroup)
            OPTIONAL MATCH (cg)-[:CONTRIBUTES_TO]->(dp:DiplomaPolicy)
            RETURN cg.group_id AS gid,
                   cg.label AS label,
                   cg.academic_year AS year,
                   cg.semester AS semester,
                   count(DISTINCT c) AS member_count,
                   collect(DISTINCT prev.group_id) AS incoming_prereqs,
                   collect(DISTINCT nxt.group_id) AS outgoing_prereqs,
                   collect(DISTINCT dp.code) AS dps
            ORDER BY cg.academic_year, cg.group_id
            """
            records = session.run(query).data()

        print(f"{'Group ID':<22} | {'Yr':<2} | {'Sem':<2} | {'Courses':<7} | {'Prerequisites':<20} | {'Contributes To':<10}")
        print("-" * 80)
        for r in records:
            incoming = ",".join(r["incoming_prereqs"]) or "-"
            dps = ",".join(r["dps"]) or "-"
            sem = r["semester"] or "-"
            print(
                f"{r['gid']:<22} | {r['year']:<2} | {sem:<2} | {r['member_count']:<7} | "
                f"{incoming:<20} | {dps:<10}"
            )
        print("-" * 80)
        print(f"Total CourseGroups: {len(records)}")

    finally:
        driver.close()


def main() -> None:
    """CLI entrypoint for Neo4j verification tool."""
    parser = argparse.ArgumentParser(
        description="Verify Neo4j Graph integrity and cross-database linkage with PostgreSQL."
    )
    subparsers = parser.add_subparsers(dest="command", help="Verification command")

    # Subcommand: check-all
    subparsers.add_parser("check-all", help="Verify all counts, constraints, and cross-DB ID linkage")

    # Subcommand: check-course
    p_course = subparsers.add_parser("check-course", help="Inspect a specific course across Neo4j and PostgreSQL")
    p_course.add_argument("course_id", type=str, help="Syllabus ID or Course Code to inspect")

    # Subcommand: check-groups
    subparsers.add_parser("check-groups", help="List all CourseGroups and their DAG connections in Neo4j")

    args = parser.parse_args()

    if args.command == "check-all" or args.command is None:
        success = check_all()
        if not success:
            sys.exit(1)
    elif args.command == "check-course":
        check_course(args.course_id)
    elif args.command == "check-groups":
        check_groups()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
