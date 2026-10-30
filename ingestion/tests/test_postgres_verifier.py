"""
Unit tests for PostgreSQL verification tool.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from src.loaders.postgres.db import get_db_config
from src.loaders.postgres.verify_data import (
    format_course_display,
    diff_with_json,
    execute_read_query,
)


def test_get_db_config(monkeypatch):
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "test_db")
    monkeypatch.setenv("DB_USER", "test_user")
    monkeypatch.setenv("DB_PASSWORD", "test_pass")

    cfg = get_db_config()
    assert cfg["host"] == "127.0.0.1"
    assert cfg["port"] == 5432
    assert cfg["dbname"] == "test_db"
    assert cfg["user"] == "test_user"
    assert cfg["password"] == "test_pass"


def test_format_course_display():
    sample_course = {
        "syllabus_id": "162242",
        "timetable_code": "64214",
        "subject_name": "ユニットオペレーション１",
        "academic_year": 2026,
        "year_range": "２年次",
        "semester": "春",
        "term_schedule": "火2",
        "credits": 2.0,
        "credits_raw": "2",
        "faculties": ["環"],
        "department_codes": ["01320031"],
        "teaching_type": "講義（対面型）",
        "instructors": [{"name": "荒木 貞夫", "code": "70726", "is_primary": True}],
        "description": "化学工学単位操作の解説。",
        "objectives": "流動伝熱の基礎修得。",
        "grading_policy": "平常点70%と小テスト30%",
        "schedule_sessions": [{"raw_line": "第1回 オリエンテーション"}],
        "textbooks": ["教科書A"],
        "references": ["参考書B"],
        "detail_url": "https://example.com/ref/162242.html",
    }

    output = format_course_display(sample_course)
    assert "ユニットオペレーション１" in output
    assert "64214" in output
    assert "荒木 貞夫 [Code: 70726] (担任)" in output
    assert "化学工学単位操作の解説。" in output
    assert "第1回 オリエンテーション" in output
    assert "教科書A" in output


def test_diff_with_json_perfect_match(tmp_path: Path):
    json_path = tmp_path / "test_courses.json"
    sample_data = [
        {
            "syllabus_id": "162242",
            "subject_name": "ユニットオペレーション１",
            "course_code": "055060",
            "timetable_code": "64214",
            "academic_year": 2026,
            "semester": "春",
            "term_schedule": "火2",
            "credits": 2.0,
            "credits_raw": "2",
            "description": "概要",
            "objectives": "目標",
            "grading_policy": "評価",
        }
    ]
    json_path.write_text(json.dumps(sample_data), encoding="utf-8")

    # Mock DB connection and cursor
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # DB returns matching row
    mock_cur.fetchall.return_value = [
        {
            "syllabus_id": "162242",
            "subject_name": "ユニットオペレーション１",
            "course_code": "055060",
            "timetable_code": "64214",
            "academic_year": 2026,
            "semester": "春",
            "term_schedule": "火2",
            "credits": 2.0,
            "credits_raw": "2",
            "description": "概要",
            "objectives": "目標",
            "grading_policy": "評価",
        }
    ]

    report = diff_with_json(mock_conn, json_path)
    assert report["total_json"] == 1
    assert report["total_db"] == 1
    assert report["missing_in_db_count"] == 0
    assert report["extra_in_db_count"] == 0
    assert report["mismatches_count"] == 0
    assert report["is_perfect_match"] is True


def test_diff_with_json_mismatches(tmp_path: Path):
    json_path = tmp_path / "test_courses.json"
    sample_data = [
        {
            "syllabus_id": "162242",
            "subject_name": "ユニットオペレーション１",
            "course_code": "055060",
            "credits": 2.0,
            "credits_raw": "2",
        },
        {
            "syllabus_id": "999999",
            "subject_name": "未登録科目",
            "course_code": "000000",
            "credits": 1.0,
            "credits_raw": "1",
        },
    ]
    json_path.write_text(json.dumps(sample_data), encoding="utf-8")

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # DB returns 162242 with altered credits (1.0 vs 2.0) and missing 999999
    mock_cur.fetchall.return_value = [
        {
            "syllabus_id": "162242",
            "subject_name": "ユニットオペレーション１",
            "course_code": "055060",
            "credits": 1.0,
            "credits_raw": "1",
        }
    ]

    report = diff_with_json(mock_conn, json_path)
    assert report["total_json"] == 2
    assert report["total_db"] == 1
    assert report["missing_in_db_count"] == 1
    assert "999999" in report["missing_in_db_samples"]
    assert report["mismatches_count"] == 1
    assert report["is_perfect_match"] is False


def test_execute_read_query_forbidden(capsys):
    mock_conn = MagicMock()
    execute_read_query(mock_conn, "DROP TABLE courses;")
    captured = capsys.readouterr()
    assert "ERROR: Only read queries" in captured.out
    mock_conn.cursor.assert_not_called()
