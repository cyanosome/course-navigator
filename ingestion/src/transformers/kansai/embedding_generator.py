"""
Syllabus Embedding Generator for Kansai University (Fail-Fast, Strict Gemini API).

Generates 768-dimensional text embeddings for courses using Google Gemini (gemini-embedding-001).
Fails fast with explicit errors if GEMINI_API_KEY is missing or Gemini API is unreachable,
preventing silent errors caused by fabricated mock vectors.
"""

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx

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

GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_DIMENSION = 768


class GeminiConnectionError(RuntimeError):
    """Raised when communication with Gemini API fails."""
    pass


def sanitize_key(key: Optional[str]) -> str:
    """Trim leading/trailing whitespaces, newlines, and single/double quotes."""
    if not key:
        return ""
    return key.strip().strip("'\"").strip()


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


class EmbeddingGenerator:
    """Handles embedding generation via Gemini API strictly without mock fallback."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = GEMINI_EMBEDDING_MODEL,
        dimension: int = DEFAULT_DIMENSION,
    ):
        self.api_key = sanitize_key(api_key or os.getenv("GEMINI_API_KEY"))
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY が未設定です。.env に設定するか、"
                "python -m src.tools.verify_gemini でキーの健全性を確認してください。"
            )
        self.model = model.removeprefix("models/")
        self.dimension = dimension

    def probe_connectivity(self) -> None:
        """Probe Gemini API with 1 text to ensure connectivity before batch processing."""
        logger.info("Probing Gemini API connectivity (model=%s)...", self.model)
        try:
            res = self.embed_texts_batch_gemini(["疎通テスト"])
            if not res or len(res[0]) != self.dimension:
                raise GeminiConnectionError(f"Unexpected embedding dimension: {len(res[0]) if res else 0}")
            logger.info("Gemini API probe succeeded (dimension=%d).", len(res[0]))
        except Exception as e:
            raise GeminiConnectionError(
                f"Gemini API への事前疎通テストに失敗しました。\n"
                f"理由: {e}\n"
                f"python -m src.tools.verify_gemini を実行して原因と対処法を確認してください。"
            ) from e

    def embed_texts_batch_gemini(self, texts: List[str]) -> List[List[float]]:
        """Call Google Gemini batchEmbedContents API."""
        model_name = self.model.removeprefix("models/")
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
                raise GeminiConnectionError(
                    f"Gemini Embedding API error (HTTP {resp.status_code}): {resp.text[:300]}"
                )
            data = resp.json()
            embeddings = data.get("embeddings", [])
            if len(embeddings) != len(texts):
                raise GeminiConnectionError(
                    f"Expected {len(texts)} embeddings, but received {len(embeddings)}"
                )
            return [e["values"] for e in embeddings]

    def generate_embeddings_for_courses(
        self,
        courses: List[Dict[str, Any]],
        batch_size: int = 50,
    ) -> Dict[str, Any]:
        """Generate embeddings for all courses with progress logging (Fail-Fast)."""
        results: Dict[str, Any] = {}
        total = len(courses)
        logger.info("Generating embeddings for %d courses via Gemini API...", total)

        # Preflight connectivity probe
        self.probe_connectivity()

        for i in range(0, total, batch_size):
            batch = courses[i : i + batch_size]
            batch_texts = [build_course_text(c) for c in batch]
            
            try:
                batch_embeddings = self.embed_texts_batch_gemini(batch_texts)
            except Exception as e:
                logger.error("Gemini API call failed for batch starting at index %d: %s", i, e)
                raise GeminiConnectionError(
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

    generator = EmbeddingGenerator(dimension=DEFAULT_DIMENSION)
    data = generator.generate_embeddings_for_courses(courses=courses, batch_size=batch_size)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("Saved %d embeddings to %s", data["count"], output_path)

    return data


def main():
    parser = argparse.ArgumentParser(description="Generate course embeddings for Neo4j Vector Index (Strict Gemini API)")
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
