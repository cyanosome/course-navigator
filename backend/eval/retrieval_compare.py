"""検索方式比較（シード）の実行ハーネス（prereg_retrieval_seed.md の実装）。

backend コンテナの /backend_app で実行する。実験用 DB の接続先は EVAL_DB_* で渡す（dev の DB_* は使わない）:

    uv run --no-sync python -m eval.retrieval_compare setup-db --manifest <m.json> --git-sha <sha>
    uv run --no-sync python -m eval.retrieval_compare embed-docs --manifest <m.json> --git-sha <sha>
    uv run --no-sync python -m eval.retrieval_compare embed-queries --manifest <m.json> --git-sha <sha>
    uv run --no-sync python -m eval.retrieval_compare retrieve --out <r.jsonl> --git-sha <sha>
    uv run --no-sync python -m eval.retrieval_compare generate --input <r.jsonl> [--out <g.jsonl>] --git-sha <sha>
    uv run --no-sync python -m eval.retrieval_compare summarize --input <r.jsonl>

manifest は既定で <r.jsonl> と同じ場所の <stem>_manifest.json。全コマンドの LLM・埋め込みのリクエスト数を
sessions に積み、§7 の予算（LLM 150 回・埋め込み 100 回）の残りをそこから計算する。
本番コードの挙動は変えない（traversal・rank・grounding・compose_agent は呼ぶだけ）。
"""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import statistics
import sys
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import asyncpg
from google import genai
from google.adk import Workflow
from neo4j import AsyncDriver, AsyncGraphDatabase

