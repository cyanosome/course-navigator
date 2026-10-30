"""検索方式比較のサマリー（Markdown）を組み立てる（prereg_retrieval_seed.md §8）。I/O は持たない。"""

import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from eval.metrics import GoldenCase, compare_rates
from eval.query_spec import QuerySpec
from eval.retrieval_metrics import (
    CONDITIONS,
    DIRECTIONAL_MODES,
    NEXT_STEP_MODE,
    PRIMARY_K,
    SECONDARY_K,
    TOPIC_MODE,
    GenerationRecord,
    RetrievalRecord,
    cost_label,
    evaluate_hypotheses,
    random_expected_ndcg,
    random_expected_recall,
)

__all__ = ["DEVIATIONS", "render_summary"]

LABELS = {
    "pure_vector": "C1 pure_vector",
    "vector_metadata": "C2 vector_metadata",
    "pure_graph": "C3 pure_graph",
    "hybrid": "C4 hybrid",
}
_NONE = "—"
_CORPUS_SIZE = 20
# 予算を記録していない manifest（元の実行）の分母。prereg_retrieval_seed.md §7 の値
_DEFAULT_BUDGET = {"llm": 150, "embedding": 100}

# 事前登録からの逸脱（実行後に分かったものをここに足し、サマリーに出す）
DEVIATIONS: list[str] = [
    "§3.4 の厳密検索の設定は、接続ごとの SET ではなく接続の起動パラメータ（server_settings）で "
    "enable_indexscan = off を渡した。asyncpg のプールは接続を返すたびに RESET ALL を流すので、"
    "SET だと2回目以降の取得で設定が消え、HNSW を使う計画になることを実行前の EXPLAIN の確認で見つけたため。"
    "効果（セッション単位でインデックス走査を使わない）は登録どおりで、検索結果を記録する前に直した。",
]


def _fmt(value: float | None, digits: int = 2) -> str:
    return _NONE if value is None else f"{value:.{digits}f}"


