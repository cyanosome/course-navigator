"""データの API（D1〜D6）のエンドポイントのテスト。実 DB を使わず CI で回る。

- ルーターだけを載せた FastAPI と TestClient（lifespan＝DB の接続を通らない）。
- DB の代役: app.state に偽のプールと偽の Neo4j ドライバを置き、リポジトリの関数を偽物に差し替える
  （SQL・Cypher の文字列は検査しない。返した行の写像と応答の形を検査する）。
- リポジトリの関数そのものは、記録する偽の接続で「$n の数と引数の数が合う」ことだけを確かめる。
データはすべて架空。
"""

import asyncio
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from catalog_rows import course_row, graduation_row
from api.routers import catalog as catalog_router
from course_core.repositories import neo4j_curriculum_repo, postgres_courses_repo, postgres_requirements_repo
from course_core.repositories.neo4j_curriculum_repo import GroupRecord, SimilarEdgeStats
from course_core.repositories.postgres_requirements_repo import RequirementsTables

_DEPT = "kansai-enechem-2026"


@dataclass
class FakeDb:
    """偽のリポジトリが返す値と、受け取った引数の記録。"""

    courses: list[dict[str, Any]] = field(default_factory=list)
    kinds: dict[str, str] = field(default_factory=dict)  # syllabus_id → requirement_type
    tables: RequirementsTables = field(default_factory=lambda: RequirementsTables(graduation=True, course=True))
    graduation: dict[str, Any] | None = None
    groups: list[GroupRecord] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    similar: SimilarEdgeStats = field(default_factory=lambda: SimilarEdgeStats(count=0, models=()))
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def _with_kind(self, row: dict[str, Any], join_code: str | None) -> dict[str, Any]:
        kind = self.kinds.get(row["syllabus_id"]) if join_code else None
        return {**row, "kind": kind}

    # --- PostgreSQL ---
    async def count_courses(self, conn, academic_year):
        self.calls.append(("count_courses", {"academic_year": academic_year}))
        return len(self.courses)

    async def fetch_courses_by_ids(self, conn, syllabus_ids, *, kinds_department_code=None):
        self.calls.append(("fetch_courses_by_ids", {"ids": list(syllabus_ids), "join": kinds_department_code}))
        wanted = set(syllabus_ids)
        rows = [r for r in self.courses if r["syllabus_id"] in wanted]
        return [self._with_kind(r, kinds_department_code) for r in sorted(rows, key=lambda r: r["syllabus_id"])]

    async def search_courses(self, conn, *, academic_year, patterns, kinds_department_code):
        self.calls.append(("search_courses", {"patterns": list(patterns), "join": kinds_department_code}))
        return [self._with_kind(r, kinds_department_code) for r in self.courses]

    async def fetch_course_detail(self, conn, syllabus_id, *, kinds_department_code):
        self.calls.append(("fetch_course_detail", {"id": syllabus_id, "join": kinds_department_code}))
        row = next((r for r in self.courses if r["syllabus_id"] == syllabus_id), None)
        return None if row is None else self._with_kind(row, kinds_department_code)

    async def requirements_tables_exist(self, conn):
        return self.tables

    async def fetch_graduation_requirements(self, conn, academic_year, faculty_code, department_code):
        self.calls.append(("fetch_graduation_requirements", {"key": (academic_year, faculty_code, department_code)}))
        return self.graduation

    async def count_course_kinds(self, conn, department_code):
        self.calls.append(("count_course_kinds", {"department_code": department_code}))
        counts: dict[str, int] = {}
        for kind in self.kinds.values():
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    # --- Neo4j ---
    async def fetch_groups(self, session, faculty, department):
        self.calls.append(("fetch_groups", {"faculty": faculty, "department": department}))
        return self.groups

    async def fetch_group_edges(self, session, faculty, department, edge_types):
        self.calls.append(("fetch_group_edges", {"edge_types": list(edge_types)}))
        return [e for e in self.edges if e["edge_type"] in edge_types]

    async def count_group_edges(self, session, faculty, department):
        return len(self.edges)

    async def count_similar_edges(self, session):
        return self.similar

    async def fetch_course_group(self, session, syllabus_id, faculty, department):
        return [g.group_id for g in self.groups if syllabus_id in g.members]

    def called(self, name: str) -> list[dict[str, Any]]:
        return [args for called_name, args in self.calls if called_name == name]


class _FakePool:
    @asynccontextmanager
    async def acquire(self):
        yield object()


class _FakeDriver:
    @asynccontextmanager
    async def session(self):
        yield object()


