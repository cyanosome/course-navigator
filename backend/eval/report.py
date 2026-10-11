"""node_compare の実行記録から集計表・仮説の判定・質問別の表を Markdown で書く純関数。"""

from collections.abc import Callable, Sequence

from eval.metrics import (
    CONDITIONS,
    Condition,
    ConditionSummary,
    GoldenCase,
    RunRecord,
    compare_rates,
    evaluate_hypotheses,
    ratio,
    summarize_condition,
)

__all__ = ["render_summary"]

CONDITION_LABELS: dict[Condition, str] = {
    "static": "S0 static",
    "static_llm": "S1 static_llm",
    "mcp_free": "M1 mcp_free",
    "mcp_grounded": "M2 mcp_grounded",
}
# §7 の比較の組（左 − 右 / 左 ÷ 右）
COMPARISON_PAIRS: tuple[tuple[Condition, Condition], ...] = (
    ("static_llm", "static"),
    ("mcp_free", "static"),
    ("mcp_grounded", "static"),
    ("mcp_grounded", "mcp_free"),
)
COST_RATIO_THRESHOLD = 1.5
COUNT_DIFF_THRESHOLD = 2
_DASH = "—"
_CODE_SEPARATOR = ", "


def _fmt(value: float | None, digits: int = 2) -> str:
    return _DASH if value is None else f"{value:.{digits}f}"


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    return [_row(header), _row(["---"] * len(header)), *(_row(row) for row in rows)]


def _short(condition: Condition) -> str:
    return CONDITION_LABELS[condition].split(" ", 1)[0]


def _sessions_section(sessions: Sequence[dict[str, object]], records: Sequence[RunRecord]) -> list[str]:
    versions = sorted({version for record in records for version in record.model_versions})
    rows = [
        [
            str(session["run_id"]),
            str(session["git_sha"]),
            str(session["model"]),
            str(session["started_at"]),
            str(session["finished_at"]),
            f"{session['llm_requests_used']}/{session['budget']}",
            str(session["aborted"]),
        ]
        for session in sessions
    ]
    last = sessions[-1]
    return [
        "## 実行条件",
        "",
        *_table(["run_id", "git", "モデル", "開始 (UTC)", "終了 (UTC)", "LLM 使用/予算", "打ち切り"], rows),
        "",
        f"- 応答が返した model_version: {_CODE_SEPARATOR.join(versions) or _DASH}",
        f"- 生成設定: {last['generation_config']}",
        f"- DB の件数: {last['db_counts']}",
        f"- プロンプトの SHA-256（先頭16桁）: {last['prompt_sha256_16']}",
        f"- ライブラリ: {last['libraries']}（Python {last['python']}）",
        f"- 打ち切り条件: 1実行の LLM 上限 {last['per_run_llm_cap']} 回、タイムアウト {last['run_timeout_seconds']} 秒、"
        f"やり直し {last['retry']}",
        "",
    ]


def _summary_section(summaries: dict[Condition, ConditionSummary]) -> list[str]:
    def cells(render: Callable[[ConditionSummary], str]) -> list[str]:
        return [render(summaries[condition]) for condition in CONDITIONS]

    rows = [
        ["成功", *cells(lambda s: f"{s.successes}/{s.runs}")],
        ["recall 平均（検索系、失敗は0）", *cells(lambda s: _fmt(s.recall_mean))],
        ["recall 中央値（検索系）", *cells(lambda s: _fmt(s.recall_median))],
        ["precision 平均（定義される実行）", *cells(lambda s: _fmt(s.precision_mean))],
        ["precision 未定義（C' が空）", *cells(lambda s: str(s.precision_undefined))],
        ["forbidden 合計（該当質問数）", *cells(lambda s: f"{s.forbidden_total}（{s.forbidden_questions}）")],
        ["unverified 合計（該当質問数）※事後検証", *cells(lambda s: f"{s.unverified_total}（{s.unverified_questions}）")],
        ["unclear 合格", *cells(lambda s: f"{s.unclear_pass}/{s.unclear_runs}")],
        ["LLM リクエスト 平均 / 中央値（全問）", *cells(lambda s: f"{_fmt(s.llm_requests_mean, 1)} / {_fmt(s.llm_requests_median, 1)}")],
        ["LLM リクエスト 平均（検索系）", *cells(lambda s: _fmt(s.search_llm_requests_mean, 1))],
        ["ツール呼び出し 平均 / 中央値（全問）", *cells(lambda s: f"{_fmt(s.tool_calls_mean, 1)} / {_fmt(s.tool_calls_median, 1)}")],
        ["latency 平均 / 中央値 秒（全問）", *cells(lambda s: f"{_fmt(s.latency_mean_s, 1)} / {_fmt(s.latency_median_s, 1)}")],
        ["latency 中央値 秒（検索系）", *cells(lambda s: _fmt(s.search_latency_median_s, 1))],
        ["LLM リクエスト合計（予算の消費。失敗・やり直しを含む）", *cells(lambda s: str(s.llm_requests_total))],
        ["トークン 入力 / 出力 / 思考", *cells(lambda s: f"{s.input_tokens_total} / {s.output_tokens_total} / {s.thoughts_tokens_total}")],
    ]
    header = ["指標", *(CONDITION_LABELS[condition] for condition in CONDITIONS)]
    return ["## 条件別の集計", "", *_table(header, rows), ""]


