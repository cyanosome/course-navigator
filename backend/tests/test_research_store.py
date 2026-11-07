"""研究のログの保存（course_core/research/store.py・events.py）と sink の実装のテスト。"""

import asyncio
import itertools
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from course_core.research import sink
from course_core.research.events import CLIENT_EVENT_TYPES, flags_digest
from course_core.research.store import (
    JST,
    JsonlResearchSink,
    ResearchConflict,
    ResearchStore,
    SessionNotFound,
    check_completeness,
)
from course_core.research.study import StudyError, build_study, parse_arm_spec
from course_core.research.variants import VARIANTS
from course_core.schemas.research import ClientEvent

_NOW = datetime(2026, 11, 9, 10, 0, tzinfo=JST)
_TS = datetime(2026, 11, 9, 1, 0, tzinfo=timezone.utc)
_STUDY_ID = "S1109"
_NO_DATA_STATUS = {"similar_to_edges": 0, "similar_models": []}


@pytest.fixture
def store(tmp_path: Path) -> ResearchStore:
    counter = itertools.count(1)
    study, _ = build_study(
        study_id=_STUDY_ID,
        department_id="kansai-enechem-2026",
        arms=dict(parse_arm_spec(s) for s in ("branchA=N:K:V01,A:M:V00", "branchB=N:J:V02,A:L:V01")),
        task_sets=["P1", "P2"],
        n=4,
        spares=0,
        consent_version="v1",
        questionnaires_per_block=2,
        now=_NOW,
        token_factory=lambda: f"token-{next(counter):010d}",
    )
    research_store = ResearchStore(tmp_path / "research")
    research_store.create_study(study)
    research_store.activate_arm(_STUDY_ID, "branchA", "E1 5問中5問")
    return research_store


def _event(event_type: str, seq: int, task_id: str | None = None, **payload) -> ClientEvent:
    return ClientEvent(
        event_id=uuid.uuid4(), event_type=event_type, seq=seq, ts_client=_TS, task_id=task_id, payload=payload
    )


def _lines(store: ResearchStore) -> list[dict]:
    return store.read_events(_STUDY_ID)


def _start(store: ResearchStore, pid: str = "P01") -> str:
    state = store.start_session(_STUDY_ID, pid, data_status=_NO_DATA_STATUS, frontend_version="abc1234")
    store.record_consent(state.session_id, consent_version="v1", form_serial="0001", agreed=True, frontend_version=None)
    return state.session_id


def _run_block(store: ResearchStore, session_id: str, block: int, first_seq: int) -> int:
    """ブロックを1つ通す（課題2つ・質問票2つ）。次の seq を返す。"""
    store.start_block(session_id, block, frontend_version=None)
    seq = first_seq
    if block == 0:
        events = [_event("task_start", seq, "practice"), _event("task_submit", seq + 1, "practice")]
    else:
        task_set = "P1" if block == 1 else "P2"
        events = []
        for offset, suffix in enumerate(("a", "b")):
            task_id = f"{task_set}-{suffix}"
            events += [
                _event("task_start", seq + 2 * offset, task_id),
                _event("task_submit", seq + 2 * offset + 1, task_id),
            ]
        events += [
            _event("questionnaire_submit", seq + 4, scale="SEQ"),
            _event("questionnaire_submit", seq + 5, scale="UEQ-S"),
        ]
    store.append_client_events(session_id, events, frontend_version=None)
    store.end_block(session_id, block, frontend_version=None)
    return seq + len(events)


# --- 封筒 -------------------------------------------------------------------------


def test_client_event_gets_the_full_envelope_from_the_server(store, monkeypatch):
    monkeypatch.setenv("APP_COMMIT", "be12345")
    session_id = _start(store)
    store.start_block(session_id, 0, frontend_version=None)
    store.end_block(session_id, 0, frontend_version=None)
    store.start_block(session_id, 1, frontend_version="fe67890")

    result = store.append_client_events(
        session_id, [_event("syllabus_open", 1, "P1-a", syllabus_id="26001234")], frontend_version=None
    )

    assert (result.accepted, result.duplicates, result.last_seq, result.warnings) == (1, 0, 1, [])
    line = _lines(store)[-1]
    assert line["schema_version"] == "1.0"
    assert (line["origin"], line["seq"], line["event_type"]) == ("client", 1, "syllabus_open")
    assert (line["pid"], line["sequence_id"], line["study_id"], line["arm"]) == ("P01", "Q1", _STUDY_ID, "branchA")
    assert (line["block"], line["condition_id"], line["variant_id"], line["task_id"]) == (1, "K", "V01", "P1-a")
    assert line["flags"] == VARIANTS["V01"].model_dump() and len(line["flags"]) == 20
    assert line["flags_version"] == "2"
    assert line["app_version"] == {"frontend": "fe67890", "backend": "be12345"}
    assert (line["consent_version"], line["mode"]) == ("v1", "onsite")
    assert line["ts_client"] == "2026-11-09T10:00:00.000+09:00"
    assert line["ts_server"].endswith("+09:00")
    assert line["payload"] == {"syllabus_id": "26001234"}
    assert line["warnings"] == []


