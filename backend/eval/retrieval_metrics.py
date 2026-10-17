"""検索方式比較の採点・集計・仮説判定の純関数群（prereg_retrieval_seed.md §5・§6）。

I/O を持たないので DB・LLM 無しでテストできる。式を変えるときは事前登録との対応を崩さないこと。
「差あり」の判定は昨日の事前登録と同じ規則なので eval.metrics.compare_rates を使う。
"""

import math
import statistics
from collections.abc import Collection, Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from agent.grounding import normalize_codes
from eval.metrics import GoldenCase, RateComparison, Verdict, VerdictLabel, compare_rates

__all__ = [
    "CONDITIONS",
    "DIRECTIONAL_MODES",
    "GenerationRecord",
    "GenerationScore",
    "RetrievalRecord",
    "RetrievalScore",
    "count_label",
    "dcg",
    "evaluate_hypotheses",
    "ndcg_at_k",
    "prerequisite_closure",
    "prerequisite_violations",
    "random_expected_ndcg",
    "random_expected_recall",
    "recall_at_k",
    "score_generation",
    "score_retrieval",
]

RetrievalCondition = Literal["pure_vector", "vector_metadata", "pure_graph", "hybrid"]
CONDITIONS: tuple[RetrievalCondition, ...] = ("pure_vector", "vector_metadata", "pure_graph", "hybrid")
PRIMARY_K = 5
SECONDARY_K = 10
DIRECTIONAL_MODES = ("next_step", "prereq")
NEXT_STEP_MODE = "next_step"
TOPIC_MODE = "topic"

# §6 の閾値（率の「差あり」は eval.metrics の RATE_DELTA_THRESHOLD / SIGN_MARGIN_THRESHOLD）
COUNT_DIFFERENCE_THRESHOLD = 2
COST_RATIO_THRESHOLD = 1.5
H3_COMPETITIVE_MARGIN = 0.10


# --- 1問の採点（§5） -------------------------------------------------------------


def recall_at_k(ranked: Sequence[str], expected: Collection[str], k: int) -> float | None:
    """|R_K ∩ E| / |E|。E が空なら未定義。"""
    if not expected:
        return None
    top = set(ranked[:k])
    return len(top & set(expected)) / len(set(expected))


def dcg(gains: Sequence[float]) -> float:
    return math.fsum(gain / math.log2(position + 1) for position, gain in enumerate(gains, start=1))


def ndcg_at_k(ranked: Sequence[str], expected: Collection[str], k: int) -> float | None:
    """2値の関連度（E に入れば1）。IDCG は min(|E|, K) 件がすべて関連のときの DCG。"""
    expected_set = set(expected)
    if not expected_set:
        return None
    gains = [1.0 if code in expected_set else 0.0 for code in ranked[:k]]
    ideal = dcg([1.0] * min(len(expected_set), k))
    return dcg(gains) / ideal


def prerequisite_closure(prerequisites: Mapping[str, Sequence[str]], code: str) -> set[str]:
    """code の前提科目の推移閉包（code 自身は含まない）。循環があっても止まる。"""
    seen: set[str] = set()
    stack = list(prerequisites.get(code, ()))
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(prerequisites.get(current, ()))
    seen.discard(code)
    return seen


def completed_set(prerequisites: Mapping[str, Sequence[str]], anchor: str) -> set[str]:
    """履修済みとみなす集合 D = {a} ∪ a の前提科目の推移閉包。"""
    return {anchor} | prerequisite_closure(prerequisites, anchor)


def prerequisite_violations(
    ranked: Sequence[str], prerequisites: Mapping[str, Sequence[str]], anchor: str, k: int
) -> list[str]:
    """R_K のうち、直接の前提科目が1つでも D に無い科目（推薦順）。"""
    done = completed_set(prerequisites, anchor)
    return [
        code
        for code in ranked[:k]
        if any(prereq not in done for prereq in prerequisites.get(code, ()))
    ]


def random_expected_recall(k: int, candidates: int) -> float:
    """ランダムな順位での Recall@K の期待値 = min(K, N) / N。"""
    return min(k, candidates) / candidates


def random_expected_ndcg(k: int, relevant: int, candidates: int) -> float:
    """ランダムな順位での NDCG@K の期待値 = (|E|/N) Σ_{i≤min(K,N)} 1/log2(i+1) / IDCG@K。"""
    if relevant == 0:
        raise ValueError("関連科目が0件の問いには定義されません")
    expected_dcg = (relevant / candidates) * dcg([1.0] * min(k, candidates))
    return expected_dcg / dcg([1.0] * min(relevant, k))