from agent import runner
from agent.compose_agent import build_compose_agent
from agent.grounding import build_grounded_answer, normalize_codes
from agent.schemas import AnswerPayload
from course_core import config
from course_core.repositories import postgres_repo
from eval import node_compare, retrieval_report
from eval.corpus import (
    EMBEDDING_TABLE,
    SEED_PATH,
    SYLLABUS_TABLE,
    Corpus,
    canonical_sha256,
    document_body,
    file_sha256,
    load_seed_corpus,
)
from eval.embeddings import (
    DOCUMENT_TEMPLATE,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    QUERY_TEMPLATE,
    Embedder,
    format_document,
    format_query,
    vector_literal,
)
from eval.metrics import GoldenCase
from eval.node_compare import BudgetExhausted, LlmMeter
from eval.query_spec import QuerySpec, load_specs
from eval.retrieval_metrics import (
    CONDITIONS,
    PRIMARY_K,
    SECONDARY_K,
    GenerationRecord,
    RankedEntry,
    RetrievalRecord,
    score_generation,
    score_retrieval,
)
from eval.retrievers import (
    CREATE_FULLTEXT_INDEX,
    FULLTEXT_ANALYZER,
    FULLTEXT_INDEX,
    HYBRID_ENTRY_COUNT,
    REGISTRY,
    RRF_K,
    QueryCounter,
    RankedItem,
    RetrievalBackends,
    exclude_anchor,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = BACKEND_ROOT / "tests" / "golden" / "questions.json"
DEFAULT_SPECS = BACKEND_ROOT / "eval" / "specs" / "seed_query_specs.json"

# §7 予算（このタスク全体。manifest の sessions に積んだ使用量を差し引く）
LLM_BUDGET_TOTAL = 150
EMBEDDING_BUDGET_TOTAL = 100
# §3.4 / §3.5
RETRIEVE_DEPTH = SECONDARY_K + 1  # 起点を除いてから10件に切るので1件多く取る
REPEATS = 5
GENERATION_TOP_K = PRIMARY_K
PER_RUN_LLM_CAP = 3
GENERATION_TIMEOUT_SECONDS = 120
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 30
EXPECTED_COURSES = 20
LIBRARIES = ("google-adk", "google-genai", "asyncpg", "neo4j")
MERGE_INFO = {
    "base_branch": "dev/akiha_node-eval",
    "merged_branch": "origin/test/vector-graph-eval",
    "merged_head": "9766c06",
    "note": "pgvector の Dockerfile・init SQL・test_course_embeddings の DDL・実験計画書を取り込んだ",
}
EVAL_DB_DEFAULTS = {"EVAL_DB_PORT": "5432", "EVAL_DB_NAME": "coursenavigator_eval", "EVAL_DB_USER": "eval"}
EVAL_DB_REQUIRED = ("EVAL_DB_HOST", "EVAL_DB_PASSWORD")

# §3.5 の指示文（事前登録に本文を凍結してある。変えるなら逸脱として記録する）。
GENERATION_INSTRUCTION = """\
あなたは大学の履修選択を支援する「履修アドバイザーAI（Course Navigator）」です。
入力は、検索部が返した候補科目の JSON（question、intent、candidates）です。あなたはツールを使えません。

1. 回答の根拠にしてよいのは入力 JSON の内容（question、intent、candidates の code / title / evidence）だけです。入力に無い科目を挙げたり、科目間の関係を推測で補ったりしてはいけません。
2. 「楽単」「単位が取りやすい」「おすすめ」「先生が厳しい」といった主観的・非公式な評価は述べないでください。
3. 回答文中で言及した科目の科目コードは、必ず cited_codes フィールドに漏れなくリストアップしてください。
4. 回答は日本語で、結論を先に書き、各候補を「科目名 [科目コード]」の形で挙げて evidence の内容を根拠として添えてください。
5. candidates が空のときは、該当する科目が見つからなかったことを伝えてください。
"""

CREATE_QUERY_EMBEDDINGS = f"""
CREATE TABLE IF NOT EXISTS eval_query_embeddings (
    question_id TEXT PRIMARY KEY,
    text_sha256 TEXT NOT NULL,
    model TEXT NOT NULL,
    dims INTEGER NOT NULL,
    embedding vector({EMBEDDING_DIMENSIONS}) NOT NULL,
    raw_norm DOUBLE PRECISION NOT NULL,
    latency_ms INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
CREATE_DOCUMENT_META = f"""
CREATE TABLE IF NOT EXISTS eval_document_embedding_meta (
    course_id UUID PRIMARY KEY REFERENCES {SYLLABUS_TABLE}(id) ON DELETE CASCADE,
    text_sha256 TEXT NOT NULL,
    model TEXT NOT NULL,
    dims INTEGER NOT NULL,
    raw_norm DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class Session:
    """manifest の1セッション（1コマンドの実行）。終わったら必ず finished_at を書く。"""

    def __init__(self, path: Path, command: str, git_sha: str) -> None:
        self.path = path
        self.data: dict[str, Any] = {
            "command": command,
            "run_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
            "started_at": _now(),
            "finished_at": None,
            "git_sha": git_sha,
            "merge": MERGE_INFO,
            "llm_requests": 0,
            "embedding_requests": 0,
            "embedding_texts": 0,
            "aborted": None,
        }

    def remaining(self) -> tuple[int, int]:
        sessions = _load_sessions(self.path)
        used_llm = sum(int(item.get("llm_requests", 0)) for item in sessions)
        used_embedding = sum(int(item.get("embedding_requests", 0)) for item in sessions)
        return LLM_BUDGET_TOTAL - used_llm, EMBEDDING_BUDGET_TOTAL - used_embedding

    def finish(self) -> None:
        """finally から呼ぶ。成功の印（aborted=False）が付いていなければ途中で止まったとみなす。"""
        self.data["finished_at"] = _now()
        if self.data["aborted"] is None:
            self.data["aborted"] = True
        self.save()

    def save(self) -> None:
        sessions = [item for item in _load_sessions(self.path) if item.get("run_id") != self.data["run_id"]]
        sessions.append(self.data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"experiment": "retrieval_seed", "sessions": sessions}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")


def _load_sessions(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text("utf-8"))["sessions"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- 接続 -------------------------------------------------------------------------


# §3.4: HNSW を使わず厳密検索にする（pgvector README の enable_indexscan = off）。
# プールは接続を返すたびに RESET ALL するので、SET ではなく接続の起動パラメータで渡す
# （起動パラメータはセッションの既定値になり、RESET ALL のあとも残る）。
EXACT_SEARCH_SETTINGS = {"enable_indexscan": "off"}


async def connect_eval_db() -> asyncpg.Pool:
    missing = [name for name in EVAL_DB_REQUIRED if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"実験用 DB の環境変数が未設定です: {missing}")
    host = os.environ["EVAL_DB_HOST"]
    if host == config.DB_HOST:
        raise SystemExit("EVAL_DB_HOST が dev の DB_HOST と同じです。dev の DB には接続しません")
    settings = {name: os.environ.get(name, default) for name, default in EVAL_DB_DEFAULTS.items()}
    return await asyncpg.create_pool(
        host=host,
        port=int(settings["EVAL_DB_PORT"]),
        database=settings["EVAL_DB_NAME"],
        user=settings["EVAL_DB_USER"],
        password=os.environ["EVAL_DB_PASSWORD"],
        server_settings=EXACT_SEARCH_SETTINGS,
        min_size=1,
        max_size=2,
    )


def connect_neo4j() -> AsyncDriver:
    config.validate_required_env()
    return AsyncGraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))


async def _cypher(driver: AsyncDriver, query: str, **params: Any) -> list[dict[str, Any]]:
    async with driver.session() as session:
        result = await session.run(query, params)
        return await result.data()


# --- スナップショット -----------------------------------------------------------------


async def load_corpus(pool: asyncpg.Pool) -> Corpus:
    async with pool.acquire() as conn:
        corpus = await load_seed_corpus(conn)
    if len(corpus.courses) != EXPECTED_COURSES:
        raise SystemExit(f"科目数がシードの {EXPECTED_COURSES} と違います: {len(corpus.courses)}")
    return corpus


async def neo4j_snapshot(driver: AsyncDriver) -> dict[str, Any]:
    nodes = await _cypher(driver, "MATCH (c:Course) RETURN c.id AS id, c.code AS code, c.title AS title ORDER BY code")
    prereqs = await _cypher(
        driver,
        "MATCH (a:Course)-[:REQUIRES_PREREQUISITE]->(b:Course) RETURN a.code AS course, b.code AS prereq "
        "ORDER BY course, prereq",
    )
    topics = await _cypher(
        driver,
        "MATCH (c:Course)-[:COVERS_TOPIC]->(t:Topic) RETURN c.code AS course, t.name AS topic ORDER BY course, topic",
    )
    version = await _cypher(driver, "CALL dbms.components() YIELD versions, edition RETURN versions[0] AS v, edition")
    return {"nodes": nodes, "prereqs": prereqs, "topics": topics, "version": version[0]}


def check_graph_matches_corpus(graph: dict[str, Any], corpus: Corpus) -> None:
    """Neo4j の Course.id が実験用 DB の id と一致し、前提関係が seed と同じことを確かめる。"""
    ids = {node["code"]: node["id"] for node in graph["nodes"]}
    db_ids = {course.code: course.id for course in corpus.courses}
    if ids != db_ids:
        raise SystemExit("Neo4j の Course.id と実験用 DB の id が一致しません")
    edges = {(edge["course"], edge["prereq"]) for edge in graph["prereqs"]}
    seed_edges = {(course.code, prereq) for course in corpus.courses for prereq in course.prerequisite_codes}
    if edges != seed_edges:
        raise SystemExit("Neo4j の前提関係が seed/courses.json と一致しません")


async def corpus_snapshot(pool: asyncpg.Pool, driver: AsyncDriver, corpus: Corpus) -> dict[str, Any]:
    graph = await neo4j_snapshot(driver)
    check_graph_matches_corpus(graph, corpus)
    async with pool.acquire() as conn:
        doc_vectors = await conn.fetch(
            f"SELECT s.code, e.embedding::text AS v FROM {EMBEDDING_TABLE} e "
            f"JOIN {SYLLABUS_TABLE} s ON s.id = e.course_id ORDER BY s.code"
        )
        query_vectors = await conn.fetch(
            "SELECT question_id, embedding::text AS v FROM eval_query_embeddings ORDER BY question_id"
        )
        versions = await conn.fetchrow(
            "SELECT version() AS pg, (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS pgvector"
        )
    return {
        "postgres_rows_sha256": canonical_sha256(corpus.row_snapshot()),
        "postgres_rows": len(corpus.courses),
        "seed_courses_json_sha256": file_sha256(SEED_PATH),
        "neo4j_graph_sha256": canonical_sha256(
            {key: graph[key] for key in ("nodes", "prereqs", "topics")}
        ),
        "neo4j_counts": {key: len(graph[key]) for key in ("nodes", "prereqs", "topics")},
        "neo4j_version": graph["version"],
        "document_embeddings_sha256": canonical_sha256([dict(row) for row in doc_vectors]),
        "document_embeddings": len(doc_vectors),
        "query_embeddings_sha256": canonical_sha256([dict(row) for row in query_vectors]),
        "query_embeddings": len(query_vectors),
        "postgres_version": versions["pg"],
        "pgvector_version": versions["pgvector"],
    }


async def check_exact_search_plan(pool: asyncpg.Pool) -> dict[str, Any]:
    """§3.4: ベクトル検索の SQL が HNSW を使わない計画になることを EXPLAIN で確かめる。

    プールが返却時に RESET ALL するので、取得し直しても設定が残ることまで見るために2回確かめる。
    """
    zero = vector_literal([0.0] * (EMBEDDING_DIMENSIONS - 1) + [1.0])
    sql = (
        f"EXPLAIN (FORMAT JSON) SELECT s.code FROM {EMBEDDING_TABLE} e JOIN {SYLLABUS_TABLE} s "
        "ON s.id = e.course_id ORDER BY e.embedding <=> $1::vector ASC, s.code ASC LIMIT 11"
    )
    node_types: set[str] = set()
    settings: list[str] = []
    for _ in range(2):
        async with pool.acquire() as conn:
            plan = await conn.fetchval(sql, zero)
            settings.append(await conn.fetchval("SHOW enable_indexscan"))
        plan_text = json.dumps(plan) if not isinstance(plan, str) else plan
        if "idx_course_embeddings_hnsw" in plan_text:
            raise SystemExit("ベクトル検索が HNSW インデックスを使う計画になっています（厳密検索になっていない）")
        node_types.update(_plan_node_types(json.loads(plan_text)))
    return {"enable_indexscan": settings, "uses_hnsw_index": False, "plan_node_types": sorted(node_types)}


def _plan_node_types(plan: Any) -> list[str]:
    if isinstance(plan, list):
        return [name for item in plan for name in _plan_node_types(item)]
    if isinstance(plan, dict):
        own = [plan["Node Type"]] if "Node Type" in plan else []
        return own + [name for value in plan.values() for name in _plan_node_types(value)]
    return []


def library_versions() -> dict[str, str]:
    return {name: metadata.version(name) for name in LIBRARIES}


# --- setup-db ------------------------------------------------------------------------


async def setup_db(args: argparse.Namespace) -> None:
    session = Session(args.manifest, "setup-db", args.git_sha)
    pool = await connect_eval_db()
    driver = connect_neo4j()
    try:
        async with pool.acquire() as conn:
            await conn.execute(postgres_repo.ENABLE_VECTOR_EXTENSION)
            await conn.execute(postgres_repo.CREATE_TEST_COURSE_EMBEDDINGS)
            await conn.execute(postgres_repo.CREATE_HNSW_INDEX)
            await conn.execute(CREATE_QUERY_EMBEDDINGS)
            await conn.execute(CREATE_DOCUMENT_META)
        corpus = await load_corpus(pool)
        await _cypher(driver, CREATE_FULLTEXT_INDEX)
        await _cypher(driver, "CALL db.awaitIndex($name, 120)", name=FULLTEXT_INDEX)
        index = await _cypher(
            driver,
            "SHOW FULLTEXT INDEXES YIELD name, labelsOrTypes, properties, options, state "
            "WHERE name = $name RETURN name, labelsOrTypes, properties, options.indexConfig AS config, state",
            name=FULLTEXT_INDEX,
        )
        graph = await neo4j_snapshot(driver)
        check_graph_matches_corpus(graph, corpus)
        session.data.update(
            {
                "ddl": ["ENABLE_VECTOR_EXTENSION", "CREATE_TEST_COURSE_EMBEDDINGS", "CREATE_HNSW_INDEX"],
                "eval_tables": ["eval_query_embeddings", "eval_document_embedding_meta"],
                "neo4j_fulltext_index": {"statement": CREATE_FULLTEXT_INDEX, "show": index},
                "postgres_rows_sha256": canonical_sha256(corpus.row_snapshot()),
                "neo4j_counts": {key: len(graph[key]) for key in ("nodes", "prereqs", "topics")},
                "aborted": False,
            }
        )
        print(json.dumps(index, ensure_ascii=False, default=str))
    finally:
        session.finish()
        await pool.close()
        await driver.close()


# --- 埋め込み ----------------------------------------------------------------------


def _embedder(budget: int) -> Embedder:
    if not (config.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")):
        raise SystemExit("GEMINI_API_KEY が未設定です")
    return Embedder(genai.Client(), budget=budget)


async def embed_docs(args: argparse.Namespace) -> None:
    session = Session(args.manifest, "embed-docs", args.git_sha)
    _, embedding_left = session.remaining()
    embedder = _embedder(embedding_left)
    pool = await connect_eval_db()
    try:
        async with pool.acquire() as conn:
            existing = await conn.fetchval(f"SELECT count(*) FROM {EMBEDDING_TABLE}")
        if existing:
            raise SystemExit(f"{EMBEDDING_TABLE} に既に {existing} 行あります（作り直すなら実験用 DB で手で消す）")
        corpus = await load_corpus(pool)
        texts = [format_document(course.title, document_body(course)) for course in corpus.courses]
        try:
            results, latency_ms = await embedder.embed(texts)
        finally:
            session.data.update(
                {
                    "embedding_requests": embedder.requests,
                    "embedding_texts": embedder.texts,
                    "retry_reasons": embedder.retry_reasons,
                }
            )
        async with pool.acquire() as conn, conn.transaction():
            for course, text, result in zip(corpus.courses, texts, results, strict=True):
                await conn.execute(
                    f"INSERT INTO {EMBEDDING_TABLE} (id, course_id, embedding) VALUES ($1, $2, $3::vector)",
                    uuid.uuid4(),
                    uuid.UUID(course.id),
                    vector_literal(result.vector),
                )
                await conn.execute(
                    "INSERT INTO eval_document_embedding_meta (course_id, text_sha256, model, dims, raw_norm) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.UUID(course.id),
                    _sha256(text),
                    EMBEDDING_MODEL,
                    EMBEDDING_DIMENSIONS,
                    result.raw_norm,
                )
        norms = [result.raw_norm for result in results]
        session.data.update(
            {
                "model": EMBEDDING_MODEL,
                "dimensions": EMBEDDING_DIMENSIONS,
                "document_template": DOCUMENT_TEMPLATE,
                "document_body": "トピック: {topics を「、」で連結}。{syllabus_text}",
                "documents": len(texts),
                "latency_ms": latency_ms,
                "raw_norm_min": min(norms),
                "raw_norm_max": max(norms),
                "example_document": texts[0],
                "aborted": False,
            }
        )
        print(f"embedded {len(texts)} documents in 1 request; raw norm {min(norms):.6f}..{max(norms):.6f}")
    finally:
        session.finish()
        await pool.close()


async def embed_queries(args: argparse.Namespace) -> None:
    session = Session(args.manifest, "embed-queries", args.git_sha)
    _, embedding_left = session.remaining()
    embedder = _embedder(embedding_left)
    specs = load_specs(args.specs)
    pool = await connect_eval_db()
    norms: list[float] = []
    try:
        async with pool.acquire() as conn:
            done = {row["question_id"] for row in await conn.fetch("SELECT question_id FROM eval_query_embeddings")}
        for spec in specs:
            if spec.question_id in done:
                continue
            text = format_query(spec.embedding_text)
            try:
                [result], latency_ms = await embedder.embed([text])
            finally:
                session.data.update(
                    {"embedding_requests": embedder.requests, "embedding_texts": embedder.texts}
                )
            norms.append(result.raw_norm)
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO eval_query_embeddings "
                    "(question_id, text_sha256, model, dims, embedding, raw_norm, latency_ms) "
                    "VALUES ($1, $2, $3, $4, $5::vector, $6, $7)",
                    spec.question_id,
                    _sha256(text),
                    EMBEDDING_MODEL,
                    EMBEDDING_DIMENSIONS,
                    vector_literal(result.vector),
                    result.raw_norm,
                    latency_ms,
                )
            print(f"{spec.question_id} embedded ({latency_ms} ms, raw norm {result.raw_norm:.6f})", flush=True)
        session.data.update(
            {
                "model": EMBEDDING_MODEL,
                "dimensions": EMBEDDING_DIMENSIONS,
                "query_template": QUERY_TEMPLATE,
                "queries": len(norms),
                "raw_norm_min": min(norms) if norms else None,
                "raw_norm_max": max(norms) if norms else None,
                "retry_reasons": embedder.retry_reasons,
                "aborted": False,
            }
        )
    finally:
        session.finish()
        await pool.close()


async def load_query_vectors(pool: asyncpg.Pool, specs: Sequence[QuerySpec]) -> dict[str, list[float]]:
    """質問の埋め込みを読み、質問文のハッシュ・モデル・次元が今の spec と設定に合うか確かめる。"""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT question_id, text_sha256, model, dims, embedding::text AS v FROM eval_query_embeddings"
        )
    by_id = {row["question_id"]: row for row in rows}
    vectors = {}
    for spec in specs:
        row = by_id.get(spec.question_id)
        if row is None:
            raise SystemExit(f"{spec.question_id} の質問の埋め込みがありません")
        if row["text_sha256"] != _sha256(format_query(spec.embedding_text)):
            raise SystemExit(f"{spec.question_id} の埋め込みが今の質問文と違います")
        if (row["model"], row["dims"]) != (EMBEDDING_MODEL, EMBEDDING_DIMENSIONS):
            raise SystemExit(f"{spec.question_id} の埋め込みのモデルか次元が設定と違います")
        vectors[spec.question_id] = json.loads(row["v"])
    return vectors


