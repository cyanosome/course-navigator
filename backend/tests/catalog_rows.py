"""データの API のテストで使う DB の行の架空の例（tests/fake_graph.py と同じく tests の下の部品）。

asyncpg の既定どおり JSONB の列は JSON の文字列で持つ。
"""

import json
from decimal import Decimal


def course_row(**overrides):
    """courses の1行（＋ kind・cr_* 列）の架空の例。asyncpg の既定どおり JSONB は文字列で持つ。"""
    row = {
        "syllabus_id": "900001",
        "academic_year": 2026,
        "course_code": "X00001",
        "subject_name": "架空の反応工学１",
        "subtitle": None,
        "credits": Decimal("2.0"),
        "year_range": "１〜４年次",
        "semester": "春",
        "term_schedule": "火2",
        "faculties": ["環", "化"],
        "instructors": json.dumps(
            [
                {"name": "架空 一郎", "code": "1", "is_primary": False},
                {"name": "架空 花子", "code": "2", "is_primary": True},
            ],
            ensure_ascii=False,
        ),
        "description": "あ" * 130,
        "detail_url": "https://example.invalid/900001",
        "objectives": "架空の到達目標",
        "schedule_sessions": json.dumps(
            [{"session_number": 1, "raw_line": "1. 導入", "topic": "導入"}], ensure_ascii=False
        ),
        "work_outside_class": None,
        "grading_policy": "架空の評価方法",
        "evaluation_criteria": None,
        "textbooks": ["架空の教科書"],
        "textbook_notes": None,
        "references": None,
        "notes": None,
        "language": "日本語(Japanese)",
        "teaching_type": "講義（対面型）",
        "kind": None,
        "cr_subject_name_bulletin": None,
        "cr_credits": None,
        "cr_assigned_year": None,
        "cr_bulletin_code": None,
        "cr_field_category": None,
    }
    row.update(overrides)
    return row


def graduation_row(**overrides):
    row = {
        "requirement_id": "2099_fictional",
        "academic_year": 2026,
        "total_credits": Decimal("124.0"),
        "general_education_credits": Decimal("10.0"),
        "general_designated_credits": Decimal("6.0"),
        "foreign_language_credits": Decimal("8.0"),
        "foreign_lang_first_credits": Decimal("6.0"),
        "foreign_lang_second_credits": Decimal("2.0"),
        "major_credits": Decimal("90.0"),
        "major_required_credits": Decimal("40.0"),
        "major_elective_required_credits": Decimal("20.0"),
        "thesis_requirements": json.dumps(
            {
                "max_unearned_required_courses": 3,
                "max_unearned_required_credits": 6,
                "min_major_elective_required_credits": 10.0,
                "mandatory_courses_completed": ["架空の実験"],
                "prerequisite_course": None,
                "raw_condition_text": "架空の条件",
            },
            ensure_ascii=False,
        ),
        "rules_notes": ["架空の注記"],
    }
    row.update(overrides)
    return row
