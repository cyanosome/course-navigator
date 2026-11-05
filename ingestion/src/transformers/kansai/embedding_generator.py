"""
Syllabus Embedding Generator for Kansai University.

Generates 768-dimensional text embeddings for courses using Google Gemini (text-embedding-004)
or a deterministic mock generator (fallback for offline/testing environments).
Saves results into course_embeddings.json for Neo4j Vector Index and similarity calculation.
"""

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
import numpy as np

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

GEMINI_EMBEDDING_MODEL = "text-embedding-004"
DEFAULT_DIMENSION = 768


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


def generate_deterministic_mock_embedding(text: str, dimension: int = DEFAULT_DIMENSION) -> List[float]:
    """
    Generate a deterministic unit-norm pseudo-random vector based on text SHA-256 hash.
    Ensures identical text produces identical embedding vectors for test repeatability.
    """
    h = hashlib.sha256(text.encode("utf-8")).digest()
    # Use first 8 bytes of hash as integer seed
    seed = int.from_bytes(h[:8], byteorder="big") % (2**32)
    rng = np.random.RandomState(seed)
    raw_vec = rng.randn(dimension).astype(np.float32)
    norm = np.linalg.norm(raw_vec)
    if norm > 0:
        normalized_vec = raw_vec / norm
    else:
        normalized_vec = raw_vec
    return [round(float(v), 6) for v in normalized_vec]


class EmbeddingGenerator:
    """Handles embedding generation via Gemini API with deterministic fallback."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = GEMINI_EMBEDDING_MODEL,
        dimension: int = DEFAULT_DIMENSION,
        force_mock: bool = False,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model
        self.dimension = dimension
        self.force_mock = force_mock

        if not self.api_key or self.api_key in ("gemini", "your_gemini_api_key_here", ""):
            if not self.force_mock:
                logger.warning("Valid GEMINI_API_KEY not found in environment. Falling back to deterministic mock embeddings.")
            self.force_mock = True

    def embed_texts_batch_gemini(self, texts: List[str]) -> List[List[float]]:
        """Call Google Gemini batchEmbedContents API."""
        model_name = self.model if self.model.startswith("models/") else f"models/{self.model}"
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:batchEmbedContents"
        requests = [
            {
                "model": model_name,
                "content": {"parts": [{"text": t}]},
                "taskType": "RETRIEVAL_DOCUMENT",
            }
            for t in texts
        ]
        payload = {"requests": requests}
        
        with httpx.Client(timeout=30.0) as client:
            headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Gemini Embedding API error ({resp.status_code}): {resp.text}"
                )
            data = resp.json()
            embeddings = data.get("embeddings", [])
            return [e["values"] for e in embeddings]

    def generate_embeddings_for_courses(
        self,
        courses: List[Dict[str, Any]],
        batch_size: int = 50,
    ) -> Dict[str, Any]:
        """Generate embeddings for all courses with progress logging."""
        results: Dict[str, Any] = {}
        total = len(courses)
        logger.info("Generating embeddings for %d courses (force_mock=%s)...", total, self.force_mock)

        for i in range(0, total, batch_size):
            batch = courses[i : i + batch_size]
            batch_texts = [build_course_text(c) for c in batch]
            
            if self.force_mock:
                batch_embeddings = [
                    generate_deterministic_mock_embedding(t, self.dimension)
                    for t in batch_texts
                ]
            else:
                try:
                    batch_embeddings = self.embed_texts_batch_gemini(batch_texts)
                except Exception as e:
                    logger.warning("Gemini API call failed for batch %d: %s. Switching to mock fallback for remaining batches.", i, e)
                    self.force_mock = True
                    batch_embeddings = [
                        generate_deterministic_mock_embedding(t, self.dimension)
                        for t in batch_texts
                    ]

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
            "model": "deterministic-mock-768" if self.force_mock else self.model,
            "dimension": self.dimension,
            "count": len(results),
            "courses": results,
        }
        return output_data


def run_generate_embeddings(
    input_path: Path = DEFAULT_COURSES_DETAIL,
    output_path: Path = DEFAULT_EMBEDDINGS_OUTPUT,
    force_mock: bool = False,
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

    generator = EmbeddingGenerator(dimension=DEFAULT_DIMENSION, force_mock=force_mock)
    data = generator.generate_embeddings_for_courses(courses=courses, batch_size=batch_size)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Saved %d embeddings to %s", data["count"], output_path)

    return data


def main():
    parser = argparse.ArgumentParser(description="Generate course embeddings for Neo4j Vector Index")
    parser.add_argument("--input", type=Path, default=DEFAULT_COURSES_DETAIL, help="Path to courses_detail.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_EMBEDDINGS_OUTPUT, help="Output path for embeddings")
    parser.add_argument("--mock", action="store_true", help="Force deterministic mock embedding generation")
    parser.add_argument("--force", action="store_true", help="Force recomputation even if cache exists")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for embedding generation")
    args = parser.parse_args()

    run_generate_embeddings(
        input_path=args.input,
        output_path=args.output,
        force_mock=args.mock,
        force_recompute=args.force,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
