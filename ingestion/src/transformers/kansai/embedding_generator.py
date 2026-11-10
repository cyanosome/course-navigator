"""Syllabus Embedding Generator for Kansai University (Fail-Fast, Official Google GenAI SDK).

Generates 768-dimensional text embeddings for courses using Google Gemini (gemini-embedding-001)
via the centralized src.services.embedding service.
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.services.embedding import (
    DEFAULT_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingService,
    GeminiEmbeddingError,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_COURSES_DETAIL = (
    PROJECT_ROOT / "data" / "parsed" / "university" / "kansai" / "2026" / "courses_detail.json"
)
DEFAULT_EMBEDDINGS_OUTPUT = (
    PROJECT_ROOT / "data" / "parsed" / "university" / "kansai" / "2026" / "course_embeddings.json"
)


def build_course_text(course: Dict[str, Any]) -> str:
    """Build structured summary text from course detail for embedding."""
    parts = []

    subject_name = (course.get("subject_name") or "").strip()
    if subject_name:
        parts.append(f"【科目名】{subject_name}")

    subtitle = (course.get("subtitle") or "").strip()
    if subtitle:
        parts.append(f"【副題】{subtitle}")

    desc = (course.get("description") or "").strip()
    if desc:
        parts.append(f"【講義概要】\n{desc}")

    objs = (course.get("objectives") or "").strip()
    if objs:
        parts.append(f"【到達目標】\n{objs}")

    # Extract topics from 15-week schedule if available
    sessions = course.get("schedule_sessions") or []
    if sessions and isinstance(sessions, list):
        session_topics = [
            f"第{s.get('session_no', i+1)}回: {s.get('theme', '')}"
            for i, s in enumerate(sessions)
            if isinstance(s, dict) and s.get("theme")
        ]
        if session_topics:
            parts.append(f"【主な講義計画】\n" + " / ".join(session_topics[:8]))

    return "\n\n".join(parts)


class CourseEmbeddingPipeline:
    """Orchestrates course embedding generation using centralized EmbeddingService."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimension: int = DEFAULT_DIMENSION,
    ):
        self.service = EmbeddingService(api_key=api_key, model=model, dimension=dimension)
        self.model = self.service.model
        self.dimension = dimension

    def generate_embeddings_for_courses(
        self,
        courses: List[Dict[str, Any]],
        batch_size: int = 50,
    ) -> Dict[str, Any]:
        """Generate embeddings for all courses with progress logging."""
        results: Dict[str, Any] = {}
        total = len(courses)
        logger.info("Generating embeddings for %d courses via Gemini API (%s)...", total, self.model)

        # Preflight connectivity probe
        self.service.probe_connectivity()

        for i in range(0, total, batch_size):
            batch = courses[i : i + batch_size]
            batch_texts = [build_course_text(c) for c in batch]

            try:
                batch_embeddings = self.service.embed_texts(batch_texts, batch_size=batch_size)
            except Exception as e:
                logger.error("Gemini API call failed for batch starting at index %d: %s", i, e)
                raise GeminiEmbeddingError(
                    f"バッチ処理中 (インデックス {i}/{total}) に Gemini API 通信が中断しました: {e}"
                ) from e

            for course, emb in zip(batch, batch_embeddings):
                s_id = str(course.get("syllabus_id"))
                results[s_id] = {
                    "syllabus_id": s_id,
                    "course_code": course.get("course_code"),
                    "subject_name": course.get("subject_name"),
                    "embedding": emb,
                }
            logger.info("Processed %d / %d courses", min(i + batch_size, total), total)

        output_data = {
            "model": self.model,
            "dimension": self.dimension,
            "count": len(results),
            "courses": results,
        }
        return output_data


# Alias for backwards compatibility if needed
EmbeddingGenerator = CourseEmbeddingPipeline
GeminiConnectionError = GeminiEmbeddingError


def run_generate_embeddings(
    input_path: Path = DEFAULT_COURSES_DETAIL,
    output_path: Path = DEFAULT_EMBEDDINGS_OUTPUT,
    force_recompute: bool = False,
    batch_size: int = 50,
) -> Dict[str, Any]:
    """Execute embedding generation and save to cache file."""
    if output_path.exists() and not force_recompute:
        logger.info("Loading cached embeddings from %s", output_path)
        with open(output_path, "r", encoding="utf-8") as f:
            return json.load(f)

    if not input_path.exists():
        raise FileNotFoundError(f"Courses detail JSON not found at {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        courses = json.load(f)

    pipeline = CourseEmbeddingPipeline(dimension=DEFAULT_DIMENSION)
    data = pipeline.generate_embeddings_for_courses(courses=courses, batch_size=batch_size)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Saved %d embeddings to %s", data["count"], output_path)

    return data


def main():
    parser = argparse.ArgumentParser(description="Generate course embeddings for Neo4j Vector Index (Official GenAI SDK)")
    parser.add_argument("--input", type=Path, default=DEFAULT_COURSES_DETAIL, help="Path to courses_detail.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_EMBEDDINGS_OUTPUT, help="Output path for embeddings")
    parser.add_argument("--force", action="store_true", help="Force recomputation even if cache exists")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for embedding generation")
    args = parser.parse_args()

    run_generate_embeddings(
        input_path=args.input,
        output_path=args.output,
        force_recompute=args.force,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
