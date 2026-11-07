"""study（釣り合いの表・トークン・腕）のテスト（course_core/research/study.py）。"""

import csv
import itertools
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from course_core.research import cli
from course_core.research.study import (
    SEQUENCES,
    ArmCondition,
    StudyError,
    balanced_sequences,
    build_study,
    hash_token,
    parse_arm_spec,
    start_violations,
)
from course_core.research.store import JST, ResearchStore

_NOW = datetime(2026, 11, 9, 10, 0, tzinfo=JST)
_ARM_A = "branchA=N:K:V01,A:M:V00"
_ARM_B = "branchB=N:J:V02,A:L:V01"


def _tokens():
    counter = itertools.count(1)
    return lambda: f"token-{next(counter):010d}"


def _study(n: int = 12, spares: int = 4, arms: tuple[str, ...] = (_ARM_A, _ARM_B)):
    return build_study(
        study_id="S1109",
        department_id="kansai-enechem-2026",
        arms=dict(parse_arm_spec(spec) for spec in arms),
        task_sets=["P1", "P2"],
        n=n,
        spares=spares,
        consent_version="v1",
        questionnaires_per_block=2,
        now=_NOW,
        token_factory=_tokens(),
    )


# --- 釣り合いの表 -----------------------------------------------------------------


def test_n12_puts_three_people_in_each_sequence():
    study, _ = _study(n=12)
    regular = [p for p in study.participants if not p.spare]

    assert Counter(p.sequence_id for p in regular) == {"Q1": 3, "Q2": 3, "Q3": 3, "Q4": 3}


def test_first_four_cover_all_sequences_and_first_two_cover_both_orders():
    study, _ = _study(n=12)
    first_four = [p.sequence_id for p in study.participants[:4]]

    assert first_four == list(SEQUENCES)
    first_blocks = [study.block_plan(p.sequence_id, "branchA", 1).condition_id for p in study.participants[:2]]
    assert first_blocks == ["K", "M"]  # 1人目は N（K）から、2人目は A（M）から


def test_balanced_sequences_repeat_in_order():
    assert balanced_sequences(6) == ["Q1", "Q2", "Q3", "Q4", "Q1", "Q2"]


def test_spares_get_one_card_per_sequence():
    study, cards = _study(n=12, spares=4)
    spares = [p for p in study.participants if p.spare]

    assert [p.pid for p in spares] == ["R01", "R02", "R03", "R04"]
    assert [p.sequence_id for p in spares] == list(SEQUENCES)
    assert [c.pid for c in cards[:2]] == ["P01", "P02"]
    assert len(cards) == 16


def test_sequences_follow_the_plan():
    """計画 4.1: Q1＝N+P1→A+P2、Q2＝A+P1→N+P2、Q3＝N+P2→A+P1、Q4＝A+P2→N+P1。"""
    study, _ = _study()
    expected = {
        "Q1": [("K", "P1"), ("M", "P2")],
        "Q2": [("M", "P1"), ("K", "P2")],
        "Q3": [("K", "P2"), ("M", "P1")],
        "Q4": [("M", "P2"), ("K", "P1")],
    }
    for sequence_id, blocks in expected.items():
        plans = study.block_plans(sequence_id, "branchA")
        assert [(p.condition_id, p.task_set_id) for p in plans[1:]] == blocks
        assert plans[1].task_ids == [f"{blocks[0][1]}-a", f"{blocks[0][1]}-b"]


def test_branch_b_uses_the_same_cards_with_other_variants():
    study, _ = _study()

    assert study.variant_out("Q1", "branchA", 1).variant_id == "V01"
    assert study.variant_out("Q1", "branchB", 1).variant_id == "V02"
    assert study.variant_out("Q1", "branchB", 2).variant_id == "V01"


def test_practice_block_shows_block_one_flags_under_condition_p():
    study, _ = _study()

    practice = study.block_plan("Q2", "branchA", 0)
    variant = study.variant_out("Q2", "branchA", 0)
    assert (practice.condition_id, practice.task_set_id, practice.task_ids) == ("P", "practice", ["practice"])
    assert (variant.condition_id, variant.variant_id) == ("P", "V00")


# --- トークン ----------------------------------------------------------------------


def test_study_file_keeps_only_token_hashes():
    study, cards = _study()
    dumped = study.model_dump_json()

    for card in cards:
        assert card.token not in dumped
        assert study.participant(card.pid).token_sha256 == hash_token(card.token)