_REPO_FUNCTIONS = {
    postgres_courses_repo: ("count_courses", "fetch_courses_by_ids", "search_courses", "fetch_course_detail"),
    postgres_requirements_repo: ("requirements_tables_exist", "fetch_graduation_requirements", "count_course_kinds"),
    neo4j_curriculum_repo: (
        "fetch_groups",
        "fetch_group_edges",
        "count_group_edges",
        "count_similar_edges",
        "fetch_course_group",
    ),
}


def _sample_db() -> FakeDb:
    return FakeDb(
        courses=[
            course_row(syllabus_id="900001", subject_name="架空の反応工学１", year_range="２年次", semester="春", term_schedule="火2"),
            course_row(syllabus_id="900002", subject_name="架空の熱力学", year_range="１年次", semester="秋", term_schedule="月1"),
            course_row(syllabus_id="900003", subject_name="架空の反応工学２", year_range="３年次", semester="秋", term_schedule="集中"),
        ],
        kinds={"900001": "required", "900003": "elective_required"},
        graduation=graduation_row(),
        groups=[
            GroupRecord("G_1Y_X", "【架空基礎系グループ】", 1, None, ("900002",)),
            GroupRecord("G_2Y_X", "【架空反応系グループ】", 2, "春", ("900001", "900099")),  # 900099 は courses に無い
        ],
        edges=[
            {"source": "G_1Y_X", "target": "G_2Y_X", "edge_type": "prerequisite", "is_major": True},
            {"source": "G_2Y_X", "target": "G_1Y_X", "edge_type": "english_track", "is_major": False},
        ],
    )


@pytest.fixture
def db(monkeypatch) -> FakeDb:
    fake = _sample_db()
    for module, names in _REPO_FUNCTIONS.items():
        for name in names:
            monkeypatch.setattr(module, name, getattr(fake, name))
    return fake


@pytest.fixture
def client(db) -> TestClient:
    app = FastAPI()
    app.include_router(catalog_router.router)
    app.state.db_pool = _FakePool()
    app.state.neo4j_driver = _FakeDriver()
    return TestClient(app, raise_server_exceptions=False)


# --- D1・D2 ------------------------------------------------------------------------------


def test_list_departments(client):
    response = client.get("/departments")
    assert response.status_code == 200
    assert response.headers["X-Navi-Contract"] == "navi-v1"
    assert response.json() == [
        {
            "id": _DEPT,
            "university": "関西大学",
            "faculty": "環境都市工学部",
            "name": "エネルギー環境・化学工学科",
            "syllabus_year": 2026,
            "data_version": "unset",
            "course_count": 3,
            "group_count": 2,
        }
    ]


def test_department_overview_with_data(client, db):
    db.similar = SimilarEdgeStats(count=5, models=("deterministic-mock-768",))
    body = client.get(f"/departments/{_DEPT}").json()
    assert body["course_count"] == 3
    assert body["data_status"] == {
        "requirements": {"status": "available", "reason": None},
        "kinds": {"status": "available", "reason": None},
        "classified_courses": 2,
        "similar_to_edges": 5,
        "similar_models": ["deterministic-mock-768"],
        "group_edges": 2,
    }
    assert db.called("fetch_graduation_requirements") == [{"key": (2026, "320", "031")}]
    assert db.called("count_course_kinds") == [{"department_code": "031"}]


def test_department_overview_without_requirement_tables(client, db):
    db.tables = RequirementsTables(graduation=False, course=False)
    status = client.get(f"/departments/{_DEPT}").json()["data_status"]
    assert status["requirements"] == {"status": "pending", "reason": "表が無い"}
    assert status["kinds"] == {"status": "pending", "reason": "表が無い"}
    assert status["classified_courses"] == 0
    assert db.called("fetch_graduation_requirements") == []


def test_unknown_department_is_404(client):
    for path in ("/departments/nope", "/departments/nope/graph", "/departments/nope/requirements"):
        response = client.get(path)
        assert response.status_code == 404, path
        assert "nope" in response.json()["detail"]


# --- D3 ----------------------------------------------------------------------------------


