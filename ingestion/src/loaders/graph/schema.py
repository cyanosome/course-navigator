"""
Neo4j schema definitions, constraints, and Cypher queries for Curriculum & Course Ingestion.
"""

# Constraints ensuring uniqueness and fast lookups
CONSTRAINTS = [
    "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Course) REQUIRE c.syllabus_id IS UNIQUE",
    "CREATE INDEX IF NOT EXISTS FOR (c:Course) ON (c.course_code)",
    "CREATE INDEX IF NOT EXISTS FOR (c:Course) ON (c.timetable_code)",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (g:CourseGroup) REQUIRE g.group_id IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (dp:DiplomaPolicy) REQUIRE dp.code IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Professor) REQUIRE p.name IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Department) REQUIRE d.code IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (f:Faculty) REQUIRE f.name IS UNIQUE",
]

# Legacy Komazawa compatibility constraints
LEGACY_CONSTRAINTS = [
    "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Course) REQUIRE c.code IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Department) REQUIRE d.name IS UNIQUE",
]

# Legacy Komazawa batch ingestion query
BATCH_INGEST_QUERY = """
UNWIND $batch AS row
MERGE (c:Course {code: row.course_code})
SET c.name = row.course_name,
    c.title = row.course_name,
    c.name_kana = row.course_name_kana,
    c.year = row.year,
    c.term = row.term,
    c.credits = row.credits,
    c.day_of_week = row.day_of_week,
    c.period = row.period,
    c.text = row.text

WITH c, row
WHERE row.instructor IS NOT NULL AND row.instructor <> ''
MERGE (p:Professor {name: row.instructor})
ON CREATE SET p.name_kana = row.instructor_kana
ON MATCH SET p.name_kana = coalesce(p.name_kana, row.instructor_kana)
MERGE (c)-[:TAUGHT_BY]->(p)

WITH c, row
WHERE row.department IS NOT NULL AND row.department <> ''
MERGE (d:Department {name: row.department})
MERGE (c)-[:BELONGS_TO]->(d)
"""

# --- Curriculum Group Queries ---

INGEST_COURSE_GROUPS_QUERY = """
UNWIND $groups AS g
MERGE (cg:CourseGroup {group_id: g.group_id})
SET cg.label = g.label,
    cg.academic_year = g.academic_year,
    cg.semester = g.semester,
    cg.faculty = $faculty,
    cg.department = $department
"""

INGEST_DIPLOMA_POLICIES_QUERY = """
UNWIND $dps AS dp
MERGE (d:DiplomaPolicy {code: dp.code})
SET d.name = dp.name,
    d.faculty = $faculty,
    d.department = $department
"""

INGEST_GROUP_PREREQUISITES_QUERY = """
UNWIND $edges AS e
MATCH (src:CourseGroup {group_id: e.source_group_id})
MATCH (tgt:CourseGroup {group_id: e.target_group_id})
MERGE (src)-[r:PREREQUISITE_FOR]->(tgt)
SET r.edge_type = e.edge_type,
    r.is_major = e.is_major_connection
"""

INGEST_DP_CONTRIBUTIONS_QUERY = """
UNWIND $dp_edges AS de
MATCH (src:CourseGroup {group_id: de.source_group_id})
MATCH (dp:DiplomaPolicy {code: de.target_group_id})
MERGE (src)-[r:CONTRIBUTES_TO]->(dp)
SET r.edge_type = de.edge_type
"""

INGEST_COURSE_MEMBERSHIPS_QUERY = """
UNWIND $memberships AS m
MATCH (cg:CourseGroup {group_id: m.group_id})
MERGE (c:Course {syllabus_id: m.syllabus_id})
ON CREATE SET c.name = m.subject_name
MERGE (c)-[:BELONGS_TO_GROUP]->(cg)
"""

# --- Detailed Course Queries (RDB Projection) ---

INGEST_COURSES_QUERY = """
UNWIND $batch AS row
MERGE (c:Course {syllabus_id: row.syllabus_id})
SET c.course_code = row.course_code,
    c.timetable_code = row.timetable_code,
    c.name = row.subject_name,
    c.title = row.subject_name,
    c.subtitle = row.subtitle,
    c.credits = row.credits,
    c.academic_year = row.academic_year,
    c.year_range = row.year_range,
    c.class_name = row.class_name,
    c.semester = row.semester,
    c.term_schedule = row.term_schedule,
    c.language = row.language,
    c.teaching_type = row.teaching_type,
    c.detail_url = row.detail_url
"""

INGEST_COURSE_PROFESSORS_QUERY = """
UNWIND $batch AS row
MATCH (c:Course {syllabus_id: row.syllabus_id})
UNWIND row.instructors AS inst
WITH c, inst WHERE inst.name IS NOT NULL AND inst.name <> ''
MERGE (p:Professor {name: inst.name})
ON CREATE SET p.code = inst.code
MERGE (c)-[r:TAUGHT_BY]->(p)
SET r.is_primary = inst.is_primary
"""

INGEST_COURSE_DEPARTMENTS_QUERY = """
UNWIND $batch AS row
MATCH (c:Course {syllabus_id: row.syllabus_id})
UNWIND row.department_codes AS dcode
WITH c, dcode WHERE dcode IS NOT NULL AND dcode <> ''
MERGE (d:Department {code: dcode})
MERGE (c)-[:BELONGS_TO]->(d)
"""

INGEST_COURSE_FACULTIES_QUERY = """
UNWIND $batch AS row
MATCH (c:Course {syllabus_id: row.syllabus_id})
UNWIND row.faculties AS fname
WITH c, fname WHERE fname IS NOT NULL AND fname <> ''
MERGE (f:Faculty {name: fname})
MERGE (c)-[:OFFERED_BY]->(f)
"""
