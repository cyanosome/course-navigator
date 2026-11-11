"""Study 1 の完全性の検査（eval.study1.integrity・eventlog）のテスト。イベントは合成。"""

import json
from datetime import datetime, timedelta

import pytest

from eval.study1 import integrity as ig
from eval.study1.eventlog import premise_failures, read_events, sessions_of
from eval.study1.score import load_tasks
from study1_fixtures import JST, Builder, complete_participant, write_events

TASK_IDS = {set_id: ts.task_ids for set_id, ts in load_tasks().task_sets.items()}


def _start(hours: int) -> datetime:
    return datetime(2026, 11, 12, 10, 0, tzinfo=JST) + timedelta(hours=hours)


def _check(tmp_path, builders, extra_lines=(), **kwargs):
    events, read = read_events(write_events(tmp_path / "events.jsonl", builders, extra_lines))
    sessions = sessions_of(events)
    return {r.pid: r for r in ig.check_sessions(sessions, TASK_IDS, **kwargs)}, sessions, read


def test_complete_participants_have_no_defects(tmp_path, capsys):
    builders = [
        complete_participant(f"P0{i}", q, start=_start(i))
        for i, q in zip(range(1, 5), ("Q1", "Q2", "Q3", "Q4"), strict=True)
    ]
    reports, sessions, read = _check(tmp_path, builders)
    assert read.unreadable == [] and read.problems == []
    assert all(r.status == "complete" and r.defects == [] for r in reports.values()), {
        p: r.defects for p, r in reports.items()
    }
    assert ig.distribution_order(sessions) == []
    assert ig.main(["--events", str(tmp_path / "events.jsonl")]) == 0
    out = capsys.readouterr().out
    assert "| P01 | Q1 | remote | complete |" in out and "書いた文" not in out


def test_seq_gaps_and_e3(tmp_path):
    builder = complete_participant("P01", "Q1")
    client = [line for line in builder.lines if line["origin"] == "client"]
    for line in client[3:8]:  # 5 件を落とす（33 件中。15% で E3）
        builder.lines.remove(line)
    report = _check(tmp_path, [builder])[0]["P01"]
    assert len(report.missing_seq) == 5 and report.gap_ratio > ig.E3_SEQ_GAP_LIMIT
    assert any("seq の欠け 5 件" in d and "E3" in d for d in report.defects)


def test_missing_questionnaire_and_task_events(tmp_path):
    builder = complete_participant("P01", "Q1")
    sus = next(
        line
        for line in builder.lines
        if line["event_type"] == "questionnaire_submit" and line["payload"]["scale"] == "SUS"
    )
    submit_b = next(line for line in builder.lines if line["event_type"] == "task_submit" and line["task_id"] == "P2-b")
    builder.lines.remove(sus)
    submit_b["payload"]["plan"] = "壊れた"
    defects = _check(tmp_path, [builder])[0]["P01"].defects
    assert any("ブロック 1 の questionnaire_submit（SUS）が 0 件" in d for d in defects)
    assert any("ブロック 2 の課題 b の最終プランが読めない" in d for d in defects)
    final = next(line for line in builder.lines if line["payload"].get("scale") == "振り返り")
    builder.lines.remove(final)
    assert any(
        "最後の questionnaire_submit（振り返り）が 0 件" in d for d in _check(tmp_path, [builder])[0]["P01"].defects
    )


def test_in_progress_session_is_not_a_defect(tmp_path):
    builder = Builder("P01", "Q1")
    builder.start()
    builder.begin_block(0, "P", "V30", "practice")
    builder.diagnose("practice", "practice")
    report = _check(tmp_path, [builder])[0]["P01"]
    assert report.status == "in_progress" and report.defects == []


def test_flags_mismatch_and_inconsistent_plans_are_e4(tmp_path):
    builders = [complete_participant(f"P0{i}", "Q1", start=_start(i)) for i in range(1, 4)]
    applied = next(line for line in builders[0].lines if line["event_type"] == "variant_applied" and line["block"] == 1)
    applied["payload"]["flags_digest"] = "fnv1a32:00000000"
    shown = next(line for line in builders[2].lines if line["event_type"] == "plan_shown" and line["task_id"] == "P2-a")
    shown["payload"]["plan"] = [{"year": 1, "term": "春", "syllabus_ids": ["s01"]}]
    reports, sessions, _ = _check(tmp_path, builders)
    assert any("ブロック 1 の 5.2 の前提: 旗の指紋が違う" in d for d in reports["P01"].defects)
    assert any("ブロック 2 の 5.2 の前提: 同じ答えの初期プランが他と違う" in d for d in reports["P03"].defects)
    assert reports["P02"].defects == []
    failures = premise_failures(sessions, TASK_IDS)
    assert set(failures) == {(sessions[0].session_id, 1), (sessions[2].session_id, 2)}


