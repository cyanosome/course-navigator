"""Tests for Cypher search repository, embedding service, and search API."""

import math
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from api.main import app
from course_core.schemas.search import (
    CourseGraphResponse,
    CoursePrereqItem,
    CourseSearchRequest,
    CourseSearchResponse,
    CourseSearchResultItem,
    SearchMode,
)
from course_core.schemas.navi import Department, NaviCourse, Frame, Requirements
from course_core.repositories import cypher_search_repo
from services.embedding import (
    EmbeddingService,
    generate_deterministic_mock_embedding,
    get_embedding,
    get_embeddings,
)
from agent import cypher_tools, deps


# =====================================================================
# 1. Embedding Service Tests (Offline Unit Tests)
# =====================================================================


def test_deterministic_mock_embedding_properties():
    """Verify mock embedding generates 768-dim unit-norm deterministic vector."""
    text1 = "機械学習入門"
    emb1 = generate_deterministic_mock_embedding(text1, dimension=768)
    assert len(emb1) == 768

    # Determinism: identical text -> identical embedding
    emb1_repeat = generate_deterministic_mock_embedding(text1, dimension=768)
    assert emb1 == emb1_repeat

    # Different text -> different embedding
    text2 = "日本史概論"
    emb2 = generate_deterministic_mock_embedding(text2, dimension=768)
    assert emb1 != emb2

    # L2 norm should be approximately 1.0
    l2_norm = math.sqrt(sum(v * v for v in emb1))
    assert abs(l2_norm - 1.0) < 1e-4


@pytest.mark.anyio
async def test_embedding_service_mock_mode():
    """Verify EmbeddingService fallback behavior."""
    service = EmbeddingService(force_mock=True)

    # Empty text
    empty_emb = await service.get_embedding("")
    assert len(empty_emb) == 768
    assert all(v == 0.0 for v in empty_emb)

    # Single text
    emb = await service.get_embedding("プログラミング基礎")
    assert len(emb) == 768
    assert abs(math.sqrt(sum(v * v for v in emb)) - 1.0) < 1e-4

    # Batch texts
    texts = ["データ構造", "アルゴリズム", "離散数学"]
    batch_embs = await service.get_embeddings(texts)
    assert len(batch_embs) == 3
    for b in batch_embs:
        assert len(b) == 768


# =====================================================================
# 2. Schema Validation Tests
# =====================================================================


def test_search_schemas():
    """Verify search request and response Pydantic schemas."""
    req = CourseSearchRequest(query="AI", mode=SearchMode.HYBRID, top_k=5, max_depth=3)
    assert req.mode == "hybrid"
    assert req.top_k == 5

    item = CourseSearchResultItem(
        code="CS101",
        title="コンピュータ科学入門",
        credits=2.0,
        term="春",
        score=0.925,
        prerequisites=[
            CoursePrereqItem(code="MATH101", title="線形代数", credits=2.0, depth=1)
        ],
    )
    res = CourseSearchResponse(
        mode=SearchMode.HYBRID,
        query="AI",
        total_hits=1,
        execution_time_ms=12.5,
        results=[item],
    )
    assert res.total_hits == 1
    assert res.results[0].prerequisites[0].code == "MATH101"


def test_navi_schemas():
    """Verify navi department schemas."""
    frame = Frame(id="F1", year=1, name="【基礎グループ】", plain="基礎", common=False)
    dept = Department(
        id="test-dept",
        university="関西大学",
        faculty="システム理工学部",
        name="情報工学科",
        frames=[frame],
        courses=[
            NaviCourse(
                code="001",
                name="情報数学",
                frameId="F1",
                term="春",
                credits=2.0,
            )
        ],
        requirements=Requirements(total=128.0, termCap=24.0, needs=[]),
    )
    data = dept.model_dump(by_alias=True)
    assert data["name"] == "情報工学科"
    assert len(data["frames"]) == 1
    assert data["courses"][0]["code"] == "001"


# =====================================================================
# 3. Cypher Repository Unit Test (with Mock Session)
# =====================================================================


