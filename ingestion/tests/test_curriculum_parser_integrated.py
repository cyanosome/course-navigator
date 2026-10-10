"""Integration tests for the overall curriculum parser dispatcher."""

import json
from pathlib import Path
import pytest

from src.parsers.komazawa.curriculum_parser import parse_all_curriculums

RAW_DIR = (
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


def test_parse_all_curriculums_integrated(tmp_path: Path):
    """Should process all 23 documents and generate json outputs."""
    report = parse_all_curriculums(
        raw_dir=RAW_DIR,
        parsed_dir=tmp_path,
        syllabus_path=SYLLABUS_FILE,
    )

    assert report.total_files_processed == 23
    assert report.total_subjects_extracted >= 1800
    assert report.total_syllabus_matches >= 1000
    assert report.overall_match_rate_pct >= 50.0

    # Verify generated files
    areacodes_file = tmp_path / "areacodes.json"
    subjects_file = tmp_path / "curriculum_subjects.json"
    report_file = tmp_path / "parse_report.json"

    assert areacodes_file.exists()
    assert subjects_file.exists()
    assert report_file.exists()

    subjects_data = json.loads(subjects_file.read_text(encoding="utf-8"))
    assert len(subjects_data) == report.total_subjects_extracted

    # Spot check one subject structure
    sample = subjects_data[0]
    assert "id" in sample
    assert "name" in sample
    assert "faculty" in sample
    assert "department" in sample
    assert 1 <= sample["year"] <= 4
    assert sample["requirement_type"] in ["必修", "選択必修", "選択", "不明"]
