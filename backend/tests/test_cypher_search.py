"""Tests for Cypher search repository, embedding service, and search API."""

import asyncio
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
    GeminiApiUnavailableError,
    get_embedding,
    get_embeddings,
)
from agent import cypher_tools, deps


# =====================================================================
# 1. Embedding Service Tests (Fail-Fast, Strict API)
# =====================================================================


def test_embedding_service_missing_key_raises_error(monkeypatch):
    """Verify EmbeddingService raises GeminiApiUnavailableError when key is missing."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    service = EmbeddingService(api_key="")
    with pytest.raises(GeminiApiUnavailableError, match="GEMINI_API_KEY が未設定です"):
        asyncio.run(service.get_embedding("テスト講義"))


def test_embedding_service_api_failure_raises_error(monkeypatch):
    """Verify EmbeddingService fails fast with explicit error on API failure."""
    import asyncio
    from unittest.mock import MagicMock

    monkeypatch.setenv("GEMINI_API_KEY", "AQ.test_key")
    service = EmbeddingService()

    mock_client = MagicMock()
    mock_client.models.embed_content.side_effect = Exception("API key not valid")
    service._client = mock_client

    with pytest.raises(GeminiApiUnavailableError, match="通信に失敗しました"):
        asyncio.run(service.get_embedding("プログラミング基礎"))


def test_embedding_service_successful_api_with_mocked_http(monkeypatch):
    """Verify EmbeddingService returns dimension vector on successful response."""
    import asyncio
    from unittest.mock import MagicMock

    monkeypatch.setenv("GEMINI_API_KEY", "AQ.test_key")
    service = EmbeddingService(dimension=768)
    dummy_vec = [0.05] * 768

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_emb = MagicMock()
    mock_emb.values = dummy_vec
    mock_resp.embeddings = [mock_emb]
    mock_client.models.embed_content.return_value = mock_resp
    service._client = mock_client

    res = asyncio.run(service.get_embedding("データ構造"))
    assert len(res) == 768
    assert res == dummy_vec


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
async def test_real_db_search_modes(monkeypatch):
    """Verify Mode A (Hybrid), Mode B (Similarity), and Mode C (Pure Graph) against real Neo4j."""
    from neo4j import AsyncGraphDatabase
    from course_core import config

    monkeypatch.setattr(
        "services.embedding.get_embedding",
        AsyncMock(return_value=[0.05] * 768),
    )

    driver = AsyncGraphDatabase.driver(
        config.NEO4J_URI,
        auth=(config.NEO4J_USER, config.NEO4J_PASSWORD or "secure_password_please_change"),
    )

    async with driver.session() as session:
        # Mode A: Hybrid search & Deduplication check
        vec = [0.05] * 768
        hybrid_results = await cypher_search_repo.search_hybrid(
            session=session, query_embedding=vec, top_k=5
        )
        assert len(hybrid_results) > 0
        assert hybrid_results[0].code != ""
        assert hybrid_results[0].score > 0.0
        # Verify deduplication: no duplicate course codes
        hybrid_codes = [r.code for r in hybrid_results if r.code]
        assert len(hybrid_codes) == len(set(hybrid_codes)), f"Duplicates found in hybrid results: {hybrid_codes}"

        # Mode B: Precomputed similarity search
        sim_results = await cypher_search_repo.search_by_similarity_edge(
            session=session, identifier="テニス", top_k=3, min_score=0.5
        )
        assert len(sim_results) > 0
        assert sim_results[0].code != ""
        assert sim_results[0].score >= 0.5
        sim_codes = [r.code for r in sim_results if r.code]
        assert len(sim_codes) == len(set(sim_codes))

        # Mode C: Pure graph keyword search
        graph_results = await cypher_search_repo.search_pure_graph(
            session=session, identifier="特別研究", top_k=5
        )
        assert len(graph_results) > 0
        graph_codes = [r.code for r in graph_results if r.code]
        assert len(graph_codes) == len(set(graph_codes)), f"Duplicates found in pure_graph: {graph_codes}"

        # Graph extraction for course (no self-loops)
        course_graph = await cypher_search_repo.get_course_graph(
            session=session, course_code="062620"
        )
        assert course_graph.course_code == "062620"
        assert len(course_graph.nodes) > 0
        assert not any(e.source == e.target for e in course_graph.edges), "Self-loop edge found in graph response"

    await driver.close()


@pytest.mark.db
@pytest.mark.anyio
async def test_real_db_agent_tools(monkeypatch):
    """Verify ADK / MCP cypher tools with real Neo4j."""
    from neo4j import AsyncGraphDatabase
    from course_core import config

    monkeypatch.setattr(
        "services.embedding.get_embedding",
        AsyncMock(return_value=[0.05] * 768),
    )

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

        res_sim = await cypher_tools.get_similar_courses("102878")
        assert res_sim.get("course_code") == "102878"
        assert "similar_courses" in res_sim
        assert len(res_sim["similar_courses"]) > 0
    finally:
        deps.set_backends(None, None)
        await driver.close()


@pytest.mark.db
def test_real_db_api_endpoints(monkeypatch):
    """Verify FastAPI search and navi endpoints through TestClient (both stripped and /api prefixed)."""
    monkeypatch.setattr(
        "services.embedding.get_embedding",
        AsyncMock(return_value=[0.05] * 768),
    )

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

        # 2. POST /search/courses (Similarity)
        r2_sim = client.post(
            "/search/courses",
            json={"query": "テニス", "mode": "similarity", "top_k": 3},
        )
        assert r2_sim.status_code == 200
        data2_sim = r2_sim.json()
        assert data2_sim["mode"] == "similarity"
        assert len(data2_sim["results"]) > 0

        # 3. POST /search/courses (Pure Graph)
        r2 = client.post(
            "/search/courses",
            json={"query": "特別研究", "mode": "pure_graph", "top_k": 3},
        )
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["mode"] == "pure_graph"

        # 4. GET /courses/{code}/graph
        r3 = client.get("/courses/062620/graph")
        assert r3.status_code == 200
        data3 = r3.json()
        assert data3["course_code"] == "062620"
        assert len(data3["nodes"]) > 0

        # 5. GET /navi/departments/kansai-system-eng
        r4 = client.get("/navi/departments/kansai-system-eng")
        assert r4.status_code == 200
        data4 = r4.json()
        assert data4["university"] == "関西大学"
        assert len(data4["courses"]) > 0
        # Verify elective_required courses have kind == "選択"
        assert any(c["kind"] == "選択" for c in data4["courses"])

        # 6. Direct /api/ prefix verification
        r5 = client.post(
            "/api/search/courses",
            json={"query": "物理", "mode": "hybrid", "top_k": 2},
        )
        assert r5.status_code == 200
        assert r5.json()["total_hits"] > 0

        r6 = client.get("/api/navi/departments/kansai-system-eng")
        assert r6.status_code == 200
        assert len(r6.json()["courses"]) > 0


@pytest.mark.db
def test_search_api_hybrid_fails_with_503_when_gemini_unavailable(monkeypatch):
    """Verify FastAPI hybrid search endpoint returns 503 when Gemini API fails."""
    async def mock_fail(_):
        raise GeminiApiUnavailableError("Gemini Embedding API との通信に失敗しました。")

    monkeypatch.setattr("services.embedding.get_embedding", mock_fail)

    with TestClient(app) as client:
        r = client.post(
            "/search/courses",
            json={"query": "プログラミング", "mode": "hybrid", "top_k": 3},
        )
        assert r.status_code == 503
        data = r.json()
        assert "Gemini Embedding API との通信に失敗しました" in data["detail"]
