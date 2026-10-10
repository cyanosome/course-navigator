"""Unit tests for curriculum_booklet_parser (Style 3)."""

import json
from pathlib import Path
import pytest

from src.parsers.komazawa.curriculum_block_parser import normalize_string
from src.parsers.komazawa.curriculum_booklet_parser import parse_booklet_pdf

PDF_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "raw"
    / "university"
    / "komazawa"
    / "2026"
    / "curriculum"
    / "2026_22.pdf"
)

SYLLABUS_FILE = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "parsed"
    / "university"
    / "komazawa"
    / "2026"
    / "courses_summary.json"
)


@pytest.fixture(scope="module")
def syllabus_lookup():
    if not SYLLABUS_FILE.exists():
        return {}
    with open(SYLLABUS_FILE, encoding="utf-8") as f:
        courses = json.load(f)
    lookup = {}
    for c in courses:
        norm = normalize_string(c["course_name"])
        if norm not in lookup:
            lookup[norm] = []
        lookup[norm].append(c["course_code"])
    return lookup


def test_parse_common_education_booklet(syllabus_lookup):
    """Should extract general education courses from 2026_22.pdf."""
    assert PDF_PATH.exists()

    items = parse_booklet_pdf(
        pdf_path=PDF_PATH,
        syllabus_lookup=syllabus_lookup,
    )

    assert len(items) >= 150, f"Expected at least 150 courses, got {len(items)}"

    # Check series names
    series = set(i.field_name for i in items if i.field_name)
    assert any("教養教育科目" in s for s in series)
    assert any("外国語科目" in s for s in series)
    assert any("保健体育科目" in s for s in series)

    # Spot checks on common education course names
    names = [i.name for i in items]
    assert any("文化人類学" in n for n in names)
    assert any("データサイエンス" in n or "情報" in n for n in names)