class RetrievalScore(BaseModel):
    k: int
    returned: int
    recall: float | None = None
    ndcg: float | None = None
    forbidden_hits: list[str] = Field(default_factory=list)
    violations: list[str] | None = None  # next_step のみ
    violation_rate: float | None = None  # next_step で R_K が空でないときのみ
    completed_hits: list[str] | None = None  # next_step のみ（副次）
    within_alternatives: bool | None = None  # unclear のみ（記述）


def score_retrieval(
    case: GoldenCase,
    ranked: Sequence[str],
    prerequisites: Mapping[str, Sequence[str]],
    k: int,
) -> RetrievalScore:
    """起点を除いた順位リスト ranked を §5 の式で採点する。"""
    top = list(ranked[:k])
    if not case.is_search:
        return RetrievalScore(
            k=k, returned=len(top), within_alternatives=set(top) <= set(case.alternatives)
        )
    forbidden = set(case.forbidden_codes)
    score = RetrievalScore(
        k=k,
        returned=len(top),
        recall=recall_at_k(top, case.expected_codes, k),
        ndcg=ndcg_at_k(top, case.expected_codes, k),
        forbidden_hits=[code for code in top if code in forbidden],
    )
    if case.mode == NEXT_STEP_MODE and case.anchor_code:
        violations = prerequisite_violations(top, prerequisites, case.anchor_code, k)
        done = completed_set(prerequisites, case.anchor_code) - {case.anchor_code}
        score = score.model_copy(
            update={
                "violations": violations,
                "violation_rate": len(violations) / len(top) if top else None,
                "completed_hits": [code for code in top if code in done],
            }
        )
    return score


class GenerationScore(BaseModel):
    scored_codes: list[str] = Field(default_factory=list)  # C'（正規化後、起点を除く）
    outside_candidates: list[str] = Field(default_factory=list)  # C' のうち LLM に渡していないコード
    recall: float | None = None
    precision: float | None = None
    forbidden_hits: list[str] = Field(default_factory=list)


def score_generation(
    case: GoldenCase, cited_codes: Sequence[str], candidate_codes: Collection[str]
) -> GenerationScore:
    cited = normalize_codes(cited_codes)
    scored = [code for code in cited if code != case.anchor_code]
    expected = set(case.expected_codes)
    hits = [code for code in scored if code in expected]
    return GenerationScore(
        scored_codes=scored,
        outside_candidates=[code for code in scored if code not in set(candidate_codes)],
        recall=len(hits) / len(expected) if expected else None,
        precision=len(hits) / len(scored) if scored else None,
        forbidden_hits=[code for code in scored if code in set(case.forbidden_codes)],
    )


# --- 記録 ------------------------------------------------------------------------


class RankedEntry(BaseModel):
    code: str
    title: str
    score: float
    evidence: list[str] = Field(default_factory=list)


class RetrievalRecord(BaseModel):
    kind: Literal["retrieval"] = "retrieval"
    run_id: str
    condition: RetrievalCondition
    question_id: str
    mode: str
    anchor_code: str | None = None
    ranked: list[RankedEntry] = Field(default_factory=list)  # 起点を除いた上位10件
    raw_returned: int = 0  # 起点を除く前に retriever が返した件数
    anchor_removed: bool = False
    repeats: int = 0
    identical_across_repeats: bool = True
    latency_ms_runs: list[float] = Field(default_factory=list)
    latency_ms_median: float = 0.0
    sql_queries: int = 0
    cypher_queries: int = 0
    scores: dict[str, RetrievalScore] = Field(default_factory=dict)  # "5" / "10"
    started_at: str

    @property
    def db_queries(self) -> int:
        return self.sql_queries + self.cypher_queries

    @property
    def codes(self) -> list[str]:
        return [entry.code for entry in self.ranked]


class GenerationRecord(BaseModel):
    kind: Literal["generation"] = "generation"
    run_id: str
    condition: RetrievalCondition
    question_id: str
    mode: str
    model: str | None = None
    model_versions: list[str] = Field(default_factory=list)
    success: bool
    error: str | None = None
    attempts: int = 1
    retry_reasons: list[str] = Field(default_factory=list)
    candidate_codes: list[str] = Field(default_factory=list)  # LLM に渡した上位5件
    answer: str = ""
    cited_codes: list[str] = Field(default_factory=list)
    unverified_codes: list[str] = Field(default_factory=list)
    sources_count: int = 0
    score: GenerationScore | None = None
    llm_requests: int = 0
    llm_requests_all_attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thoughts_tokens: int = 0
    latency_ms: int = 0
    started_at: str


# --- 判定（§6） ------------------------------------------------------------------


def count_label(a_total: int, b_total: int) -> str:
    return "差あり" if abs(a_total - b_total) >= COUNT_DIFFERENCE_THRESHOLD else "差なし"


