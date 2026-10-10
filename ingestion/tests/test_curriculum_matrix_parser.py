"""Unit tests for curriculum_matrix_parser (Style 1)."""

from pathlib import Path
import pytest

from src.parsers.komazawa.curriculum_matrix_parser import (
    determine_year_from_x,
    normalize_title,
    parse_matrix_pdf,
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


def test_normalize_title():
    """Should correctly normalize title variants."""
    assert normalize_title("Oral  Communication Ⅰ") == "Oral Communication I"
    assert normalize_title("プログラミング基礎　") == "プログラミング基礎"
    assert normalize_title("ミクロ経済学Ⅱ") == "ミクロ経済学II"


def test_determine_year_from_x():
    """Should accurately assign year based on split boundaries."""
    boundaries = [300.0, 500.0, 700.0]
    assert determine_year_from_x(150.0, boundaries) == 1
    assert determine_year_from_x(350.0, boundaries) == 2
    assert determine_year_from_x(600.0, boundaries) == 3
    assert determine_year_from_x(750.0, boundaries) == 4


def test_parse_gms_curriculum():
    """Should extract courses from GMS curriculum PDF (2026_21.pdf)."""
    pdf_path = BASE_DIR / "2026_21.pdf"
    assert pdf_path.exists()

    items = parse_matrix_pdf(
        pdf_path=pdf_path,
        faculty="グローバル･メディア･スタディーズ学部",
        department="グローバル･メディア学科",
        manifest_id="gms_global_media",
    )

    assert len(items) >= 100, f"Expected at least 100 courses, got {len(items)}"

    # Check year distribution (all 4 years must exist)
    years = set(item.year for item in items)
    assert years == {1, 2, 3, 4}, f"All 4 years should be present, got {years}"

    # Check requirement types
    reqs = set(item.requirement_type for item in items)
    assert "必修" in reqs
    assert "選択必修" in reqs
    assert "選択" in reqs

    # Check 10-digit code presence
    with_code = [item for item in items if item.curriculum_code]
    assert len(with_code) >= 80
    assert with_code[0].field_code == with_code[0].curriculum_code[:3]


def test_parse_economics_curriculum():
    """Should extract courses from Economics curriculum PDF (2026_4.pdf)."""
    pdf_path = BASE_DIR / "2026_4.pdf"
    assert pdf_path.exists()

    items = parse_matrix_pdf(
        pdf_path=pdf_path,
        faculty="経済学部",
        department="経済学科",
        manifest_id="economics_economics",
    )

    assert len(items) >= 150, f"Expected at least 150 courses, got {len(items)}"
    years = set(item.year for item in items)
    assert 1 in years and 2 in years and 3 in years


def test_parse_law_multipage_curriculum():
    """Should extract courses from multipage Law curriculum PDF (2026_5.pdf)."""
    pdf_path = BASE_DIR / "2026_5.pdf"
    assert pdf_path.exists()

    items = parse_matrix_pdf(
        pdf_path=pdf_path,
        faculty="法学部",
        department="法律学科",
        manifest_id="law_law",
    )

    assert len(items) >= 50
