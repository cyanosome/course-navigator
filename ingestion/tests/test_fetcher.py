import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from src.fetchers.nagasaki.fetch_data import download_file, fetch_all, TARGET_FILES


def test_download_file_already_exists(tmp_path: Path):
    test_file = tmp_path / "test.pdf"
    test_file.write_bytes(b"dummy content")

    client = MagicMock()
    downloaded = download_file("https://example.com/test.pdf", test_file, client)

    assert downloaded is False
    client.get.assert_not_called()


def test_download_file_success(tmp_path: Path):
    test_file = tmp_path / "subdir" / "new.pdf"

    mock_resp = MagicMock()
    mock_resp.content = b"pdf binary content"
    mock_resp.raise_for_status = MagicMock()

    client = MagicMock()
    client.get.return_value = mock_resp

    downloaded = download_file("https://example.com/new.pdf", test_file, client)

    assert downloaded is True
    assert test_file.exists()
    assert test_file.read_bytes() == b"pdf binary content"
    client.get.assert_called_once()


def test_fetch_all(tmp_path: Path):
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.content = b"sample pdf data"
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        summary = fetch_all(base_dir=tmp_path)

        assert summary["downloaded"] == len(TARGET_FILES)
        assert summary["skipped"] == 0
        assert summary["failed"] == 0

        # Second run without force should skip all
        summary_second = fetch_all(base_dir=tmp_path)
        assert summary_second["downloaded"] == 0
        assert summary_second["skipped"] == len(TARGET_FILES)
        assert summary_second["failed"] == 0
