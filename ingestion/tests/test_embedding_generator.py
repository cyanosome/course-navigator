"""
Unit tests for Syllabus Embedding Generator.
"""

import json
from pathlib import Path
import numpy as np
import pytest

from src.transformers.kansai.embedding_generator import (
    build_course_text,
    generate_deterministic_mock_embedding,
    EmbeddingGenerator,
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


def test_generate_deterministic_mock_embedding():
    text1 = "物理化学１ 化学熱力学"
    text2 = "物理化学１ 化学熱力学"
    text3 = "有機化学１ 構造と反応"

    emb1 = generate_deterministic_mock_embedding(text1, dimension=DEFAULT_DIMENSION)
    emb2 = generate_deterministic_mock_embedding(text2, dimension=DEFAULT_DIMENSION)
    emb3 = generate_deterministic_mock_embedding(text3, dimension=DEFAULT_DIMENSION)

    assert len(emb1) == DEFAULT_DIMENSION
    assert emb1 == emb2, "Identical text must generate identical embeddings"
    assert emb1 != emb3, "Different text must generate different embeddings"

    # Verify unit norm
    norm = np.linalg.norm(emb1)
    assert pytest.approx(norm, rel=1e-3) == 1.0


def test_embedding_generator_mock_batch():
    generator = EmbeddingGenerator(dimension=DEFAULT_DIMENSION, force_mock=True)
    courses = [
        {"syllabus_id": "1001", "course_code": "C01", "subject_name": "科目A", "description": "説明A"},
        {"syllabus_id": "1002", "course_code": "C02", "subject_name": "科目B", "description": "説明B"},
    ]
    res = generator.generate_embeddings_for_courses(courses, batch_size=1)
    assert res["count"] == 2
    assert "1001" in res["courses"]
    assert "1002" in res["courses"]
    assert len(res["courses"]["1001"]["embedding"]) == DEFAULT_DIMENSION


def test_run_generate_embeddings_cache(tmp_path: Path):
    dummy_input = tmp_path / "dummy_courses.json"
    dummy_output = tmp_path / "dummy_embeddings.json"

    sample = [{"syllabus_id": "999", "subject_name": "テスト科目", "description": "テスト"}]
    with open(dummy_input, "w", encoding="utf-8") as f:
        json.dump(sample, f)

    res1 = run_generate_embeddings(
        input_path=dummy_input,
        output_path=dummy_output,
        force_mock=True,
    )
    assert dummy_output.exists()
    assert res1["count"] == 1

    # Call again without force_recompute -> must load from cache
    res2 = run_generate_embeddings(
        input_path=dummy_input,
        output_path=dummy_output,
        force_recompute=False,
    )
    assert res2 == res1
