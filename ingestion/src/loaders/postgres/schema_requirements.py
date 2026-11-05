"""
PostgreSQL Schema Definitions for Graduation Requirements and Course Classifications.
"""

import psycopg


def create_requirements_tables(conn: psycopg.Connection) -> None:
    """Create graduation_requirements and course_requirements tables if not exist."""
    with conn.cursor() as cur:
        # 1. Graduation Requirements Master Table
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS graduation_requirements (
                requirement_id VARCHAR(50) PRIMARY KEY,
                academic_year INTEGER NOT NULL,
                faculty_code VARCHAR(20) NOT NULL,
                faculty_name VARCHAR(50) NOT NULL,
                department_code VARCHAR(20) NOT NULL,
                department_name VARCHAR(50) NOT NULL,
                total_credits NUMERIC(4,1) NOT NULL,
                general_education_credits NUMERIC(4,1) NOT NULL,
                general_designated_credits NUMERIC(4,1) NOT NULL,
                foreign_language_credits NUMERIC(4,1) NOT NULL,
                foreign_lang_first_credits NUMERIC(4,1) NOT NULL,
                foreign_lang_second_credits NUMERIC(4,1) NOT NULL,
                major_credits NUMERIC(4,1) NOT NULL,
                major_required_credits NUMERIC(4,1) NOT NULL,
                major_elective_required_credits NUMERIC(4,1) NOT NULL,
                thesis_requirements JSONB NOT NULL,
                rules_notes TEXT[] DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )

        # 2. Course Requirement Classification Table
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS course_requirements (
                syllabus_id VARCHAR(20) NOT NULL REFERENCES courses(syllabus_id) ON DELETE CASCADE,
                department_code VARCHAR(20) NOT NULL,
                department_name VARCHAR(50) NOT NULL,
                subject_name_bulletin VARCHAR(255) NOT NULL,
                requirement_type VARCHAR(30) NOT NULL, -- 'required', 'elective_required', 'elective'
                credits NUMERIC(3,1) NOT NULL,
                assigned_year INTEGER,
                bulletin_code VARCHAR(50),
                field_category VARCHAR(50),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (syllabus_id, department_code)
            );
            """
        )

        # Create helpful indexes
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_course_req_type ON course_requirements(requirement_type);
            CREATE INDEX IF NOT EXISTS idx_course_req_dept ON course_requirements(department_code);
            CREATE INDEX IF NOT EXISTS idx_course_req_year ON course_requirements(assigned_year);
            """
        )

    conn.commit()


def drop_requirements_tables(conn: psycopg.Connection) -> None:
    """Drop graduation_requirements and course_requirements tables."""
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS course_requirements CASCADE;")
        cur.execute("DROP TABLE IF EXISTS graduation_requirements CASCADE;")
    conn.commit()
