"""検索方式比較（シード）の再現実行の突き合わせ（prereg_retrieval_seed_replication.md §4・§5.3）。

backend コンテナの /backend_app で実行する。コンテナに .git が無いので、git の木はホストから標準入力で渡す:

    git ls-tree --full-tree -r -z <HEAD> -- backend | docker exec -i --env-file client.env -w /backend_app <backend コンテナ> \\
      uv run --no-sync python -m eval.replication_compare --ls-tree - --ls-tree-commit <HEAD> \\
        --original eval/results/2026-10-13_retrieval_seed.jsonl \\
        --rerun eval/results/2026-10-13_retrieval_seed_rerun_original_embeddings.jsonl \\
        --replication eval/results/2026-10-13_retrieval_seed_replication.jsonl \\
        --original-db coursenavigator_eval --replication-db coursenavigator_eval_replication \\
        --out eval/results/2026-10-13_retrieval_seed_replication_compare

元 = 元の実行、R1 = 元の埋め込みのまま検索だけを流し直したもの、R2 = 最初からの再現実行。
埋め込みのベクトルは2つの実験用 DB から読み、差の統計だけを書き出す（ベクトルそのものは残さない）。
"""

import argparse
import asyncio
import json
import math
import statistics
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from eval import provenance, retrieval_compare
from eval.corpus import EMBEDDING_TABLE, SYLLABUS_TABLE, canonical_sha256
from eval.metrics import GoldenCase
from eval.query_spec import load_specs
from eval.retrieval_metrics import (
    CONDITIONS,
    NEXT_STEP_MODE,
    PRIMARY_K,
    SECONDARY_K,
    GenerationRecord,
    RetrievalRecord,
    evaluate_hypotheses,
)
from eval.retrieval_report import _outside_in_evidence  # サマリーと同じ定義で数えるため

# §4.1「ほぼ一致」: ビット一致ではないが、34本すべてでコサイン類似度がこの値以上
NEAR_IDENTICAL_COSINE = 0.9999
# §4.3 の「H0〜H6 の判定が一致」に使う仮説（H7 は生成なので別に見る）
RETRIEVAL_HYPOTHESES = 7
SNAPSHOT_FIELDS = (
    ("retrieve", "corpus.postgres_rows_sha256"),
    ("retrieve", "corpus.postgres_rows"),
    ("retrieve", "corpus.seed_courses_json_sha256"),
    ("retrieve", "corpus.neo4j_graph_sha256"),
    ("retrieve", "corpus.neo4j_counts"),
    ("retrieve", "corpus.neo4j_version"),
    ("retrieve", "corpus.postgres_version"),
    ("retrieve", "corpus.pgvector_version"),
    ("retrieve", "corpus.document_embeddings_sha256"),
    ("retrieve", "corpus.query_embeddings_sha256"),
    ("retrieve", "specs_sha256"),
    ("retrieve", "golden_sha256"),
    ("retrieve", "exact_search"),
    ("retrieve", "embedding"),
    ("retrieve", "params"),
    ("retrieve", "python"),
    ("retrieve", "libraries"),
    ("generate", "model"),
    ("generate", "instruction_sha256"),
    ("generate", "generation_top_k"),
    ("generate", "per_run_llm_cap"),
    ("generate", "timeout_seconds"),
)
# スナップショットのうち、R2 で一致すると予測したもの（§4.2 P2）
P2_FIELDS = (
    "corpus.postgres_rows_sha256",
    "corpus.seed_courses_json_sha256",
    "corpus.neo4j_graph_sha256",
    "specs_sha256",
    "golden_sha256",
)
_NONE = "—"


# --- 検索の行の突き合わせ -------------------------------------------------------------


def _max_score_diff(base: RetrievalRecord, other: RetrievalRecord) -> float | None:
    """同じ科目コードどうしのスコアの差の絶対値の最大（共通の科目が無ければ None）。"""
    base_scores = {entry.code: entry.score for entry in base.ranked}
    other_scores = {entry.code: entry.score for entry in other.ranked}
    common = base_scores.keys() & other_scores.keys()
    if not common:
        return None
    return max(abs(base_scores[code] - other_scores[code]) for code in common)


