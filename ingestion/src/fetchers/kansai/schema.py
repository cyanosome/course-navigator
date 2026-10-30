"""
Schema definitions for Kansai University Syllabus Fetcher.
"""

from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel, Field


class CatalogEntry(BaseModel):
    """Represents a single course entry extracted from the curriculum catalog table."""
    syllabus_id: str = Field(..., description="6-digit syllabus reference code (e.g. '034454')")
    timetable_code: Optional[str] = Field(None, description="Timetable / course code (e.g. '00301')")
    subject_name: str = Field(..., description="Course / subject title")
    year_range: Optional[str] = Field(None, description="Eligible academic years (e.g. '１〜４年次')")
    credits: Optional[str] = Field(None, description="Number of credits (e.g. '2')")
    class_name: Optional[str] = Field(None, description="Class division / group")
    instructors: Optional[str] = Field(None, description="Instructor / professor name(s)")
    term_schedule: Optional[str] = Field(None, description="Term, day, and period (e.g. '春学期 火2')")
    detail_url: str = Field(..., description="Absolute URL to syllabus detail HTML")
    relative_ref_path: str = Field(..., description="Relative path within ref hierarchy (e.g. '0/3/44/034454.html')")


class FetchSummary(BaseModel):
    """Summary of a fetch operation."""
    total_entries: int = 0
    newly_downloaded: int = 0
    skipped_existing: int = 0
    failed: int = 0
    failed_ids: List[str] = Field(default_factory=list)
