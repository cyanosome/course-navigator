"""Unit tests for Komazawa University syllabus fetcher."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import httpx
import pytest

from src.fetchers.komazawa.fetch_data import (
    download_file,
    fetch_all,
    TARGET_FILES,
)


def test_download_file_already_exists(tmp_path: Path):
    """Should skip downloading if destination file already exists and is not empty."""
    test_file = tmp_path / "test.js"
    test_file.write_bytes(b"var dummy = [];")

    client = MagicMock()
    downloaded = download_file("https://example.com/test.js", test_file, client)

    assert downloaded is False
    client.stream.assert_not_called()


def test_download_file_success(tmp_path: Path):
    """Should stream download chunks and atomically save the destination file."""
    test_file = tmp_path / "subdir" / "syllabus_information.js"

    # Mock response for client.stream context manager
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.iter_bytes.return_value = [b"var nendo = '2026';", b"var data = [];"]

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__enter__.return_value = mock_response
    mock_stream_ctx.__exit__.return_value = None

    client = MagicMock()
    client.stream.return_value = mock_stream_ctx

    downloaded = download_file("https://example.com/test.js", test_file, client)

    assert downloaded is True
    assert test_file.exists()
    assert test_file.read_bytes() == b"var nendo = '2026';var data = [];"
    # Ensure temporary file is cleaned up
    tmp_file = test_file.with_name(f"{test_file.name}.tmp")
    assert not tmp_file.exists()
    client.stream.assert_called_once()


def test_download_file_failure_cleans_tmp(tmp_path: Path):
    """Should clean up partial temporary file if an exception occurs during streaming."""
    test_file = tmp_path / "failed.js"

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
        download_file("https://example.com/notfound.js", test_file, client)

    assert not test_file.exists()
    tmp_file = test_file.with_name(f"{test_file.name}.tmp")
    assert not tmp_file.exists()


def test_fetch_all(tmp_path: Path):
    """Should iterate through TARGET_FILES and return accurate download summary."""
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.iter_bytes.return_value = [b"data chunk"]

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__enter__.return_value = mock_response
        mock_stream_ctx.__exit__.return_value = None

        mock_client.stream.return_value = mock_stream_ctx

        # First run: should download
        summary = fetch_all(base_dir=tmp_path)
        assert summary["downloaded"] == len(TARGET_FILES)
        assert summary["skipped"] == 0
        assert summary["failed"] == 0

        # Second run: should skip existing files
        summary_second = fetch_all(base_dir=tmp_path)
        assert summary_second["downloaded"] == 0
        assert summary_second["skipped"] == len(TARGET_FILES)
        assert summary_second["failed"] == 0

        # Force run: should re-download
        summary_force = fetch_all(force=True, base_dir=tmp_path)
        assert summary_force["downloaded"] == len(TARGET_FILES)
        assert summary_force["skipped"] == 0
        assert summary_force["failed"] == 0


def test_fetch_all_with_failure(tmp_path: Path):
    """Should record failure count when download fails."""
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client_cls.return_value = mock_client

        mock_client.stream.side_effect = httpx.RequestError("Network connection error")

        summary = fetch_all(base_dir=tmp_path)
        assert summary["downloaded"] == 0
        assert summary["skipped"] == 0
        assert summary["failed"] == len(TARGET_FILES)
