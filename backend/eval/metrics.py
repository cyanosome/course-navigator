"""ノード設計比較の採点・集計・仮説判定を行う純関数群（prereg_node_compare.md §4〜§7）。

I/O を持たないので DB・LLM 無しでテストできる。式を変えるときは事前登録との対応を崩さないこと。
"""

import re
import statistics
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from agent.grounding import normalize_codes

__all__ = [
    "CONDITIONS",
    "ConditionSummary",
    "GoldenCase",
    "QuestionScore",
    "RateComparison",
    "RunRecord",
    "ToolCallSummary",
    "Verdict",
    "compare_rates",
    "evaluate_hypotheses",
    "extract_answer_codes",
    "ratio",
    "score_question",
    "summarize_condition",
]

Condition = Literal["static", "static_llm", "mcp_free", "mcp_grounded"]
CONDITIONS: tuple[Condition, ...] = ("static", "static_llm", "mcp_free", "mcp_grounded")
UNCLEAR_MODE = "unclear"

# 回答文から科目コードを拾う形（シードは "GMS-101"）。NFKC で全角を半角に寄せてから当てる。
_ANSWER_CODE_PATTERN = re.compile(r"[A-Z]{2,5}-\d{3}")
_MS_PER_SECOND = 1000

# §7「意味のある差」の基準
RATE_DELTA_THRESHOLD = 0.10
SIGN_MARGIN_THRESHOLD = 3
# §6 仮説固有の閾値
H2_LATENCY_RATIO = 10.0
H2_LLM_REQUEST_RATIO = 5.0
H3_MIN_MATCHES = 9


class GoldenCase(BaseModel):
    """tests/golden/questions.json の1問。採点に使わない列（expected_order など）は読み捨てる。"""

    id: str
    question: str
    mode: str
    anchor_code: str | None = None
    alternatives: list[str] = Field(default_factory=list)
    expected_codes: list[str] = Field(default_factory=list)
    forbidden_codes: list[str] = Field(default_factory=list)

    @property
    def is_search(self) -> bool:
        return self.mode != UNCLEAR_MODE


class QuestionScore(BaseModel):
    """1実行の採点結果（§4 の質問ごとの指標のうち cited_codes から決まるもの）。"""

    scored_codes: list[str] = Field(default_factory=list)  # C'（正規化後、起点科目を除く）
    recall: float | None = None  # 検索系のみ
    precision: float | None = None  # 検索系かつ C' が空でないときのみ
    forbidden_hits: list[str] = Field(default_factory=list)
    unclear_pass: bool | None = None  # unclear のみ
    answer_codes: list[str] = Field(default_factory=list)  # 回答文に現れたコード
    uncited_answer_codes: list[str] = Field(default_factory=list)  # 回答文にあるが C に無い（起点を除く）


class ToolCallSummary(BaseModel):
    name: str
    args: dict[str, object] = Field(default_factory=dict)


class RunRecord(BaseModel):
    """JSONL の1行（1条件×1質問の1回の実行）。"""

    run_id: str
    condition: Condition
    question_id: str
    mode: str
    model: str | None = None
    model_versions: list[str] = Field(default_factory=list)  # 応答が返した model_version
    success: bool
    error: str | None = None
    attempts: int = 1
    retry_reasons: list[str] = Field(default_factory=list)
    route: str | None = None
    node_sequence: list[str] = Field(default_factory=list)
    answer: str = ""
    cited_codes: list[str] = Field(default_factory=list)  # 正規化前（条件が返したまま）
    score: QuestionScore | None = None  # 失敗した実行では None
    unverified_codes: list[str] = Field(default_factory=list)  # 事後検証（§2 共通事項）
    pipeline_unverified_codes: list[str] | None = None  # M2 の attach_sources の結果
    sources_count: int = 0  # 事後検証で DB の行が見つかったコードの数
    llm_requests: int = 0  # 最後の試行の分
    llm_requests_all_attempts: int = 0  # やり直した試行も含む（予算の消費量）
    input_tokens: int = 0
    output_tokens: int = 0
    thoughts_tokens: int = 0
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)
    tool_call_count: int = 0  # set_model_response を除く
    latency_ms: int = 0
    pipeline_latency_ms: int | None = None  # M2 の run_mcp_grounded が返した値
    mcp_preflight_ms: int | None = None  # M1 の MCP 事前接続
    started_at: str


