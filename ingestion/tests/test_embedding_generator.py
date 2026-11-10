"""
Unit tests for Syllabus Embedding Generator (Fail-Fast, Strict API).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.transformers.kansai.embedding_generator import (
    build_course_text,
    EmbeddingGenerator,
    GeminiEmbeddingError,
    GeminiConnectionError,
    run_generate_embeddings,
    DEFAULT_DIMENSION,
)


def test_build_course_text():
    sample_course = {
        "syllabus_id": "64224",
        "subject_name": "物理化学１",
        "subtitle": "化学熱力学の基礎",
        "description": "熱力学第一法則、第二法則を中心に解説する。",
        "objectives": "エンタルピーとエントロピーを計算できること。",
        "schedule_sessions": [
            {"session_no": 1, "theme": "ガイダンスと熱力学の基礎"},
            {"session_no": 2, "theme": "第一法則と内部エネルギー"},
        ],
    }
    text = build_course_text(sample_course)
    assert "【科目名】物理化学１" in text
    assert "【副題】化学熱力学の基礎" in text
    assert "【講義概要】" in text
    assert "熱力学第一法則" in text
    assert "【到達目標】" in text
    assert "【主な講義計画】" in text
    assert "第1回: ガイダンスと熱力学の基礎" in text


def test_missing_api_key_raises_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY が未設定です"):
        EmbeddingGenerator(api_key="")


def test_api_failure_fails_fast_without_mock(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.test_key")
    with patch("src.services.embedding.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = RuntimeError("API key not valid")
        mock_client_cls.return_value = mock_client

        generator = EmbeddingGenerator()
        with pytest.raises(GeminiEmbeddingError, match="事前疎通テストに失敗しました"):
            generator.generate_embeddings_for_courses([
                {"syllabus_id": "1", "course_code": "C01", "subject_name": "テスト"}
            ])


def test_embedding_generator_successful_batch(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.test_key")
    dummy_vector = [0.1] * DEFAULT_DIMENSION

    with patch("src.services.embedding.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_res = MagicMock()
        mock_emb = MagicMock()
        mock_emb.values = dummy_vector
        mock_res.embeddings = [mock_emb, mock_emb]
        mock_client.models.embed_content.return_value = mock_res
        mock_client_cls.return_value = mock_client

        generator = EmbeddingGenerator(dimension=DEFAULT_DIMENSION)

        # Mock service.probe_connectivity and service.embed_texts
        with patch.object(generator.service, "probe_connectivity", return_value=None), \
             patch.object(generator.service, "embed_texts", return_value=[dummy_vector, dummy_vector]):
            courses = [
                {"syllabus_id": "1001", "course_code": "C01", "subject_name": "科目A"},
                {"syllabus_id": "1002", "course_code": "C02", "subject_name": "科目B"},
            ]
            res = generator.generate_embeddings_for_courses(courses, batch_size=2)
            assert res["count"] == 2
            assert res["courses"]["1001"]["embedding"] == dummy_vector
            assert res["courses"]["1002"]["embedding"] == dummy_vector


def test_run_generate_embeddings_cache(tmp_path: Path):
    dummy_input = tmp_path / "dummy_courses.json"
    dummy_output = tmp_path / "dummy_embeddings.json"

    # Pre-populate cache file
    cached_data = {
        "model": "gemini-embedding-001",
        "dimension": DEFAULT_DIMENSION,
        "count": 1,
        "courses": {"999": {"syllabus_id": "999", "embedding": [0.5] * DEFAULT_DIMENSION}},
    }
    with open(dummy_output, "w", encoding="utf-8") as f:
        json.dump(cached_data, f)

    # Must load from cache without calling API
    res = run_generate_embeddings(
        input_path=dummy_input,
        output_path=dummy_output,
        force_recompute=False,
    )
    assert res == cached_data