# --- retrieve -------------------------------------------------------------------------


def load_golden(path: Path = GOLDEN_PATH) -> dict[str, GoldenCase]:
    return {case["id"]: GoldenCase.model_validate(case) for case in json.loads(path.read_text("utf-8"))}


def spec_matches_golden(spec: QuerySpec, case: GoldenCase) -> bool:
    """H0: 検索系の問いで spec の mode と anchor が golden と一致するか（unclear は mode だけ見る）。"""
    if not case.is_search:
        return spec.mode == case.mode
    return spec.mode == case.mode and spec.anchor_code == case.anchor_code


def rotated(index: int) -> list[str]:
    """条件の順を質問ごとに1つずつずらす（q01: C1 C2 C3 C4、q02: C2 C3 C4 C1、…）。"""
    shift = index % len(CONDITIONS)
    return list(CONDITIONS[shift:] + CONDITIONS[:shift])


async def retrieve_once(
    condition: str, spec: QuerySpec, backends: RetrievalBackends
) -> tuple[list[RankedItem], QueryCounter, float]:
    counter = QueryCounter()
    started = time.perf_counter()
    items = await REGISTRY[condition](spec, RETRIEVE_DEPTH, backends, counter)
    return items, counter, (time.perf_counter() - started) * 1000


async def retrieve_record(
    condition: str,
    spec: QuerySpec,
    case: GoldenCase,
    backends: RetrievalBackends,
    prerequisites: dict[str, list[str]],
    run_id: str,
) -> RetrievalRecord:
    """§3.4: 5回流して順位が一致することを確かめ、所要時間は中央値を取る。"""
    started_at = _now()
    runs = [await retrieve_once(condition, spec, backends) for _ in range(REPEATS)]
    first_items, first_counter, _ = runs[0]
    signature = [item.model_dump() for item in first_items]
    identical = all([item.model_dump() for item in items] == signature for items, _, _ in runs)
    if not identical:
        raise SystemExit(f"{spec.question_id} {condition}: 5回の検索結果が一致しません（不具合）")
    kept = exclude_anchor(first_items, spec.anchor_code)[:SECONDARY_K]
    codes = [item.code for item in kept]
    latencies = [round(latency, 3) for _, _, latency in runs]
    return RetrievalRecord(
        run_id=run_id,
        condition=condition,
        question_id=spec.question_id,
        mode=case.mode,
        anchor_code=spec.anchor_code,
        ranked=[RankedEntry(**item.model_dump()) for item in kept],
        raw_returned=len(first_items),
        anchor_removed=any(item.code == spec.anchor_code for item in first_items),
        repeats=REPEATS,
        identical_across_repeats=identical,
        latency_ms_runs=latencies,
        latency_ms_median=statistics.median(latencies),
        sql_queries=first_counter.sql,
        cypher_queries=first_counter.cypher,
        scores={
            str(k): score_retrieval(case, codes, prerequisites, k) for k in (PRIMARY_K, SECONDARY_K)
        },
        started_at=started_at,
    )


