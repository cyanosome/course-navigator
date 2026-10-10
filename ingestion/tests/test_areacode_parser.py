"""Unit tests for areacode_parser (Style 4)."""

import json
from pathlib import Path
import pytest

from src.parsers.komazawa.areacode_parser import (
    parse_areacode_pdf,
    save_areacodes,
)

PDF_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "raw"
    / "university"
    / "komazawa"
    / "2026"
    / "curriculum"
    / "areacode.pdf"
)


def test_parse_areacode_pdf():
    """Should correctly parse areacode.pdf into SubjectFieldItem objects."""
    assert PDF_PATH.exists(), f"areacode.pdf missing at {PDF_PATH}"

    items = parse_areacode_pdf(PDF_PATH)
    assert len(items) >= 70, f"Expected at least 70 area codes, got {len(items)}"

    # Check uniqueness of codes
    codes = [item.code for item in items]
    assert len(codes) == len(set(codes)), "Codes must be unique"

    # Spot checks on known codes
    code_map = {item.code: item for item in items}

    # 011 -> 宗教教育
    assert "011" in code_map
    assert code_map["011"].category == "全学共通科目"
    assert "宗教" in code_map["011"].field

    # 111 -> 情報学基礎
    assert "111" in code_map
    assert code_map["111"].category == "総合系"
    assert "情報学基礎" in code_map["111"].field

    # 361 -> 理論経済学
    assert "361" in code_map
    assert code_map["361"].category == "社会科学系"
    assert "理論経済学" in code_map["361"].field

    # 252 -> 日本史
    assert "252" in code_map
    assert code_map["252"].category == "人文学系"
    assert "日本史" in code_map["252"].field


def test_save_areacodes(tmp_path: Path):
    """Should save parsed codes to json properly."""
    items = parse_areacode_pdf(PDF_PATH)
    out_file = tmp_path / "areacodes.json"
    save_areacodes(items, out_file)

    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(data) == len(items)
    assert data[0]["code"] == items[0].code
