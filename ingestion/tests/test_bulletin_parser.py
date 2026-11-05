"""
Unit tests for Kansai University Bulletin Parser and Splitter.
"""

from pathlib import Path
import pytest

from src.transformers.kansai.bulletin_parser import (
    KansaiBulletinParser,
    normalize_subject_name,
)
from src.transformers.kansai.bulletin_schema import BulletinParsedPayload


def test_normalize_subject_name():
    """Verify Japanese Roman numerals and variations map to standard Arabic forms."""
    assert normalize_subject_name("線形代数Ⅰ") == "線形代数1"
    assert normalize_subject_name("線形代数Ⅱ") == "線形代数2"
    assert normalize_subject_name("物理化学Ⅲ") == "物理化学3"
    assert normalize_subject_name("ユニットオペレーションⅣ") == "ユニットオペレーション4"
    assert normalize_subject_name("外国語Ⅴ") == "外国語5"
    assert normalize_subject_name("数学を学ぶ（微分積分Ⅰ）") == "数学を学ぶ(微分積分1)"
    assert normalize_subject_name(" 入門 化学結合論 ") == "入門化学結合論"


def test_bulletin_parser_execution(tmp_path: Path):
    """Verify bulletin parser generates valid payload with graduation requirements and courses."""
    pdf_path = Path("data/raw/university/kansai/2026/bulletin/all_page.pdf")
    courses_path = Path("data/parsed/university/kansai/2026/courses_detail.json")
    out_json = tmp_path / "test_bulletin_cee.json"

    if not pdf_path.exists() or not courses_path.exists():
        pytest.skip("Required raw PDF or courses_detail.json not found.")

    parser = KansaiBulletinParser(
        pdf_path=pdf_path,
        courses_json_path=courses_path,
        output_json_path=out_json,
    )
    payload = parser.parse_all()

    assert isinstance(payload, BulletinParsedPayload)
    assert payload.graduation_requirement.total_credits == 128.0
    assert payload.graduation_requirement.major_required_credits == 53.0
    assert payload.graduation_requirement.major_elective_required_credits == 30.0

    # Verify thesis requirements
    thesis_rule = payload.graduation_requirement.thesis_requirements
    assert thesis_rule.max_unearned_required_courses == 4
    assert "化学工学実験" in thesis_rule.mandatory_courses_completed
    assert "有機化学実験" in thesis_rule.mandatory_courses_completed

    # Verify courses
    assert payload.total_bulletin_courses >= 70
    assert payload.matched_courses_count >= 70

    # Verify specific courses exist
    subject_names = [c.subject_name_bulletin for c in payload.courses]
    assert "線形代数Ⅰ" in subject_names
    assert "化学工学実験" in subject_names
    assert "粉体工学" in subject_names

    # Verify requirement types
    course_by_name = {c.subject_name_bulletin: c for c in payload.courses}
    assert course_by_name["線形代数Ⅰ"].requirement_type == "required"
    assert course_by_name["化学工学実験"].requirement_type == "required"
    assert course_by_name["粉体工学"].requirement_type == "elective_required"