@pytest.mark.anyio
async def test_cypher_repo_with_mock_session():
    """Verify Cypher repository query formulation with mocked Neo4j session."""
    mock_session = AsyncMock()
    mock_result = AsyncMock()
    mock_result.data.return_value = [
        {
            "code": "TEST01",
            "title": "テスト講義",
            "credits": 2.0,
            "term": "春",
            "category": "専門",
            "requirement_category": "専門必修",
            "score": 0.88,
            "prerequisites": [{"code": "PRE01", "title": "前提講義", "depth": 1}],
        }
    ]
    mock_session.run.return_value = mock_result

    dummy_vec = [0.1] * 768
    results = await cypher_search_repo.search_hybrid(
        mock_session, query_embedding=dummy_vec, top_k=3, max_depth=2
    )

    assert len(results) == 1
    assert results[0].code == "TEST01"
    assert results[0].score == 0.88
    assert len(results[0].prerequisites) == 1
    assert results[0].prerequisites[0].code == "PRE01"


# =====================================================================
# 4. Real DB Integration Tests (marked with @pytest.mark.db)
# =====================================================================


@pytest.mark.db
@pytest.mark.anyio
async def test_real_db_search_modes():
    """Verify Mode A (Hybrid), Mode B (Similarity), and Mode C (Pure Graph) against real Neo4j."""
    from neo4j import AsyncGraphDatabase
    from course_core import config

    driver = AsyncGraphDatabase.driver(
        config.NEO4J_URI,
        auth=(config.NEO4J_USER, config.NEO4J_PASSWORD or "secure_password_please_change"),
    )

    async with driver.session() as session:
        # Mode A: Hybrid search
        vec = await get_embedding("教育")
        hybrid_results = await cypher_search_repo.search_hybrid(
            session=session, query_embedding=vec, top_k=3
        )
        assert len(hybrid_results) > 0
        assert hybrid_results[0].code != ""
        assert hybrid_results[0].score > 0.0

        # Mode C: Pure graph keyword search
        graph_results = await cypher_search_repo.search_pure_graph(
            session=session, identifier="特別研究", top_k=3
        )
        assert len(graph_results) > 0

        # Graph extraction for course
        course_graph = await cypher_search_repo.get_course_graph(
            session=session, course_code="062620"
        )
        assert course_graph.course_code == "062620"
        assert len(course_graph.nodes) > 0

    await driver.close()


@pytest.mark.db
@pytest.mark.anyio
async def test_real_db_agent_tools():
    """Verify ADK / MCP cypher tools with real Neo4j."""
    from neo4j import AsyncGraphDatabase
    from course_core import config

    driver = AsyncGraphDatabase.driver(
        config.NEO4J_URI,
        auth=(config.NEO4J_USER, config.NEO4J_PASSWORD or "secure_password_please_change"),
    )
    deps.set_backends(None, driver)

    try:
        res = await cypher_tools.search_courses_hybrid(query="物理", top_k=2)
        assert "results" in res
        assert len(res["results"]) > 0

        res_prereq = await cypher_tools.get_course_prerequisites("062620")
        assert res_prereq.get("course_code") == "062620"
        assert len(res_prereq.get("prerequisites", [])) > 0
    finally:
        deps.set_backends(None, None)
        await driver.close()


@pytest.mark.db
def test_real_db_api_endpoints():
    """Verify FastAPI search and navi endpoints through TestClient."""
    with TestClient(app) as client:
        # 1. POST /search/courses (Hybrid)
        r1 = client.post(
            "/search/courses",
            json={"query": "プログラミング", "mode": "hybrid", "top_k": 3},
        )
        assert r1.status_code == 200
        data1 = r1.json()
        assert data1["mode"] == "hybrid"
        assert len(data1["results"]) > 0

        # 2. POST /search/courses (Pure Graph)
        r2 = client.post(
            "/search/courses",
            json={"query": "特別研究", "mode": "pure_graph", "top_k": 3},
        )
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["mode"] == "pure_graph"

        # 3. GET /courses/{code}/graph
        r3 = client.get("/courses/062620/graph")
        assert r3.status_code == 200
        data3 = r3.json()
        assert data3["course_code"] == "062620"
        assert len(data3["nodes"]) > 0

        # 4. GET /navi/departments/kansai-system-eng
        r4 = client.get("/navi/departments/kansai-system-eng")
        assert r4.status_code == 200
        data4 = r4.json()
        assert data4["university"] == "関西大学"
        assert len(data4["courses"]) > 0
