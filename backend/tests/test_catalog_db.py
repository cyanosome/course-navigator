"""データの API（D1〜D6）を実 DB（関西のデータを入れたローカルの PostgreSQL と Neo4j）で確かめる。

CI では `-m "not db"` で除く。接続先は backend と同じ環境変数（DB_HOST・DB_PASSWORD・NEO4J_URI・NEO4J_PASSWORD など）。
アプリの lifespan（シードの自動投入）は通らず、接続だけを作る小さな lifespan で動かす。
件数は 2026-11-05 の設計（impl-plan.md B1 の完了の判定）の値。データを入れ直したら見直す。
"""

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

asyncpg = pytest.importorskip("asyncpg")
from neo4j import AsyncGraphDatabase  # noqa: E402

from api.routers import catalog as catalog_router  # noqa: E402
from course_core import config  # noqa: E402

pytestmark = pytest.mark.db

_DEPT = "kansai-enechem-2026"
_COURSE_COUNT = 1029
_GROUP_COUNT = 18
_DEFAULT_EDGE_COUNT = 22
_MEMBER_RANGE = range(65, 68)  # 65〜67（系統図の名前を syllabus_id に解決できた数。設計 C 3.4）
_TOTAL_CREDITS = 128.0


@asynccontextmanager
async def _connections_only(app: FastAPI):
    config.validate_required_env()
    pool = await asyncpg.create_pool(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
    )
    driver = AsyncGraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    app.state.db_pool = pool
    app.state.neo4j_driver = driver
    try:
        yield
    finally:
        await pool.close()
        await driver.close()


@pytest.fixture(scope="module")
def client():
    app = FastAPI(lifespan=_connections_only)
    app.include_router(catalog_router.router)
    with TestClient(app) as test_client:
        yield test_client


def test_departments_counts(client):
    body = client.get("/departments").json()
    assert [d["id"] for d in body] == [_DEPT]
    assert body[0]["course_count"] == _COURSE_COUNT
    assert body[0]["group_count"] == _GROUP_COUNT


def test_department_data_status(client):
    status = client.get(f"/departments/{_DEPT}").json()["data_status"]
    # 実験の DB には SIMILAR_TO を入れない（ab-variants.md C8）
    assert status["similar_to_edges"] == 0, status["similar_models"]
    assert status["group_edges"] == _DEFAULT_EDGE_COUNT


def test_department_graph_counts(client):
    body = client.get(f"/departments/{_DEPT}/graph").json()
    assert len(body["groups"]) == _GROUP_COUNT
    assert len(body["edges"]) == _DEFAULT_EDGE_COUNT
    assert len(body["members"]) in _MEMBER_RANGE
    assert all(m["group_id"] for m in body["members"])
    prereq_only = client.get(f"/departments/{_DEPT}/graph", params={"edge_types": "prerequisite"}).json()
    assert {e["edge_type"] for e in prereq_only["edges"]} <= {"prerequisite"}


def test_course_search_and_detail(client):
    graph = client.get(f"/departments/{_DEPT}/graph").json()
    member = graph["members"][0]
    page = client.get("/courses", params={"q": member["name"], "limit": 100}).json()
    assert member["syllabus_id"] in [item["syllabus_id"] for item in page["items"]]

    detail = client.get(f"/courses/{member['syllabus_id']}")
    assert detail.status_code == 200
    assert detail.json()["group_id"] == member["group_id"]
    assert client.get("/courses/000000000").status_code == 404

    everything = client.get("/courses", params={"limit": 100, "offset": 0}).json()
    assert everything["total"] == _COURSE_COUNT


def test_requirements_both_paths(client):
    """卒業要件を入れる前は pending、入れた後は available で総単位 128。"""
    body = client.get(f"/departments/{_DEPT}/requirements").json()
    if body["status"] == "pending":
        assert body["reason"] in ("表が無い", "この学科の行が無い")
        assert body["requirements"] is None
        return
    assert body["requirements"]["total_credits"] == _TOTAL_CREDITS
    assert body["kinds"]["status"] == "available"
    assert sum(body["kinds_count"].values()) > 0
