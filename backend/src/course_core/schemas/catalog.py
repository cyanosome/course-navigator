"""データの API（D1〜D6、navi-v1）の応答の型。項目名は snake_case（画面の型への写像は画面の純関数）。"""

from typing import Literal

from pydantic import BaseModel

KindCode = Literal["required", "elective_required", "elective"]
Term = Literal["春", "秋", "通年"]
EdgeType = Literal["prerequisite", "capstone", "english_track"]
Availability = Literal["available", "pending"]
CreditBucketKey = Literal[
    "general_education",
    "general_designated",
    "foreign_language",
    "foreign_lang_first",
    "foreign_lang_second",
    "major",
    "major_required",
    "major_elective_required",
]


# --- D1・D2 学科 --------------------------------------------------------------------


class DepartmentSummary(BaseModel):
    id: str
    university: str
    faculty: str
    name: str
    syllabus_year: int
    data_version: str
    course_count: int
    group_count: int


class DataStatus(BaseModel):
    status: Availability
    reason: str | None = None  # pending の理由（"表が無い"・"この学科の行が無い"）


class DepartmentDataStatus(BaseModel):
    requirements: DataStatus  # graduation_requirements の行
    kinds: DataStatus  # course_requirements の行
    classified_courses: int  # course_requirements の行数（この学科）
    similar_to_edges: int  # SIMILAR_TO の本数（DB 全体）
    similar_models: list[str]  # SIMILAR_TO の model の値
    group_edges: int  # PREREQUISITE_FOR の本数（DP を除く）


class DepartmentOverview(DepartmentSummary):
    data_status: DepartmentDataStatus


# --- D4・D5 科目 --------------------------------------------------------------------


class CourseSummary(BaseModel):
    syllabus_id: str
    course_code: str
    name: str
    subtitle: str | None
    group_id: str | None
    year_min: int | None
    year_max: int | None
    year_range: str | None
    term: Term | None
    term_raw: str | None
    slots: list[str]
    slot_note: str | None
    credits: float | None
    faculties: list[str]
    teacher: str | None
    lead: str
    kind: KindCode | None
    detail_url: str | None


class CoursePage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CourseSummary]
    kinds_status: Availability


class ScheduleItem(BaseModel):
    number: int | None
    topic: str


class Instructor(BaseModel):
    name: str
    is_primary: bool


class BulletinInfo(BaseModel):
    subject_name_bulletin: str
    requirement_type: KindCode
    credits: float
    assigned_year: int | None
    bulletin_code: str | None
    field_category: str | None


class CourseDetail(CourseSummary):
    academic_year: int
    description: str | None
    objectives: str | None
    schedule: list[ScheduleItem]
    work_outside_class: str | None
    grading_policy: str | None
    evaluation_criteria: str | None
    textbooks: list[str]
    textbook_notes: str | None
    references: list[str]
    notes: str | None
    instructors: list[Instructor]
    language: str | None
    teaching_type: str | None
    bulletin: BulletinInfo | None
    source: str = "postgres:courses"


# --- D3 系統図 ----------------------------------------------------------------------


class GroupNode(BaseModel):
    group_id: str
    label: str
    name: str
    plain: str | None
    common: bool
    academic_year: int
    semester: str | None
    member_count: int


class GroupEdge(BaseModel):
    source: str
    target: str
    edge_type: EdgeType
    is_major: bool


class InterestExtraOut(BaseModel):
    syllabus_id: str
    why: str
    source: str


class InterestOut(BaseModel):
    id: str
    label: str
    targets: list[str]
    extras: list[InterestExtraOut]


class DepartmentGraph(BaseModel):
    department_id: str
    edge_types: list[EdgeType]
    groups: list[GroupNode]
    edges: list[GroupEdge]
    interests: list[InterestOut]
    members: list[CourseSummary]


# --- D6 卒業要件と区分 ---------------------------------------------------------------


class CreditBucket(BaseModel):
    key: CreditBucketKey
    label: str
    credits: float


class ThesisRule(BaseModel):
    """thesis_requirements JSONB（ingestion の bulletin_schema.ThesisRequirementRule の形）。"""

    max_unearned_required_courses: int
    max_unearned_required_credits: int
    min_major_elective_required_credits: float
    mandatory_courses_completed: list[str]
    prerequisite_course: str | None
    raw_condition_text: str


class GraduationRequirements(BaseModel):
    requirement_id: str
    academic_year: int
    total_credits: float
    buckets: list[CreditBucket]
    thesis: ThesisRule
    rules_notes: list[str]
    term_cap: float | None = None  # 学期の履修上限は DB に無い。常に null


class RequirementsOut(BaseModel):
    department_id: str
    status: Availability  # 卒業要件の有無
    reason: str | None
    requirements: GraduationRequirements | None
    kinds: DataStatus  # 区分の有無
    kinds_count: dict[str, int]  # required / elective_required / elective の件数
    source: str = "postgres:graduation_requirements,course_requirements"
