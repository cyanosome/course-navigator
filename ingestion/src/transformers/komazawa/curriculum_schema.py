"""Pydantic data models for Komazawa University curriculum tree data."""

from typing import List, Optional
from pydantic import BaseModel, Field


class SubjectFieldItem(BaseModel):
    """Academic subject field code master record from areacode.pdf."""

    code: str = Field(description="3-digit subject area code (e.g. '111', '011')")
    category: str = Field(description="Broad category (大分類, e.g. '情報学', '宗教教育')")
    field: str = Field(description="Field (分野, e.g. '情報学基礎', '宗教')")
    subfield: Optional[str] = Field(default=None, description="Detailed field (細目)")


class CurriculumSubjectItem(BaseModel):
    """Canonical curriculum subject extracted from curriculum tree PDF."""

    id: str = Field(description="Unique ID for canonical subject")
    name: str = Field(description="Normalized course title")
    raw_name: str = Field(description="Original text extracted from PDF")
    faculty: str = Field(description="Faculty name (学部)")
    department: str = Field(description="Department / Program name (学科・専攻)")
    year: int = Field(ge=1, le=4, description="Target curriculum year (1 to 4)")
    requirement_type: str = Field(
        default="選択",
        description="Requirement category: '必修', '選択必修', '選択', '不明'",
    )
    credits: float = Field(default=2.0, description="Credits")
    dp_targets: List[str] = Field(
        default_factory=list,
        description="Diploma policy target items (e.g. ['2', '3'])",
    )
    curriculum_code: Optional[str] = Field(
        default=None, description="10-digit curriculum code if available"
    )
    field_code: Optional[str] = Field(
        default=None, description="3-digit field code (first 3 digits of code)"
    )
    field_name: Optional[str] = Field(
        default=None, description="Track / Area / Series name from layout"
    )
    source_file: str = Field(description="Source PDF filename")
    style: str = Field(description="Parser style used: Style1, Style2, Style3, Style4")

    # Syllabus entity resolution linkage
    matched_syllabus_codes: List[str] = Field(
        default_factory=list,
        description="List of 6-digit syllabus course codes matched",
    )
    match_status: str = Field(
        default="unmatched",
        description="Linkage status: 'exact', 'normalized', 'unmatched'",
    )


class DepartmentParseReport(BaseModel):
    """Parsing summary for a single department PDF."""

    id: str
    faculty: str
    department: str
    filename: str
    style: str
    extracted_count: int
    matched_count: int
    unmatched_count: int
    year_distribution: dict[int, int]
    requirement_distribution: dict[str, int]


class ParseReport(BaseModel):
    """Overall curriculum parsing audit report."""

    total_files_processed: int
    total_subjects_extracted: int
    total_syllabus_matches: int
    overall_match_rate_pct: float
    departments: List[DepartmentParseReport]
