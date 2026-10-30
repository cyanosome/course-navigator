"""
Unit tests for PostgreSQL course loader.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from psycopg.types.json import Jsonb

from src.loaders.postgres.loader import (
    PostgresCourseLoader,
    LoadReport,
    UPSERT_COURSE_SQL,
)


def test_entry_to_row_full():
    entry = {
        "syllabus_id": "162242",
        "academic_year": 2026,
        "course_code": "055060",
        "timetable_code": "64214",
        "subject_name": "ユニットオペレーション１",
        "subtitle": "副題",
        "credits": 2.0,
        "credits_raw": "2",
        "year_range": "２年次",
        "class_name": "1組",
        "semester": "春学期",
        "term_schedule": "火2",
        "faculties": ["環"],
        "department_codes": ["01320031"],
        "subject_type_code": "01320031",
        "category_code": "0001",
        "language": "日本語",
        "teaching_type": "講義（対面型）",
        "teaching_methods": ["対面"],
        "instructors": [{"name": "荒木 貞夫", "code": "70726", "is_primary": True}],
        "instructors_tantou_raw": ["荒木 貞夫"],
        "instructors_tannin_raw": ["荒木 貞夫"],
        "instructor_codes": ["70726"],
        "contact_method": "メール",
        "description": "化学工学単位操作の解説。",
        "objectives": "流動伝熱の基礎修得。",
        "schedule_raw": "第1回 オリエンテーション",
        "schedule_sessions": [{"session_number": 1, "topic": "オリエンテーション"}],
        "work_outside_class": "予習復習",
        "grading_policy": "定期試験70%",
        "evaluation_criteria": "評価基準",
        "feedback_method": "講評",
        "textbooks": ["教科書A"],
        "textbook_notes": "特になし",
        "references": ["参考書B"],
        "reference_notes": "特になし",
        "notes": "注意事項",
        "detail_url": "https://example.com/162242.html",
        "relative_ref_path": "ref/162242.html",
    }

    row = PostgresCourseLoader.entry_to_row(entry)
    assert len(row) == 39
    assert row[0] == "162242"
    assert row[1] == 2026
    assert row[4] == "ユニットオペレーション１"
    assert row[6] == 2.0
    assert row[12] == ["環"]
    assert isinstance(row[19], Jsonb)
    assert row[19].obj == [{"name": "荒木 貞夫", "code": "70726", "is_primary": True}]
    assert isinstance(row[27], Jsonb)
    assert row[27].obj == [{"session_number": 1, "topic": "オリエンテーション"}]
    assert row[32] == ["教科書A"]
    assert row[34] == ["参考書B"]
    assert row[38] == "ref/162242.html"


def test_entry_to_row_sparse_defaults():
    entry = {
        "syllabus_id": "162243",
        "academic_year": 2026,
        "course_code": "055061",
        "subject_name": "演習",
    }

    row = PostgresCourseLoader.entry_to_row(entry)
    assert len(row) == 39
    assert row[0] == "162243"
    assert row[4] == "演習"
    assert row[12] == []  # faculties default empty list
    assert row[13] == []  # department_codes default empty list
    assert isinstance(row[19], Jsonb)
    assert row[19].obj == []
    assert row[20] == []
    assert isinstance(row[27], Jsonb)
    assert row[27].obj == []
    assert row[32] == []
    assert row[34] == []


def test_load_from_json_empty(tmp_path: Path):
    empty_json = tmp_path / "empty.json"
    empty_json.write_text("[]", encoding="utf-8")

    mock_conn = MagicMock()
    mock_conn.closed = False
    loader = PostgresCourseLoader(conn=mock_conn)
    report = loader.load_from_json(json_path=empty_json)

    assert report.total_records == 0
    assert report.loaded_records == 0
    assert report.is_verified is True


def test_load_from_json_dry_run(tmp_path: Path):
    json_path = tmp_path / "sample.json"
    sample_data = [
        {
            "syllabus_id": "162242",
            "academic_year": 2026,
            "course_code": "055060",
            "subject_name": "ユニットオペレーション１",
        }
    ]
    json_path.write_text(json.dumps(sample_data), encoding="utf-8")

    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    loader = PostgresCourseLoader(conn=mock_conn)
    with patch("src.loaders.postgres.loader.create_courses_table") as mock_create_table:
        report = loader.load_from_json(json_path=json_path, dry_run=True)

        assert mock_create_table.called
        assert mock_cursor.executemany.called
        assert mock_conn.rollback.called
        assert report.dry_run is True
        assert report.loaded_records == 1


def test_load_from_json_live_success(tmp_path: Path):
    json_path = tmp_path / "sample.json"
    sample_data = [
        {
            "syllabus_id": "162242",
            "academic_year": 2026,
            "course_code": "055060",
            "subject_name": "ユニットオペレーション１",
        }
    ]
    json_path.write_text(json.dumps(sample_data), encoding="utf-8")

    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.transaction.return_value.__enter__.return_value = None

    loader = PostgresCourseLoader(conn=mock_conn)
    with patch("src.loaders.postgres.loader.create_courses_table"), \
         patch("src.loaders.postgres.loader.diff_with_json") as mock_diff:
        mock_diff.return_value = {
            "is_perfect_match": True,
            "mismatches_count": 0,
            "missing_in_db_count": 0,
        }

        report = loader.load_from_json(json_path=json_path, dry_run=False, skip_verify=False)

        assert mock_cursor.executemany.called
        assert mock_diff.called
        assert report.is_verified is True
        assert report.dry_run is False
        assert report.loaded_records == 1


def test_load_from_json_verification_failure(tmp_path: Path):
    json_path = tmp_path / "sample.json"
    sample_data = [
        {
            "syllabus_id": "162242",
            "academic_year": 2026,
            "course_code": "055060",
            "subject_name": "ユニットオペレーション１",
        }
    ]
    json_path.write_text(json.dumps(sample_data), encoding="utf-8")

    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.transaction.return_value.__enter__.return_value = None

    loader = PostgresCourseLoader(conn=mock_conn)
    with patch("src.loaders.postgres.loader.create_courses_table"), \
         patch("src.loaders.postgres.loader.diff_with_json") as mock_diff:
        mock_diff.return_value = {
            "is_perfect_match": False,
            "mismatches_count": 2,
            "missing_in_db_count": 1,
        }

        with pytest.raises(RuntimeError) as exc_info:
            loader.load_from_json(json_path=json_path, dry_run=False, skip_verify=False)

        assert "Post-load verification failed" in str(exc_info.value)
