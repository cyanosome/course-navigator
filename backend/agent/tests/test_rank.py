"""Evidence 生成のテスト（設計書 実験3-2 §4.4 / §8.3 の A5 の純関数部分）。

DB も LLM も不要。層A（Cypher）の戻り値を手で組んで build_candidate_set に流し、
根拠文と traversed_edges が設計書の生成例と逐語一致することを見る。
"""

import pytest

from agent.rank import build_candidate_set
from agent.schemas import Candidate, SearchIntent

# §8.2 の q01 相当（アンカー GMS-301 の後続を逆方向に辿ったケース）
NEXT_STEP_INTENT = SearchIntent(
    mode="next_step",
    anchor_code="GMS-301",
    anchor_title="データサイエンス入門",
    anchor_status="exact",
    raw_question="データサイエンス入門の次に取れる科目は?",
    matched_rule="keyword:次 / title:データサイエンス入門",
)
NEXT_STEP_CANDIDATES = [
    Candidate(
        code="GMS-303",
        title="機械学習",
        hops=1,
        path_codes=["GMS-301", "GMS-303"],
        reason="prerequisite_of",
    ),
    Candidate(
        code="GMS-401",
        title="データサイエンス実習",
        hops=1,
        path_codes=["GMS-301", "GMS-401"],
        reason="prerequisite_of",
    ),
]

# q05 相当（アンカー GMS-303 の前提を順方向に辿ったケース。path_codes は依存側→前提側）
PREREQ_INTENT = SearchIntent(
    mode="prereq",
    anchor_code="GMS-303",
    anchor_title="機械学習",
    anchor_status="exact",
    raw_question="機械学習を取るのに必要な前提科目は?",
    matched_rule="keyword:前提 / title:機械学習",
)
PREREQ_CANDIDATES = [
    Candidate(
        code="GMS-101",
        title="情報リテラシー",
        hops=3,
        path_codes=["GMS-303", "GMS-301", "GMS-201", "GMS-101"],
        reason="requires",
    ),
    Candidate(
        code="GMS-301",
        title="データサイエンス入門",
        hops=1,
        path_codes=["GMS-303", "GMS-301"],
        reason="requires",
    ),
]

# §4.4 の生成例2つめ（アンカー GMS-302 とトピックを共有するケース）
TOPIC_INTENT = SearchIntent(
    mode="topic",
    anchor_code="GMS-302",
    anchor_title="データベース",
    anchor_status="exact",
    raw_question="データベースに近い分野の科目は?",
    matched_rule="keyword:近い / title:データベース",
)
TOPIC_CANDIDATES = [
    Candidate(
        code="GMS-402",
        title="メディア情報論",
        hops=1,
        shared_topics=["データベース"],
        reason="shares_topic",
    ),
    Candidate(
        code="GMS-201",
        title="プログラミング入門",
        hops=1,
        # collect の順序に依存しないことを見るため、あえて昇順でない並びを渡す
        shared_topics=["プログラミング", "データベース"],
        reason="shares_topic",
    ),
]

ALL_CASES = [
    (NEXT_STEP_INTENT, NEXT_STEP_CANDIDATES),
    (PREREQ_INTENT, PREREQ_CANDIDATES),
    (TOPIC_INTENT, TOPIC_CANDIDATES),
]
ALL_IDS = ["next_step", "prereq", "topic"]


def test_prereq_path_evidence_matches_design_example() -> None:
    """§4.4 の生成例1と逐語一致すること。"""
    result = build_candidate_set(NEXT_STEP_INTENT, NEXT_STEP_CANDIDATES)

    evidence = result.candidates[0].evidence[0]
    assert evidence.kind == "prereq_path"
    assert evidence.text == (
        "GMS-303 機械学習 は GMS-301 データサイエンス入門 と前提関係で 1 段"
        "つながっています（GMS-301 → GMS-303）"
    )
    assert evidence.edge_refs == ["GMS-301 <-REQUIRES_PREREQUISITE- GMS-303"]
    # §8.2 の trace 例と同じ2本になること
    assert result.traversed_edges == [
        "GMS-301 <-REQUIRES_PREREQUISITE- GMS-303",
        "GMS-301 <-REQUIRES_PREREQUISITE- GMS-401",
    ]


def test_topic_share_evidence_matches_design_example() -> None:
    """§4.4 の生成例2と逐語一致すること。"""
    result = build_candidate_set(TOPIC_INTENT, TOPIC_CANDIDATES)

    evidence = result.candidates[0].evidence[0]
    assert evidence.kind == "topic_share"
    assert evidence.text == (
        "GMS-402 メディア情報論 は GMS-302 データベース とトピック「データベース」を共有します"
    )
    assert evidence.edge_refs == [
        "GMS-302 -COVERS_TOPIC-> データベース <-COVERS_TOPIC- GMS-402"
    ]