def extract_answer_codes(answer: str) -> list[str]:
    """回答文に現れた科目コードを出現順・重複なしで返す。"""
    text = unicodedata.normalize("NFKC", answer)
    return list(dict.fromkeys(_ANSWER_CODE_PATTERN.findall(text)))


def score_question(case: GoldenCase, cited_codes: Iterable[str], answer: str) -> QuestionScore:
    """§4 の式で1実行を採点する。起点科目（anchor_code）は C' から除く。"""
    cited = normalize_codes(cited_codes)
    scored = [code for code in cited if code != case.anchor_code]
    answer_codes = extract_answer_codes(answer)
    uncited = [code for code in answer_codes if code not in cited and code != case.anchor_code]

    if not case.is_search:
        return QuestionScore(
            scored_codes=scored,
            unclear_pass=set(cited) <= set(case.alternatives),
            answer_codes=answer_codes,
            uncited_answer_codes=uncited,
        )

    expected = set(case.expected_codes)
    forbidden = set(case.forbidden_codes)
    hits = [code for code in scored if code in expected]
    return QuestionScore(
        scored_codes=scored,
        recall=len(hits) / len(expected),
        precision=len(hits) / len(scored) if scored else None,
        forbidden_hits=[code for code in scored if code in forbidden],
        answer_codes=answer_codes,
        uncited_answer_codes=uncited,
    )


# --- 集計（§5） -----------------------------------------------------------------


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


class ConditionSummary(BaseModel):
    condition: Condition
    runs: int
    successes: int
    search_runs: int
    recall_mean: float | None
    recall_median: float | None
    precision_mean: float | None
    precision_undefined: int  # 成功した検索系の実行のうち C' が空だった数
    forbidden_total: int
    forbidden_questions: int
    unverified_total: int
    unverified_questions: int
    unclear_pass: int
    unclear_runs: int
    llm_requests_total: int  # 失敗・やり直しも含む予算の消費量
    llm_requests_mean: float | None
    llm_requests_median: float | None
    search_llm_requests_mean: float | None
    search_llm_requests_median: float | None
    tool_calls_mean: float | None
    tool_calls_median: float | None
    search_tool_calls_mean: float | None
    search_tool_calls_median: float | None
    latency_mean_s: float | None
    latency_median_s: float | None
    search_latency_mean_s: float | None
    search_latency_median_s: float | None
    mcp_preflight_median_s: float | None  # M1 のみ（副次指標）
    input_tokens_total: int
    output_tokens_total: int
    thoughts_tokens_total: int