def test_department_graph(client, db):
    response = client.get(f"/departments/{_DEPT}/graph")
    assert response.status_code == 200
    body = response.json()
    assert body["department_id"] == _DEPT
    assert body["edge_types"] == ["prerequisite", "capstone", "english_track"]
    assert body["groups"][1] == {
        "group_id": "G_2Y_X",
        "label": "【架空反応系グループ】",
        "name": "架空反応系",
        "plain": None,
        "common": False,
        "academic_year": 2,
        "semester": "春",
        "member_count": 2,
    }
    assert body["edges"] == [
        {"source": "G_1Y_X", "target": "G_2Y_X", "edge_type": "prerequisite", "is_major": True},
        {"source": "G_2Y_X", "target": "G_1Y_X", "edge_type": "english_track", "is_major": False},
    ]
    assert body["interests"] == []
    # 系統図の順（学年 → group_id）に、courses で解決できた科目だけ
    assert [(m["syllabus_id"], m["group_id"], m["kind"]) for m in body["members"]] == [
        ("900002", "G_1Y_X", None),
        ("900001", "G_2Y_X", "required"),
    ]
    assert db.called("fetch_courses_by_ids") == [{"ids": ["900002", "900001", "900099"], "join": "031"}]


def test_department_graph_edge_types(client, db):
    body = client.get(f"/departments/{_DEPT}/graph", params={"edge_types": "prerequisite"}).json()
    assert body["edge_types"] == ["prerequisite"]
    assert [e["edge_type"] for e in body["edges"]] == ["prerequisite"]
    assert db.called("fetch_group_edges") == [{"edge_types": ["prerequisite"]}]


@pytest.mark.parametrize("edge_types", ["", "prerequisite,similar", "DP"])
def test_department_graph_rejects_unknown_edge_types(client, edge_types):
    assert client.get(f"/departments/{_DEPT}/graph", params={"edge_types": edge_types}).status_code == 422


# --- D4 ----------------------------------------------------------------------------------


def test_search_courses_query_and_order(client, db):
    response = client.get("/courses", params={"q": "反応　工学"})
    assert response.status_code == 200
    body = response.json()
    assert db.called("search_courses") == [{"patterns": ["%反応%", "%工学%"], "join": "031"}]
    # 偽のリポジトリは語で絞らないので、科目名に全部の語を含む 900001・900003 が先、900002 が後
    assert [item["syllabus_id"] for item in body["items"]] == ["900001", "900003", "900002"]
    assert body["total"] == 3
    assert body["kinds_status"] == "available"
    assert body["items"][0]["group_id"] == "G_2Y_X"
    assert body["items"][1]["group_id"] is None


def test_search_courses_filters_and_pages(client):
    def ids(**params):
        body = client.get("/courses", params=params).json()
        return body["total"], [item["syllabus_id"] for item in body["items"]]

    assert ids(year=2) == (1, ["900001"])
    assert ids(term="秋") == (2, ["900002", "900003"])
    assert ids(slot=["月1", "火2"]) == (2, ["900001", "900002"])
    assert ids(group="G_1Y_X") == (1, ["900002"])
    assert ids(kind=["required", "elective_required"]) == (2, ["900001", "900003"])
    assert ids(limit=1, offset=1) == (3, ["900002"])
    assert ids(limit=2, offset=5) == (3, [])


def test_search_courses_without_kind_table(client, db):
    db.tables = RequirementsTables(graduation=False, course=False)
    body = client.get("/courses").json()
    assert body["kinds_status"] == "pending"
    assert {item["kind"] for item in body["items"]} == {None}
    assert db.called("search_courses") == [{"patterns": [], "join": None}]


@pytest.mark.parametrize(
    "params",
    [
        {"q": "a b c d e f"},
        {"q": "あ" * 101},
        {"year": 5},
        {"term": "夏"},
        {"slot": "月"},
        {"kind": "optional"},
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"dept": "nope"},
    ],
)
def test_search_courses_rejects_bad_params(client, params):
    assert client.get("/courses", params=params).status_code in (404, 422)


# --- D5 ----------------------------------------------------------------------------------


def test_get_course_detail(client, db):
    db.courses[0].update(
        cr_subject_name_bulletin="架空の反応工学Ⅰ",
        cr_credits=Decimal("2.0"),
        cr_assigned_year=2,
        cr_bulletin_code="CEE9",
        cr_field_category=None,
    )
    response = client.get("/courses/900001")
    assert response.status_code == 200
    assert response.headers["X-Navi-Contract"] == "navi-v1"
    body = response.json()
    assert body["syllabus_id"] == "900001"
    assert body["group_id"] == "G_2Y_X"
    assert body["kind"] == "required"
    assert body["bulletin"]["requirement_type"] == "required"
    assert body["schedule"] == [{"number": 1, "topic": "導入"}]
    assert body["source"] == "postgres:courses"
    assert db.called("fetch_course_detail") == [{"id": "900001", "join": "031"}]