async def run_retrieval(args: argparse.Namespace) -> None:
    out_path: Path = args.out
    if out_path.exists():
        raise SystemExit(f"{out_path} は既にあります")
    manifest = args.manifest or manifest_path(out_path)
    session = Session(manifest, "retrieve", args.git_sha)
    cases = load_golden()
    specs = load_specs(args.specs)
    spec_matches = {spec.question_id: spec_matches_golden(spec, cases[spec.question_id]) for spec in specs}
    pool = await connect_eval_db()
    driver = connect_neo4j()
    try:
        corpus = await load_corpus(pool)
        snapshot = await corpus_snapshot(pool, driver, corpus)
        plan = await check_exact_search_plan(pool)
        backends = RetrievalBackends(
            pool=pool, driver=driver, query_vectors=await load_query_vectors(pool, specs)
        )
        prerequisites = corpus.prerequisites()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as sink:
            for index, spec in enumerate(specs):
                for condition in rotated(index):
                    record = await retrieve_record(
                        condition, spec, cases[spec.question_id], backends, prerequisites, session.data["run_id"]
                    )
                    sink.write(record.model_dump_json() + "\n")
                    print(_retrieval_line(record), flush=True)
        session.data.update(
            {
                "specs": str(args.specs),
                "specs_sha256": file_sha256(args.specs),
                "golden_sha256": file_sha256(GOLDEN_PATH),
                "spec_matches_golden": spec_matches,
                "corpus": snapshot,
                "exact_search": plan,
                "embedding": {
                    "model": EMBEDDING_MODEL,
                    "dimensions": EMBEDDING_DIMENSIONS,
                    "normalization": "API の自動正規化（文書どおり）＋保存前に L2 正規化",
                    "query_template": QUERY_TEMPLATE,
                    "document_template": DOCUMENT_TEMPLATE,
                },
                "params": {
                    "retrieve_depth": RETRIEVE_DEPTH,
                    "k": [PRIMARY_K, SECONDARY_K],
                    "repeats": REPEATS,
                    "hybrid_entry_count": HYBRID_ENTRY_COUNT,
                    "rrf_k": RRF_K,
                    "fulltext_index": FULLTEXT_INDEX,
                    "fulltext_analyzer": FULLTEXT_ANALYZER,
                },
                "python": platform.python_version(),
                "libraries": library_versions(),
                "aborted": False,
            }
        )
    finally:
        session.finish()
        await pool.close()
        await driver.close()


