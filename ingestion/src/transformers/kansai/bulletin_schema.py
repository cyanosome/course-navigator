"""
Pydantic Schemas for Kansai University Bulletin (要覧) Requirements Data.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ThesisRequirementRule(BaseModel):
    """特別研究（卒業研究）の着手要件ルール."""
    max_unearned_required_courses: int = Field(4, description="必修未修得科目数上限")
    max_unearned_required_credits: int = Field(8, description="必修未修得単位数上限")
    min_major_elective_required_credits: float = Field(24.0, description="選択必修修得単位数下限")
    mandatory_courses_completed: List[str] = Field(
        default_factory=list,
        description="着手前に修得必須の科目名リスト (例: 化学工学実験, 有機化学実験)"
    )
    prerequisite_course: Optional[str] = Field(None, description="特別研究Ⅱの場合の前提科目 (特別研究Ⅰ)")
    raw_condition_text: str = Field(..., description="要覧に記載された条件条文全文")


class GraduationRequirementDetail(BaseModel):
    """学科の卒業所要単位内訳マスター."""
    requirement_id: str = Field(..., description="要件ID (例: 2026_env_cee)")
    academic_year: int = Field(2026, description="対象年度")
    faculty_code: str = Field("320", description="学部コード")
    faculty_name: str = Field("環境都市工学部", description="学部名")
    department_code: str = Field("031", description="学科コード")
    department_name: str = Field("エネルギー環境・化学工学科", description="学科名")
    total_credits: float = Field(128.0, description="卒業所要単位合計")
    general_education_credits: float = Field(20.0, description="共通教養科目所要単位")
    general_designated_credits: float = Field(12.0, description="自己形成科目群指定科目単位")
    foreign_language_credits: float = Field(12.0, description="外国語科目所要単位")
    foreign_lang_first_credits: float = Field(8.0, description="第1外国語単位")
    foreign_lang_second_credits: float = Field(4.0, description="第2外国語単位")
    major_credits: float = Field(96.0, description="専門教育科目所要単位")
    major_required_credits: float = Field(53.0, description="専門必修所要単位")
    major_elective_required_credits: float = Field(30.0, description="専門選択必修所要単位")
    thesis_requirements: ThesisRequirementRule = Field(..., description="特別研究着手要件")
    rules_notes: List[str] = Field(default_factory=list, description="算入上限等の特記事項条文")


class BulletinCourseItem(BaseModel):
    """要覧科目一覧表から抽出された1科目レコード."""
    bulletin_code: Optional[str] = Field(None, description="科目番号 (例: CEE1, GEC1114)")
    subject_name_bulletin: str = Field(..., description="要覧記載の科目名")
    requirement_type: str = Field(..., description="必修区分: 'required' | 'elective_required' | 'elective'")
    credits: float = Field(..., description="単位数")
    assigned_year: Optional[int] = Field(None, description="配当年次 (1, 2, 3, 4)")
    period: Optional[str] = Field(None, description="授業期間")
    weekly_hours: Optional[str] = Field(None, description="毎週授業時間")
    field_category: Optional[str] = Field(None, description="共通教養の領域区分 (人間を知る, 自然と向き合う等)")
    matched_syllabus_ids: List[str] = Field(default_factory=list, description="照合された courses テーブルの syllabus_id 一覧")
    matched_course_code: Optional[str] = Field(None, description="照合された科目コード (062650等)")


class BulletinParsedPayload(BaseModel):
    """パーサー全体の出力ペイロード."""
    graduation_requirement: GraduationRequirementDetail
    courses: List[BulletinCourseItem]
    total_bulletin_courses: int
    matched_courses_count: int
    unmatched_courses_count: int
