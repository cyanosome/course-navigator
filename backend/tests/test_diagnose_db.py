"""診断の API を実 DB（関西のデータを入れたローカルの PostgreSQL と Neo4j）で確かめる。

CI では `-m "not db"` で除く。接続先は backend と同じ環境変数。アプリの lifespan（シードの自動投入）は通らず、
接続だけを作る小さな lifespan で動かす（読み取りだけ）。件数は 2026-11-05 に入れたデータの値（test_catalog_db と同じ）。
"""

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

asyncpg = pytest.importorskip("asyncpg")
from neo4j import AsyncGraphDatabase  # noqa: E402

from api.routers import diagnose as diagnose_router  # noqa: E402
from course_core import config  # noqa: E402
from course_core.catalog.registry import load_departments  # noqa: E402
from course_core.diagnose.config import load_config, validate_config  # noqa: E402
from course_core.diagnose.source import load_catalog  # noqa: E402

pytestmark = pytest.mark.db

_DEPT = "kansai-enechem-2026"
_COURSE_COUNT = 1029
_GROUP_COUNT = 18
_DEFAULT_EDGE_COUNT = 22
_MEMBER_RANGE = range(65, 68)
_OWN_DEPARTMENT_COUNT = 104


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
def app() -> FastAPI:
    app = FastAPI(lifespan=_connections_only)
    app.include_router(diagnose_router.router)
    return app


@pytest.fixture(scope="module")
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def catalog(app, client):
    async def read():
        async with app.state.db_pool.acquire() as conn, app.state.neo4j_driver.session() as session:
            return await load_catalog(conn, session, load_departments()[_DEPT])

    return client.portal.call(read)


def _first_answers(raw_config):
    """どの質問にも最初の選択肢（scale5 は 1）で答える。"""
    return {
        question["id"]: 1 if question["kind"] == "scale5" else [question["options"][0]["id"]]
        for question in raw_config["questions"]
    }


def test_catalog_counts(catalog):
    assert len(catalog.courses) == _COURSE_COUNT
    assert len(catalog.groups) == _GROUP_COUNT
    assert len(catalog.edges) == _DEFAULT_EDGE_COUNT
    assert sum(course.group_id is not None for course in catalog.courses) in _MEMBER_RANGE
    # 系統図の線をたどると、1年のまとまりから特別研究に届く
    assert "G_Research1" in catalog.reach["G_1Y_ChemEng"]
    # 対象学部が「環」だけの科目（共通の資料 comp-diag/factsheet.md の数え方）
    assert sum(course.own_department for course in catalog.courses) == _OWN_DEPARTMENT_COUNT
    # 理由の文で使う呼び名は、表記の崩れ（【】の外の補足）を直したもの
    assert catalog.groups["G_Common"].name == "共通教養科目"
    assert catalog.groups["G_Research1"].name == "特別研究Ⅰ"
    assert all("】" not in group.name and "【" not in group.name for group in catalog.groups.values())


def test_shipped_config_matches_the_curriculum(catalog):
    loaded = load_config(_DEPT)
    assert validate_config(loaded.raw, department_id=_DEPT, known_groups=catalog.group_ids) == []


def test_plan_on_real_data_is_valid_and_deterministic(client):
    config_body = client.get("/diagnose/config", params={"department_id": _DEPT}).json()
    body = {"department_id": _DEPT, "config_version": config_body["version"], "answers": _first_answers(config_body["config"])}
    first = client.post("/diagnose/plan", json=body)
    second = client.post("/diagnose/plan", json=body)
    assert first.status_code == 200, first.text
    assert first.json() == second.json()

    cap = config_body["config"]["scope"]["credit_cap_per_term"]
    seen: set[str] = set()
    for term in first.json()["terms"]:
        slots = [slot for course in term["courses"] for slot in course["slots"]]
        assert len(slots) == len(set(slots)), term  # 同じ曜限に2つ入れない
        if cap is not None:
            assert term["credits_total"] <= cap
        ids = [course["syllabus_id"] for course in term["courses"]]
        assert not seen.intersection(ids)
        seen.update(ids)