def test_shared_topics_are_sorted() -> None:
    """shared_topics はソートしてから使う（Cypher の collect 順序に依存させない）。"""
    result = build_candidate_set(TOPIC_INTENT, TOPIC_CANDIDATES)

    candidate = result.candidates[1]
    assert candidate.shared_topics == ["データベース", "プログラミング"]
    assert candidate.evidence[0].text == (
        "GMS-201 プログラミング入門 は GMS-302 データベース と"
        "トピック「データベース、プログラミング」を共有します"
    )
    assert candidate.evidence[0].edge_refs == [
        "GMS-302 -COVERS_TOPIC-> データベース <-COVERS_TOPIC- GMS-201",
        "GMS-302 -COVERS_TOPIC-> プログラミング <-COVERS_TOPIC- GMS-201",
    ]


def test_prereq_path_arrow_points_from_prerequisite_to_dependent() -> None:
    """prereq は path_codes が [依存側→前提側] なので、矢印は反転して提示する。"""
    result = build_candidate_set(PREREQ_INTENT, PREREQ_CANDIDATES)

    one_hop = result.candidates[1]
    assert one_hop.evidence[0].text == (
        "GMS-301 データサイエンス入門 は GMS-303 機械学習 と前提関係で 1 段"
        "つながっています（GMS-301 → GMS-303）"
    )
    three_hops = result.candidates[0]
    assert "（GMS-101 → GMS-201 → GMS-301 → GMS-303）" in three_hops.evidence[0].text
    # エッジの向きは next_step と同じ表記（B が A を前提として要求する）になる
    assert three_hops.evidence[0].edge_refs == [
        "GMS-301 <-REQUIRES_PREREQUISITE- GMS-303",
        "GMS-201 <-REQUIRES_PREREQUISITE- GMS-301",
        "GMS-101 <-REQUIRES_PREREQUISITE- GMS-201",
    ]


def test_traversed_edges_are_deduplicated() -> None:
    """複数候補が同じエッジを通っても traversed_edges は先頭から重複排除される。"""
    result = build_candidate_set(PREREQ_INTENT, PREREQ_CANDIDATES)

    assert result.traversed_edges == [
        "GMS-301 <-REQUIRES_PREREQUISITE- GMS-303",
        "GMS-201 <-REQUIRES_PREREQUISITE- GMS-301",
        "GMS-101 <-REQUIRES_PREREQUISITE- GMS-201",
    ]


@pytest.mark.parametrize(("intent", "candidates"), ALL_CASES, ids=ALL_IDS)
def test_every_candidate_has_evidence(
    intent: SearchIntent, candidates: list[Candidate]
) -> None:
    """不変条件: すべての候補に Evidence が最低1件つく。"""
    result = build_candidate_set(intent, candidates)

    assert len(result.candidates) == len(candidates)
    assert all(len(c.evidence) >= 1 for c in result.candidates)


@pytest.mark.parametrize(("intent", "candidates"), ALL_CASES, ids=ALL_IDS)
def test_edge_refs_are_subset_of_traversed_edges(
    intent: SearchIntent, candidates: list[Candidate]
) -> None:
    """不変条件: 全 edge_refs が traversed_edges の要素（根拠文とエッジの一対一照合）。"""
    result = build_candidate_set(intent, candidates)

    traversed = set(result.traversed_edges)
    assert traversed
    for candidate in result.candidates:
        for evidence in candidate.evidence:
            assert evidence.edge_refs
            assert set(evidence.edge_refs) <= traversed


@pytest.mark.parametrize(("intent", "candidates"), ALL_CASES, ids=ALL_IDS)
def test_output_is_deterministic(
    intent: SearchIntent, candidates: list[Candidate]
) -> None:
    """同一入力を2回流して完全一致すること（A4 の再現性の土台）。"""
    assert build_candidate_set(intent, candidates) == build_candidate_set(
        intent, candidates
    )


@pytest.mark.parametrize(("intent", "candidates"), ALL_CASES, ids=ALL_IDS)
def test_candidate_order_is_preserved(
    intent: SearchIntent, candidates: list[Candidate]
) -> None:
    """並び順は層A（Cypher）の責務なので、ここでは入力順をそのまま保つ。"""
    result = build_candidate_set(intent, candidates)

    assert [c.code for c in result.candidates] == [c.code for c in candidates]


def test_unclear_intent_yields_no_candidates() -> None:
    """unclear は respond_unclear へ流れる。ここに来ても候補を作らない。"""
    intent = SearchIntent(
        mode="unclear",
        unclear_kind="no_mode",
        raw_question="何かおすすめの授業ある?",
        matched_rule="unclear:no_mode",
    )

    result = build_candidate_set(intent, NEXT_STEP_CANDIDATES)

    assert result.candidates == []
    assert result.traversed_edges == []
    assert result.notes