def cost_label(a: float | None, b: float | None) -> str:
    if a is None or b is None or a <= 0 or b <= 0:
        return "比較不能"
    ratio = a / b
    if ratio >= COST_RATIO_THRESHOLD or ratio <= 1 / COST_RATIO_THRESHOLD:
        return "差あり"
    return "差なし"


def _metric_map(
    records: Sequence[RetrievalRecord],
    condition: str,
    question_ids: Collection[str],
    metric: Literal["recall", "ndcg"],
    k: int = PRIMARY_K,
) -> dict[str, float | None]:
    return {
        record.question_id: getattr(record.scores[str(k)], metric)
        for record in records
        if record.condition == condition and record.question_id in question_ids
    }


def _mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return statistics.fmean(present) if present else None


def _better(comparison: RateComparison) -> bool:
    return comparison.label == "差あり" and (comparison.delta_mean or 0) > 0


def _covers(records: Sequence[RetrievalRecord], conditions: Sequence[str], ids: Collection[str]) -> bool:
    have = {(record.condition, record.question_id) for record in records}
    return all((condition, qid) in have for condition in conditions for qid in ids)


def _directional_verdict(
    name: str, records: Sequence[RetrievalRecord], challenger: str, ids: list[str]
) -> Verdict:
    if not _covers(records, [challenger, "pure_vector"], ids):
        return Verdict(hypothesis=name, label="判定不能", detail="必要な検索記録が欠けています")
    parts = []
    details = []
    for metric in ("recall", "ndcg"):
        comparison = compare_rates(
            _metric_map(records, challenger, ids, metric), _metric_map(records, "pure_vector", ids, metric)
        )
        parts.append(_better(comparison))
        details.append(f"{metric}@5 {_describe_comparison(comparison)}")
    return Verdict(hypothesis=name, label=_combine(parts), detail=f"{challenger} − pure_vector: " + "、".join(details))


def _describe_comparison(comparison: RateComparison) -> str:
    if comparison.delta_mean is None:
        return f"（{comparison.label}）"
    return f"差 {comparison.delta_mean:+.2f}・符号 {comparison.sign_margin:+d}（{comparison.label}）"


def _combine(parts: Sequence[bool]) -> VerdictLabel:
    if all(parts):
        return "支持"
    if any(parts):
        return "一部支持"
    return "不支持"


def evaluate_hypotheses(
    retrieval: Sequence[RetrievalRecord],
    generation: Sequence[GenerationRecord],
    cases: Mapping[str, GoldenCase],
    spec_matches: Mapping[str, bool],
) -> list[Verdict]:
    """§6 の H0〜H7 を機械的に判定する。spec_matches は質問 ID → spec の mode と anchor が golden と一致したか。"""
    search_ids = sorted(qid for qid, case in cases.items() if case.is_search)
    directional = [qid for qid in search_ids if cases[qid].mode in DIRECTIONAL_MODES]
    topic = [qid for qid in search_ids if cases[qid].mode == TOPIC_MODE]
    next_step = [qid for qid in search_ids if cases[qid].mode == NEXT_STEP_MODE]
    verdicts = [_h0(retrieval, search_ids, spec_matches)]
    verdicts.append(_directional_verdict("H1 向きのある問いで pure_graph > pure_vector", retrieval, "pure_graph", directional))
    verdicts.append(_directional_verdict("H2 向きのある問いで hybrid > pure_vector", retrieval, "hybrid", directional))
    verdicts.append(_h3(retrieval, topic))
    verdicts.append(_h4(retrieval, search_ids))
    verdicts.append(_h5(retrieval, next_step))
    verdicts.append(_h6(retrieval, search_ids))
    verdicts.append(_h7(generation, search_ids))
    return verdicts


def _h0(records: Sequence[RetrievalRecord], ids: list[str], spec_matches: Mapping[str, bool]) -> Verdict:
    name = "H0 妥当性（spec が golden と一致し、pure_graph の Recall@10 が1）"
    if not _covers(records, ["pure_graph"], ids):
        return Verdict(hypothesis=name, label="判定不能", detail="pure_graph の記録が欠けています")
    mismatched = [qid for qid in ids if not spec_matches.get(qid, False)]
    recalls = _metric_map(records, "pure_graph", ids, "recall", SECONDARY_K)
    short = [qid for qid in ids if recalls.get(qid) != 1.0]
    ok = not mismatched and not short
    detail = f"spec 不一致 {mismatched or 'なし'}、Recall@10<1 {short or 'なし'}"
    return Verdict(hypothesis=name, label="支持" if ok else "不支持", detail=detail)


