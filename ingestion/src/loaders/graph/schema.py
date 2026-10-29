"""Neo4j schema definitions and Cypher queries for course ingestion."""

# Constraints ensuring uniqueness and fast lookups
CONSTRAINTS = [
    "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Course) REQUIRE c.code IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Professor) REQUIRE p.name IS UNIQUE",
    "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Department) REQUIRE d.name IS UNIQUE",
]

# Batch ingestion query utilizing UNWIND for high throughput
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