def compare_rankings(base: Sequence[RetrievalRecord], other: Sequence[RetrievalRecord]) -> list[dict[str, Any]]:
    """（質問, 条件）ごとに、順位リスト・スコア・指標・evidence・クエリ数が一致するかを並べる。"""
    base_by = {(record.question_id, record.condition): record for record in base}
    other_by = {(record.question_id, record.condition): record for record in other}
    rows = []
    for key in sorted(base_by.keys() | other_by.keys()):
        a, b = base_by.get(key), other_by.get(key)
        row: dict[str, Any] = {"question_id": key[0], "condition": key[1], "present": a is not None and b is not None}
        if a is None or b is None:
            rows.append(row)
            continue
        row.update(
            {
                "codes_equal": a.codes == b.codes,
                "max_score_diff": _max_score_diff(a, b),
                "metrics_equal": a.scores == b.scores,
                "evidence_equal": [e.evidence for e in a.ranked] == [e.evidence for e in b.ranked],
                "queries_equal": (a.sql_queries, a.cypher_queries, a.raw_returned, a.anchor_removed)
                == (b.sql_queries, b.cypher_queries, b.raw_returned, b.anchor_removed),
                "identical_across_repeats": b.identical_across_repeats,
                "base_top5": a.codes[:PRIMARY_K],
                "other_top5": b.codes[:PRIMARY_K],
            }
        )
        rows.append(row)
    return rows


def ranking_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """compare_rankings の結果を条件別と全体に集計する。"""
    out: dict[str, dict[str, Any]] = {}
    for condition in (*CONDITIONS, "all"):
        own = [row for row in rows if condition == "all" or row["condition"] == condition]
        present = [row for row in own if row["present"]]
        diffs = [row["max_score_diff"] for row in present if row["max_score_diff"] is not None]
        out[condition] = {
            "rows": len(own),
            "present": len(present),
            "codes_equal": sum(1 for row in present if row["codes_equal"]),
            "metrics_equal": sum(1 for row in present if row["metrics_equal"]),
            "evidence_equal": sum(1 for row in present if row["evidence_equal"]),
            "queries_equal": sum(1 for row in present if row["queries_equal"]),
            "max_score_diff": max(diffs) if diffs else None,
        }
    return out


def all_rows_identical(rows: Sequence[Mapping[str, Any]]) -> bool:
    """P1: すべての行で順位・指標・evidence・クエリ数が一致し、スコアの差が 0。

    両方とも0件の行（unclear で C3 が何も返さないなど）はスコアの差が None になるので 0 とみなす。
    """
    return bool(rows) and all(
        row["present"]
        and row["codes_equal"]
        and row["metrics_equal"]
        and row["evidence_equal"]
        and row["queries_equal"]
        and (row["max_score_diff"] or 0) == 0
        for row in rows
    )


# --- 埋め込み ------------------------------------------------------------------------


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(math.fsum(x * x for x in a)) * math.sqrt(math.fsum(y * y for y in b))
    return dot / norm


def embedding_stats(base: Mapping[str, str], other: Mapping[str, str]) -> dict[str, Any]:
    """pgvector のテキスト表現どうしを、同じキー（科目コード・質問 ID）で突き合わせる。"""
    missing = sorted(base.keys() ^ other.keys())
    per_key: dict[str, dict[str, Any]] = {}
    for key in sorted(base.keys() & other.keys()):
        a, b = json.loads(base[key]), json.loads(other[key])
        per_key[key] = {
            "bitwise_equal": base[key] == other[key],
            "max_abs_diff": max(abs(x - y) for x, y in zip(a, b, strict=True)),
            "cosine": _cosine(a, b),
        }
    values = list(per_key.values())
    return {
        "compared": len(values),
        "missing": missing,
        "bitwise_equal": sum(1 for item in values if item["bitwise_equal"]),
        "max_abs_diff": max((item["max_abs_diff"] for item in values), default=None),
        "min_cosine": min((item["cosine"] for item in values), default=None),
        "per_key": per_key,
    }


def classify_embeddings(stats: Sequence[Mapping[str, Any]]) -> str:
    """§4.1: ビット一致 / ほぼ一致 / それ以外（文書と質問の両方を合わせて判定する）。"""
    if any(item["missing"] or item["compared"] == 0 for item in stats):
        return "それ以外"
    if all(item["bitwise_equal"] == item["compared"] for item in stats):
        return "ビット一致"
    if all(item["min_cosine"] >= NEAR_IDENTICAL_COSINE for item in stats):
        return "ほぼ一致"
    return "それ以外"


