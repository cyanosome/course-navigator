"""Unit tests for curriculum_block_parser (Style 2)."""

import json
from pathlib import Path
import pytest

from src.parsers.komazawa.curriculum_block_parser import (
    normalize_string,
    parse_block_pdf,
)

BASE_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "raw"
    / "university"
    / "komazawa"
    / "2026"
    / "curriculum"
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
    """Build normalized course title to course codes lookup."""
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


def test_parse_zen_curriculum(syllabus_lookup):
    """Should extract courses from Zen department PDF (331c...pdf)."""
    pdf_path = BASE_DIR / "331c2c0cc6cd796b1a229ea3905ac149.pdf"
    assert pdf_path.exists()

    items = parse_block_pdf(
        pdf_path=pdf_path,
        faculty="仏教学部",
        department="禅学科",
        manifest_id="buddhism_zen",
        syllabus_lookup=syllabus_lookup,
    )

    assert len(items) >= 20, f"Expected at least 20 courses, got {len(items)}"
    course_names = [i.name for i in items]
    assert any("仏教と人間" in name for name in course_names)
    assert any("新入生セミナー" in name for name in course_names)


def test_parse_japanese_curriculum(syllabus_lookup):
    """Should extract courses from Japanese Literature PDF (2026_03.pdf)."""
    pdf_path = BASE_DIR / "2026_03.pdf"
    assert pdf_path.exists()

    items = parse_block_pdf(
        pdf_path=pdf_path,
        faculty="文学部",
        department="国文学科",
        manifest_id="letters_japanese",
        syllabus_lookup=syllabus_lookup,
    )

    assert len(items) >= 15, f"Expected at least 15 courses, got {len(items)}"


def test_parse_management_multipage_curriculum(syllabus_lookup):
    """Should extract courses from 4-page Management department PDF (2026_18.pdf)."""
    pdf_path = BASE_DIR / "2026_18.pdf"
    assert pdf_path.exists()

    items = parse_block_pdf(
        pdf_path=pdf_path,
        faculty="経営学部",
        department="経営学科",
        manifest_id="business_management",
        syllabus_lookup=syllabus_lookup,
    )

    assert len(items) >= 20, f"Expected at least 20 courses, got {len(items)}"


def test_parse_radiology_multipage_curriculum(syllabus_lookup):
    """Should extract courses from 5-page Radiological Technology PDF (2026_3.pdf)."""
    pdf_path = BASE_DIR / "2026_3.pdf"
    assert pdf_path.exists()

    items = parse_block_pdf(
        pdf_path=pdf_path,
        faculty="医療健康科学部",
        department="診療放射線技術科学科",
        manifest_id="medical_radiological",
        syllabus_lookup=syllabus_lookup,
    )

    assert len(items) >= 25, f"Expected at least 25 courses, got {len(items)}"
