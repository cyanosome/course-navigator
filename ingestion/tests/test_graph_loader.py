"""Unit tests for Neo4j graph loader."""

import json
from pathlib import Path
from unittest.mock import MagicMock, call
import pytest

from src.graph.loader import (
    ensure_constraints,
    load_courses_batch,
    load_from_file,
)
from src.graph.schema import CONSTRAINTS, BATCH_INGEST_QUERY


def test_ensure_constraints():
    """Should execute all constraint queries on the session."""
    session = MagicMock()
    mock_result = MagicMock()
    session.run.return_value = mock_result

    ensure_constraints(session)

    assert session.run.call_count == len(CONSTRAINTS)
    for constraint in CONSTRAINTS:
        session.run.assert_any_call(constraint)
    assert mock_result.consume.call_count == len(CONSTRAINTS)


def test_load_courses_batch():
    """Should pass batch records to session.run with BATCH_INGEST_QUERY."""
    session = MagicMock()
    mock_result = MagicMock()
    session.run.return_value = mock_result

    batch = [
        {"course_code": "500101", "course_name": "仏教と人間"},
        {"course_code": "500201", "course_name": "哲学入門"},
    ]
    load_courses_batch(session, batch)

    session.run.assert_called_once_with(BATCH_INGEST_QUERY, batch=batch)
    mock_result.consume.assert_called_once()


def test_load_courses_batch_empty():
    """Should do nothing if batch is empty."""
    session = MagicMock()
    load_courses_batch(session, [])
    session.run.assert_not_called()


def test_load_from_file(tmp_path: Path):
    """Should load JSON file, apply constraints, and batch process records."""
    test_json = tmp_path / "courses.json"
    dummy_courses = [
        {"course_code": "101", "course_name": "Course A"},
        {"course_code": "102", "course_name": "Course B"},
        {"course_code": "103", "course_name": "Course C"},
    ]
    test_json.write_text(json.dumps(dummy_courses), encoding="utf-8")

    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session

    summary = load_from_file(test_json, driver, batch_size=2)

    assert summary["total_records"] == 3
    assert summary["records_processed"] == 3
    assert summary["batches_processed"] == 2  # batch 1: 2 items, batch 2: 1 item

    # Constraints called + 2 batches called
    expected_run_calls = len(CONSTRAINTS) + 2
    assert session.run.call_count == expected_run_calls


def test_load_from_file_not_found(tmp_path: Path):
    """Should raise FileNotFoundError when json file does not exist."""
    driver = MagicMock()
    missing_file = tmp_path / "non_existent.json"

    with pytest.raises(FileNotFoundError):
        load_from_file(missing_file, driver)