def test_get_course_without_kind_table_and_group(client, db):
    db.tables = RequirementsTables(graduation=False, course=False)
    body = client.get("/courses/900003").json()
    assert body["group_id"] is None
    assert body["kind"] is None
    assert body["bulletin"] is None
    assert db.called("fetch_course_detail") == [{"id": "900003", "join": None}]


@pytest.mark.parametrize("syllabus_id", ["999999", "bad id", "x" * 21, "a%2Fb"])
def test_get_course_not_found(client, db, syllabus_id):
    assert client.get(f"/courses/{syllabus_id}").status_code == 404


def test_get_course_with_broken_jsonb_is_500(client, db):
    db.courses[0]["instructors"] = "not json"
    assert client.get("/courses/900001").status_code == 500


# --- D6 ----------------------------------------------------------------------------------


def test_requirements_available(client):
    response = client.get(f"/departments/{_DEPT}/requirements")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["reason"] is None
    assert body["requirements"]["total_credits"] == 124.0
    assert body["requirements"]["term_cap"] is None
    assert body["kinds"] == {"status": "available", "reason": None}
    assert body["kinds_count"] == {"required": 1, "elective_required": 1, "elective": 0}
    assert body["source"] == "postgres:graduation_requirements,course_requirements"


def test_requirements_pending_without_tables(client, db):
    db.tables = RequirementsTables(graduation=False, course=False)
    body = client.get(f"/departments/{_DEPT}/requirements").json()
    assert body["status"] == "pending"
    assert body["reason"] == "表が無い"
    assert body["requirements"] is None
    assert body["kinds"] == {"status": "pending", "reason": "表が無い"}
    assert body["kinds_count"] == {"required": 0, "elective_required": 0, "elective": 0}


def test_requirements_pending_without_department_rows(client, db):
    db.graduation = None
    db.kinds = {}
    body = client.get(f"/departments/{_DEPT}/requirements").json()
    assert (body["status"], body["reason"]) == ("pending", "この学科の行が無い")
    assert body["kinds"] == {"status": "pending", "reason": "この学科の行が無い"}


# --- リポジトリの関数（$n と引数の数） ------------------------------------------------------


class _RecordingConn:
    """受けた SQL の $n の最大と引数の数が合うかを確かめ、決まった値を返す。"""

    def __init__(self, result: Any = None) -> None:
        self.result = result
        self.queries: list[tuple[str, tuple[Any, ...]]] = []

    def _check(self, sql: str, args: tuple[Any, ...]) -> None:
        numbers = {int(n) for n in re.findall(r"\$(\d+)", sql)}
        assert numbers == set(range(1, len(args) + 1)), (sql, args)
        self.queries.append((sql, args))

    async def fetch(self, sql, *args):
        self._check(sql, args)
        return self.result if self.result is not None else []

    async def fetchrow(self, sql, *args):
        self._check(sql, args)
        return self.result

    async def fetchval(self, sql, *args):
        self._check(sql, args)
        return self.result


def test_courses_repo_parameters():
    conn = _RecordingConn()
    asyncio.run(postgres_courses_repo.fetch_courses_by_ids(conn, ["1", "2"]))
    asyncio.run(postgres_courses_repo.fetch_courses_by_ids(conn, ["1"], kinds_department_code="031"))
    asyncio.run(
        postgres_courses_repo.search_courses(
            conn, academic_year=2026, patterns=["%a%", "%b%"], kinds_department_code="031"
        )
    )
    asyncio.run(postgres_courses_repo.search_courses(conn, academic_year=2026, patterns=[], kinds_department_code=None))
    asyncio.run(postgres_courses_repo.fetch_course_detail(conn, "1", kinds_department_code="031"))
    asyncio.run(postgres_courses_repo.fetch_course_detail(conn, "1", kinds_department_code=None))
    asyncio.run(postgres_courses_repo.count_courses(conn, 2026))
    assert len(conn.queries) == 7
    # JOIN しないときは course_requirements に触れない（表が無い DB でも動く）
    without_join = [sql for sql, args in conn.queries if "031" not in args]
    assert without_join and all("course_requirements" not in sql for sql in without_join)


def test_courses_repo_skips_empty_ids():
    conn = _RecordingConn()
    assert asyncio.run(postgres_courses_repo.fetch_courses_by_ids(conn, [])) == []
    assert conn.queries == []


def test_requirements_repo_refuses_duplicate_rows():
    conn = _RecordingConn(result=[{"requirement_id": "a"}, {"requirement_id": "b"}])
    with pytest.raises(ValueError, match="a, b"):
        asyncio.run(postgres_requirements_repo.fetch_graduation_requirements(conn, 2026, "320", "031"))
