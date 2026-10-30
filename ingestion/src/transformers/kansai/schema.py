"""
Pydantic schemas for Kansai University Syllabus Transformer.
Captures all information from the raw HTML files and catalog metadata
without schema narrowing or data loss.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class InstructorItem(BaseModel):
    """Structured instructor representation pairing name and official code."""
    name: str = Field(..., description="Instructor name (from tantou / tannin)")
    code: Optional[str] = Field(None, description="Official faculty code (from kyoinCdList)")
    is_primary: bool = Field(False, description="True if listed in tannin (担任者)")


class ScheduleSession(BaseModel):
    """Structured session plan for an individual class week/session."""
    session_number: Optional[int] = Field(None, description="Session / week number (1-15)")
    raw_line: str = Field(..., description="Original raw line text")
    topic: str = Field(..., description="Extracted topic or theme for this session")


class KansaiCourseDetail(BaseModel):
    """Complete machine-readable record for a single Kansai University course syllabus."""

    # 1. Primary Identifiers & Titles
    syllabus_id: str = Field(..., description="6-digit unique syllabus reference code (e.g. '162242')")
    academic_year: int = Field(..., description="Academic year (nendo, e.g. 2026)")
    course_code: str = Field(..., description="6-digit master course code (kmkCd, e.g. '055060')")
    timetable_code: Optional[str] = Field(None, description="5-digit timetable code (jikanwari, e.g. '64214')")
    subject_name: str = Field(..., description="Course / subject title (kamoku)")
    subtitle: Optional[str] = Field(None, description="Course subtitle or theme (subkamoku)")

    # 2. Curriculum, Affiliation & Delivery
    credits: Optional[float] = Field(None, description="Number of credits as float")
    credits_raw: Optional[str] = Field(None, description="Raw credits string (tani)")
    year_range: Optional[str] = Field(None, description="Eligible academic years from catalog (e.g. '１〜４年次', '２年次')")
    class_name: Optional[str] = Field(None, description="Class group / division (class, e.g. '3', 'A')")
    semester: Optional[str] = Field(None, description="Academic term / semester (jyugyokeitai, e.g. '春', '秋', '通年')")
    term_schedule: Optional[str] = Field(None, description="Schedule day and period (yougen, e.g. '火2')")
    faculties: List[str] = Field(default_factory=list, description="Target/offering faculties (gakubu, e.g. ['環'])")
    department_codes: List[str] = Field(default_factory=list, description="Target department codes (buGakuguGakka)")
    subject_type_code: Optional[str] = Field(None, description="Subject category code (jyuKbn, e.g. '01')")
    category_code: Optional[str] = Field(None, description="Course division code (gosyu)")
    language: Optional[str] = Field(None, description="Instruction language (gengo, e.g. '日本語(Japanese)')")

    # 3. Teaching & Instructors
    teaching_type: Optional[str] = Field(None, description="Format / method (jyugyohouhou, e.g. '講義（対面型）')")
    teaching_methods: List[str] = Field(default_factory=list, description="List of active learning/teaching methods (jyugyosyuhou)")
    instructors: List[InstructorItem] = Field(default_factory=list, description="List of structured instructors")
    instructors_tantou_raw: List[str] = Field(default_factory=list, description="Raw list of assigned instructors (tantou)")
    instructors_tannin_raw: List[str] = Field(default_factory=list, description="Raw list of primary instructors (tannin)")
    instructor_codes: List[str] = Field(default_factory=list, description="Raw list of instructor codes (kyoinCdList)")
    contact_method: Optional[str] = Field(None, description="Instructor contact method / office hour (toiawasehouhou)")

    # 4. Content & Pedagogy
    description: str = Field("", description="Course description and summary (gaiyo)")
    objectives: Optional[str] = Field(None, description="Course objectives and goals (mokuhyo)")
    schedule_raw: Optional[str] = Field(None, description="Full raw 15-week class schedule text (keikaku)")
    schedule_sessions: List[ScheduleSession] = Field(default_factory=list, description="Parsed week-by-week sessions")
    work_outside_class: Optional[str] = Field(None, description="Expected preparation and review (jikangaigakusyu)")

    # 5. Assessment & Policies
    grading_policy: Optional[str] = Field(None, description="Grading policy and weight breakdown (hyokahouhou)")
    evaluation_criteria: Optional[str] = Field(None, description="Evaluation criteria and standards (hyokakijyun)")
    feedback_method: Optional[str] = Field(None, description="Assignment/exam feedback method (feedback)")

    # 6. Learning Materials & Comments
    textbooks: List[str] = Field(default_factory=list, description="Required textbooks (kyokasyo)")
    textbook_notes: Optional[str] = Field(None, description="Notes regarding textbooks (kyokasyobikou)")
    references: List[str] = Field(default_factory=list, description="Recommended references (sankousyo)")
    reference_notes: Optional[str] = Field(None, description="Notes regarding references (sankousyobikou)")
    notes: Optional[str] = Field(None, description="General comments and notes (bikou)")

    # 7. Traceability
    detail_url: str = Field(..., description="Official syllabus detail URL")
    relative_ref_path: str = Field(..., description="Relative file path on disk (e.g. '1/6/22/162242.html')")


class ParseReport(BaseModel):
    """Execution summary report for batch syllabus transformation."""
    total_processed: int = 0
    success_count: int = 0
    error_count: int = 0
    errors: List[Dict[str, str]] = Field(default_factory=list)
    field_coverage: Dict[str, int] = Field(default_factory=dict)
