"""Study 1 の指標（eval.study1.metrics）のテスト。イベントと科目は合成。"""

import json

import pytest

from eval.study1 import metrics as mt
from eval.study1.score import load_tasks
from study1_fixtures import P1_INITIAL, P1_SOLVED, P2_INITIAL, P2_SOLVED, Builder, write_catalog, write_events

SECOND = 1000.0


def _p01() -> Builder:
    """系列 Q1 の1人: ブロック1（V30・P1）は手で直し、ブロック2（V31・P2）は AI に頼む。"""
    b = Builder("P01", "Q1")
    b.start()
    b.begin_block(0, "P", "V30", "practice")
    b.diagnose("practice", "practice")
    b.submit("practice", P1_INITIAL)
    b.end_block()

    b.begin_block(1, "W", "V30", "P1")
    b.diagnose("P1-a", "P1")
    b.client("task_start", {"block": 1, "task_index": 1, "continued": True}, task_id="P1-b", after=0)
    b.client("status_open", {"how": "band"}, task_id="P1-b")
    b.client("syllabus_open", {"syllabus_id": "s04", "from": "status"}, task_id="P1-b")
    b.client("syllabus_open", {"syllabus_id": "s05", "from": "plan"}, task_id="P1-b")
    b.client("checkpoint_add", {"checkpoint": {"id": "c1", "kind": "credits"}}, task_id="P1-b")
    b.client("original_open", {"syllabus_id": "s04"}, task_id="P1-b")
    b.client("page_hidden", task_id="P1-b")
    b.client("page_visible", task_id="P1-b", after=60)
    move = {"via": "status", "checkpoint_id": "free", "moved_from": "s04", "moved_to": "s04b"}
    b.edit("P1-b", "add", "s04b", 1, "春", "check_fix", **move)
    b.edit("P1-b", "remove", "s04", 1, "春", "check_fix", **move)
    b.edit("P1-b", "remove", "a05", 1, "秋", "manual")
    b.edit("P1-b", "add", "a05b", 1, "秋", "search")
    b.edit("P1-b", "add", "a07", 1, "秋", "search")
    b.edit("P1-b", "remove", "e03", 1, "秋", "manual")
    b.edit("P1-b", "remove", "e01", 1, "春", "manual")
    b.submit("P1-b", P1_SOLVED, after=5)
    b.block_questionnaires(sus=4, q11=4, q12=3)
    b.end_block()

    b.begin_block(2, "Y", "V31", "P2")
    b.diagnose("P2-a", "P2")
    b.client("task_start", {"block": 2, "task_index": 1, "continued": True}, task_id="P2-b", after=0)
    b.refine("P2-b", P2_INITIAL, local_id="1", latency_ms=12_000, add=["a08"], remove=["e06", "s01"])
    shown = [
        {"kind": "remove", "syllabus_id": "e06"},
        {"kind": "remove", "syllabus_id": "s01"},
        {"kind": "add", "syllabus_id": "a08"},
    ]
    accepted = [shown[1], shown[2]]
    b.decide("P2-b", "1", shown, accepted)
    b.edit("P2-b", "remove", "s01", 1, "春", "refine", suggestion="remove", refine_local_id="1")
    b.edit("P2-b", "add", "a08", 1, "秋", "refine", suggestion="add", refine_local_id="1")
    b.client("status_open", {"how": "row"}, task_id="P2-b")
    b.refine("P2-b", P2_INITIAL, local_id="2", latency_ms=170_000, error="timeout")
    b.refine("P2-b", P2_INITIAL, local_id="3", latency_ms=1_000, error="llm")
    ask = b.client("chat_send", {"input": "AI に聞く"}, task_id="P2-b")
    b.server(
        "chat_response",
        {
            "client_event_id": ask["event_id"],
            "latency_ms": 30_000,
            "error": None,
            "plan_delivery": None,
            "plan_suggestions": None,
            "cited_codes": ["s01"],
            "source_codes": ["s01", "zz9"],
            "unverified_codes": [],
        },
    )
    b.wait(30)
    b.edit("P2-b", "add", "s01", 1, "春", "manual")
    b.edit("P2-b", "remove", "s03", 1, "春", "manual")
    b.edit("P2-b", "add", "s03b", 1, "春", "search")
    b.submit("P2-b", P2_SOLVED, after=5)
    b.block_questionnaires(sus=5, q11=5, q12=4)
    b.end_block()
    b.finish(prefer="2")
    return b


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    directory = tmp_path_factory.mktemp("m")
    events = write_events(directory / "events.jsonl", [_p01()])
    catalog = write_catalog(directory / "catalog.json")
    return mt.build_metrics(events, catalog, load_tasks())


def _block(data, block):
    person = data["participants"][0]
    return next(b for b in person["blocks"] if b["block"] == block)


def test_success_and_achievement(data):
    v30, v31 = _block(data, 1), _block(data, 2)
    assert (v30["y"], v30["a"], v30["a0"], v30["gain"]) == (1, 1.0, 0.5, 0.5)
    assert v31["conditions"] == {"K1": "met", "K2": "met", "K3": "met", "K4": "met", "K5": "met", "K6": "met"}
    assert v30["conditions_initial"]["K2"] == "unmet"