# --- 指標・生成・判定 -------------------------------------------------------------------


def _mean(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return statistics.fmean(present) if present else None


def condition_metrics(records: Sequence[RetrievalRecord], cases: Mapping[str, GoldenCase]) -> dict[str, dict[str, Any]]:
    """条件別の検索指標（検索系10問の平均・合計。前提違反は next_step 4問の合計）。"""
    out = {}
    for condition in CONDITIONS:
        own = [r for r in records if r.condition == condition and cases[r.question_id].is_search]
        next_step = [r for r in own if cases[r.question_id].mode == NEXT_STEP_MODE]
        primary, secondary = str(PRIMARY_K), str(SECONDARY_K)
        out[condition] = {
            "questions": len(own),
            "recall@5": _mean([r.scores[primary].recall for r in own]),
            "ndcg@5": _mean([r.scores[primary].ndcg for r in own]),
            "recall@10": _mean([r.scores[secondary].recall for r in own]),
            "ndcg@10": _mean([r.scores[secondary].ndcg for r in own]),
            "forbidden@5": sum(len(r.scores[primary].forbidden_hits) for r in own),
            "violations@5": sum(len(r.scores[primary].violations or []) for r in next_step),
            "returned@5": _mean([float(r.scores[primary].returned) for r in own]),
            "latency_ms_median": statistics.median([r.latency_ms_median for r in own]) if own else None,
        }
    return out


def generation_metrics(
    records: Sequence[GenerationRecord], retrieval: Sequence[RetrievalRecord]
) -> dict[str, dict[str, Any]]:
    by_key = {(r.condition, r.question_id): r for r in retrieval}
    out = {}
    for condition in CONDITIONS:
        own = [r for r in records if r.condition == condition]
        ok = [r for r in own if r.success and r.score is not None]
        out[condition] = {
            "success": len(ok),
            "runs": len(own),
            "unverified": sum(len(r.unverified_codes) for r in ok),
            "outside": sum(len(r.score.outside_candidates) for r in ok if r.score),
            "outside_in_evidence": sum(_outside_in_evidence(r, by_key) for r in ok),
            "recall": _mean([r.score.recall for r in ok if r.score]),
            "precision": _mean([r.score.precision for r in ok if r.score]),
            "forbidden": sum(len(r.score.forbidden_hits) for r in ok if r.score),
            "llm_requests": sum(r.llm_requests_all_attempts for r in own),
            "input_tokens": _mean([float(r.input_tokens) for r in ok]),
            "output_tokens": _mean([float(r.output_tokens) for r in ok]),
            "latency_s_median": statistics.median([r.latency_ms / 1000 for r in ok]) if ok else None,
            "model_versions": sorted({v for r in own for v in r.model_versions}),
        }
    return out


def cited_agreement(base: Sequence[GenerationRecord], other: Sequence[GenerationRecord]) -> dict[str, Any]:
    """（質問, 条件）ごとに、起点を除いた引用の集合が一致するか。"""

    def scored(records: Sequence[GenerationRecord]) -> dict[tuple[str, str], set[str]]:
        return {
            (r.question_id, r.condition): set(r.score.scored_codes)
            for r in records
            if r.success and r.score is not None
        }

    a, b = scored(base), scored(other)
    common = sorted(a.keys() & b.keys())
    differ = [
        {"question_id": qid, "condition": condition, "base": sorted(a[(qid, condition)]), "other": sorted(b[(qid, condition)])}
        for qid, condition in common
        if a[(qid, condition)] != b[(qid, condition)]
    ]
    return {"compared": len(common), "equal": len(common) - len(differ), "differ": differ}


def verdicts(
    retrieval: Sequence[RetrievalRecord],
    generation: Sequence[GenerationRecord],
    cases: Mapping[str, GoldenCase],
    spec_matches: Mapping[str, bool],
) -> list[dict[str, str]]:
    return [v.model_dump() for v in evaluate_hypotheses(retrieval, generation, cases, spec_matches)]


# --- manifest -----------------------------------------------------------------------


def _get(data: Mapping[str, Any] | None, dotted: str) -> Any:
    value: Any = data
    for part in dotted.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def main_session(sessions: Sequence[Mapping[str, Any]], command: str, output: str | None = None) -> Mapping[str, Any] | None:
    """最後に成功した command のセッション。生成は本実行（output が結果ファイル）に限る（煙テストを除く）。"""
    found = [
        item
        for item in sessions
        if item.get("command") == command
        and item.get("aborted") is False
        and (output is None or item.get("output") == output)
    ]
    return found[-1] if found else None


def snapshot_rows(runs: Mapping[str, Mapping[str, Mapping[str, Any] | None]]) -> list[dict[str, Any]]:
    """runs: 実行名 → {"retrieve": セッション, "generate": セッション}。元の値と各実行の値が一致するかを並べる。"""
    rows = []
    names = list(runs)
    for command, field in SNAPSHOT_FIELDS:
        values = {name: _get(runs[name].get(command), field) for name in names}
        base = values[names[0]]
        rows.append(
            {
                "field": f"{command}.{field}",
                "values": values,
                "equal": {name: (None if values[name] is None else values[name] == base) for name in names[1:]},
            }
        )
    return rows


def provenance_rows(
    sessions: Sequence[Mapping[str, Any]], tree: Mapping[str, Any] | None, commit: str | None
) -> list[dict[str, Any]]:
    """各セッションの HEAD・clean・ソースの指紋が、渡した commit と git の木に一致するか。"""
    rows = []
    for item in sessions:
        source = item.get("source_tree")
        rows.append(
            {
                "command": item.get("command"),
                "run_id": item.get("run_id"),
                "aborted": item.get("aborted"),
                "git_sha": item.get("git_sha"),
                "sha_matches": None if commit is None else item.get("git_sha") == commit,
                "clean": item.get("git_status_clean"),
                "source_files": source.get("files") if source else None,
                "source_sha256": source.get("sha256") if source else None,
                "source_matches": (
                    None
                    if source is None or tree is None
                    else (source.get("sha256"), source.get("files")) == (tree["sha256"], tree["files"])
                ),
                "eval_db": item.get("eval_db"),
            }
        )
    return rows


def provenance_verified(rows: Sequence[Mapping[str, Any]]) -> bool:
    return bool(rows) and all(
        row["sha_matches"] is True and row["clean"] is True and row["source_matches"] is True for row in rows
    )


# --- DB ---------------------------------------------------------------------------------


async def read_embeddings(database: str) -> dict[str, Any]:
    """実験用 DB の1つのデータベースから、文書と質問の埋め込みのテキスト表現を読む（読み取りのみ）。"""
    pool = await retrieval_compare.connect_eval_db(database)
    try:
        async with pool.acquire() as conn:
            docs = await conn.fetch(
                f"SELECT s.code, e.embedding::text AS v FROM {EMBEDDING_TABLE} e "
                f"JOIN {SYLLABUS_TABLE} s ON s.id = e.course_id ORDER BY s.code"
            )
            queries = await conn.fetch(
                "SELECT question_id, embedding::text AS v FROM eval_query_embeddings ORDER BY question_id"
            )
    finally:
        await pool.close()
    return {
        "documents": {row["code"]: row["v"] for row in docs},
        "queries": {row["question_id"]: row["v"] for row in queries},
        # retrieve が manifest に残すのと同じ式（corpus_snapshot）
        "documents_sha256": canonical_sha256([dict(row) for row in docs]),
        "queries_sha256": canonical_sha256([dict(row) for row in queries]),
    }


# --- 出力 --------------------------------------------------------------------------------


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return _NONE
    if isinstance(value, bool):
        return "一致" if value else "不一致"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _sci(value: float | None) -> str:
    return _NONE if value is None else f"{value:.3g}"


def _row(cells: Sequence[object]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
    return text if len(text) <= 40 else text[:16] + "…"


def render_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# 検索方式比較（シード）の再現実行の突き合わせ",
        "",
        "`python -m eval.replication_compare` が生成した。事前登録は `eval/prereg_retrieval_seed_replication.md`。",
        "元 = 元の実行（`2026-10-13_retrieval_seed.jsonl`）、R1 = 元の埋め込みのまま検索だけを流し直したもの、"
        "R2 = 新しいデータベースで setup-db から生成までをやり直したもの。",
        "",
        "## 1. 出所",
        "",
        f"git の木: commit {result['ls_tree_commit']}、`git ls-tree --full-tree -r -z <commit> -- backend` から作った指紋 "
        f"{result['git_tree']['files']} ファイル、sha256 {result['git_tree']['sha256'][:16]}…",
        "",
        _row(["実行", "コマンド", "run_id", "途中終了", "git_sha が commit と一致", "clean", "ソースの指紋が git の木と一致", "実験用 DB"]),
        _row(["---"] * 8),
    ]
    for run in ("R1", "R2"):
        for row in result["provenance"][run]:
            db = row["eval_db"] or {}
            lines.append(
                _row(
                    [run, row["command"], row["run_id"], row["aborted"], _fmt(row["sha_matches"]), row["clean"],
                     _fmt(row["source_matches"]), db.get("name", _NONE)]
                )
            )
    lines += [
        "",
        "列の意味: git_sha は実行時にホストで取った HEAD。clean はホストの `git status --porcelain` に、eval/results/ の未追跡の結果以外が無かったこと"
        "（あればハーネスが実行を拒む）。ソースの指紋は、コンテナから見えた backend 配下のファイル（隠しファイル・"
        "キャッシュ・logs/・eval/results/ を除く）の git blob SHA-1 の一覧の SHA-256 で、git の木から同じ規則で作った値と比べた。",
        f"元の実行のセッションには指紋が無い（git_sha は {result['original_git_shas']}、`code_commit` の注記のみ）。",
        "",
        "## 2. スナップショット（manifest の値）",
        "",
        _row(["項目", "元", "R1 は元と", "R2 は元と"]),
        _row(["---"] * 4),
    ]
    for row in result["snapshot"]:
        lines.append(
            _row([row["field"], _short(row["values"]["original"]), _fmt(row["equal"].get("R1")), _fmt(row["equal"].get("R2"))])
        )
    lines += [
        "",
        "「—」はその実行にその記録が無いこと（R1 は生成をしていない）。",
        "",
        "## 3. 埋め込み（R2 対 元）",
        "",
        _row(["種類", "本数", "ビット一致", "要素の差の絶対値の最大", "コサイン類似度の最小", "対応の取れないキー"]),
        _row(["---"] * 6),
    ]
    for kind, label in (("documents", "文書"), ("queries", "質問")):
        stats = result["embeddings"][kind]
        lines.append(
            _row([label, stats["compared"], stats["bitwise_equal"], _sci(stats["max_abs_diff"]),
                  _fmt(stats["min_cosine"], 9), stats["missing"] or "なし"])
        )
    db_hash = result["embeddings"]["db_hashes"]
    lines += [
        "",
        f"分類（§4.1）: **{result['embeddings']['classification']}**（ほぼ一致の閾値はコサイン類似度 {NEAR_IDENTICAL_COSINE}）。",
        f"DB と manifest の対応: 元の DB の埋め込みのハッシュが元の manifest と {_fmt(db_hash['original_matches_manifest'])}、"
        f"R2 の DB が R2 の manifest と {_fmt(db_hash['replication_matches_manifest'])}。"
        "（ハッシュは retrieve が manifest に残すのと同じ式で、DB の中身が記録に使われたものと同じことを示す。）",
        "",
        "## 4. 検索の順位（56行 = 14問×4条件）",
        "",
        _row(["比較", "条件", "行", "順位リスト一致", "指標一致", "evidence 一致", "クエリ数一致", "スコアの差の最大"]),
        _row(["---"] * 8),
    ]
    for run in ("R1", "R2"):
        for condition, item in result["rankings"][run]["summary"].items():
            lines.append(
                _row([f"{run} 対 元", condition, item["present"], item["codes_equal"], item["metrics_equal"],
                      item["evidence_equal"], item["queries_equal"], _sci(item["max_score_diff"])])
            )
    lines += [
        "",
        "列の意味: 順位リスト一致は、起点を除いた上位10件の科目コードの列が順序も含めて同じ行の数。指標一致は K=5・10 の"
        "Recall・NDCG・forbidden・前提違反などがすべて同じ行の数。evidence は LLM に渡す根拠文（C1・C2 は類似度を小数3桁で含む）。"
        "クエリ数一致は SQL・Cypher の本数と、起点を除く前の件数が同じ行の数。スコアの差は同じ科目コードどうしの差の絶対値の最大"
        "（C1・C2 はコサイン類似度、C3 はグラフ探索の値、C4 は RRF の値）。",
        "",
    ]
    for run in ("R1", "R2"):
        differ = [row for row in result["rankings"][run]["rows"] if not (row["present"] and row["codes_equal"])]
        if differ:
            lines += [f"{run} で順位リストが違った行:", ""]
            lines += [f"- {row['question_id']} {row['condition']}: 元 {row.get('base_top5')} / {run} {row.get('other_top5')}" for row in differ]
            lines += [""]
    lines += [
        "## 5. 検索の指標（条件別。検索系10問の平均、forbidden は合計、前提違反は next_step 4問の合計）",
        "",
        _row(["条件", "実行", "Recall@5", "NDCG@5", "Recall@10", "NDCG@10", "forbidden@5", "前提違反@5", "返却件数@5", "所要時間 中央値 ms"]),
        _row(["---"] * 10),
    ]
    for condition in CONDITIONS:
        for run in ("original", "R1", "R2"):
            item = result["metrics"][run][condition]
            lines.append(
                _row([condition, run, _fmt(item["recall@5"]), _fmt(item["ndcg@5"]), _fmt(item["recall@10"]),
                      _fmt(item["ndcg@10"]), item["forbidden@5"], item["violations@5"], _fmt(item["returned@5"], 1),
                      _fmt(item["latency_ms_median"], 1)])
            )
    lines += [
        "",
        "所要時間は環境で変わるので判定に使わない（記述のみ）。",
        "",
        "## 6. 仮説の判定（元の登録 §6 を同じ関数で適用）",
        "",
        _row(["仮説", "元", "R1", "R2"]),
        _row(["---"] * 4),
    ]
    for index, verdict in enumerate(result["verdicts"]["original"]):
        lines.append(
            _row([verdict["hypothesis"], verdict["label"], result["verdicts"]["R1"][index]["label"],
                  result["verdicts"]["R2"][index]["label"]])
        )
    lines += [
        "",
        "R1 は生成をしていないので H7 は「判定不能」になる。根拠の数値は JSON の verdicts にある。",
        "",
        "## 7. 生成（検索系10問×4条件。元 / R2）",
        "",
        _row(["条件", "実行", "成功", "未検証コード", "候補外の引用", "うち根拠文に現れる", "recall", "precision", "forbidden",
              "LLM 回数", "入力トークン", "出力トークン", "所要時間 中央値 s", "model_version"]),
        _row(["---"] * 14),
    ]
    for condition in CONDITIONS:
        for run in ("original", "R2"):
            item = result["generation"][run][condition]
            lines.append(
                _row([condition, run, f"{item['success']}/{item['runs']}", item["unverified"], item["outside"],
                      item["outside_in_evidence"], _fmt(item["recall"]), _fmt(item["precision"]), item["forbidden"],
                      item["llm_requests"], _fmt(item["input_tokens"], 0), _fmt(item["output_tokens"], 0),
                      _fmt(item["latency_s_median"], 1), ", ".join(item["model_versions"]) or _NONE])
            )
    agreement = result["generation"]["cited_agreement"]
    lines += [
        "",
        "列の意味: 未検証コードは引用したコードのうち実験用 DB に行が無いもの。候補外の引用は、起点以外で LLM に渡した5件に無いコードの数。"
        "recall・precision・forbidden は起点を除いた引用を golden と突き合わせたもの（平均・合計）。LLM 回数はやり直しを含む合計。",
        f"起点を除いた引用の集合が元と R2 で一致した（質問, 条件）: {agreement['equal']}/{agreement['compared']}。生成は同じ入力でも揺れるので記述のみ。",
        "",
        "## 8. 予測の照合と結論（事前登録 §4.2・§4.3）",
        "",
        _row(["項目", "結果", "根拠"]),
        _row(["---"] * 3),
    ]
    for item in result["predictions"]:
        lines.append(_row([item["name"], item["result"], item["detail"]]))
    lines += [""]
    for item in result["conclusions"]:
        lines.append(f"- {item['name']}: **{'成り立つ' if item['holds'] else '成り立たない'}**（{item['detail']}）")
    lines += [""]
    return "\n".join(lines)


# --- 組み立て --------------------------------------------------------------------------


def _ok(value: bool) -> str:
    return "成り立つ" if value else "成り立たない"


def evaluate(result: dict[str, Any]) -> None:
    """§4.2 の予測と §4.3 の結論を機械的に判定し、result に足す。"""
    r1_rows = result["rankings"]["R1"]["rows"]
    r2_rows = result["rankings"]["R2"]["rows"]
    r2_summary = result["rankings"]["R2"]["summary"]
    p1 = all_rows_identical(r1_rows)
    p2_rows = [row for row in result["snapshot"] if row["field"].removeprefix("retrieve.") in P2_FIELDS]
    p2 = all(row["equal"].get("R2") is True for row in p2_rows)
    graph_rows = [row for row in r2_rows if row["condition"] == "pure_graph"]
    graph_equal = all(row["present"] and row["codes_equal"] and row["metrics_equal"] for row in graph_rows)
    classification = result["embeddings"]["classification"]
    r2_codes_all = r2_summary["all"]["codes_equal"] == r2_summary["all"]["rows"] == len(r2_rows) > 0
    labels = {run: [v["label"] for v in result["verdicts"][run][:RETRIEVAL_HYPOTHESES]] for run in ("original", "R2")}
    h0_h6_equal = labels["original"] == labels["R2"]
    gen = result["generation"]["R2"]
    runs = sum(item["runs"] for item in gen.values())
    success = sum(item["success"] for item in gen.values())
    unverified = sum(item["unverified"] for item in gen.values())
    outside = sum(item["outside"] for item in gen.values())
    outside_in_evidence = sum(item["outside_in_evidence"] for item in gen.values())
    expected_runs = len(CONDITIONS) * result["search_questions"]
    p5 = runs == success == expected_runs and unverified == 0 and outside == outside_in_evidence
    if classification in ("ビット一致", "ほぼ一致"):
        p4 = graph_equal and r2_codes_all and h0_h6_equal
        p4_text = _ok(p4)
    else:
        p4 = graph_equal
        p4_text = f"C3 のみ照合: {_ok(graph_equal)}（埋め込みが{classification}なので残りは予測なし）"
    provenance_ok = provenance_verified(result["provenance"]["R1"]) and provenance_verified(result["provenance"]["R2"])
    result["predictions"] = [
        {"name": "P1 R1 の56行が元と完全一致", "result": _ok(p1),
         "detail": f"順位一致 {result['rankings']['R1']['summary']['all']['codes_equal']}/{len(r1_rows)}、"
                   f"スコアの差の最大 {_sci(result['rankings']['R1']['summary']['all']['max_score_diff'])}"},
        {"name": "P2 R2 のコーパス・QuerySpec・golden のハッシュが元と一致", "result": _ok(p2),
         "detail": ", ".join(f"{row['field']}={_fmt(row['equal'].get('R2'))}" for row in p2_rows)},
        {"name": "P3 R2 の埋め込み（予測なし）", "result": classification,
         "detail": f"文書 {result['embeddings']['documents']['bitwise_equal']}/{result['embeddings']['documents']['compared']}・"
                   f"質問 {result['embeddings']['queries']['bitwise_equal']}/{result['embeddings']['queries']['compared']} がビット一致"},
        {"name": "P4 R2 の検索（C3 は無条件、残りは埋め込みがビット一致かほぼ一致のとき）", "result": p4_text,
         "detail": f"C3 一致 {sum(1 for r in graph_rows if r['present'] and r['codes_equal'])}/{len(graph_rows)}、"
                   f"全体の順位一致 {r2_summary['all']['codes_equal']}/{len(r2_rows)}、H0〜H6 の判定 {'一致' if h0_h6_equal else '不一致'}"},
        {"name": "P5 R2 の生成で未検証コード0・候補外の引用はすべて根拠文に現れる", "result": _ok(p5),
         "detail": f"成功 {success}/{runs}、未検証 {unverified}、候補外 {outside}（うち根拠文 {outside_in_evidence}）"},
        {"name": "出所（R1・R2 の全セッションで HEAD・clean・指紋が git の木と一致）", "result": _ok(provenance_ok),
         "detail": f"commit {result['ls_tree_commit']}"},
    ]
    stands = p1 and provenance_ok
    reproduced = stands and r2_codes_all and h0_h6_equal and p5
    result["conclusions"] = [
        {"name": "元の検索の結果はコミット済みのコードで成り立つ", "holds": stands, "detail": "P1 と出所の照合"},
        {"name": "元の結果は再現した", "holds": reproduced,
         "detail": "上に加えて、R2 の56行の順位リストが一致・H0〜H6 の判定が一致・P5"},
    ]


async def build(args: argparse.Namespace) -> dict[str, Any]:
    cases = retrieval_compare.load_golden()
    specs = load_specs(args.specs)
    spec_matches = {spec.question_id: retrieval_compare.spec_matches_golden(spec, cases[spec.question_id]) for spec in specs}
    paths = {"original": args.original, "R1": args.rerun, "R2": args.replication}
    records = {name: retrieval_compare.load_records(path) for name, path in paths.items()}
    sessions = {
        name: retrieval_compare._load_sessions(retrieval_compare.manifest_path(path)) for name, path in paths.items()
    }
    ls_tree = sys.stdin.buffer.read().decode("utf-8") if str(args.ls_tree) == "-" else args.ls_tree.read_text("utf-8")
    tree = provenance.fingerprint_from_ls_tree(ls_tree)
    original_db = await read_embeddings(args.original_db)
    replication_db = await read_embeddings(args.replication_db)
    main_sessions = {
        name: {
            "retrieve": main_session(sessions[name], "retrieve"),
            "generate": main_session(sessions[name], "generate", paths[name].name),
        }
        for name in paths
    }
    original_corpus = _get(main_sessions["original"]["retrieve"], "corpus") or {}
    replication_corpus = _get(main_sessions["R2"]["retrieve"], "corpus") or {}
    result: dict[str, Any] = {
        "inputs": {name: str(path) for name, path in paths.items()},
        "databases": {"original": args.original_db, "replication": args.replication_db},
        "ls_tree_commit": args.ls_tree_commit,
        "search_questions": sum(1 for case in cases.values() if case.is_search),
        "git_tree": tree,
        "original_git_shas": sorted({item.get("git_sha") for item in sessions["original"]}),
        "provenance": {
            name: provenance_rows(sessions[name], tree, args.ls_tree_commit) for name in ("R1", "R2")
        },
        "snapshot": snapshot_rows(main_sessions),
        "embeddings": {
            "documents": embedding_stats(original_db["documents"], replication_db["documents"]),
            "queries": embedding_stats(original_db["queries"], replication_db["queries"]),
            "db_hashes": {
                "original_matches_manifest": (original_db["documents_sha256"], original_db["queries_sha256"])
                == (original_corpus.get("document_embeddings_sha256"), original_corpus.get("query_embeddings_sha256")),
                "replication_matches_manifest": (replication_db["documents_sha256"], replication_db["queries_sha256"])
                == (replication_corpus.get("document_embeddings_sha256"), replication_corpus.get("query_embeddings_sha256")),
            },
        },
        "rankings": {},
        "metrics": {name: condition_metrics(records[name][0], cases) for name in paths},
        "verdicts": {name: verdicts(records[name][0], records[name][1], cases, spec_matches) for name in paths},
        "generation": {
            "original": generation_metrics(records["original"][1], records["original"][0]),
            "R2": generation_metrics(records["R2"][1], records["R2"][0]),
            "cited_agreement": cited_agreement(records["original"][1], records["R2"][1]),
        },
    }
    result["embeddings"]["classification"] = classify_embeddings(
        [result["embeddings"]["documents"], result["embeddings"]["queries"]]
    )
    for name in ("R1", "R2"):
        rows = compare_rankings(records["original"][0], records[name][0])
        result["rankings"][name] = {"summary": ranking_summary(rows), "rows": rows}
    evaluate(result)
    return result


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m eval.replication_compare", description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--rerun", type=Path, required=True, help="R1（元の埋め込みのまま検索だけを流し直した結果）")
    parser.add_argument("--replication", type=Path, required=True, help="R2（最初からの再現実行の結果）")
    parser.add_argument("--ls-tree", type=Path, required=True, help="git ls-tree --full-tree -r -z <commit> -- backend の出力（- で標準入力）")
    parser.add_argument("--ls-tree-commit", required=True)
    parser.add_argument("--original-db", required=True)
    parser.add_argument("--replication-db", required=True)
    parser.add_argument("--specs", type=Path, default=retrieval_compare.DEFAULT_SPECS)
    parser.add_argument("--out", type=Path, required=True, help="拡張子なしのパス。.md と .json を書く")
    args = parser.parse_args(argv)
    result = asyncio.run(build(args))
    args.out.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    args.out.with_suffix(".md").write_text(render_markdown(result), "utf-8")
    for item in result["predictions"]:
        print(f"{item['name']}: {item['result']}（{item['detail']}）")
    for item in result["conclusions"]:
        print(f"{item['name']}: {'成り立つ' if item['holds'] else '成り立たない'}")


if __name__ == "__main__":
    main(sys.argv[1:])
