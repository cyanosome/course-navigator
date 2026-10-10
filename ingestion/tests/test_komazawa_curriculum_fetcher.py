"""Unit tests for Komazawa University curriculum tree PDF fetcher."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import httpx
import pytest

from src.fetchers.komazawa.fetch_curriculum import (
    calculate_sha256,
    download_file,
    fetch_all_curriculums,
    TARGET_CURRICULUM_FILES,
)


def test_calculate_sha256(tmp_path: Path):
    """Should accurately compute SHA-256 hash of a file."""
    test_file = tmp_path / "sample.txt"
    test_file.write_bytes(b"hello curriculum")
    expected = "f2a2872098fcad6f1ce7fc1359c23da4508d0e60cd14f344be293819977ef13c"
    assert calculate_sha256(test_file) == expected


def test_download_file_already_exists(tmp_path: Path):
    """Should skip downloading if destination file already exists and is not empty."""
    test_file = tmp_path / "test.pdf"
    test_file.write_bytes(b"%PDF-1.4 dummy content")

    client = MagicMock()
    downloaded = download_file("https://example.com/test.pdf", test_file, client)

    assert downloaded is False
    client.stream.assert_not_called()


def test_download_file_success(tmp_path: Path):
    """Should stream download chunks and atomically save destination file."""
    test_file = tmp_path / "curriculum" / "sample.pdf"

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.iter_bytes.return_value = [b"%PDF-1.4 ", b"dummy binary data"]

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__enter__.return_value = mock_response
    mock_stream_ctx.__exit__.return_value = None

    client = MagicMock()
    client.stream.return_value = mock_stream_ctx

    downloaded = download_file("https://example.com/sample.pdf", test_file, client)

    assert downloaded is True
    assert test_file.exists()
    assert test_file.read_bytes() == b"%PDF-1.4 dummy binary data"
    tmp_file = test_file.with_name(f"{test_file.name}.tmp")
    assert not tmp_file.exists()
    client.stream.assert_called_once()


def test_download_file_failure_cleans_tmp(tmp_path: Path):
    """Should clean up partial temporary file if an exception occurs during streaming."""
    test_file = tmp_path / "failed.pdf"

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404 Not Found", request=MagicMock(), response=MagicMock()
    )

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__enter__.return_value = mock_response
    mock_stream_ctx.__exit__.return_value = None

    client = MagicMock()
    client.stream.return_value = mock_stream_ctx

    with pytest.raises(httpx.HTTPStatusError):
        download_file("https://example.com/failed.pdf", test_file, client)

    assert not test_file.exists()
    tmp_file = test_file.with_name(f"{test_file.name}.tmp")
    assert not tmp_file.exists()


def test_fetch_all_curriculums_mocked(tmp_path: Path):
    """Should download all configured curriculum files and write manifest.json."""
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.iter_bytes.return_value = [b"%PDF-1.4 mock data"]

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__enter__.return_value = mock_response
        mock_stream_ctx.__exit__.return_value = None

        mock_client.stream.return_value = mock_stream_ctx

        # Use interval_sec=0 for fast unit test
        summary = fetch_all_curriculums(base_dir=tmp_path, interval_sec=0.0)

        assert summary["total"] == len(TARGET_CURRICULUM_FILES)
        assert summary["downloaded"] == len(TARGET_CURRICULUM_FILES)
        assert summary["skipped"] == 0
        assert summary["failed"] == 0

        manifest_file = tmp_path / "curriculum" / "manifest.json"
        assert manifest_file.exists()
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert len(manifest_data) == len(TARGET_CURRICULUM_FILES)

        # Check first entry structure
        first = manifest_data[0]
        assert "id" in first
        assert "faculty" in first
        assert "department" in first
        assert "name" in first
        assert "url" in first
        assert "size_bytes" in first
        assert "sha256" in first
        assert first["size_bytes"] == len(b"%PDF-1.4 mock data")

        # Second run without force should skip all
        summary_second = fetch_all_curriculums(base_dir=tmp_path, interval_sec=0.0)
        assert summary_second["downloaded"] == 0
        assert summary_second["skipped"] == len(TARGET_CURRICULUM_FILES)
        assert summary_second["failed"] == 0


def test_fetch_all_curriculums_force_overwrites(tmp_path: Path):
    """Should re-download files when force=True is specified."""
    # Pre-create a file
    first_item = TARGET_CURRICULUM_FILES[0]
    first_file = tmp_path / first_item["category"] / first_item["name"]
    first_file.parent.mkdir(parents=True, exist_ok=True)
    first_file.write_bytes(b"old content")

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.iter_bytes.return_value = [b"new updated content"]

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__enter__.return_value = mock_response
        mock_stream_ctx.__exit__.return_value = None

        mock_client.stream.return_value = mock_stream_ctx

        summary = fetch_all_curriculums(force=True, base_dir=tmp_path, interval_sec=0.0)

        assert summary["downloaded"] == len(TARGET_CURRICULUM_FILES)
        assert first_file.read_bytes() == b"new updated content"