def test_time_hidden_and_wait(data):
    v30, v31 = _block(data, 1), _block(data, 2)
    # 課題 b: 5 秒ごとの 13 件と、隠れていた 60 秒と、出すまでの 5 秒。隠れていた分を引く
    assert v30["hidden_ms"] == 60 * SECOND
    assert v30["t_b_ms"] == (5 * 13 + 60 + 5) * SECOND - 60 * SECOND
    assert v30["W_ms"] == 0 and v30["t_b_prime_ms"] == v30["t_b_ms"]
    assert v31["W_ms"] == (12 + 170 + 1 + 30) * SECOND
    assert v31["t_b_prime_ms"] == v31["t_b_ms"] - v31["W_ms"]
    assert v30["t_a_ms"] == 61 * SECOND


def test_checking_behaviour(data):
    v30, v31 = _block(data, 1), _block(data, 2)
    assert (v30["B1"], v30["B2"], v30["B3"], v30["B4"], v30["B"]) == (1, 1, 1, 1, 2)
    assert v30["B5"] is None and v31["B5"] == 1.0


def test_change_count_pairs_moves(data):
    v30, v31 = _block(data, 1), _block(data, 2)
    assert v30["changes"] == {
        "D": 5, "adds": 3, "removes": 4, "moves": 2, "readded": 0,
        "by_source": {"check_fix": 1, "manual": 2, "search": 2}, "unknown_courses": 0,
    }  # fmt: skip
    assert v30["efficiency"] == 8 / 5
    # s01 を AI の案で外し手で戻した組も、同じ名前なので移すに数える（readded）
    assert v31["changes"]["moves"] == 2 and v31["changes"]["readded"] == 1 and v31["changes"]["D"] == 3


def test_ai_use_failures_and_reliance(data):
    v31 = _block(data, 2)
    ai = v31["ai"]
    assert (ai["requests"], ai["refine_requests"], ai["chat_requests"], ai["used"]) == (4, 3, 1, True)
    assert (ai["lines_shown"], ai["lines_accepted"]) == (3, 2) and ai["acceptance_rate"] == pytest.approx(2 / 3)
    assert ai["decisions"] == {"partial": 1, "no_decision": 0}
    # 系統図の科目（s01）を外す行だけが、満たしていた K5 を壊す。それが採られた
    assert (ai["breaking_lines_shown"], ai["breaking_lines_accepted"], ai["error_reliance"]) == (1, 1, 1.0)
    assert ai["ids_not_in_catalog"] == 1
    assert v31["ai_failures"]["failures"] == 2 and v31["ai_failures"]["by_outcome"] == {
        "error:llm": 1,
        "error:timeout": 1,
        "ok": 2,
    }
    assert v31["system_failure"] is True
    assert _block(data, 1)["ai"] is None and _block(data, 1)["system_failure"] is False


def test_questionnaires_and_person(data):
    v30, v31 = _block(data, 1), _block(data, 2)
    assert v30["SUS"] == 75.0 and v31["SUS"] == 100.0
    assert (v30["Q11"], v30["Q12"], v31["Q11"]) == (4.0, 3.0, 5.0)
    person = data["participants"][0]
    assert person["prefer_screen"] == "2" and person["prefer_variant_id"] == "V31"
    assert (person["grade"], person["faculty"], person["reflection_answered"]) == ("1", "own", 1)
    assert person["completed"] and person["both_b_submitted"] and person["seq_missing"] == 0 and not person["e3"]
    assert person["f4_minutes"] is not None and person["f4_minutes"] > 0
    text = json.dumps(data, ensure_ascii=False)
    assert "書いた文" not in text and "理由の文" not in text  # 自由記述は書かない


def test_answer_deviation_and_premises(data):
    assert _block(data, 1)["answers_deviate"] is False
    assert _block(data, 1)["premise_failures"] == []


def test_sus_formula():
    assert mt.sus_score({f"sus{i}": 3 for i in range(1, 11)}) == 50.0
    assert mt.sus_score({f"sus{i}": (5 if i % 2 else 1) for i in range(1, 11)}) == 100.0
    assert mt.sus_score({f"sus{i}": "4" for i in range(1, 11)}) == 2.5 * (15 + 5)
    assert mt.sus_score({"sus1": 3}) is None and mt.sus_score({f"sus{i}": 6 for i in range(1, 11)}) is None


def test_missing_final_plan_is_noted(tmp_path):
    b = _p01()
    submit = next(line for line in b.lines if line["event_type"] == "task_submit" and line["task_id"] == "P1-b")
    del submit["payload"]["plan"]
    data = mt.build_metrics(write_events(tmp_path / "e.jsonl", [b]), write_catalog(tmp_path / "c.json"), load_tasks())
    block = next(x for x in data["participants"][0]["blocks"] if x["block"] == 1)
    assert block["y"] is None and any("最終プランを採点できない" in note for note in block["notes"])


def test_main_writes_outside_and_refuses_overwrite(tmp_path):
    events = write_events(tmp_path / "e.jsonl", [_p01()])
    catalog = write_catalog(tmp_path / "c.json")
    out = tmp_path / "metrics.json"
    assert mt.main(["--events", str(events), "--catalog", str(catalog), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["format"] == mt.METRICS_FORMAT
    assert mt.main(["--events", str(events), "--catalog", str(catalog), "--out", str(out)]) == 1