def _rate_maps(
    records: Sequence[RunRecord], cases: dict[str, GoldenCase], condition: Condition
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    """recall（失敗は0）と precision（成功のみ）を質問 ID → 値で返す。"""
    recall: dict[str, float | None] = {}
    precision: dict[str, float | None] = {}
    for record in records:
        if record.condition != condition or not cases[record.question_id].is_search:
            continue
        ok = record.success and record.score is not None
        recall[record.question_id] = record.score.recall if ok else 0.0
        precision[record.question_id] = record.score.precision if ok else None
    return recall, precision


def _cost_label(ratio: float | None) -> str:
    if ratio is None:
        return "比較不能"
    if ratio >= COST_RATIO_THRESHOLD or ratio <= 1 / COST_RATIO_THRESHOLD:
        return "差あり"
    return "差なし"


def _count_label(diff: int) -> str:
    if abs(diff) >= COUNT_DIFF_THRESHOLD:
        return "差あり"
    if diff:
        return "1問差（偶然と区別できない）"
    return "差なし"


def _comparison_section(
    records: Sequence[RunRecord],
    cases: dict[str, GoldenCase],
    summaries: dict[Condition, ConditionSummary],
) -> list[str]:
    maps = {condition: _rate_maps(records, cases, condition) for condition in CONDITIONS}
    rate_rows = []
    for left, right in COMPARISON_PAIRS:
        for metric, index in (("recall", 0), ("precision", 1)):
            result = compare_rates(maps[left][index], maps[right][index])
            rate_rows.append([
                f"{_short(left)} vs {_short(right)}",
                metric,
                str(result.questions),
                _fmt(result.delta_mean),
                str(result.sign_margin),
                result.label,
            ])

    cost_rows = []
    count_rows = []
    for left, right in COMPARISON_PAIRS:
        a, b = summaries[left], summaries[right]
        latency = ratio(a.search_latency_median_s, b.search_latency_median_s)
        requests = ratio(a.search_llm_requests_mean, b.search_llm_requests_mean)
        tools = ratio(a.tool_calls_mean, b.tool_calls_mean)
        cost_rows.append([
            f"{_short(left)} / {_short(right)}",
            f"{_fmt(latency, 1)}（{_cost_label(latency)}）",
            f"{_fmt(requests, 1)}（{_cost_label(requests)}）",
            f"{_fmt(tools, 1)}（{_cost_label(tools)}）",
        ])
        diffs = {
            "forbidden 該当質問数": a.forbidden_questions - b.forbidden_questions,
            "unverified 該当質問数": a.unverified_questions - b.unverified_questions,
            "unclear 合格数": a.unclear_pass - b.unclear_pass,
        }
        for name, diff in diffs.items():
            count_rows.append([f"{_short(left)} − {_short(right)}", name, f"{diff:+d}", _count_label(diff)])

    return [
        "## 条件間の比較（事前登録 §7 の基準）",
        "",
        "率の指標（検索系。値が両方で定義される質問のみ。平均差・符号カウントは「左 − 右」）:",
        "",
        *_table(["比較", "指標", "質問数", "平均差", "符号カウント", "判定"], rate_rows),
        "",
        "コストの比（検索系の latency 中央値、検索系の LLM リクエスト平均、全問のツール呼び出し平均。「左 ÷ 右」）:",
        "",
        *_table(["比較", "latency", "LLM リクエスト", "ツール呼び出し"], cost_rows),
        "",
        "質問数で数える指標:",
        "",
        *_table(["比較", "指標", "差", "判定"], count_rows),
        "",
    ]


def _quality_cell(record: RunRecord | None, case: GoldenCase) -> str:
    if record is None:
        return "未実行"
    if not record.success or record.score is None:
        return "失敗"
    score = record.score
    if not case.is_search:
        if score.unclear_pass:
            return "合格"
        return f"不合格（{_CODE_SEPARATOR.join(score.scored_codes)}）"
    parts = [f"R {_fmt(score.recall)} / P {_fmt(score.precision)}"]
    if score.forbidden_hits:
        parts.append(f"F: {_CODE_SEPARATOR.join(score.forbidden_hits)}")
    if record.unverified_codes:
        parts.append(f"U: {_CODE_SEPARATOR.join(record.unverified_codes)}")
    return "<br>".join(parts)


def _cost_cell(record: RunRecord | None) -> str:
    if record is None:
        return "未実行"
    return f"{record.llm_requests} / {record.tool_call_count} / {record.latency_ms / 1000:.1f}"


def _per_question_section(records: Sequence[RunRecord], cases: dict[str, GoldenCase]) -> list[str]:
    index = {(record.condition, record.question_id): record for record in records}
    header = ["質問", "種別", *(CONDITION_LABELS[condition] for condition in CONDITIONS)]
    quality_rows = [
        [qid, case.mode, *(_quality_cell(index.get((condition, qid)), case) for condition in CONDITIONS)]
        for qid, case in cases.items()
    ]
    cost_rows = [
        [qid, case.mode, *(_cost_cell(index.get((condition, qid))) for condition in CONDITIONS)]
        for qid, case in cases.items()
    ]
    return [
        "## 質問別の結果",
        "",
        "正しさ（R = recall、P = precision、F = forbidden に当たったコード、U = DB に無いコード。"
        "unclear は合否と、提示したコード）:",
        "",
        *_table(header, quality_rows),
        "",
        "コスト（LLM リクエスト / ツール呼び出し / 秒）:",
        "",
        *_table(header, cost_rows),
        "",
    ]


def _notes_section(records: Sequence[RunRecord]) -> list[str]:
    failures = [
        f"- {record.question_id} {record.condition}: {record.error}"
        for record in records
        if not record.success
    ]
    retries = [
        f"- {record.question_id} {record.condition}: {'、'.join(record.retry_reasons)}"
        for record in records
        if record.retry_reasons
    ]
    uncited = [
        f"- {record.question_id} {record.condition}: {_CODE_SEPARATOR.join(record.score.uncited_answer_codes)}"
        for record in records
        if record.score is not None and record.score.uncited_answer_codes
    ]
    grounded = [
        record for record in records if record.condition == "mcp_grounded" and record.success
    ]
    agreeing = sum(
        1 for record in grounded if record.pipeline_unverified_codes == record.unverified_codes
    )
    return [
        "## 失敗・やり直し",
        "",
        *(failures or ["- 失敗なし"]),
        "",
        *(retries or ["- やり直しなし"]),
        "",
        "## 副次: 回答文にあるが cited_codes に無いコード（起点科目を除く）",
        "",
        *(uncited or ["- なし"]),
        "",
        "## M2 のパイプライン内検証（attach_sources）と事後検証の一致",
        "",
        f"- 一致 {agreeing}/{len(grounded)}（成功した M2 の実行）",
        "",
    ]


def render_summary(
    records: Sequence[RunRecord],
    cases: dict[str, GoldenCase],
    sessions: Sequence[dict[str, object]],
) -> str:
    summaries = {
        condition: summarize_condition(condition, records, cases) for condition in CONDITIONS
    }
    verdict_rows = [
        [verdict.hypothesis, verdict.label, verdict.detail]
        for verdict in evaluate_hypotheses(records, cases)
    ]
    lines = [
        f"# ノード設計比較の結果（{str(sessions[0]['started_at'])[:10]} 実行）",
        "",
        "このファイルは `python -m eval.node_compare summarize` が JSONL から書いた。"
        "式と判定規則は `../prereg_node_compare.md`（事前登録）。n=14・各1回の記述統計で、有意性は主張しない。",
        "",
        *_sessions_section(sessions, records),
        *_summary_section(summaries),
        "## 仮説の判定（事前登録 §6）",
        "",
        *_table(["仮説", "判定", "根拠"], verdict_rows),
        "",
        *_comparison_section(records, cases, summaries),
        *_per_question_section(records, cases),
        *_notes_section(records),
    ]
    return "\n".join(lines)
