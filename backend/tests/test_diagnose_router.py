"""診断の API（GET /diagnose/config・POST /diagnose/plan）のテスト。実 DB を使わず CI で回る。

設定とデータの読み方を依存の差し替え（dependency_overrides）で偽物にする。データはすべて架空。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from diagnose_fixtures import DEPT, answers, catalog, config_dict, course
from api.routers import diagnose as diagnose_router
from course_core.diagnose.config import ConfigError, ConfigNotFoundError, LoadedConfig, parse_config
from course_core.diagnose.model import ConfigIssue

_COURSES = [
    course("10", group_id="G_A", name="架空の反応工学", slots=("月1",)),
    course("11", slots=("火2",)),
    course("12", term="秋", slots=("月1",)),
]


class _Loaders:
    def __init__(self) -> None:
        self.raw = config_dict()
        self.config_error: Exception | None = None
        self.catalog_calls: list[str] = []

    def config(self, department_id: str) -> LoadedConfig:
        if self.config_error is not None:
            raise self.config_error
        return LoadedConfig(raw=self.raw, config=parse_config(self.raw))

    async def catalog(self, request, department):
        self.catalog_calls.append(department.id)
        return catalog(_COURSES)


@pytest.fixture
def loaders() -> _Loaders:
    return _Loaders()


@pytest.fixture
def client(loaders) -> TestClient:
    app = FastAPI()
    app.include_router(diagnose_router.router)
    app.dependency_overrides[diagnose_router.get_config_loader] = lambda: loaders.config
    app.dependency_overrides[diagnose_router.get_catalog_loader] = lambda: loaders.catalog
    return TestClient(app, raise_server_exceptions=False)


def _plan_body(**overrides):
    body = {"department_id": DEPT, "config_version": "test-1", "answers": answers()}
    body.update(overrides)
    return body


# --- GET /diagnose/config ----------------------------------------------------------------


def test_get_config(client, loaders):
    response = client.get("/diagnose/config", params={"department_id": DEPT})
    assert response.status_code == 200
    assert response.headers["X-Navi-Contract"] == "navi-v1"
    assert response.json() == {"department_id": DEPT, "version": "test-1", "config": loaders.raw}


def test_get_config_errors(client, loaders):
    assert client.get("/diagnose/config", params={"department_id": "nope"}).status_code == 404
    assert client.get("/diagnose/config").status_code == 422
    loaders.config_error = ConfigNotFoundError("診断の設定がありません")
    assert client.get("/diagnose/config", params={"department_id": DEPT}).status_code == 404
    loaders.config_error = ConfigError("test", [ConfigIssue("shape", "version", "空")])
    response = client.get("/diagnose/config", params={"department_id": DEPT})
    assert response.status_code == 500
    assert "X-Navi-Contract" not in response.headers


# --- POST /diagnose/plan -----------------------------------------------------------------


def test_plan(client, loaders):
    response = client.post("/diagnose/plan", json=_plan_body())
    assert response.status_code == 200
    assert response.headers["X-Navi-Contract"] == "navi-v1"
    body = response.json()
    assert body["config_version"] == "test-1"
    assert body["answers_digest"].startswith("sha256:")
    assert body["context_digest"] is None  # 履修の状況を送らなければ指紋は無い
    assert body["terms"] == [
        {
            "year": 1,
            "term": "春",
            "credits_total": 4.0,
            "courses": [
                {
                    "syllabus_id": "10",
                    "name": "架空の反応工学",
                    "credits": 2.0,
                    "slots": ["月1"],
                    "slot_note": None,
                    "score": 3.0,
                    "reasons": [{"primitive": "reaches_group", "text": "架空発展系につながる"}],
                    "status": "planned",
                },
                {
                    "syllabus_id": "11",
                    "name": "架空の科目11",
                    "credits": 2.0,
                    "slots": ["火2"],
                    "slot_note": None,
                    "score": 1.0,
                    "reasons": [],  # year_fit（base）だけで入った科目には理由が無い
                    "status": "planned",
                },
            ],
        },
        {
            "year": 1,
            "term": "秋",
            "credits_total": 2.0,
            "courses": [
                {
                    "syllabus_id": "12",
                    "name": "架空の科目12",
                    "credits": 2.0,
                    "slots": ["月1"],
                    "slot_note": None,
                    "score": 1.0,
                    "reasons": [],
                    "status": "planned",
                }
            ],
        },
    ]
    assert loaders.catalog_calls == [DEPT]


def test_same_answers_give_same_plan_and_digest(client):
    first = client.post("/diagnose/plan", json=_plan_body(answers=answers(interest=["adv", "word"]))).json()
    second = client.post("/diagnose/plan", json=_plan_body(answers=answers(interest=["word", "adv"]))).json()
    assert first == second


def test_plan_with_other_version_is_409(client, loaders):
    response = client.post("/diagnose/plan", json=_plan_body(config_version="test-0"))
    assert response.status_code == 409
    assert "test-1" in response.json()["detail"]
    assert loaders.catalog_calls == []


@pytest.mark.parametrize(
    "raw_answers",
    [
        answers(extra=["x"]),
        {"interest": ["adv"], "morning": ["ok"]},
        answers(interest=["nope"]),
        answers(interest=["adv", "solo", "word"]),
        answers(morning=["ok", "avoid"]),
        answers(scale=9),
        answers(scale=True),
        answers(scale="3"),
        answers(morning=[1]),
    ],
)
def test_plan_with_bad_answers_is_422(client, loaders, raw_answers):
    response = client.post("/diagnose/plan", json=_plan_body(answers=raw_answers))
    assert response.status_code == 422
    assert loaders.catalog_calls == []


def test_plan_body_shape_errors(client):
    assert client.post("/diagnose/plan", json={**_plan_body(), "extra": 1}).status_code == 422
    assert client.post("/diagnose/plan", json=_plan_body(department_id="nope")).status_code == 404


def test_plan_with_groups_missing_from_the_curriculum_is_500(client, loaders):
    loaders.raw["base_effects"].append({"primitive": "in_group", "args": {"groups": ["G_GONE"]}, "weight": 1})
    response = client.post("/diagnose/plan", json=_plan_body())
    assert response.status_code == 500
    assert "X-Navi-Contract" not in response.headers


def test_plan_without_history_items_matches_empty_ones(client):
    """履修の状況を送らないときと、空の配列を送るときは同じ応答（前と同じプラン、context_digest は null）。"""
    plain = client.post("/diagnose/plan", json=_plan_body())
    empty = client.post("/diagnose/plan", json=_plan_body(start=None, completed=[], registered=[]))
    assert plain.status_code == empty.status_code == 200
    assert plain.json() == empty.json()


def test_plan_with_history(client):
    body = _plan_body(
        start={"year": 1, "term": "秋"},
        completed=["10"],
        registered=[{"year": 1, "term": "秋", "syllabus_ids": [" 11 "]}],  # 前後の空白は外す
    )
    response = client.post("/diagnose/plan", json=body)
    assert response.status_code == 200, response.text
    out = response.json()
    plain = client.post("/diagnose/plan", json=_plan_body()).json()
    assert out["answers_digest"] == plain["answers_digest"]
    assert out["context_digest"].startswith("sha256:")
    assert [(term["year"], term["term"]) for term in out["terms"]] == [(1, "秋")]
    autumn = out["terms"][0]
    # 登録済みの 11（春の科目でも、送られた学期にそのまま置く）が先、月1 の 12 が後
    assert [(c["syllabus_id"], c["status"]) for c in autumn["courses"]] == [("11", "registered"), ("12", "planned")]
    assert autumn["credits_total"] == 4.0


@pytest.mark.parametrize(
    ("history", "status"),
    [
        ({"start": {"year": 2, "term": "春"}}, 422),  # scope の外
        ({"completed": ["99"]}, 422),  # 知らない科目
        ({"completed": ["10", "10"]}, 422),
        ({"registered": [{"year": 1, "term": "春", "syllabus_ids": ["10"]}], "completed": ["10"]}, 422),
        ({"start": {"year": 1, "term": "秋"}, "registered": [{"year": 1, "term": "春", "syllabus_ids": ["10"]}]}, 422),
        ({"start": {"year": 1, "term": "夏"}}, 422),  # 形の誤り
        ({"start": {"year": "1", "term": "春"}}, 422),
        ({"start": {"year": 1, "term": "春", "extra": 1}}, 422),
        ({"registered": [{"year": 1, "term": "春"}]}, 422),
        ({"completed": [""]}, 422),
    ],
)
def test_plan_with_bad_history_is_422(client, history, status):
    response = client.post("/diagnose/plan", json=_plan_body(**history))
    assert response.status_code == status, response.text
    assert "X-Navi-Contract" not in response.headers


def test_default_loaders_are_the_real_ones():
    from course_core.diagnose.config import load_config

    assert diagnose_router.get_config_loader() is load_config
    assert diagnose_router.get_catalog_loader() is diagnose_router._catalog_from_db
