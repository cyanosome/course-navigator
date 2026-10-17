"""eval.retrieval_metrics（検索方式比較の採点・判定の純関数）のテスト。DB・LLM は使わない。"""

import itertools
import json
import math
from pathlib import Path

import pytest

from eval.metrics import GoldenCase
from eval.retrieval_metrics import (
    CONDITIONS,
    GenerationRecord,
    RankedEntry,
    RetrievalRecord,
    count_label,
    cost_label,
    evaluate_hypotheses,
    ndcg_at_k,
    prerequisite_closure,
    prerequisite_violations,
    random_expected_ndcg,
    random_expected_recall,
    recall_at_k,
    score_generation,
    score_retrieval,
)

_SEED = Path(__file__).resolve().parents[2] / "seed" / "courses.json"
_PREREQS = {course["code"]: course["prerequisite_codes"] for course in json.loads(_SEED.read_text("utf-8"))}

_Q01 = GoldenCase(
    id="q01",
    question="データサイエンス入門の次に取れる科目は?",
    mode="next_step",
    anchor_code="GMS-301",
    expected_codes=["GMS-303", "GMS-401"],
    forbidden_codes=["GMS-101", "GMS-201"],
)
_Q08 = GoldenCase(
    id="q08",
    question="データベースに近い分野の科目は?",
    mode="topic",
    anchor_code="GMS-302",
    expected_codes=["GMS-201", "GMS-301", "GMS-402"],
    forbidden_codes=["GMS-102", "GMS-202"],
)
_Q14 = GoldenCase(
    id="q14", question="データサイエンスの次は?", mode="unclear", alternatives=["GMS-301", "GMS-401"]
)


def test_recall_counts_only_top_k_and_is_undefined_without_expected():
    assert recall_at_k(["A", "X", "B"], {"A", "B"}, 2) == 0.5
    assert recall_at_k(["A", "X", "B"], {"A", "B"}, 3) == 1.0
    assert recall_at_k(["A"], set(), 5) is None


def test_ndcg_matches_hand_computation():
    expected_dcg = 1 / math.log2(2) + 1 / math.log2(4)
    ideal = 1 / math.log2(2) + 1 / math.log2(3)
    assert ndcg_at_k(["A", "X", "B"], {"A", "B"}, 3) == pytest.approx(expected_dcg / ideal)
    assert ndcg_at_k(["A", "B"], {"A", "B"}, 5) == pytest.approx(1.0)
    assert ndcg_at_k(["X", "Y"], {"A"}, 5) == 0.0


def test_ndcg_ideal_is_capped_at_k_when_expected_is_larger():
    # |E|=6 > K=5 でも上位5件が全部関連なら1（IDCG は min(|E|, K) 件で作る）
    assert ndcg_at_k(list("ABCDE"), set("ABCDEF"), 5) == pytest.approx(1.0)
    assert recall_at_k(list("ABCDE"), set("ABCDEF"), 5) == pytest.approx(5 / 6)


def test_prerequisite_closure_follows_seed_transitively():
    assert prerequisite_closure(_PREREQS, "GMS-301") == {"GMS-201", "GMS-203", "GMS-101", "GMS-102"}
    assert prerequisite_closure(_PREREQS, "GMS-101") == set()
    assert prerequisite_closure({"A": ["B"], "B": ["A"]}, "A") == {"B"}  # 循環でも止まる


def test_prerequisite_violation_needs_an_unfinished_direct_prerequisite():
    # q01: 履修済み D = {301, 201, 203, 101, 102}。303 は 202 が未履修なので違反、202 自体は前提 102 が済んでいるので違反でない
    ranked = ["GMS-303", "GMS-401", "GMS-202", "GMS-302", "GMS-101"]
    assert prerequisite_violations(ranked, _PREREQS, "GMS-301", 5) == ["GMS-303"]
    assert prerequisite_violations(ranked, _PREREQS, "GMS-301", 1) == ["GMS-303"]
    assert prerequisite_violations(["GMS-401"], _PREREQS, "GMS-301", 5) == []


def test_score_retrieval_for_next_step_reports_constraints():
    score = score_retrieval(_Q01, ["GMS-303", "GMS-401", "GMS-202", "GMS-101", "GMS-201"], _PREREQS, 5)
    assert score.recall == 1.0
    assert score.ndcg == pytest.approx(1.0)
    assert score.forbidden_hits == ["GMS-101", "GMS-201"]
    assert score.violations == ["GMS-303"]
    assert score.violation_rate == pytest.approx(1 / 5)
    assert score.completed_hits == ["GMS-101", "GMS-201"]
    assert score.returned == 5


def test_score_retrieval_topic_has_no_violation_fields_and_handles_short_lists():
    score = score_retrieval(_Q08, ["GMS-201"], _PREREQS, 5)
    assert score.returned == 1
    assert score.recall == pytest.approx(1 / 3)
    assert score.violations is None and score.violation_rate is None


