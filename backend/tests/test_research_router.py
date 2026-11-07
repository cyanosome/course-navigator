"""研究の API（R1〜R9、api/routers/research.py）のテスト。

ルーターだけを載せた FastAPI と TestClient で回す（lifespan の DB 接続を通らない）。
SIMILAR_TO の数え上げ（Neo4j）は dependency_overrides で偽物を差し込む。
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import research
from course_core.research.store import JST, ResearchStore, check_completeness
from course_core.research.study import build_study, parse_arm_spec

_STUDY_ID = "S1109"
_TOKENS = [f"card-token-{i:04d}" for i in range(1, 5)]
_CONSENT = {"consent_version": "v1", "form_serial": "0007", "agreed": True}


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "research"
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(root))
    monkeypatch.delenv("RESEARCH_DEV", raising=False)
    monkeypatch.delenv("NAVI_DEFAULT_VARIANT", raising=False)
    return root


def _create_study(root: Path, *, activate: bool = True) -> ResearchStore:
    tokens = iter(_TOKENS)
    study, _ = build_study(
        study_id=_STUDY_ID,
        department_id="kansai-enechem-2026",
        arms=dict(parse_arm_spec(s) for s in ("branchA=N:K:V01,A:M:V00", "branchB=N:J:V02,A:L:V01")),
        task_sets=["P1", "P2"],
        n=4,
        spares=0,
        consent_version="v1",
        questionnaires_per_block=2,
        now=datetime(2026, 11, 9, tzinfo=JST),
        token_factory=lambda: next(tokens),
    )
    store = ResearchStore(root)
    store.create_study(study)
    if activate:
        store.activate_arm(_STUDY_ID, "branchA", "E1 通過")
    return store


@pytest.fixture
def store(data_dir: Path) -> ResearchStore:
    return _create_study(data_dir)


def _client(similar_to_edges: int = 0) -> TestClient:
    app = FastAPI()
    app.include_router(research.router)

    async def _probe(_request) -> dict:
        return {"similar_to_edges": similar_to_edges, "similar_models": []}

    app.dependency_overrides[research.get_data_status_probe] = lambda: _probe
    return TestClient(app, raise_server_exceptions=False)


def _events(*items: tuple[str, str | None, dict], start: int) -> dict:
    return {
        "events": [
            {
                "event_id": str(uuid.uuid4()),
                "event_type": event_type,
                "seq": start + offset,
                "ts_client": "2026-11-09T01:00:00.000Z",
                "task_id": task_id,
                "payload": payload,
            }
            for offset, (event_type, task_id, payload) in enumerate(items)
        ]
    }


def _lines(store: ResearchStore) -> list[dict]:
    return store.read_events(_STUDY_ID)


# --- 通しの流れ -------------------------------------------------------------------------


def test_full_session_from_card_to_end_leaves_no_gaps(store):
    client = _client()

    started = client.post("/research/sessions", json={"token": _TOKENS[0]})
    assert started.status_code == 200
    assert started.headers["X-Navi-Contract"] == "navi-v1"
    body = started.json()
    assert (body["pid"], body["sequence_id"], body["consent_recorded"], body["current_block"]) == ("P01", "Q1", False, None)
    assert [b["condition_id"] for b in body["blocks"]] == ["P", "K", "M"]
    cookie = started.headers["set-cookie"]
    assert "navi_sid=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()

    assert client.post("/research/blocks/0/start").status_code == 409  # 同意の前
    assert client.post("/research/consent", json={**_CONSENT, "consent_version": "v0"}).status_code == 409
    consent = client.post("/research/consent", json=_CONSENT)
    assert consent.status_code == 200 and consent.json()["consent_recorded"] is True
    assert client.post("/research/blocks/1/start").status_code == 409  # 練習が先

    seq = 1
    for block, task_ids in ((0, ["practice"]), (1, ["P1-a", "P1-b"]), (2, ["P2-a", "P2-b"])):
        opened = client.post(f"/research/blocks/{block}/start")
        assert opened.status_code == 200
        assert opened.json()["plan"]["task_ids"] == task_ids
        items = [("variant_applied", None, {"flags_digest": "fnv1a32:00000000"})]
        for task_id in task_ids:
            items += [("task_start", task_id, {}), ("syllabus_open", task_id, {"syllabus_id": "26001234"}), ("task_submit", task_id, {})]
        if block:
            items += [("questionnaire_submit", None, {"scale": "SEQ"}), ("questionnaire_submit", None, {"scale": "UEQ-S"})]
        sent = client.post("/research/events", json=_events(*items, start=seq))
        assert sent.status_code == 200
        assert sent.json()["accepted"] == len(items)
        seq += len(items)
        assert client.post(f"/research/blocks/{block}/end").status_code == 200

    current = client.get("/research/sessions/current").json()
    assert (current["completed_blocks"], current["last_seq"]) == ([0, 1, 2], seq - 1)
    assert client.post("/research/events", json=_events(("session_end", None, {"device": "pc"}), start=seq)).status_code == 200
    ended = client.post("/research/sessions/current/end")
    assert ended.status_code == 204
    assert 'navi_sid=""' in ended.headers["set-cookie"] or "Max-Age=0" in ended.headers["set-cookie"]

    [result] = check_completeness(store.load_study(_STUDY_ID), _lines(store))
    assert (result.status, result.defects) == ("complete", [])
    assert client.get("/research/sessions/current").status_code == 404


def test_block_start_returns_the_flags_of_the_block(store):
    client = _client()
    client.post("/research/sessions", json={"token": _TOKENS[1]})  # P02 = Q2: ブロック 1 は A（M、V00）
    client.post("/research/consent", json=_CONSENT)
    client.post("/research/blocks/0/start")
    client.post("/research/blocks/0/end")

    opened = client.post("/research/blocks/1/start").json()

    assert opened["plan"] == {"block": 1, "condition_id": "M", "task_set_id": "P1", "task_ids": ["P1-a", "P1-b"]}
    assert (opened["variant"]["variant_id"], opened["variant"]["condition_id"]) == ("V00", "M")
    assert opened["variant"]["flags"]["assistant"] == "on"
    assert client.get("/research/sessions/current").json()["variant"]["variant_id"] == "V00"


# --- 記録しないもの ------------------------------------------------------------------------


def test_events_without_a_session_get_401_and_write_nothing(store):
    before = _lines(store)

    response = _client().post("/research/events", json=_events(("page_hidden", None, {}), start=1))
    with_bad_header = _client().post(
        "/research/events", json=_events(("page_hidden", None, {}), start=1), headers={"X-Navi-Session": "z" * 32}
    )

    assert response.status_code == 401 and with_bad_header.status_code == 401
    assert _lines(store) == before


def test_unknown_event_type_is_422_and_nothing_is_written(store):
    client = _client()
    client.post("/research/sessions", json={"token": _TOKENS[0]})
    before = _lines(store)

    response = client.post(
        "/research/events", json=_events(("page_hidden", None, {}), ("chat_response", None, {}), start=1)
    )

    assert response.status_code == 422
    assert _lines(store) == before


def test_unknown_token_is_404_and_writes_nothing(store):
    before = _lines(store)

    response = _client().post("/research/sessions", json={"token": "no-such-token-000"})

    assert response.status_code == 404
    assert _lines(store) == before


def test_body_that_is_not_utf8_is_422_not_500(store):
    """手の通しで見つけた: CP932 の本文が検証のエラーの表示で 500 になっていた。"""
    client = _client()
    client.post("/research/sessions", json={"token": _TOKENS[0]})
    body = json.dumps(_events(("search_query", None, {"q": "熱力学"}), start=1), ensure_ascii=False)

    response = client.post(
        "/research/events", content=body.encode("cp932"), headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert _lines(store)[-1]["event_type"] == "session_start"


def test_validation_errors_do_not_echo_the_body(store):
    client = _client()
    client.post("/research/sessions", json={"token": _TOKENS[0]})

    response = client.post("/research/events", json=_events(("page_hidden", None, {"note": "秘密のメモ"}), start=0))

    assert response.status_code == 422
    assert "秘密のメモ" not in response.text


def test_too_large_body_is_413(store):
    client = _client()
    client.post("/research/sessions", json={"token": _TOKENS[0]})

    response = client.post("/research/events", json=_events(("client_error", None, {"message": "x" * 300_000}), start=1))

    assert response.status_code == 413


# --- セッションの開始の条件 -------------------------------------------------------------------


def test_session_needs_an_active_arm(data_dir):
    _create_study(data_dir, activate=False)

    response = _client().post("/research/sessions", json={"token": _TOKENS[0]})

    assert response.status_code == 409
    assert "腕が未決定" in response.json()["detail"]


def test_similar_to_edges_in_the_db_stop_the_start(store):
    response = _client(similar_to_edges=1419).post("/research/sessions", json={"token": _TOKENS[0]})

    assert response.status_code == 409
    assert "C8" in response.json()["detail"]
    assert store.sessions(_STUDY_ID) == []


def test_same_token_again_returns_the_same_session(store):
    first = _client().post("/research/sessions", json={"token": _TOKENS[0]}).json()
    second = _client().post("/research/sessions", json={"token": _TOKENS[0]}).json()

    assert first["session_id"] == second["session_id"]
    assert sum(1 for line in _lines(store) if line["event_type"] == "session_start") == 1


def test_header_session_works_without_cookie(store):
    session_id = _client().post("/research/sessions", json={"token": _TOKENS[0]}).json()["session_id"]
    other_tab = _client()

    current = other_tab.get("/research/sessions/current", headers={"X-Navi-Session": session_id})

    assert current.status_code == 200 and current.json()["pid"] == "P01"


def test_beacon_text_plain_body_is_accepted(store):
    client = _client()
    client.post("/research/sessions", json={"token": _TOKENS[0]})

    response = client.post(
        "/research/events",
        content=json.dumps(_events(("page_hidden", None, {}), start=1)),
        headers={"Content-Type": "text/plain;charset=UTF-8"},
    )

    assert response.status_code == 200 and response.json()["accepted"] == 1


def test_withdrawn_card_cannot_start_again(store):
    _client().post("/research/sessions", json={"token": _TOKENS[0]})
    store.withdraw(_STUDY_ID, "P01")

    response = _client().post("/research/sessions", json={"token": _TOKENS[0]})

    assert response.status_code == 409
    assert all(line["pid"] != "P01" for line in _lines(store))


def test_ended_session_cannot_send_events(store):
    client = _client()
    session_id = client.post("/research/sessions", json={"token": _TOKENS[0]}).json()["session_id"]
    client.post("/research/sessions/current/end")

    response = client.post(
        "/research/events", json=_events(("page_hidden", None, {}), start=1), headers={"X-Navi-Session": session_id}
    )
    again = _client().post("/research/sessions", json={"token": _TOKENS[0]})

    assert response.status_code == 409
    assert again.status_code == 409


# --- R8・R9 変種の旗 ----------------------------------------------------------------------


def test_default_variant_follows_the_environment(data_dir, monkeypatch):
    client = _client()

    default = client.get("/research/variants/default").json()
    monkeypatch.setenv("NAVI_DEFAULT_VARIANT", "V00")
    switched = client.get("/research/variants/default").json()

    assert (default["variant_id"], default["condition_id"], default["flags"]["assistant"]) == ("V01", None, "off")
    assert default["flags_version"] == "1"
    assert switched["variant_id"] == "V00"


def test_variant_by_id_is_only_for_development(data_dir, monkeypatch):
    client = _client()

    assert client.get("/research/variants/V03").status_code == 404
    monkeypatch.setenv("RESEARCH_DEV", "true")
    assert client.get("/research/variants/V03").json()["flags"]["graph"] == "off"
    assert client.get("/research/variants/V99").status_code == 404
