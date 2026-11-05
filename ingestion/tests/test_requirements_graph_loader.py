"""
Unit tests for Neo4j Requirements and Course Prerequisite Loader.
"""

import pytest
from pathlib import Path
from src.loaders.graph.requirements_loader import get_driver, Neo4jRequirementsLoader


def test_neo4j_requirements_loader():
    """Verify loading requirements and prerequisite edges into Neo4j."""
    driver = get_driver()
    loader = Neo4jRequirementsLoader(driver=driver)

    json_path = Path("data/parsed/university/kansai/2026/bulletin_cee_requirements.json")
    if not json_path.exists():
        pytest.skip("Requirements JSON not found.")

    try:
        res = loader.load_requirements(json_path=json_path)
        assert res["requirement_id"] == "2026_env_cee"
        assert res["categories_created"] == 3
        assert res["classified_edges_created"] > 0
        assert res["prerequisites_created"] == 3

        # Cypher validation
        with driver.session() as s:
            gr = s.run("MATCH (gr:GraduationRequirement {requirement_id: '2026_env_cee'}) RETURN gr.total_credits, gr.major_required_credits;").single()
            assert gr is not None
            assert gr[0] == 128.0
            assert gr[1] == 53.0

            # Prerequisite edge check
            prereq = s.run("MATCH (t:Course {name: '特別研究２'})-[:REQUIRES_PREREQUISITE]->(p:Course {name: '特別研究１'}) RETURN p LIMIT 1;").single()
            assert prereq is not None
    finally:
        loader.close()
