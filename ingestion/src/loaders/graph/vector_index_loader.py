"""
Neo4j Course Embedding Loader and Vector Index Creator.

Loads course embeddings into (:Course) nodes and builds Neo4j 5.x native Vector Index
`course_embedding_index` for semantic similarity search.
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from neo4j import GraphDatabase, Driver

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
INDEX_NAME = "course_embedding_index"


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


class Neo4jVectorIndexLoader:
    """Loads embeddings to Course nodes and manages Neo4j Vector Index."""

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

    def load_embeddings_to_nodes(
        self,
        embeddings_path: Path = DEFAULT_EMBEDDINGS_JSON,
        batch_size: int = 500,
    ) -> Dict[str, Any]:
        """Load embeddings from JSON and set c.embedding on (:Course) nodes."""
        if not embeddings_path.exists():
            raise FileNotFoundError(f"Embeddings JSON not found at {embeddings_path}")

        with open(embeddings_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        dimension = data.get("dimension", 768)
        courses_dict = data.get("courses", {})
        items = list(courses_dict.values())
        total = len(items)

        logger.info("Setting c.embedding for %d Course nodes (batch_size=%d)...", total, batch_size)

        updated_count = 0
        with self.driver.session() as session:
            for i in range(0, total, batch_size):
                batch = items[i : i + batch_size]
                # Prepare batch payload
                payload = [
                    {
                        "syllabus_id": str(item["syllabus_id"]),
                        "embedding": item["embedding"],
                    }
                    for item in batch
                ]
                result = session.run(
                    """
                    UNWIND $batch AS item
                    MATCH (c:Course {syllabus_id: item.syllabus_id})
                    SET c.embedding = item.embedding
                    RETURN count(c) AS cnt;
                    """,
                    {"batch": payload},
                )
                cnt = result.single()["cnt"]
                updated_count += cnt
                logger.info("Updated %d / %d Course embeddings", min(i + batch_size, total), total)

        logger.info("Finished setting embeddings on %d Course nodes in Neo4j", updated_count)
        return {
            "dimension": dimension,
            "total_courses": total,
            "updated_nodes": updated_count,
        }

    def create_vector_index(
        self,
        index_name: str = INDEX_NAME,
        dimension: int = 768,
        similarity_function: str = "cosine",
    ) -> Dict[str, Any]:
        """Create native Neo4j 5.x Vector Index and wait until ONLINE."""
        logger.info("Creating Neo4j Vector Index '%s' (dim=%d, sim=%s)...", index_name, dimension, similarity_function)
        
        with self.driver.session() as session:
            # Cypher for creating vector index (Neo4j 5.x indexConfig syntax)
            create_query = f"""
            CREATE VECTOR INDEX {index_name} IF NOT EXISTS
            FOR (c:Course) ON (c.embedding)
            OPTIONS {{
              indexConfig: {{
                `vector.dimensions`: {dimension},
                `vector.similarity_function`: '{similarity_function}'
              }}
            }};
            """
            session.run(create_query)

            # Wait for index to become ONLINE
            logger.info("Waiting for vector index '%s' to become ONLINE...", index_name)
            is_online = False
            for _ in range(30):
                res = session.run("SHOW VECTOR INDEXES YIELD name, state, populationPercent;")
                records = list(res)
                for r in records:
                    if r["name"] == index_name:
                        logger.info("Index '%s' state: %s (population: %s%%)", index_name, r["state"], r.get("populationPercent", "N/A"))
                        if r["state"] == "ONLINE":
                            is_online = True
                            break
                if is_online:
                    break
                time.sleep(1.0)

            if not is_online:
                logger.warning("Vector index '%s' is not yet ONLINE, but created.", index_name)

        return {"index_name": index_name, "dimension": dimension, "online": is_online}

    def verify_query(
        self,
        sample_vector: List[float],
        top_k: int = 3,
        index_name: str = INDEX_NAME,
    ) -> List[Dict[str, Any]]:
        """Verify dynamic vector querying using CALL db.index.vector.queryNodes."""
        with self.driver.session() as session:
            query = f"""
            CALL db.index.vector.queryNodes('{index_name}', {top_k}, $vec)
            YIELD node, score
            RETURN node.syllabus_id AS syllabus_id, node.name AS name, score
            ORDER BY score DESC;
            """
            result = session.run(query, {"vec": sample_vector})
            matches = [
                {"syllabus_id": r["syllabus_id"], "name": r["name"], "score": round(float(r["score"]), 4)}
                for r in result
            ]
            return matches


def run_vector_index_loader(
    embeddings_path: Path = DEFAULT_EMBEDDINGS_JSON,
    index_name: str = INDEX_NAME,
) -> Dict[str, Any]:
    """Execute complete embedding loading and index creation."""
    with Neo4jVectorIndexLoader() as loader:
        load_res = loader.load_embeddings_to_nodes(embeddings_path=embeddings_path)
        dimension = load_res["dimension"]
        idx_res = loader.create_vector_index(index_name=index_name, dimension=dimension)
        
        # Test query with first course's vector
        with open(embeddings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        first_course = next(iter(data["courses"].values()))
        sample_vec = first_course["embedding"]
        test_matches = loader.verify_query(sample_vector=sample_vec, top_k=3, index_name=index_name)
        logger.info("Test vector query top matches for '%s':", first_course.get("subject_name"))
        for m in test_matches:
            logger.info("  -> [%s] %s (score: %.4f)", m["syllabus_id"], m["name"], m["score"])

        return {
            "load_summary": load_res,
            "index_summary": idx_res,
            "test_matches": test_matches,
        }


def main():
    parser = argparse.ArgumentParser(description="Load course embeddings and create Neo4j Vector Index")
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS_JSON, help="Path to course_embeddings.json")
    parser.add_argument("--index-name", type=str, default=INDEX_NAME, help="Neo4j Vector Index name")
    args = parser.parse_args()

    run_vector_index_loader(embeddings_path=args.embeddings, index_name=args.index_name)


if __name__ == "__main__":
    main()
