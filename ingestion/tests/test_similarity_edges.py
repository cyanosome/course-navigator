"""
Unit tests for Neo4j Similarity Edge and Vector Index Loader.
"""

from pathlib import Path
import numpy as np
import pytest

from src.loaders.graph.similarity_edge_loader import (
    compute_similarity_pairs,
    get_driver,
    SimilarityEdgeLoader,
)
from src.loaders.graph.vector_index_loader import Neo4jVectorIndexLoader, INDEX_NAME


def test_compute_similarity_pairs_logic():
    # 3 dummy courses with known vectors
    # Course 1 & 2 are identical (cos_sim = 1.0)
    # Course 3 is orthogonal (cos_sim = 0.0)
    courses = {
        "C1": {"syllabus_id": "C1", "embedding": [1.0, 0.0, 0.0]},
        "C2": {"syllabus_id": "C2", "embedding": [1.0, 0.0, 0.0]},
        "C3": {"syllabus_id": "C3", "embedding": [0.0, 1.0, 0.0]},
    }

    pairs = compute_similarity_pairs(courses, threshold=0.5, top_k=2)
    
    # Self-loops must not exist
    for p in pairs:
        assert p["source_id"] != p["target_id"]

    # C1 should have C2 as similar with score 1.0
    c1_targets = [p for p in pairs if p["source_id"] == "C1"]
    assert len(c1_targets) == 1
    assert c1_targets[0]["target_id"] == "C2"
    assert pytest.approx(c1_targets[0]["score"], rel=1e-3) == 1.0

    # C3 has 0.0 similarity to C1 and C2, so with threshold=0.5 it should have no pairs
    c3_targets = [p for p in pairs if p["source_id"] == "C3"]
    assert len(c3_targets) == 0


def test_neo4j_vector_index_online():
    """Verify Neo4j Vector Index is ONLINE."""
    driver = get_driver()
    with driver.session() as session:
        records = list(session.run("SHOW VECTOR INDEXES YIELD name, state;"))
        index_states = {r["name"]: r["state"] for r in records}
        assert INDEX_NAME in index_states, f"Vector index '{INDEX_NAME}' not found."
        assert index_states[INDEX_NAME] == "ONLINE"
    driver.close()


def test_neo4j_similarity_edges_query():
    """Verify [:SIMILAR_TO] edges exist and can be queried in Neo4j."""
    driver = get_driver()
    with driver.session() as session:
        res = session.run("MATCH ()-[r:SIMILAR_TO]->() RETURN count(r) AS cnt;").single()
        assert res is not None
        assert res["cnt"] > 0, "No [:SIMILAR_TO] edges found in Neo4j."

        # Verify edge properties
        sample = session.run(
            """
            MATCH (src:Course)-[r:SIMILAR_TO]->(tgt:Course)
            RETURN src.syllabus_id AS src_id, tgt.syllabus_id AS tgt_id, r.score AS score
            LIMIT 1;
            """
        ).single()
        assert sample is not None
        assert sample["src_id"] != sample["tgt_id"]
        assert 0.0 <= sample["score"] <= 1.0
    driver.close()