def test_score_retrieval_unclear_only_describes():
    assert score_retrieval(_Q14, ["GMS-301", "GMS-401"], _PREREQS, 5).within_alternatives is True
    score = score_retrieval(_Q14, ["GMS-301", "GMS-303"], _PREREQS, 5)
    assert score.within_alternatives is False
    assert score.recall is None and score.ndcg is None


def test_random_expectations_match_brute_force():
    candidates, k = 5, 2
    relevant = {"A", "B"}
    items = ["A", "B", "C", "D", "E"]
    ndcgs, recalls = [], []
    for order in itertools.permutations(items):
        ndcgs.append(ndcg_at_k(list(order), relevant, k))
        recalls.append(recall_at_k(list(order), relevant, k))
    assert random_expected_ndcg(k, len(relevant), candidates) == pytest.approx(sum(ndcgs) / len(ndcgs))
    assert random_expected_recall(k, candidates) == pytest.approx(sum(recalls) / len(recalls))
    with pytest.raises(ValueError):
        random_expected_ndcg(5, 0, 19)


def test_score_generation_excludes_anchor_and_flags_outside_candidates():
    score = score_generation(_Q01, ["[GMS-301]", "GMS-303", "ＧＭＳ－２０２"], ["GMS-303", "GMS-401"])
    assert score.scored_codes == ["GMS-303", "GMS-202"]
    assert score.outside_candidates == ["GMS-202"]
    assert score.recall == 0.5
    assert score.precision == 0.5


def test_count_and_cost_labels():
    assert count_label(5, 3) == "差あり"
    assert count_label(4, 3) == "差なし"
    assert cost_label(15.0, 10.0) == "差あり"
    assert cost_label(14.0, 10.0) == "差なし"
    assert cost_label(None, 10.0) == "比較不能"


# --- 仮説判定 ---------------------------------------------------------------------


def _record(condition: str, case: GoldenCase, codes: list[str]) -> RetrievalRecord:
    return RetrievalRecord(
        run_id="t",
        condition=condition,
        question_id=case.id,
        mode=case.mode,
        anchor_code=case.anchor_code,
        ranked=[RankedEntry(code=code, title=code, score=0.0) for code in codes],
        scores={str(k): score_retrieval(case, codes, _PREREQS, k) for k in (5, 10)},
        started_at="t",
    )


def _directional_cases() -> list[GoldenCase]:
    return [
        GoldenCase(id=f"d{i}", question="q", mode="prereq", anchor_code="GMS-303", expected_codes=["GMS-301", "GMS-202"])
        for i in range(3)
    ]


def test_h1_supported_when_graph_wins_by_margin_on_three_questions():
    cases = _directional_cases()
    records = []
    for case in cases:
        records.append(_record("pure_graph", case, ["GMS-301", "GMS-202"]))
        records.append(_record("pure_vector", case, ["GMS-101", "GMS-102"]))
    verdicts = {v.hypothesis[:2]: v for v in evaluate_hypotheses(records, [], {c.id: c for c in cases}, {})}
    assert verdicts["H1"].label == "支持"
    assert verdicts["H2"].label == "判定不能"  # hybrid の記録が無い


def test_h5_and_h6_on_next_step():
    records = [
        _record("pure_vector", _Q01, ["GMS-303", "GMS-402", "GMS-403"]),  # 違反3件
        _record("vector_metadata", _Q01, ["GMS-303", "GMS-402", "GMS-403"]),
        _record("pure_graph", _Q01, ["GMS-401"]),  # 違反0件
        _record("hybrid", _Q01, ["GMS-401", "GMS-303"]),  # 違反1件
    ]
    verdicts = {v.hypothesis[:2]: v for v in evaluate_hypotheses(records, [], {"q01": _Q01}, {"q01": True})}
    assert verdicts["H5"].label == "支持"
    assert "pure_vector 3、pure_graph 0、hybrid 1" in verdicts["H5"].detail
    assert verdicts["H6"].label == "支持"
    assert verdicts["H0"].label == "不支持"  # pure_graph の Recall@10 が 0.5


def test_h7_needs_every_generation_and_counts_unverified():
    def generation(condition: str, unverified: list[str]) -> GenerationRecord:
        return GenerationRecord(
            run_id="t",
            condition=condition,
            question_id="q01",
            mode="next_step",
            success=True,
            unverified_codes=unverified,
            score=score_generation(_Q01, ["GMS-303"], ["GMS-303"]),
            started_at="t",
        )

    complete = [generation(condition, []) for condition in CONDITIONS]
    verdict = evaluate_hypotheses([], complete, {"q01": _Q01}, {})[-1]
    assert verdict.label == "支持"
    assert "1/1" in verdict.detail
    broken = [generation(condition, ["GMS-999"] if condition == "hybrid" else []) for condition in CONDITIONS]
    assert evaluate_hypotheses([], broken, {"q01": _Q01}, {})[-1].label == "一部支持"
    assert evaluate_hypotheses([], complete[:3], {"q01": _Q01}, {})[-1].label == "判定不能"