def _mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return statistics.fmean(present) if present else None


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _row(cells: Sequence[object]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    return [_row(header), _row(["---"] * len(header)), *(_row(row) for row in rows)]


def _records(records: Sequence[RetrievalRecord], condition: str, ids: Sequence[str]) -> list[RetrievalRecord]:
    by_id = {r.question_id: r for r in records if r.condition == condition}
    return [by_id[qid] for qid in ids if qid in by_id]


def _metric(records: Sequence[RetrievalRecord], name: str, k: int) -> list[float | None]:
    return [getattr(record.scores[str(k)], name) for record in records]


def _random_baseline(cases: Mapping[str, GoldenCase], ids: Sequence[str], k: int) -> tuple[float, float]:
    recalls, ndcgs = [], []
    for qid in ids:
        case = cases[qid]
        candidates = _CORPUS_SIZE - (1 if case.anchor_code else 0)
        recalls.append(random_expected_recall(k, candidates))
        ndcgs.append(random_expected_ndcg(k, len(case.expected_codes), candidates))
    return statistics.fmean(recalls), statistics.fmean(ndcgs)


def _session(sessions: Sequence[Mapping[str, Any]], command: str) -> Mapping[str, Any] | None:
    found = [item for item in sessions if item.get("command") == command]
    return found[-1] if found else None


def _overview(sessions: Sequence[Mapping[str, Any]], generation: Sequence[GenerationRecord]) -> list[str]:
    retrieve = _session(sessions, "retrieve") or {}
    corpus = retrieve.get("corpus", {})
    embedding = retrieve.get("embedding", {})
    params = retrieve.get("params", {})
    plan = retrieve.get("exact_search", {})
    versions = sorted({v for record in generation for v in record.model_versions})
    models = sorted({record.model for record in generation if record.model})
    llm_used = sum(int(item.get("llm_requests", 0)) for item in sessions)
    embedding_used = sum(int(item.get("embedding_requests", 0)) for item in sessions)
    budget = next((item["budget"] for item in reversed(sessions) if "budget" in item), _DEFAULT_BUDGET)
    clean = retrieve.get("git_status_clean", "未記録")
    source = retrieve.get("source_tree", {})
    lines = [
        "## 実行条件",
        "",
        f"- 検索の run_id: {retrieve.get('run_id', _NONE)}（git {retrieve.get('git_sha', _NONE)}、作業ツリー clean={clean}、"
        f"ソースの指紋 {source.get('files', _NONE)} ファイル {str(source.get('sha256', ''))[:16] or _NONE}…）。"
        f"マージ: {retrieve.get('merge', {}).get('merged_branch', _NONE)} @ {retrieve.get('merge', {}).get('merged_head', _NONE)}",
        f"- コーパス: PostgreSQL {corpus.get('postgres_rows', _NONE)} 行（sha256 {str(corpus.get('postgres_rows_sha256', ''))[:16]}…）、"
        f"seed/courses.json（{str(corpus.get('seed_courses_json_sha256', ''))[:16]}…）、"
        f"Neo4j {corpus.get('neo4j_counts', {})}（{str(corpus.get('neo4j_graph_sha256', ''))[:16]}…、"
        f"{corpus.get('neo4j_version', {}).get('v', _NONE)}）",
        f"- 実験用 DB: {corpus.get('postgres_version', _NONE)}、pgvector {corpus.get('pgvector_version', _NONE)}。"
        f"厳密検索の確認: enable_indexscan={plan.get('enable_indexscan', _NONE)}、HNSW 使用={plan.get('uses_hnsw_index', _NONE)}、"
        f"計画ノード {plan.get('plan_node_types', [])}",
        f"- 埋め込み: {embedding.get('model', _NONE)}、{embedding.get('dimensions', _NONE)} 次元、"
        f"{embedding.get('normalization', _NONE)}。質問 `{embedding.get('query_template', _NONE)}`、"
        f"文書 `{embedding.get('document_template', _NONE)}`",
        f"- パラメータ: K={params.get('k', _NONE)}（主は {PRIMARY_K}）、取得件数 {params.get('retrieve_depth', _NONE)}、"
        f"繰り返し {params.get('repeats', _NONE)} 回、hybrid の入口 m={params.get('hybrid_entry_count', _NONE)}、"
        f"RRF k={params.get('rrf_k', _NONE)}、全文検索 {params.get('fulltext_index', _NONE)}（{params.get('fulltext_analyzer', _NONE)}）",
        f"- 生成: モデル {models or _NONE}、応答の model_version {versions or _NONE}、生成設定は API 既定値",
        f"- リクエスト数（manifest の全セッション、煙テストを含む）: LLM {llm_used} / {budget['llm']}、"
        f"埋め込み {embedding_used} / {budget['embedding']}",
        "",
    ]
    return lines


def _retrieval_tables(
    records: Sequence[RetrievalRecord], cases: Mapping[str, GoldenCase], search_ids: Sequence[str]
) -> list[str]:
    directional = [qid for qid in search_ids if cases[qid].mode in DIRECTIONAL_MODES]
    topic = [qid for qid in search_ids if cases[qid].mode == TOPIC_MODE]
    next_step = [qid for qid in search_ids if cases[qid].mode == NEXT_STEP_MODE]
    lines = ["## 検索（検索系10問）", ""]
    header = [
        "条件", "Recall@5", "NDCG@5", "Recall@10", "NDCG@10", "forbidden@5（問）", "返却件数@5 平均",
        "所要時間 中央値 ms", "DB クエリ数 平均",
    ]
    rows = []
    for condition in CONDITIONS:
        own = _records(records, condition, search_ids)
        forbidden = [len(r.scores[str(PRIMARY_K)].forbidden_hits) for r in own]
        rows.append(
            [
                LABELS[condition],
                _fmt(_mean(_metric(own, "recall", PRIMARY_K))),
                _fmt(_mean(_metric(own, "ndcg", PRIMARY_K))),
                _fmt(_mean(_metric(own, "recall", SECONDARY_K))),
                _fmt(_mean(_metric(own, "ndcg", SECONDARY_K))),
                f"{sum(forbidden)}（{sum(1 for f in forbidden if f)}）",
                _fmt(_mean([float(r.scores[str(PRIMARY_K)].returned) for r in own]), 1),
                _fmt(_median([r.latency_ms_median for r in own]), 1),
                _fmt(_mean([float(r.db_queries) for r in own]), 1),
            ]
        )
    recall5, ndcg5 = _random_baseline(cases, search_ids, PRIMARY_K)
    recall10, ndcg10 = _random_baseline(cases, search_ids, SECONDARY_K)
    rows.append(["参考: ランダム（解析解）", _fmt(recall5), _fmt(ndcg5), _fmt(recall10), _fmt(ndcg10), _NONE, "5.0", _NONE, _NONE])
    lines += _table(header, rows)
    lines += [
        "",
        "列の意味: Recall@K は期待科目のうち上位 K 件に入った割合、NDCG@K は期待科目が上位に来るほど高い順位の質（1が最良）。"
        "どちらも起点科目を除いた順位で測り、10問の平均。forbidden@5 は出してはいけない科目が上位5件に入った件数の合計"
        "（括弧は該当した質問数）。返却件数は上位5件に実際に入った件数（グラフは5件に満たないことがある）。"
        "所要時間は各問5回の中央値をさらに10問で中央値にしたもので、質問の埋め込みを作る時間は含まない。"
        "K=10 は記述のみ（20科目では差が縮む）。",
        "",
        "### 問いの種類別（@5 の平均）",
        "",
    ]
    group_rows = []
    for condition in CONDITIONS:
        d = _records(records, condition, directional)
        t = _records(records, condition, topic)
        n = _records(records, condition, next_step)
        violations = [len(r.scores[str(PRIMARY_K)].violations or []) for r in n]
        rates = [r.scores[str(PRIMARY_K)].violation_rate for r in n]
        completed = [len(r.scores[str(PRIMARY_K)].completed_hits or []) for r in n]
        group_rows.append(
            [
                LABELS[condition],
                _fmt(_mean(_metric(d, "recall", PRIMARY_K))),
                _fmt(_mean(_metric(d, "ndcg", PRIMARY_K))),
                _fmt(_mean(_metric(t, "recall", PRIMARY_K))),
                _fmt(_mean(_metric(t, "ndcg", PRIMARY_K))),
                sum(violations),
                _fmt(_mean(rates)),
                sum(completed),
            ]
        )
    lines += _table(
        [
            "条件", f"向きあり{len(directional)}問 Recall@5", "向きあり NDCG@5", f"topic{len(topic)}問 Recall@5",
            "topic NDCG@5", f"next_step{len(next_step)}問 前提違反@5 合計", "前提違反率 平均", "履修済みの推薦 合計",
        ],
        group_rows,
    )
    lines += [
        "",
        "前提違反@5: next_step の問いで、起点科目とその前提科目をすべて履修済みとみなしたとき、上位5件のうち"
        "直接の前提科目に未履修のものがある科目の数。違反率はそれを返却件数で割ったもの。"
        "履修済みの推薦は、履修済みとみなした科目（起点を除く）を推薦してしまった数。",
        "",
    ]
    return lines


def _comparisons(records: Sequence[RetrievalRecord], cases: Mapping[str, GoldenCase], search_ids: Sequence[str]) -> list[str]:
    groups = {
        "向きあり": [qid for qid in search_ids if cases[qid].mode in DIRECTIONAL_MODES],
        "topic": [qid for qid in search_ids if cases[qid].mode == TOPIC_MODE],
        "検索系すべて": list(search_ids),
    }
    pairs = [("pure_graph", "pure_vector"), ("hybrid", "pure_vector"), ("hybrid", "pure_graph"), ("vector_metadata", "pure_vector")]
    rows = []
    for group, ids in groups.items():
        for a, b in pairs:
            for metric in ("recall", "ndcg"):
                values_a = {r.question_id: r.scores[str(PRIMARY_K)].model_dump()[metric] for r in _records(records, a, ids)}
                values_b = {r.question_id: r.scores[str(PRIMARY_K)].model_dump()[metric] for r in _records(records, b, ids)}
                comparison = compare_rates(values_a, values_b)
                rows.append(
                    [group, f"{a} − {b}", f"{metric}@5", comparison.questions, _fmt(comparison.delta_mean), f"{comparison.sign_margin:+d}", comparison.label]
                )
    lines = ["### 条件の対比較（事前登録 §6 の「差あり」の基準）", ""]
    lines += _table(["問い", "比較", "指標", "問数", "平均差", "符号カウント", "判定"], rows)
    cost_rows = []
    vector = _records(records, "pure_vector", search_ids)
    vector_latency = _median([r.latency_ms_median for r in vector])
    vector_queries = _mean([float(r.db_queries) for r in vector])
    for condition in CONDITIONS[1:]:
        own = _records(records, condition, search_ids)
        latency = _median([r.latency_ms_median for r in own])
        queries = _mean([float(r.db_queries) for r in own])
        cost_rows.append(
            [
                f"{condition} / pure_vector",
                _fmt(latency / vector_latency if latency and vector_latency else None),
                cost_label(latency, vector_latency),
                _fmt(queries / vector_queries if queries and vector_queries else None),
                cost_label(queries, vector_queries),
            ]
        )
    lines += ["", "コスト（検索系10問、比が1.5倍以上で「差あり」）:", ""]
    lines += _table(["比", "所要時間の比", "判定", "DB クエリ数の比", "判定"], cost_rows)
    lines += [""]
    return lines


def _per_question(records: Sequence[RetrievalRecord], cases: Mapping[str, GoldenCase], search_ids: Sequence[str]) -> list[str]:
    lines = ["## 質問別（検索系、@5）", ""]
    header = ["質問", "mode", "期待科目 E", *[f"{LABELS[c]} R/N・上位5件" for c in CONDITIONS]]
    by_key = {(r.condition, r.question_id): r for r in records}
    rows = []
    for qid in search_ids:
        case = cases[qid]
        cells = [qid, case.mode, " ".join(case.expected_codes)]
        for condition in CONDITIONS:
            record = by_key.get((condition, qid))
            if record is None:
                cells.append(_NONE)
                continue
            score = record.scores[str(PRIMARY_K)]
            cells.append(f"{_fmt(score.recall)}/{_fmt(score.ndcg)} {' '.join(record.codes[:PRIMARY_K]) or '（0件）'}")
        rows.append(cells)
    lines += _table(header, rows)
    lines += ["", "R/N は Recall@5 / NDCG@5。上位5件は起点科目を除いた順位。", ""]
    return lines


def _unclear(records: Sequence[RetrievalRecord], cases: Mapping[str, GoldenCase], specs: Mapping[str, QuerySpec]) -> list[str]:
    ids = sorted(qid for qid, case in cases.items() if not case.is_search)
    by_key = {(r.condition, r.question_id): r for r in records}
    rows = []
    for qid in ids:
        spec = specs.get(qid)
        constraints = spec.constraints.model_dump(exclude_none=True) if spec else {}
        cells = [qid, cases[qid].question, constraints or _NONE]
        for condition in CONDITIONS:
            record = by_key.get((condition, qid))
            if record is None:
                cells.append(_NONE)
                continue
            score = record.scores[str(PRIMARY_K)]
            mark = "（alternatives 内）" if qid == "q14" and score.within_alternatives else ""
            cells.append(f"{score.returned}件 {' '.join(record.codes[:PRIMARY_K]) or ''}{mark}")
        rows.append(cells)
    lines = ["## unclear の4問（記述のみ。正解の順位は無い）", ""]
    lines += _table(["質問", "質問文", "constraints", *[LABELS[c] for c in CONDITIONS]], rows)
    lines += [
        "",
        "静的 DAG はこの4問で候補を出さないのが期待動作（聞き返す）。検索部だけを比べるこの実験では、"
        "どの条件も「聞き返す」判断を持たないので、返した件数と中身をそのまま記録する。",
        "",
    ]
    return lines


def _outside_in_evidence(record: GenerationRecord, retrieval: Mapping[tuple[str, str], RetrievalRecord]) -> int:
    """候補外の引用のうち、LLM に渡した上位5件の根拠文（経路の表記など）に現れたコードの数。"""
    source = retrieval.get((record.condition, record.question_id))
    if source is None or record.score is None:
        return 0
    evidence = " ".join(text for entry in source.ranked[: len(record.candidate_codes)] for text in entry.evidence)
    return sum(1 for code in record.score.outside_candidates if code in evidence)


def _generation(
    records: Sequence[GenerationRecord], retrieval: Sequence[RetrievalRecord], search_ids: Sequence[str]
) -> list[str]:
    if not records:
        return ["## 生成", "", "生成の記録はありません。", ""]
    by_key = {(r.condition, r.question_id): r for r in retrieval}
    rows = []
    for condition in CONDITIONS:
        own = [r for r in records if r.condition == condition and r.question_id in search_ids]
        ok = [r for r in own if r.success and r.score is not None]
        rows.append(
            [
                LABELS[condition],
                f"{len(ok)}/{len(own)}",
                sum(len(r.unverified_codes) for r in ok),
                sum(len(r.score.outside_candidates) for r in ok if r.score),
                sum(_outside_in_evidence(r, by_key) for r in ok),
                _fmt(_mean([r.score.recall for r in ok if r.score])),
                _fmt(_mean([r.score.precision for r in ok if r.score])),
                sum(len(r.score.forbidden_hits) for r in ok if r.score),
                _fmt(_mean([float(r.llm_requests) for r in ok]), 1),
                _fmt(_mean([float(r.input_tokens) for r in ok]), 0),
                _fmt(_mean([float(r.output_tokens) for r in ok]), 0),
                _fmt(_median([r.latency_ms / 1000 for r in ok]), 1),
            ]
        )
    lines = ["## 生成（検索系10問×4条件、上位5件から LLM 1回）", ""]
    lines += _table(
        ["条件", "成功", "未検証コード 合計", "候補外の引用 合計", "うち根拠文に現れるコード", "recall 平均", "precision 平均", "forbidden 合計",
         "LLM 回数 平均", "入力トークン 平均", "出力トークン 平均", "所要時間 中央値 s"],
        rows,
    )
    lines += [
        "",
        "列の意味: 未検証コードは、回答が引用したコードのうち PostgreSQL に行が無いもの（存在しない科目）。"
        "候補外の引用は、起点以外で LLM に渡した5件に無いコードを引用した数。そのうち、渡した5件の根拠文"
        "（前提関係の経路の表記や入口科目の名前）に現れるコードの数を隣の列に出す（指示文の規則1は根拠文の内容を使うことを認めている）。"
        "recall / precision は引用（起点を除く）を golden の期待科目と突き合わせたもの。",
        "",
    ]
    failures = [r for r in records if not r.success]
    if failures:
        lines += ["失敗した生成:", ""]
        lines += [f"- {r.question_id} {r.condition}: {r.error}" for r in failures]
        lines += [""]
    return lines


def render_summary(
    retrieval: Sequence[RetrievalRecord],
    generation: Sequence[GenerationRecord],
    cases: Mapping[str, GoldenCase],
    specs: Sequence[QuerySpec],
    sessions: Sequence[Mapping[str, Any]],
    spec_matches: Mapping[str, bool],
) -> str:
    search_ids = sorted(qid for qid, case in cases.items() if case.is_search)
    spec_by_id = {spec.question_id: spec for spec in specs}
    lines = [
        "# 検索方式比較（シード）の結果サマリー",
        "",
        "`python -m eval.retrieval_compare summarize` が生成した。事前登録は `eval/prereg_retrieval_seed.md`。",
        "シードの golden は静的探索の出力に合わせて作られているので、C3 が満点に近いのは設計上の前提で、方式の優劣の証拠にはならない。",
        "",
    ]
    lines += _overview(sessions, generation)
    lines += _retrieval_tables(retrieval, cases, search_ids)
    lines += _comparisons(retrieval, cases, search_ids)
    lines += _per_question(retrieval, cases, search_ids)
    lines += _unclear(retrieval, cases, spec_by_id)
    lines += _generation(generation, retrieval, search_ids)
    lines += ["## 事前登録に照らした判定", ""]
    verdicts = evaluate_hypotheses(retrieval, generation, cases, spec_matches)
    lines += _table(["仮説", "判定", "根拠"], [[v.hypothesis, v.label, v.detail] for v in verdicts])
    lines += ["", "## 事前登録からの逸脱", ""]
    lines += [f"- {item}" for item in DEVIATIONS] or ["- なし"]
    lines += [""]
    return "\n".join(lines)
