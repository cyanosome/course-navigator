"""
PostgreSQL schema definitions and table creation helpers for Course Navigator.
"""

import psycopg

CREATE_COURSES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS courses (
    syllabus_id VARCHAR(20) PRIMARY KEY,
    academic_year INTEGER NOT NULL,
    course_code VARCHAR(20) NOT NULL,
    timetable_code VARCHAR(20),
    subject_name VARCHAR(255) NOT NULL,
    subtitle TEXT,
    credits NUMERIC(3, 1),
    credits_raw VARCHAR(20),
    year_range VARCHAR(50),
    class_name VARCHAR(50),
    semester VARCHAR(50),
    term_schedule VARCHAR(50),
    faculties TEXT[] DEFAULT '{}',
    department_codes TEXT[] DEFAULT '{}',
    subject_type_code VARCHAR(20),
    category_code VARCHAR(20),
    language VARCHAR(50),
    teaching_type VARCHAR(100),
    teaching_methods TEXT[] DEFAULT '{}',
    instructors JSONB DEFAULT '[]'::jsonb,
    instructors_tantou_raw TEXT[] DEFAULT '{}',
    instructors_tannin_raw TEXT[] DEFAULT '{}',
    instructor_codes TEXT[] DEFAULT '{}',
    contact_method TEXT,
    description TEXT,
    objectives TEXT,
    schedule_raw TEXT,
    schedule_sessions JSONB DEFAULT '[]'::jsonb,
    work_outside_class TEXT,
    grading_policy TEXT,
    evaluation_criteria TEXT,
    feedback_method TEXT,
    textbooks TEXT[] DEFAULT '{}',
    textbook_notes TEXT,
    "references" TEXT[] DEFAULT '{}',
    reference_notes TEXT,
    notes TEXT,
    detail_url TEXT,
    relative_ref_path TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_courses_timetable_code ON courses (timetable_code);
CREATE INDEX IF NOT EXISTS idx_courses_course_code ON courses (course_code);
CREATE INDEX IF NOT EXISTS idx_courses_subject_name ON courses (subject_name);
CREATE INDEX IF NOT EXISTS idx_courses_semester ON courses (semester);
CREATE INDEX IF NOT EXISTS idx_courses_year ON courses (academic_year);
"""

DROP_COURSES_TABLE_SQL = """
DROP TABLE IF EXISTS courses CASCADE;
"""


def create_courses_table(conn: psycopg.Connection) -> None:
    """Create the courses table and indexes if they do not exist."""
    with conn.cursor() as cur:
        cur.execute(CREATE_COURSES_TABLE_SQL)
    conn.commit()


def drop_courses_table(conn: psycopg.Connection) -> None:
    """Drop the courses table if it exists."""
    with conn.cursor() as cur:
        cur.execute(DROP_COURSES_TABLE_SQL)
    conn.commit()