def _retrieval_line(record: RetrievalRecord) -> str:
    score = record.scores[str(PRIMARY_K)]
    metric = (
        f"R@5={score.recall:.2f} N@5={score.ndcg:.2f}" if score.recall is not None else f"returned={score.returned}"
    )
    return (
        f"{record.question_id} {record.condition:<16} {metric} q={record.db_queries} "
        f"{record.latency_ms_median:.1f}ms top5={record.codes[:PRIMARY_K]}"
    )


# --- generate ---------------------------------------------------------------------------


def generation_input(spec: QuerySpec, candidates: Sequence[RankedEntry]) -> str:
    """§3.5 の LLM への入力 JSON。"""
    payload = {
        "question": spec.question,
        "intent": {"mode": spec.mode, "anchor_code": spec.anchor_code, "anchor_title": spec.anchor_title},
        "candidates": [
            {"rank": rank, "code": item.code, "title": item.title, "evidence": item.evidence}
            for rank, item in enumerate(candidates, start=1)
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


async def compose(prompt: str, meter: LlmMeter) -> tuple[AnswerPayload, str | None]:
    """S1 と同じ形: 本番の build_compose_agent（ツール無し）を1ノードの Workflow で1回動かす。"""
    agent = build_compose_agent(instruction=GENERATION_INSTRUCTION, enable_mcp=False)
    workflow = Workflow(name="retrieval_generation", edges=[("START", agent)])
    node = meter.instrument(node_compare._llm_node(workflow))
    events = await node_compare._run_events(workflow, prompt)
    return node_compare._final_payload(events), runner._model_name(node)


async def generate_record(
    record: RetrievalRecord,
    spec: QuerySpec,
    case: GoldenCase,
    meter: LlmMeter,
    pool: asyncpg.Pool,
    run_id: str,
) -> tuple[GenerationRecord, bool]:
    """1条件×1問の生成。2つ目の値は予算切れで全体を止めるべきか。"""
    started_at = _now()
    candidates = record.ranked[:GENERATION_TOP_K]
    prompt = generation_input(spec, candidates)
    retry_reasons: list[str] = []
    attempts = 0
    requests_all = 0
    while True:
        attempts += 1
        meter.reset_run()
        payload: AnswerPayload | None = None
        model: str | None = None
        error: Exception | None = None
        started = time.perf_counter()
        try:
            payload, model = await asyncio.wait_for(compose(prompt, meter), GENERATION_TIMEOUT_SECONDS)
        except Exception as exc:  # 失敗は記録して次へ進む（error 列に残す）
            error = exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        requests_all += meter.run_requests
        status = node_compare._retryable_status(error)
        if status is None or attempts > MAX_RETRIES:
            break
        retry_reasons.append(f"HTTP {status}（試行 {attempts}）")
        await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempts)
    if payload is not None and meter.run_requests == 0:
        error = RuntimeError("LLM リクエストが数えられていません")
    result = GenerationRecord(
        run_id=run_id,
        condition=record.condition,
        question_id=record.question_id,
        mode=record.mode,
        model=model,
        model_versions=list(meter.model_versions),
        success=error is None and payload is not None,
        error=_describe(error) if error is not None else None,
        attempts=attempts,
        retry_reasons=retry_reasons,
        candidate_codes=[item.code for item in candidates],
        llm_requests=meter.run_requests,
        llm_requests_all_attempts=requests_all,
        input_tokens=meter.input_tokens,
        output_tokens=meter.output_tokens,
        thoughts_tokens=meter.thoughts_tokens,
        latency_ms=latency_ms,
        started_at=started_at,
    )
    if result.success and payload is not None:
        async with pool.acquire() as conn:
            rows = await postgres_repo.get_syllabi_by_codes(conn, normalize_codes(payload.cited_codes))
        grounded = build_grounded_answer(payload, rows)
        result = result.model_copy(
            update={
                "answer": payload.answer,
                "cited_codes": payload.cited_codes,
                "unverified_codes": grounded.unverified_codes,
                "sources_count": len(grounded.sources),
                "score": score_generation(case, payload.cited_codes, result.candidate_codes),
            }
        )
    return result, node_compare._find_exception(error, BudgetExhausted) is not None


def _describe(error: BaseException) -> str:
    if isinstance(error, TimeoutError):
        return f"TimeoutError: {GENERATION_TIMEOUT_SECONDS} 秒を超えました"
    return node_compare._redact(f"{type(error).__name__}: {error}")[: node_compare.ERROR_MAX_CHARS]


def load_records(path: Path) -> tuple[list[RetrievalRecord], list[GenerationRecord]]:
    retrieval: list[RetrievalRecord] = []
    generation: list[GenerationRecord] = []
    if not path.exists():
        return retrieval, generation
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if data["kind"] == "retrieval":
            retrieval.append(RetrievalRecord.model_validate(data))
        else:
            generation.append(GenerationRecord.model_validate(data))
    return retrieval, generation


def h0_holds(retrieval: Sequence[RetrievalRecord], cases: dict[str, GoldenCase], specs: Sequence[QuerySpec]) -> bool:
    search_ids = {qid for qid, case in cases.items() if case.is_search}
    if not all(spec_matches_golden(spec, cases[spec.question_id]) for spec in specs if spec.question_id in search_ids):
        return False
    graph = {r.question_id: r for r in retrieval if r.condition == "pure_graph"}
    return all(qid in graph and graph[qid].scores[str(SECONDARY_K)].recall == 1.0 for qid in search_ids)


async def run_generation(args: argparse.Namespace) -> None:
    input_path: Path = args.input
    out_path: Path = args.out or input_path
    manifest = args.manifest or manifest_path(input_path)
    session = Session(manifest, "generate", args.git_sha)
    session.data["output"] = out_path.name
    cases = load_golden()
    specs = {spec.question_id: spec for spec in load_specs(args.specs)}
    retrieval, _ = load_records(input_path)
    if not h0_holds(retrieval, cases, list(specs.values())):
        raise SystemExit("H0（妥当性の確認）を満たさないので生成に進みません")
    _, existing = load_records(out_path)
    done = {(record.condition, record.question_id) for record in existing}
    by_key = {(record.condition, record.question_id): record for record in retrieval}
    search_ids = [qid for qid in sorted(cases) if cases[qid].is_search]
    chosen_questions = _selected(args.questions, search_ids)
    chosen_conditions = set(_selected(args.conditions, list(CONDITIONS)))
    llm_left, _ = session.remaining()
    meter = LlmMeter(llm_left, PER_RUN_LLM_CAP)
    pool = await connect_eval_db()
    aborted = False
    try:
        with out_path.open("a", encoding="utf-8") as sink:
            for index, qid in enumerate(search_ids):
                if qid not in chosen_questions:
                    continue
                for condition in rotated(index):
                    if condition not in chosen_conditions or (condition, qid) in done:
                        continue
                    record, exhausted = await generate_record(
                        by_key[(condition, qid)], specs[qid], cases[qid], meter, pool, session.data["run_id"]
                    )
                    sink.write(record.model_dump_json() + "\n")
                    sink.flush()
                    session.data["llm_requests"] = meter.total
                    session.save()
                    print(_generation_line(record, meter), flush=True)
                    if exhausted:
                        aborted = True
                        break
                if aborted:
                    break
    except BaseException:  # 予算切れ以外で止まったときも manifest に途中終了として残す
        aborted = True
        raise
    finally:
        session.data.update(
            {
                "llm_requests": meter.total,
                "model": config.AGENT_MODEL,
                "generation_config": "未指定（API 既定値。本番の build_compose_agent が渡していないため）",
                "instruction_sha256": _sha256(GENERATION_INSTRUCTION),
                "generation_top_k": GENERATION_TOP_K,
                "per_run_llm_cap": PER_RUN_LLM_CAP,
                "timeout_seconds": GENERATION_TIMEOUT_SECONDS,
                "questions": chosen_questions,
                "conditions": sorted(chosen_conditions),
                "aborted": aborted,
                "finished_at": _now(),
            }
        )
        session.save()
        await pool.close()


def _generation_line(record: GenerationRecord, meter: LlmMeter) -> str:
    status = "ok" if record.success else f"NG {record.error}"
    return (
        f"{record.question_id} {record.condition:<16} {status} llm={record.llm_requests} "
        f"{record.latency_ms / 1000:.1f}s cited={record.cited_codes} unverified={record.unverified_codes} "
        f"total_llm={meter.total}"
    )


def _selected(raw: str, allowed: Sequence[str]) -> list[str]:
    if raw == "all":
        return list(allowed)
    chosen = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [item for item in chosen if item not in allowed]
    if unknown:
        raise SystemExit(f"不明な指定: {unknown}（選べるもの: {list(allowed)}）")
    return chosen


# --- summarize ----------------------------------------------------------------------------


def manifest_path(results_path: Path) -> Path:
    return results_path.with_name(f"{results_path.stem}_manifest.json")


def summary_path(results_path: Path) -> Path:
    return results_path.with_name(f"{results_path.stem}_summary.md")


def summarize(args: argparse.Namespace) -> None:
    retrieval, generation = load_records(args.input)
    if not retrieval:
        raise SystemExit(f"{args.input} に検索の記録がありません")
    cases = load_golden()
    specs = load_specs(args.specs)
    sessions = _load_sessions(args.manifest or manifest_path(args.input))
    spec_matches = {spec.question_id: spec_matches_golden(spec, cases[spec.question_id]) for spec in specs}
    out = args.out or summary_path(args.input)
    out.write_text(
        retrieval_report.render_summary(retrieval, generation, cases, specs, sessions, spec_matches), "utf-8"
    )
    print(f"wrote {out}")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m eval.retrieval_compare", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("setup-db", "embed-docs", "embed-queries"):
        sub = commands.add_parser(name)
        sub.add_argument("--manifest", type=Path, required=True)
        sub.add_argument("--git-sha", required=True, help="コンテナ内に .git が無いので外から渡す")
        sub.add_argument("--specs", type=Path, default=DEFAULT_SPECS)
    retrieve = commands.add_parser("retrieve")
    retrieve.add_argument("--out", type=Path, required=True)
    retrieve.add_argument("--manifest", type=Path)
    retrieve.add_argument("--git-sha", required=True)
    retrieve.add_argument("--specs", type=Path, default=DEFAULT_SPECS)
    generate = commands.add_parser("generate")
    generate.add_argument("--input", type=Path, required=True)
    generate.add_argument("--out", type=Path)
    generate.add_argument("--manifest", type=Path)
    generate.add_argument("--git-sha", required=True)
    generate.add_argument("--specs", type=Path, default=DEFAULT_SPECS)
    generate.add_argument("--questions", default="all")
    generate.add_argument("--conditions", default="all")
    summary = commands.add_parser("summarize")
    summary.add_argument("--input", type=Path, required=True)
    summary.add_argument("--manifest", type=Path)
    summary.add_argument("--specs", type=Path, default=DEFAULT_SPECS)
    summary.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    handlers = {
        "setup-db": setup_db,
        "embed-docs": embed_docs,
        "embed-queries": embed_queries,
        "retrieve": run_retrieval,
        "generate": run_generation,
    }
    if args.command == "summarize":
        summarize(args)
        return
    asyncio.run(handlers[args.command](args))


if __name__ == "__main__":
    main(sys.argv[1:])