def test_duplicate_tokens_stop_creation():
    with pytest.raises(StudyError, match="トークンが重なりました"):
        build_study(
            study_id="S1",
            department_id="d",
            arms=dict([parse_arm_spec(_ARM_A)]),
            task_sets=["P1", "P2"],
            n=2,
            spares=0,
            consent_version="v1",
            questionnaires_per_block=2,
            now=_NOW,
            token_factory=lambda: "same-token-0000",
        )


# --- 腕 ------------------------------------------------------------------------


def test_parse_arm_spec():
    name, conditions = parse_arm_spec(_ARM_A)

    assert name == "branchA"
    assert conditions == {
        "N": ArmCondition(condition_id="K", variant_id="V01"),
        "A": ArmCondition(condition_id="M", variant_id="V00"),
    }


@pytest.mark.parametrize(
    "spec",
    ["branchA", "branchA=N:K:V01", "branchA=N:K:V01,N:M:V00", "branchA=N:K,A:M:V00", "bad name=N:K:V01,A:M:V00"],
)
def test_parse_arm_spec_rejects_malformed(spec):
    with pytest.raises(StudyError):
        parse_arm_spec(spec)


@pytest.mark.parametrize(
    ("arms", "message"),
    [
        (("x=N:K:V01,A:M:V07",), "C11"),  # mcp_free は未実装の水準
        (("x=N:K:V01,A:M:V23",), "C4"),  # verify=off は人に出さない
        (("x=N:K:V01,A:M:V18",), "C6"),  # detail=core と課題 b
        (("x=N:K:V01,A:M:V99",), "表にありません"),
        (("x=N:K:V01,A:M:V01",), "同じ変種"),
        (("x=N:P:V01,A:M:V00",), "練習"),
        ((_ARM_A, "y=N:K:V02,A:L:V01"), "重なっています"),
    ],
)
def test_arms_outside_the_constraints_are_refused(arms, message):
    with pytest.raises(StudyError, match=message):
        _study(arms=arms)


def test_bad_ids_and_task_sets_are_refused():
    with pytest.raises(StudyError, match="study_id"):
        build_study(
            study_id="../x",
            department_id="d",
            arms=dict([parse_arm_spec(_ARM_A)]),
            task_sets=["P1", "P1"],
            n=1,
            spares=0,
            consent_version="v1",
            questionnaires_per_block=2,
            now=_NOW,
        )


# --- 開始の検査（C8・C9） -------------------------------------------------------------


def test_similar_to_edges_stop_an_ai_arm():
    study, _ = _study()
    study.active_arm = "branchA"

    assert start_violations(study, similar_to_edges=0, similar_models=[]) == []
    violations = start_violations(study, similar_to_edges=1419, similar_models=["text-embedding-004"])
    assert len(violations) == 1 and violations[0].startswith("C8")


def test_similar_to_edges_do_not_stop_an_arm_without_ai():
    study, _ = _study()
    study.active_arm = "branchB"

    assert start_violations(study, similar_to_edges=1419, similar_models=["deterministic-mock-768"]) == []


def test_no_active_arm_is_a_violation():
    study, _ = _study()

    assert start_violations(study, similar_to_edges=0, similar_models=[]) == ["study の腕が未決定"]


# --- CLI（create-study） --------------------------------------------------------------


def _create_args(cards_out: Path) -> list[str]:
    return [
        "create-study", "--study-id", "S1109", "--department", "kansai-enechem-2026",
        "--arm", _ARM_A, "--arm", _ARM_B, "--task-sets", "P1,P2", "--n", "12", "--spares", "4",
        "--consent-version", "v1", "--cards-out", str(cards_out), "--base-url", "https://example.org",
    ]  # fmt: skip


def test_cli_writes_cards_once_and_the_study_keeps_only_hashes(tmp_path):
    store = ResearchStore(tmp_path / "research")
    cards_out = tmp_path / "private" / "cards.csv"

    assert cli.main(_create_args(cards_out), store=store) == 0
    assert cli.main(_create_args(cards_out), store=store) == 1  # 上書きしない

    rows = list(csv.DictReader(cards_out.open(encoding="utf-8")))
    study_text = (tmp_path / "research" / "S1109" / "study.json").read_text(encoding="utf-8")
    assert len(rows) == 16
    assert rows[0]["url"] == f"https://example.org/s/{rows[0]['token']}"
    assert all(row["token"] not in study_text for row in rows)
    assert store.load_study("S1109").active_arm is None


def test_cli_refuses_cards_inside_a_git_worktree(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    store = ResearchStore(tmp_path / "research")

    assert cli.main(_create_args(tmp_path / "repo" / "cards.csv"), store=store) == 1
    assert not (tmp_path / "repo" / "cards.csv").exists()
    assert store.study_ids() == []