def test_server_events_outside_a_block_have_no_flags(store):
    session_id = _start(store)

    start, consent = _lines(store)[-2:]
    assert (start["event_type"], start["origin"], start["seq"]) == ("session_start", "server", None)
    assert start["payload"] == {"data_status": _NO_DATA_STATUS}
    assert (start["block"], start["condition_id"], start["variant_id"], start["flags"]) == (None, None, None, None)
    assert start["consent_version"] is None
    assert consent["event_type"] == "consent_recorded"
    assert consent["payload"] == {"consent_version": "v1", "form_serial": "0001", "agreed": True}
    assert consent["consent_version"] == "v1"
    assert session_id


def test_arm_activation_is_logged_without_a_session(store):
    first = _lines(store)[0]

    assert first["event_type"] == "study_arm_activated"
    assert (first["session_id"], first["pid"], first["arm"]) == (None, None, "branchA")
    assert first["payload"]["note"] == "E1 5問中5問"


# --- 重複・seq・課題 --------------------------------------------------------------------


def test_same_event_id_twice_is_counted_and_dropped(store):
    session_id = _start(store)
    event = _event("page_hidden", 1)

    first = store.append_client_events(session_id, [event, event], frontend_version=None)
    again = store.append_client_events(session_id, [event], frontend_version=None)

    assert (first.accepted, first.duplicates) == (1, 1)
    assert (again.accepted, again.duplicates, again.last_seq) == (0, 1, 1)
    assert sum(1 for line in _lines(store) if line["event_type"] == "page_hidden") == 1


def test_seq_gap_and_out_of_order_are_marked_but_kept(store):
    session_id = _start(store)

    gap = store.append_client_events(session_id, [_event("page_hidden", 1), _event("page_visible", 3)], frontend_version=None)
    late = store.append_client_events(session_id, [_event("page_hidden", 2)], frontend_version=None)

    assert gap.warnings == ["seq_gap"] and gap.last_seq == 3
    assert late.warnings == ["seq_out_of_order"] and late.last_seq == 3
    assert [line["warnings"] for line in _lines(store)[-3:]] == [[], ["seq_gap"], ["seq_out_of_order"]]


def test_task_outside_the_block_and_missing_payload_are_marked(store):
    session_id = _start(store)
    store.start_block(session_id, 0, frontend_version=None)

    result = store.append_client_events(
        session_id,
        [_event("task_start", 1, "P2-a"), _event("task_submit", 2), _event("syllabus_open", 3)],
        frontend_version=None,
    )

    assert result.accepted == 3
    assert result.warnings == ["task_not_in_block", "task_id_missing", "payload_missing:syllabus_id"]


def test_variant_applied_digest_is_compared_with_the_server_flags(store):
    session_id = _start(store)
    store.start_block(session_id, 0, frontend_version=None)  # Q1 の練習は V01 の旗
    good = flags_digest(VARIANTS["V01"].model_dump())

    ok = store.append_client_events(session_id, [_event("variant_applied", 1, flags_digest=good)], frontend_version=None)
    bad = store.append_client_events(
        session_id, [_event("variant_applied", 2, flags_digest="fnv1a32:00000000")], frontend_version=None
    )

    assert ok.warnings == []
    assert bad.warnings == ["flags_mismatch"]


def test_flags_digest_matches_the_frontend():
    """frontend/src/navi/variant.ts の flagsDigest を node で回した値（表の版 2。f3c866a の devVariantOut の旗）。"""
    assert flags_digest(VARIANTS["V00"].model_dump()) == "fnv1a32:9dceb921"
    assert flags_digest(VARIANTS["V01"].model_dump()) == "fnv1a32:ee6dfb25"
    assert flags_digest(VARIANTS["V30"].model_dump()) == "fnv1a32:37a1f183"
    assert flags_digest(VARIANTS["V31"].model_dump()) == "fnv1a32:ef5b9837"