def summarize_condition(
    condition: Condition, records: Sequence[RunRecord], cases: dict[str, GoldenCase]
) -> ConditionSummary:
    """1条件の実行記録を §5 の値に畳む。失敗は recall 0・unclear 不合格として数える（§4）。"""
    own = [record for record in records if record.condition == condition]
    ok = [record for record in own if record.success and record.score is not None]
    search = [record for record in own if cases[record.question_id].is_search]
    unclear = [record for record in own if not cases[record.question_id].is_search]
    ok_search = [record for record in ok if cases[record.question_id].is_search]

    recalls = [
        record.score.recall
        if record.success and record.score is not None and record.score.recall is not None
        else 0.0
        for record in search
    ]
    precisions = [
        record.score.precision for record in ok_search if record.score.precision is not None
    ]
    forbidden_counts = [len(record.score.forbidden_hits) for record in ok_search]
    unverified_counts = [len(record.unverified_codes) for record in ok]

    return ConditionSummary(
        condition=condition,
        runs=len(own),
        successes=len(ok),
        search_runs=len(search),
        recall_mean=_mean(recalls),
        recall_median=_median(recalls),
        precision_mean=_mean(precisions),
        precision_undefined=len(ok_search) - len(precisions),
        forbidden_total=sum(forbidden_counts),
        forbidden_questions=sum(1 for count in forbidden_counts if count),
        unverified_total=sum(unverified_counts),
        unverified_questions=sum(1 for count in unverified_counts if count),
        unclear_pass=sum(
            1 for record in unclear if record.success and record.score and record.score.unclear_pass
        ),
        unclear_runs=len(unclear),
        llm_requests_total=sum(record.llm_requests_all_attempts for record in own),
        llm_requests_mean=_mean([record.llm_requests for record in ok]),
        llm_requests_median=_median([record.llm_requests for record in ok]),
        search_llm_requests_mean=_mean([record.llm_requests for record in ok_search]),
        search_llm_requests_median=_median([record.llm_requests for record in ok_search]),
        tool_calls_mean=_mean([record.tool_call_count for record in ok]),
        tool_calls_median=_median([record.tool_call_count for record in ok]),
        search_tool_calls_mean=_mean([record.tool_call_count for record in ok_search]),
        search_tool_calls_median=_median([record.tool_call_count for record in ok_search]),
        latency_mean_s=_seconds(_mean([record.latency_ms for record in ok])),
        latency_median_s=_seconds(_median([record.latency_ms for record in ok])),
        search_latency_mean_s=_seconds(_mean([record.latency_ms for record in ok_search])),
        search_latency_median_s=_seconds(_median([record.latency_ms for record in ok_search])),
        mcp_preflight_median_s=_seconds(
            _median([record.mcp_preflight_ms for record in ok if record.mcp_preflight_ms is not None])
        ),
        input_tokens_total=sum(record.input_tokens for record in own),
        output_tokens_total=sum(record.output_tokens for record in own),
        thoughts_tokens_total=sum(record.thoughts_tokens for record in own),
    )


def _seconds(milliseconds: float | None) -> float | None:
    return None if milliseconds is None else milliseconds / _MS_PER_SECOND


# --- 比較と仮説判定（§6・§7） ----------------------------------------------------


class RateComparison(BaseModel):
    """率の指標を2条件で比べた結果（§7）。値が両方で定義される質問だけを使う。"""

    questions: int
    delta_mean: float | None  # a − b
    sign_margin: int  # (a > b の質問数) − (a < b の質問数)
    label: Literal["差あり", "差は小さい", "差なし", "比較不能"]


def compare_rates(a: dict[str, float | None], b: dict[str, float | None]) -> RateComparison:
    """質問 ID → 値の2つの対応から、平均差と符号カウントで §7 の判定を返す。"""
    shared = sorted(
        qid for qid in a.keys() & b.keys() if a[qid] is not None and b[qid] is not None
    )
    if not shared:
        return RateComparison(questions=0, delta_mean=None, sign_margin=0, label="比較不能")
    pairs = [(a[qid], b[qid]) for qid in shared]
    delta = statistics.fmean(x for x, _ in pairs) - statistics.fmean(y for _, y in pairs)
    margin = sum(1 for x, y in pairs if x > y) - sum(1 for x, y in pairs if x < y)
    big_delta = abs(delta) >= RATE_DELTA_THRESHOLD
    big_margin = abs(margin) >= SIGN_MARGIN_THRESHOLD and (margin > 0) == (delta > 0)
    if big_delta and big_margin:
        label = "差あり"
    elif big_delta or big_margin:
        label = "差は小さい"
    else:
        label = "差なし"
    return RateComparison(questions=len(shared), delta_mean=delta, sign_margin=margin, label=label)


VerdictLabel = Literal["支持", "一部支持", "不支持", "判定不能"]


class Verdict(BaseModel):
    hypothesis: str
    label: VerdictLabel
    detail: str


def _by_question(records: Sequence[RunRecord], condition: Condition) -> dict[str, RunRecord]:
    return {record.question_id: record for record in records if record.condition == condition}


