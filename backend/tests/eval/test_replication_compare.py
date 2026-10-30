"""再現実行の突き合わせ（eval.replication_compare）の純関数のテスト（DB・LLM 無し）。"""

import pytest

from eval import replication_compare as rc
from eval.retrieval_metrics import GenerationRecord, GenerationScore, RankedEntry, RetrievalRecord, RetrievalScore


def _record(question_id: str, condition: str, ranked: list[tuple[str, float]], recall: float = 1.0) -> RetrievalRecord:
    return RetrievalRecord(
        run_id="r",
        condition=condition,
        question_id=question_id,
        mode="next_step",
        ranked=[RankedEntry(code=code, title=code, score=score, evidence=[f"{code} {score:.3f}"]) for code, score in ranked],
        sql_queries=1,
        scores={"5": RetrievalScore(k=5, returned=len(ranked), recall=recall)},
        started_at="t",
    )


def test_identical_records_are_identical_in_every_column():
    base = [_record("q01", "pure_vector", [("A", 0.9), ("B", 0.8)])]
    rows = rc.compare_rankings(base, [record.model_copy(update={"run_id": "other"}) for record in base])
    assert rows[0]["codes_equal"] and rows[0]["metrics_equal"] and rows[0]["evidence_equal"] and rows[0]["queries_equal"]
    assert rows[0]["max_score_diff"] == 0
    assert rc.all_rows_identical(rows)


def test_rows_that_return_nothing_on_both_sides_count_as_identical():
    rows = rc.compare_rankings([_record("q11", "pure_graph", [])], [_record("q11", "pure_graph", [])])
    assert rows[0]["max_score_diff"] is None
    assert rc.all_rows_identical(rows)


def test_score_drift_keeps_the_ranking_but_breaks_full_identity():
    base = [_record("q01", "pure_vector", [("A", 0.9), ("B", 0.8)])]
    other = [_record("q01", "pure_vector", [("A", 0.9001), ("B", 0.8)])]
    rows = rc.compare_rankings(base, other)
    assert rows[0]["codes_equal"]
    assert rows[0]["max_score_diff"] == pytest.approx(0.0001)
    assert not rc.all_rows_identical(rows)


def test_swapped_order_and_missing_rows_are_reported():
    base = [_record("q01", "hybrid", [("A", 0.5), ("B", 0.4)]), _record("q02", "hybrid", [("C", 0.5)])]
    other = [_record("q01", "hybrid", [("B", 0.5), ("A", 0.4)], recall=0.5)]
    rows = rc.compare_rankings(base, other)
    by_q = {row["question_id"]: row for row in rows}
    assert not by_q["q01"]["codes_equal"] and not by_q["q01"]["metrics_equal"]
    assert by_q["q02"]["present"] is False
    summary = rc.ranking_summary(rows)
    assert summary["hybrid"] == {
        "rows": 2,
        "present": 1,
        "codes_equal": 0,
        "metrics_equal": 0,
        "evidence_equal": 0,
        "queries_equal": 1,
        "max_score_diff": pytest.approx(0.1),
    }
    assert summary["pure_vector"]["rows"] == 0


def test_embedding_stats_and_classification():
    same = rc.embedding_stats({"a": "[1,0]", "b": "[0,1]"}, {"a": "[1,0]", "b": "[0,1]"})
    assert (same["bitwise_equal"], same["max_abs_diff"], same["min_cosine"], same["missing"]) == (2, 0, 1.0, [])
    assert rc.classify_embeddings([same]) == "ビット一致"
    near = rc.embedding_stats({"a": "[1,0]"}, {"a": "[0.99999999,0.0001]"})
    assert near["bitwise_equal"] == 0 and near["min_cosine"] >= rc.NEAR_IDENTICAL_COSINE
    assert rc.classify_embeddings([same, near]) == "ほぼ一致"
    far = rc.embedding_stats({"a": "[1,0]", "b": "[0,1]"}, {"a": "[0.6,0.8]"})
    assert far["missing"] == ["b"]
    assert rc.classify_embeddings([far]) == "それ以外"


def test_provenance_rows_require_commit_clean_and_matching_tree():
    tree = {"files": 3, "sha256": "x"}
    good = {"command": "retrieve", "git_sha": "c", "git_status_clean": True, "source_tree": {"files": 3, "sha256": "x"}}
    assert rc.provenance_verified(rc.provenance_rows([good], tree, "c"))
    assert not rc.provenance_verified(rc.provenance_rows([good], tree, "other"))
    assert not rc.provenance_verified(rc.provenance_rows([{**good, "source_tree": {"files": 3, "sha256": "y"}}], tree, "c"))
    # 元の実行のように指紋が無いセッションは「確かめられない」
    legacy = rc.provenance_rows([{"command": "retrieve", "git_sha": "c"}], tree, "c")
    assert legacy[0]["source_matches"] is None and not rc.provenance_verified(legacy)
    assert not rc.provenance_verified([])


def test_main_session_skips_aborted_runs_and_the_smoke_test():
    sessions = [
        {"command": "retrieve", "aborted": True, "run_id": "1"},
        {"command": "retrieve", "aborted": False, "run_id": "2"},
        {"command": "generate", "aborted": False, "output": "smoke.jsonl", "run_id": "3"},
        {"command": "generate", "aborted": False, "output": "r.jsonl", "run_id": "4"},
    ]
    assert rc.main_session(sessions, "retrieve")["run_id"] == "2"
    assert rc.main_session(sessions, "generate", "r.jsonl")["run_id"] == "4"


def _generation(question_id: str, condition: str, codes: list[str]) -> GenerationRecord:
    return GenerationRecord(
        run_id="g",
        condition=condition,
        question_id=question_id,
        mode="next_step",
        success=True,
        score=GenerationScore(scored_codes=codes),
        started_at="t",
    )


def test_cited_agreement_compares_sets_per_question_and_condition():
    base = [_generation("q01", "pure_vector", ["A", "B"]), _generation("q02", "pure_vector", ["C"])]
    other = [_generation("q01", "pure_vector", ["B", "A"]), _generation("q02", "pure_vector", ["D"])]
    agreement = rc.cited_agreement(base, other)
    assert (agreement["compared"], agreement["equal"]) == (2, 1)
    assert agreement["differ"] == [{"question_id": "q02", "condition": "pure_vector", "base": ["C"], "other": ["D"]}]
