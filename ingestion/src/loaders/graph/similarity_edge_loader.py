"""
Neo4j Course Similarity Edge Loader.

Computes cosine similarity matrix across all courses using NumPy,
filters top-K candidates above a given threshold, and loads [:SIMILAR_TO] edges
into Neo4j via UNWIND batching.
"""

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from neo4j import GraphDatabase, Driver
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_EMBEDDINGS_JSON = (
    PROJECT_ROOT / "data" / "parsed" / "university" / "kansai" / "2026" / "course_embeddings.json"
)

DEFAULT_NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
DEFAULT_NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
DEFAULT_NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "devpassword")


def get_driver(
    uri: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> Driver:
    """Create Neo4j driver connection."""
    u = uri or os.getenv("NEO4J_URI", DEFAULT_NEO4J_URI)
    usr = user or os.getenv("NEO4J_USER", DEFAULT_NEO4J_USER)
    pwd = password or os.getenv("NEO4J_PASSWORD", DEFAULT_NEO4J_PASSWORD)
    return GraphDatabase.driver(u, auth=(usr, pwd))


def compute_similarity_pairs(
    courses_dict: Dict[str, Any],
    threshold: float = 0.70,
    top_k: int = 5,
    model_name: str = "text-embedding-004",
) -> List[Dict[str, Any]]:
    """
    Compute pairwise cosine similarities using NumPy matrix multiplication.
    Returns list of edge dicts: [{source_id, target_id, score, model}, ...]
    """
    items = list(courses_dict.values())
    n = len(items)
    if n == 0:
        return []

    syllabus_ids = [str(item["syllabus_id"]) for item in items]
    # Build 2D matrix: shape (N, D)
    raw_vectors = np.array([item["embedding"] for item in items], dtype=np.float32)
    # Ensure unit norm
    norms = np.linalg.norm(raw_vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized_matrix = raw_vectors / norms

    # Compute cosine similarity matrix S = X X^T: shape (N, N)
    sim_matrix = np.dot(normalized_matrix, normalized_matrix.T)

    # Mask diagonal (self-similarity)
    np.fill_diagonal(sim_matrix, -1.0)

    pairs: List[Dict[str, Any]] = []

    for i in range(n):
        row = sim_matrix[i]
        # Find indices above threshold
        candidate_indices = np.where(row >= threshold)[0]
        if len(candidate_indices) == 0:
            continue

        # Sort candidate indices by score descending
        candidate_scores = row[candidate_indices]
        sorted_order = np.argsort(-candidate_scores)
        top_indices = candidate_indices[sorted_order][:top_k]

        src_id = syllabus_ids[i]
        for j in top_indices:
            tgt_id = syllabus_ids[j]
            score = float(row[j])
            pairs.append({
                "source_id": src_id,
                "target_id": tgt_id,
                "score": round(score, 4),
                "model": model_name,
            })

    return pairs


class SimilarityEdgeLoader:
    """Loads [:SIMILAR_TO] edges into Neo4j."""

    def __init__(self, driver: Optional[Driver] = None):
        self.driver = driver or get_driver()
        self._owned_driver = driver is None

    def close(self):
        if self._owned_driver and self.driver:
            self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def clear_similarity_edges(self):
        """Remove all existing [:SIMILAR_TO] edges."""
        logger.info("Clearing existing [:SIMILAR_TO] edges...")
        with self.driver.session() as session:
            res = session.run("MATCH ()-[r:SIMILAR_TO]->() DELETE r RETURN count(r) AS cnt;")
            cnt = res.single()["cnt"]
            logger.info("Deleted %d existing [:SIMILAR_TO] edges", cnt)

    def load_similarity_edges(
        self,
        pairs: List[Dict[str, Any]],
        batch_size: int = 1000,
    ) -> int:
        """Batch insert [:SIMILAR_TO] edges using UNWIND."""
        total = len(pairs)
        logger.info("Loading %d [:SIMILAR_TO] edges into Neo4j (batch_size=%d)...", total, batch_size)

        inserted_count = 0
        with self.driver.session() as session:
            for i in range(0, total, batch_size):
                batch = pairs[i : i + batch_size]
                query = """
                UNWIND $batch AS rel
                MATCH (src:Course {syllabus_id: rel.source_id})
                MATCH (tgt:Course {syllabus_id: rel.target_id})
                MERGE (src)-[r:SIMILAR_TO]->(tgt)
                SET r.score = rel.score,
                    r.model = rel.model,
                    r.updated_at = datetime()
                RETURN count(r) AS cnt;
                """
                res = session.run(query, {"batch": batch})
                cnt = res.single()["cnt"]
                inserted_count += cnt
                logger.info("Merged %d / %d similarity edges", min(i + batch_size, total), total)

        logger.info("Successfully merged %d [:SIMILAR_TO] edges into Neo4j", inserted_count)
        return inserted_count


def run_similarity_edge_pipeline(
    embeddings_path: Path = DEFAULT_EMBEDDINGS_JSON,
    threshold: float = 0.70,
    top_k: int = 5,
    clear_first: bool = False,
    batch_size: int = 1000,
) -> Dict[str, Any]:
    """Execute end-to-end similarity computation and Neo4j edge loading."""
    if not embeddings_path.exists():
        raise FileNotFoundError(f"Embeddings JSON not found at {embeddings_path}")

    with open(embeddings_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    courses = data.get("courses", {})
    model_name = data.get("model", "text-embedding-004")

    logger.info("Computing similarity pairs for %d courses (threshold=%.2f, top_k=%d)...", len(courses), threshold, top_k)
    pairs = compute_similarity_pairs(
        courses_dict=courses,
        threshold=threshold,
        top_k=top_k,
        model_name=model_name,
    )
    logger.info("Computed %d candidate similarity pairs", len(pairs))

    with SimilarityEdgeLoader() as loader:
        if clear_first:
            loader.clear_similarity_edges()
        loaded_count = loader.load_similarity_edges(pairs=pairs, batch_size=batch_size)

    return {
        "total_courses": len(courses),
        "threshold": threshold,
        "top_k": top_k,
        "candidate_pairs": len(pairs),
        "loaded_edges": loaded_count,
    }


def main():
    parser = argparse.ArgumentParser(description="Compute course similarities and load [:SIMILAR_TO] edges into Neo4j")
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS_JSON, help="Path to course_embeddings.json")
    parser.add_argument("--threshold", type=float, default=0.70, help="Minimum cosine similarity score (0.0 - 1.0)")
    parser.add_argument("--top-k", type=int, default=5, help="Maximum similar outgoing edges per course")
    parser.add_argument("--clear-first", action="store_true", help="Clear existing [:SIMILAR_TO] edges before loading")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for Neo4j UNWIND loading")
    args = parser.parse_args()

    run_similarity_edge_pipeline(
        embeddings_path=args.embeddings,
        threshold=args.threshold,
        top_k=args.top_k,
        clear_first=args.clear_first,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