def _precision_map(rows: dict[str, RunRecord], search_ids: Sequence[str]) -> dict[str, float | None]:
    return {
        qid: rows[qid].score.precision if rows[qid].success and rows[qid].score else None
        for qid in search_ids
        if qid in rows
    }


def _combine(parts: Sequence[bool]) -> VerdictLabel:
    if all(parts):
        return "支持"
    if any(parts):
        return "一部支持"
    return "不支持"


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    """分母が0・欠損なら None（比較不能）。"""
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def _fmt(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def evaluate_hypotheses(
    records: Sequence[RunRecord], cases: dict[str, GoldenCase]
) -> list[Verdict]:
    """§6 の H5・H1〜H4 を機械的に判定する。必要な実行が欠けていれば判定不能。"""
    search_ids = [qid for qid, case in cases.items() if case.is_search]
    unclear_ids = [qid for qid, case in cases.items() if not case.is_search]
    rows = {condition: _by_question(records, condition) for condition in CONDITIONS}
    summaries = {
        condition: summarize_condition(condition, records, cases) for condition in CONDITIONS
    }

    def complete(*conditions: Condition, ids: Sequence[str] = tuple(cases)) -> bool:
        return all(qid in rows[condition] for condition in conditions for qid in ids)

    # H1 の (a) は M2 の全14問、(b) は M1・M2 の検索系を使う
    h1_complete = complete("mcp_grounded") and complete("mcp_free", ids=search_ids)
    return [
        _h5(rows["static"], search_ids, unclear_ids, complete("static")),
        _h1(rows, summaries, search_ids, h1_complete),
        _h2(summaries, complete("static_llm", "mcp_free", "mcp_grounded", ids=search_ids)),
        _h3(rows, search_ids, complete("static", "static_llm", ids=search_ids)),
        _h4(summaries, complete(*CONDITIONS, ids=unclear_ids)),
    ]


def _undecidable(name: str) -> Verdict:
    return Verdict(hypothesis=name, label="判定不能", detail="必要な実行が欠けている")


def _h5(
    static: dict[str, RunRecord], search_ids: Sequence[str], unclear_ids: Sequence[str], ok: bool
) -> Verdict:
    name = "H5 S0 の妥当性"
    if not ok:
        return _undecidable(name)
    perfect = [
        qid
        for qid in search_ids
        if static[qid].success
        and static[qid].score is not None
        and static[qid].score.recall == 1.0
        and static[qid].score.precision == 1.0
        and not static[qid].score.forbidden_hits
    ]
    passed = [
        qid
        for qid in unclear_ids
        if static[qid].success and static[qid].score and static[qid].score.unclear_pass
    ]
    holds = len(perfect) == len(search_ids) and len(passed) == len(unclear_ids)
    return Verdict(
        hypothesis=name,
        label="支持" if holds else "不支持",
        detail=f"検索系で満点 {len(perfect)}/{len(search_ids)}、unclear 合格 {len(passed)}/{len(unclear_ids)}",
    )


def _h1(
    rows: dict[Condition, dict[str, RunRecord]],
    summaries: dict[Condition, ConditionSummary],
    search_ids: Sequence[str],
    ok: bool,
) -> Verdict:
    name = "H1 出典の検証（M2 vs M1）"
    if not ok:
        return _undecidable(name)
    zero_unverified = summaries["mcp_grounded"].unverified_total == 0
    comparison = compare_rates(
        _precision_map(rows["mcp_grounded"], search_ids), _precision_map(rows["mcp_free"], search_ids)
    )
    better_precision = (
        comparison.delta_mean is not None
        and comparison.delta_mean >= RATE_DELTA_THRESHOLD
        and comparison.sign_margin >= SIGN_MARGIN_THRESHOLD
    )
    return Verdict(
        hypothesis=name,
        label=_combine([zero_unverified, better_precision]),
        detail=(
            f"(a) M2 unverified 合計 {summaries['mcp_grounded'].unverified_total}"
            f"（M1 は {summaries['mcp_free'].unverified_total}）→ {'満たす' if zero_unverified else '満たさない'}。"
            f" (b) precision 平均差 M2−M1 = {_fmt(comparison.delta_mean)}、"
            f"符号カウント {comparison.sign_margin}（{comparison.questions}問）"
            f"→ {'満たす' if better_precision else '満たさない'}"
        ),
    )


def _h2(summaries: dict[Condition, ConditionSummary], ok: bool) -> Verdict:
    name = "H2 コスト（M1・M2 vs S1、検索系）"
    if not ok:
        return _undecidable(name)
    base = summaries["static_llm"]
    latency_ratios = {
        condition: ratio(summaries[condition].search_latency_median_s, base.search_latency_median_s)
        for condition in ("mcp_free", "mcp_grounded")
    }
    request_ratios = {
        condition: ratio(summaries[condition].search_llm_requests_mean, base.search_llm_requests_mean)
        for condition in ("mcp_free", "mcp_grounded")
    }
    slow = all(value is not None and value >= H2_LATENCY_RATIO for value in latency_ratios.values())
    chatty = all(
        value is not None and value >= H2_LLM_REQUEST_RATIO for value in request_ratios.values()
    )
    return Verdict(
        hypothesis=name,
        label=_combine([slow, chatty]),
        detail=(
            f"(a) latency 中央値の比 M1 {_fmt(latency_ratios['mcp_free'], 1)}倍・"
            f"M2 {_fmt(latency_ratios['mcp_grounded'], 1)}倍（基準 {H2_LATENCY_RATIO:g}倍）"
            f"→ {'満たす' if slow else '満たさない'}。"
            f" (b) LLM リクエスト平均の比 M1 {_fmt(request_ratios['mcp_free'], 1)}倍・"
            f"M2 {_fmt(request_ratios['mcp_grounded'], 1)}倍（基準 {H2_LLM_REQUEST_RATIO:g}倍）"
            f"→ {'満たす' if chatty else '満たさない'}"
        ),
    )


def _h3(rows: dict[Condition, dict[str, RunRecord]], search_ids: Sequence[str], ok: bool) -> Verdict:
    name = "H3 S1 は S0 の候補を保つ"
    if not ok:
        return _undecidable(name)
    matched = [
        qid
        for qid in search_ids
        if rows["static_llm"][qid].success
        and rows["static_llm"][qid].score is not None
        and rows["static"][qid].score is not None
        and set(rows["static_llm"][qid].score.scored_codes)
        == set(rows["static"][qid].score.scored_codes)
    ]
    mismatched = [qid for qid in search_ids if qid not in matched]
    return Verdict(
        hypothesis=name,
        label="支持" if len(matched) >= H3_MIN_MATCHES else "不支持",
        detail=(
            f"集合が一致 {len(matched)}/{len(search_ids)}（基準 {H3_MIN_MATCHES}問以上）"
            + (f"。不一致: {', '.join(mismatched)}" if mismatched else "")
        ),
    )


def _h4(summaries: dict[Condition, ConditionSummary], ok: bool) -> Verdict:
    name = "H4 unclear で候補を作らない"
    if not ok:
        return _undecidable(name)
    static_ok = all(
        summaries[condition].unclear_pass == summaries[condition].unclear_runs
        for condition in ("static", "static_llm")
    )
    # 「3/4 以下」= 少なくとも1問で alternatives に無い科目を提示した
    mcp_fail = all(
        summaries[condition].unclear_pass < summaries[condition].unclear_runs
        for condition in ("mcp_free", "mcp_grounded")
    )
    counts = "、".join(
        f"{condition} {summaries[condition].unclear_pass}/{summaries[condition].unclear_runs}"
        for condition in CONDITIONS
    )
    return Verdict(
        hypothesis=name,
        label="支持" if static_ok and mcp_fail else "不支持",
        detail=f"unclear 合格: {counts}",
    )