def test_client_event_types_match_the_frontend_list():
    """frontend/src/navi/apiTypes.ts の CLIENT_EVENT_TYPES（23 種）と同じ。"""
    assert len(CLIENT_EVENT_TYPES) == 23
    assert {"session_end", "variant_applied", "questionnaire_submit", "client_error"} <= CLIENT_EVENT_TYPES
    assert "chat_response" not in CLIENT_EVENT_TYPES  # サーバーが書く


# --- 状態の遷移 ---------------------------------------------------------------------


def test_blocks_need_consent_and_go_in_order(store):
    state = store.start_session(_STUDY_ID, "P01", data_status=_NO_DATA_STATUS, frontend_version=None)

    with pytest.raises(ResearchConflict, match="同意"):
        store.start_block(state.session_id, 0, frontend_version=None)
    store.record_consent(state.session_id, consent_version="v1", form_serial="1", agreed=True, frontend_version=None)
    with pytest.raises(ResearchConflict, match="ブロック 0"):
        store.start_block(state.session_id, 1, frontend_version=None)
    store.start_block(state.session_id, 0, frontend_version=None)
    store.start_block(state.session_id, 0, frontend_version=None)  # 開いているブロックの2回目は書かない
    with pytest.raises(ResearchConflict, match="終わっていません"):
        store.start_block(state.session_id, 1, frontend_version=None)
    with pytest.raises(ResearchConflict, match="開いていません"):
        store.end_block(state.session_id, 1, frontend_version=None)

    assert sum(1 for line in _lines(store) if line["event_type"] == "block_start") == 1


def test_refused_consent_is_recorded_but_does_not_open_blocks(store):
    state = store.start_session(_STUDY_ID, "P01", data_status=_NO_DATA_STATUS, frontend_version=None)

    after = store.record_consent(state.session_id, consent_version="v1", form_serial="1", agreed=False, frontend_version=None)

    assert after.consent_version is None
    assert _lines(store)[-1]["payload"]["agreed"] is False
    with pytest.raises(ResearchConflict):
        store.record_consent(state.session_id, consent_version="v2", form_serial="1", agreed=True, frontend_version=None)


def test_same_pid_returns_the_existing_session(store):
    first = store.start_session(_STUDY_ID, "P01", data_status=_NO_DATA_STATUS, frontend_version=None)
    second = store.start_session(_STUDY_ID, "P01", data_status=_NO_DATA_STATUS, frontend_version=None)

    assert first.session_id == second.session_id
    assert sum(1 for line in _lines(store) if line["event_type"] == "session_start") == 1


def test_arm_cannot_change_after_the_first_session(store):
    store.start_session(_STUDY_ID, "P01", data_status=_NO_DATA_STATUS, frontend_version=None)

    with pytest.raises(StudyError, match="切り替えられません"):
        store.activate_arm(_STUDY_ID, "branchB", "やり直し")


def test_session_end_is_written_once(store):
    with_client_end = _start(store, "P01")
    store.append_client_events(with_client_end, [_event("session_end", 1, device="pc")], frontend_version=None)
    store.end_session(with_client_end, frontend_version=None)
    store.end_session(with_client_end, frontend_version=None)
    without_client_end = _start(store, "P02")
    store.end_session(without_client_end, frontend_version=None)

    ends = [line for line in _lines(store) if line["event_type"] == "session_end"]
    assert [(line["pid"], line["origin"]) for line in ends] == [("P01", "client"), ("P02", "server")]
    with pytest.raises(ResearchConflict, match="終了"):
        store.append_client_events(with_client_end, [_event("page_hidden", 2)], frontend_version=None)


# --- 撤回 -----------------------------------------------------------------------------


def test_withdraw_removes_the_pid_lines_and_records_the_count(store):
    p01 = _start(store, "P01")
    store.append_client_events(p01, [_event("page_hidden", 1)], frontend_version=None)
    _start(store, "P02")
    before = _lines(store)

    record = store.withdraw(_STUDY_ID, "P01")

    after = _lines(store)
    assert record.removed_lines == sum(1 for line in before if line["pid"] == "P01") == 3
    assert record.removed_sessions == 1
    assert all(line["pid"] != "P01" for line in after)
    assert len(after) == len(before) - 3
    study = store.load_study(_STUDY_ID)
    assert study.participant("P01").withdrawn
    assert study.withdrawals[0].pid == "P01"
    assert store.session(p01) is None
    with pytest.raises(ResearchConflict, match="撤回"):
        store.start_session(_STUDY_ID, "P01", data_status=_NO_DATA_STATUS, frontend_version=None)