def test_ai_response_between_diagnosis_and_plan_is_e4(tmp_path):
    builder = Builder("P01", "Q2")
    builder.start()
    builder.begin_block(1, "Y", "V31", "P1")
    send = builder.client("chat_send", {"input": "q"}, task_id="P1-a")
    builder.server("chat_response", {"client_event_id": send["event_id"], "latency_ms": 70_500, "error": None})
    builder.diagnose("P1-a", "P1")  # 依頼の 70 秒後に diag_submit、その1秒後に plan_shown（応答の 70.5 秒はその間）
    events, _ = read_events(write_events(tmp_path / "e.jsonl", [builder]))
    failures = premise_failures(sessions_of(events), TASK_IDS)
    assert failures == {(builder.session_id, 1): ["診断の送信からプランの表示までに AI の応答がある"]}


def test_distribution_order_ignores_spares(tmp_path):
    builders = [
        complete_participant("P02", "Q2", start=_start(1)),
        complete_participant("P01", "Q1", start=_start(2)),
        complete_participant("P04", "Q4", start=_start(3)),
        complete_participant("R01", "Q1", start=_start(0)),
    ]
    reports, sessions, _ = _check(tmp_path, builders)
    problems = ig.distribution_order(sessions)
    assert any("抜けた番号 3" in p for p in problems) and "P01 が P02 より先に始まった" not in problems
    assert any("P02" in p and "P01" in p for p in problems)
    assert all(r.defects == [] for r in reports.values())


def test_start_order_is_reference_only_and_exit_code_stays_zero(tmp_path, capsys):
    builders = [
        complete_participant("P02", "Q2", start=_start(1)),
        complete_participant("P01", "Q1", start=_start(2)),
        complete_participant("P04", "Q4", start=_start(3)),
    ]
    path = write_events(tmp_path / "events.jsonl", builders)
    json_out = tmp_path / "out" / "integrity.json"
    assert ig.main(["--events", str(path), "--json-out", str(json_out)]) == 0  # 番号の順でなくても欠けではない
    out = capsys.readouterr().out
    assert "参考（欠けに数えず、終了コードにも入れない）" in out and "抜けた番号 3" in out
    assert "読めない行 0" in out
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert data["defects"] == 0 and data["reference"]["started_order"] and data["reference"]["sent_order"] is None


def test_sent_order_differences_are_reference_only(tmp_path, capsys):
    builders = [
        complete_participant("P02", "Q2", start=_start(1)),
        complete_participant("P01", "Q1", start=_start(2)),
        complete_participant("R01", "Q1", start=_start(3)),
    ]
    events = write_events(tmp_path / "events.jsonl", builders)
    sent = tmp_path / "sent.txt"
    sent.write_text("# 送った順（pid だけ）\nP01\nP02, P03\n", encoding="utf-8")
    assert ig.read_sent_order(sent) == ["P01", "P02", "P03"]
    assert ig.main(["--events", str(events), "--sent-order", str(sent)]) == 0
    out = capsys.readouterr().out
    assert "P02（送った順 2）が P01（送った順 1）より先に始まった" in out
    assert "送ったがまだ始まっていない（P03）" in out and "送った順に無い pid が始まっている（R01）" in out
    # pid の形でない値（名前など）は読まずに止める
    sent.write_text("P01\nなまえ\n", encoding="utf-8")
    with pytest.raises(ig.SentOrderError, match="2 行目"):
        ig.read_sent_order(sent)
    assert ig.main(["--events", str(events), "--sent-order", str(sent)]) == 2
    sent.write_text("P01\nP01\n", encoding="utf-8")
    with pytest.raises(ig.SentOrderError, match="2回目"):
        ig.read_sent_order(sent)


def test_consent_version_and_study_id_are_arguments(tmp_path):
    builder = Builder("P01", "Q1")
    builder.start(consent="v2-link-202611")
    report = _check(tmp_path, [builder])[0]["P01"]
    assert any("同意の版が v1-diag-ab-202611 でない" in d for d in report.defects)
    assert _check(tmp_path, [builder], consent_version="v2-link-202611")[0]["P01"].defects == []
    assert _check(tmp_path, [builder], consent_version=None)[0]["P01"].defects == []
    other = _check(tmp_path, [builder], consent_version=None, study_id="pilot2-link-202611")[0]["P01"]
    assert any("study_id が pilot2-link-202611 でない行" in d for d in other.defects)


def test_unreadable_lines_and_exit_codes(tmp_path, capsys):
    path = write_events(
        tmp_path / "events.jsonl", [complete_participant("P01", "Q1")], ["{壊れた行", '{"event_id": "x"}']
    )
    assert ig.main(["--events", str(path)]) == 1
    assert "読めない行 2" in capsys.readouterr().out
    assert ig.main(["--events", str(tmp_path / "無い.jsonl")]) == 2
    path = write_events(tmp_path / "ok.jsonl", [complete_participant("P01", "Q1")])
    json_out = tmp_path / "out" / "integrity.json"
    assert ig.main(["--events", str(path), "--json-out", str(json_out)]) == 0
    assert json_out.is_file()
    assert ig.main(["--events", str(path), "--json-out", str(json_out)]) == 2  # 上書きしない


def test_unmatched_responses_are_noted(tmp_path):
    builder = complete_participant("P01", "Q1")
    builder.block = 2
    builder.server("chat_response", {"client_event_id": "どこにも無い", "latency_ms": 10, "error": None})
    report = _check(tmp_path, [builder])[0]["P01"]
    assert "依頼に結べない chat_response 1 件" in report.notes
