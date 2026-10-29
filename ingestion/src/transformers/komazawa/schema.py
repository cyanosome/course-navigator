"""Pydantic schemas for Komazawa University syllabus parser."""

from typing import Optional
from pydantic import BaseModel, Field


class CourseSummary(BaseModel):
    """Normalized syllabus summary record for a course."""

    course_code: str = Field(..., description="Unique course code (rishu_code)")
    course_name: str = Field(..., description="Course name (kamoku_name)")
    course_name_kana: Optional[str] = Field(None, description="Course name reading in katakana")
    instructor: str = Field(..., description="Instructor name (kyoin_shimei)")
    instructor_kana: Optional[str] = Field(None, description="Instructor name reading in katakana")
    department: str = Field(..., description="Department or faculty affiliation (gakka_srnm)")
    year: int = Field(..., description="Academic year (syllabus_nendo)")
    term: Optional[str] = Field(None, description="Academic term (e.g. 通年, 前期, 後期)")
    credits: Optional[float] = Field(None, description="Number of credits")
    day_of_week: Optional[str] = Field(None, description="Day of week (e.g. 月曜日)")
    period: Optional[str] = Field(None, description="Class period (e.g. 1時限)")
    text: str = Field(..., description="Cleaned syllabus description/body text for search and embedding")
    raw_subject: str = Field(..., description="Original unparsed subject field for traceability")