def test_no_plain_token_is_left_in_the_data_dir(store):
    _start(store)
    texts = [path.read_text(encoding="utf-8") for path in store.root.rglob("*") if path.is_file()]

    assert all("token-" not in text for text in texts)


# --- 完全性の検査 ---------------------------------------------------------------------


def test_check_finds_no_defects_in_a_full_session(store):
    session_id = _start(store)
    seq = 1
    for block in (0, 1, 2):
        seq = _run_block(store, session_id, block, seq)
    store.append_client_events(session_id, [_event("session_end", seq)], frontend_version=None)
    store.end_session(session_id, frontend_version=None)

    [result] = check_completeness(store.load_study(_STUDY_ID), _lines(store))

    assert (result.pid, result.status, result.defects, result.last_seq) == ("P01", "complete", [], seq)


def test_check_reports_seq_holes_and_missing_tasks(store):
    session_id = _start(store)
    store.start_block(session_id, 0, frontend_version=None)
    store.end_block(session_id, 0, frontend_version=None)
    store.start_block(session_id, 1, frontend_version=None)
    store.append_client_events(
        session_id, [_event("task_start", 1, "P1-a"), _event("task_submit", 4, "P1-a")], frontend_version=None
    )
    store.end_block(session_id, 1, frontend_version=None)

    [result] = check_completeness(store.load_study(_STUDY_ID), _lines(store))

    assert result.status == "in_progress"
    assert result.defects == [
        "seq の欠け: 2, 3",
        "ブロック 1 の task_start が 1 件（2 件のはず）",
        "ブロック 1 の task_submit が 1 件（2 件のはず）",
        "ブロック 1 の questionnaire_submit が 0 件（2 件以上のはず）",
    ]
    assert result.warnings == {"seq_gap": 1}


def test_unfinished_block_is_not_a_defect(store):
    session_id = _start(store)
    store.start_block(session_id, 0, frontend_version=None)
    store.end_session(session_id, frontend_version=None)

    [result] = check_completeness(store.load_study(_STUDY_ID), _lines(store))

    assert (result.status, result.defects) == ("ended_incomplete", [])


# --- sink（AI の口が使う） --------------------------------------------------------------


def test_sink_reports_the_current_block_and_writes_server_events(store, monkeypatch):
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(store.root))
    research_sink = sink.get_research_sink()
    assert isinstance(research_sink, JsonlResearchSink)
    session_id = _start(store, "P02")  # Q2: ブロック 1 は A（M、V00）

    outside = asyncio.run(research_sink.current_variant(session_id))
    store.start_block(session_id, 0, frontend_version=None)
    store.end_block(session_id, 0, frontend_version=None)
    store.start_block(session_id, 1, frontend_version=None)
    inside = asyncio.run(research_sink.current_variant(session_id))
    asyncio.run(research_sink.append_server_event(session_id, "chat_response", {"latency_ms": 1200}))

    assert (outside.block, outside.variant_id, outside.flags) == (None, None, None)
    assert (inside.block, inside.condition_id, inside.variant_id) == (1, "M", "V00")
    assert inside.flags == VARIANTS["V00"]
    line = _lines(store)[-1]
    assert (line["event_type"], line["origin"], line["block"], line["variant_id"]) == ("chat_response", "server", 1, "V00")
    assert line["payload"] == {"latency_ms": 1200}
    assert asyncio.run(research_sink.current_variant("x" * 32)) is None


def test_sink_refuses_unknown_sessions_and_types(store):
    research_sink = JsonlResearchSink(store)
    session_id = _start(store)

    with pytest.raises(SessionNotFound):
        asyncio.run(research_sink.append_server_event("y" * 32, "chat_response", {}))
    with pytest.raises(ValueError):
        asyncio.run(research_sink.append_server_event(session_id, "task_start", {}))  # type: ignore[arg-type]


def test_naive_client_time_is_kept_and_marked(store):
    session_id = _start(store)
    event = ClientEvent(
        event_id=uuid.uuid4(), event_type="page_hidden", seq=1, ts_client=datetime(2026, 11, 9, 10, 0)
    )

    result = store.append_client_events(session_id, [event], frontend_version=None)

    assert result.warnings == ["ts_client_naive"]
    assert _lines(store)[-1]["ts_client"] == "2026-11-09T10:00:00.000"


def test_events_file_is_one_json_object_per_line(store):
    _start(store)

    raw = (store.root / _STUDY_ID / "events.jsonl").read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert all(isinstance(json.loads(line), dict) for line in raw.splitlines())