def _h3(records: Sequence[RetrievalRecord], ids: list[str]) -> Verdict:
    name = "H3 トピックの問いで pure_vector も戦える（NDCG@5 が pure_graph − 0.10 以上）"
    if not _covers(records, ["pure_vector", "pure_graph"], ids):
        return Verdict(hypothesis=name, label="判定不能", detail="必要な検索記録が欠けています")
    vector = _mean(list(_metric_map(records, "pure_vector", ids, "ndcg").values()))
    graph = _mean(list(_metric_map(records, "pure_graph", ids, "ndcg").values()))
    if vector is None or graph is None:
        return Verdict(hypothesis=name, label="判定不能", detail="NDCG が定義されません")
    ok = vector >= graph - H3_COMPETITIVE_MARGIN
    return Verdict(
        hypothesis=name,
        label="支持" if ok else "不支持",
        detail=f"pure_vector {vector:.2f}、pure_graph {graph:.2f}（{len(ids)}問）",
    )


def _h4(records: Sequence[RetrievalRecord], ids: list[str]) -> Verdict:
    name = "H4 hybrid は pure_vector・pure_graph のどちらにも NDCG@5 で「差あり」で劣らない"
    if not _covers(records, ["hybrid", "pure_vector", "pure_graph"], ids):
        return Verdict(hypothesis=name, label="判定不能", detail="必要な検索記録が欠けています")
    hybrid = _metric_map(records, "hybrid", ids, "ndcg")
    worse = []
    details = []
    for other in ("pure_vector", "pure_graph"):
        comparison = compare_rates(hybrid, _metric_map(records, other, ids, "ndcg"))
        details.append(f"対 {other} {_describe_comparison(comparison)}")
        if comparison.label == "差あり" and (comparison.delta_mean or 0) < 0:
            worse.append(other)
    label: VerdictLabel = "不支持" if worse else "支持"
    return Verdict(hypothesis=name, label=label, detail="、".join(details))


def _violation_total(records: Sequence[RetrievalRecord], condition: str, ids: Collection[str]) -> int:
    return sum(
        len(record.scores[str(PRIMARY_K)].violations or [])
        for record in records
        if record.condition == condition and record.question_id in ids
    )


def _h5(records: Sequence[RetrievalRecord], ids: list[str]) -> Verdict:
    name = "H5 next_step の前提違反@5 の合計で pure_graph・hybrid が pure_vector より2件以上少ない"
    if not _covers(records, ["pure_vector", "pure_graph", "hybrid"], ids):
        return Verdict(hypothesis=name, label="判定不能", detail="必要な検索記録が欠けています")
    vector = _violation_total(records, "pure_vector", ids)
    graph = _violation_total(records, "pure_graph", ids)
    hybrid = _violation_total(records, "hybrid", ids)
    parts = [graph <= vector - COUNT_DIFFERENCE_THRESHOLD, hybrid <= vector - COUNT_DIFFERENCE_THRESHOLD]
    return Verdict(
        hypothesis=name,
        label=_combine(parts),
        detail=f"違反の合計: pure_vector {vector}、pure_graph {graph}、hybrid {hybrid}（{len(ids)}問）",
    )


def _h6(records: Sequence[RetrievalRecord], ids: list[str]) -> Verdict:
    name = "H6 制約の無い検索系10問で vector_metadata の順位が pure_vector と同じ"
    if not _covers(records, ["pure_vector", "vector_metadata"], ids):
        return Verdict(hypothesis=name, label="判定不能", detail="必要な検索記録が欠けています")
    by_key = {(record.condition, record.question_id): record.codes for record in records}
    differ = [qid for qid in ids if by_key[("vector_metadata", qid)] != by_key[("pure_vector", qid)]]
    return Verdict(
        hypothesis=name,
        label="不支持" if differ else "支持",
        detail=f"順位が違う質問: {differ or 'なし'}",
    )


def _h7(records: Sequence[GenerationRecord], ids: list[str]) -> Verdict:
    name = "H7 生成で DB に無いコードも候補外のコードも引用しない"
    ok = [record for record in records if record.success and record.score is not None]
    expected_runs = len(ids) * len(CONDITIONS)
    if len(ok) < expected_runs:
        return Verdict(
            hypothesis=name, label="判定不能", detail=f"成功した生成が {len(ok)}/{expected_runs} 回"
        )
    unverified = sum(len(record.unverified_codes) for record in ok)
    outside = sum(len(record.score.outside_candidates) for record in ok if record.score)
    by_key = {(record.condition, record.question_id): set(record.score.scored_codes) for record in ok if record.score}
    agree = sum(
        1 for qid in ids if by_key.get(("pure_vector", qid)) == by_key.get(("vector_metadata", qid))
    )
    return Verdict(
        hypothesis=name,
        label=_combine([unverified == 0, outside == 0]),
        detail=(
            f"未検証コードの合計 {unverified}、候補外の引用の合計 {outside}（{len(ok)} 回）。"
            f"同じ候補を渡した pure_vector と vector_metadata で引用集合が一致した質問 {agree}/{len(ids)}"
        ),
    )
