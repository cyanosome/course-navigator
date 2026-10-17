"""検索条件（retriever）の共通の口と4条件の実装（prereg_retrieval_seed.md §3.4）。

どの条件も `retrieve(spec, k, backends, counter) -> list[RankedItem]` の形で、名前で REGISTRY に登録する。
グラフの展開は既存の course_core.graph.traversal の関数をそのまま呼び、根拠文は agent.rank の
テンプレートで作る（静的 DAG と同じ文面）。DB のクエリ数は接続・セッションの薄い包みで数える。
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import asyncpg
from neo4j import AsyncDriver
from pydantic import BaseModel, Field

from agent import rank
from agent.schemas import SearchIntent
from course_core.graph import traversal
from course_core.schemas.traversal import Candidate, Envelope
from eval.corpus import EMBEDDING_TABLE, SYLLABUS_TABLE
from eval.embeddings import vector_literal
from eval.query_spec import Constraints, Direction, QuerySpec

__all__ = [
    "FULLTEXT_INDEX",
    "HYBRID_ENTRY_COUNT",
    "REGISTRY",
    "RRF_K",
    "QueryCounter",
    "RankedItem",
    "RetrievalBackends",
    "constraint_clause",
    "exclude_anchor",
    "rrf_merge",
]

# §3.4 の事前登録パラメータ
HYBRID_ENTRY_COUNT = 3  # C4 の入口にするベクトル上位 m 件
RRF_K = 60
FULLTEXT_INDEX = "eval_course_topic_fulltext"
FULLTEXT_ANALYZER = "cjk"

CREATE_FULLTEXT_INDEX = (
    f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX} IF NOT EXISTS "
    "FOR (n:Course|Topic) ON EACH [n.title, n.name] "
    f"OPTIONS {{indexConfig: {{`fulltext.analyzer`: '{FULLTEXT_ANALYZER}'}}}}"
)

_VECTOR_SQL = """
SELECT s.code, s.title, 1 - (e.embedding <=> $1::vector) AS score
FROM {embeddings} e JOIN {syllabus} s ON s.id = e.course_id
{where}
ORDER BY e.embedding <=> $1::vector ASC, s.code ASC
LIMIT $2
"""

# Topic に当たったら、その Topic を扱う科目に置き換える。科目ごとに最大スコアを取る。
_FULLTEXT_CYPHER = """
CALL db.index.fulltext.queryNodes($index, $query) YIELD node, score
WITH node, score,
     CASE WHEN node:Course THEN [node] ELSE [(c:Course)-[:COVERS_TOPIC]->(node) | c] END AS courses,
     CASE WHEN node:Course THEN '科目' ELSE 'トピック' END AS kind,
     coalesce(node.title, node.name) AS matched
UNWIND courses AS c
WITH c, score, kind, matched
ORDER BY score DESC, matched ASC
WITH c, max(score) AS best, collect(kind + '「' + matched + '」') AS via
RETURN c.code AS code, c.title AS title, best AS score, via[0..3] AS via
ORDER BY score DESC, code ASC
LIMIT $limit
"""


class RankedItem(BaseModel):
    code: str
    title: str
    score: float  # 条件ごとの意味は evidence に書く（グラフは 1/順位）
    evidence: list[str] = Field(default_factory=list)


class QueryCounter:
    """1回の retrieve で PostgreSQL と Neo4j に送ったクエリの数（§3.4）。"""

    def __init__(self) -> None:
        self.sql = 0
        self.cypher = 0

    @property
    def total(self) -> int:
        return self.sql + self.cypher


class _CountingConnection:
    def __init__(self, conn: asyncpg.Connection, counter: QueryCounter) -> None:
        self._conn = conn
        self._counter = counter

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        self._counter.sql += 1
        return await self._conn.fetch(query, *args)


class _CountingSession:
    """traversal の関数が呼ぶ `session.run` だけを数えて本物に渡す。"""

    def __init__(self, session: Any, counter: QueryCounter) -> None:
        self._session = session
        self._counter = counter

    async def run(self, query: str, parameters: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        self._counter.cypher += 1
        return await self._session.run(query, parameters, **kwargs)


@dataclass
class RetrievalBackends:
    pool: asyncpg.Pool  # 実験用 DB。接続ごとに SET enable_indexscan = off（厳密検索）
    driver: AsyncDriver
    query_vectors: Mapping[str, Sequence[float]]  # question_id → 質問の埋め込み（全条件で共有）


Retriever = Callable[[QuerySpec, int, RetrievalBackends, QueryCounter], Awaitable[list[RankedItem]]]
REGISTRY: dict[str, Retriever] = {}


def register(name: str) -> Callable[[Retriever], Retriever]:
    def decorator(func: Retriever) -> Retriever:
        REGISTRY[name] = func
        return func

    return decorator


# --- 純関数 ---------------------------------------------------------------------


def constraint_clause(constraints: Constraints, first_param: int) -> tuple[str, list[Any]]:
    """C2 の WHERE 句と引数。曜日と時限が両方あれば「金曜3限」のように続けて部分一致させる。"""
    conditions: list[str] = []
    params: list[Any] = []
    patterns: list[str] = []
    if constraints.term:
        patterns.append(constraints.term)
    if constraints.day and constraints.period is not None:
        patterns.append(f"{constraints.day}曜{constraints.period}限")
    elif constraints.day:
        patterns.append(f"{constraints.day}曜")
    elif constraints.period is not None:
        patterns.append(f"{constraints.period}限")
    for pattern in patterns:
        conditions.append(f"s.schedule LIKE '%' || ${first_param + len(params)} || '%'")
        params.append(pattern)
    if constraints.credits is not None:
        conditions.append(f"s.credits = ${first_param + len(params)}")
        params.append(constraints.credits)
    if not conditions:
        return "", []
    return "WHERE " + " AND ".join(conditions), params


def rrf_merge(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion。score(c) = Σ 1/(k + 順位)（順位は1始まり）。同点はコード昇順。"""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, code in enumerate(dict.fromkeys(ranking), start=1):
            scores[code] = scores.get(code, 0.0) + 1.0 / (k + position)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def exclude_anchor(items: Sequence[RankedItem], anchor_code: str | None) -> list[RankedItem]:
    """§3.4 の共通の後処理: ユーザーが名前を挙げた起点科目を推薦から除く。"""
    return [item for item in items if item.code != anchor_code]


def graph_items(
    spec: QuerySpec, anchor_code: str, anchor_title: str, candidates: Sequence[Candidate]
) -> list[RankedItem]:
    """traversal の候補に、静的 DAG と同じテンプレートで根拠文を付ける。score は 1/順位。"""
    intent = SearchIntent(
        mode=spec.mode,
        anchor_code=anchor_code,
        anchor_title=anchor_title,
        anchor_status="exact",
        raw_question=spec.question,
    )
    ranked = rank.build_candidate_set(intent, list(candidates)).candidates
    return [
        RankedItem(
            code=candidate.code,
            title=candidate.title,
            score=1.0 / position,
            evidence=[evidence.text for evidence in candidate.evidence],
        )
        for position, candidate in enumerate(ranked, start=1)
    ]


# --- DB に触る部分 -----------------------------------------------------------------


async def _expand(session: _CountingSession, direction: Direction, code: str, k: int) -> list[Candidate]:
    finders: dict[Direction, Callable[[], Awaitable[Envelope[list[Candidate]]]]] = {
        "forward": lambda: traversal.find_next_courses(session, code),
        "backward": lambda: traversal.find_prerequisites(session, code),
        "topic": lambda: traversal.find_related_by_topic(session, code, limit=k),
    }
    envelope = await finders[direction]()
    if not envelope.ok:  # 実験では DB の失敗を「候補0件」に化けさせない
        raise RuntimeError(f"グラフ探索に失敗しました（{code}, {direction}）: {envelope.message_ja}")
    return envelope.data or []


async def _vector_search(
    spec: QuerySpec, k: int, backends: RetrievalBackends, counter: QueryCounter, constraints: Constraints
) -> list[RankedItem]:
    vector = backends.query_vectors.get(spec.question_id)
    if vector is None:
        raise RuntimeError(f"{spec.question_id} の質問の埋め込みがありません（embed-queries を先に流す）")
    where, params = constraint_clause(constraints, first_param=3)
    sql = _VECTOR_SQL.format(embeddings=EMBEDDING_TABLE, syllabus=SYLLABUS_TABLE, where=where)
    async with backends.pool.acquire() as raw:
        rows = await _CountingConnection(raw, counter).fetch(sql, vector_literal(vector), k, *params)
    condition_note = _constraint_note(constraints) if where else None
    items = []
    for position, row in enumerate(rows, start=1):
        evidence = [f"質問文とのコサイン類似度 {row['score']:.3f}（ベクトル検索の {position} 位）"]
        if condition_note:
            evidence.append(condition_note)
        items.append(RankedItem(code=row["code"], title=row["title"], score=row["score"], evidence=evidence))
    return items


def _constraint_note(constraints: Constraints) -> str:
    parts = [
        constraints.term,
        f"{constraints.day}曜" if constraints.day else None,
        f"{constraints.period}限" if constraints.period is not None else None,
        f"{constraints.credits}単位" if constraints.credits is not None else None,
    ]
    return "条件（" + "・".join(part for part in parts if part) + "）に合致"


@register("pure_vector")
async def pure_vector(
    spec: QuerySpec, k: int, backends: RetrievalBackends, counter: QueryCounter
) -> list[RankedItem]:
    """C1: 質問の埋め込みとのコサイン類似度で全科目を並べる（厳密検索）。"""
    return await _vector_search(spec, k, backends, counter, Constraints())


@register("vector_metadata")
async def vector_metadata(
    spec: QuerySpec, k: int, backends: RetrievalBackends, counter: QueryCounter
) -> list[RankedItem]:
    """C2: C1 に spec.constraints の WHERE を足す。constraints が空なら C1 と同じ SQL。"""
    return await _vector_search(spec, k, backends, counter, spec.constraints)


@register("pure_graph")
async def pure_graph(
    spec: QuerySpec, k: int, backends: RetrievalBackends, counter: QueryCounter
) -> list[RankedItem]:
    """C3: anchor があれば direction に沿って展開、無ければ全文検索を入口にする（展開しない）。"""
    async with backends.driver.session() as raw:
        session = _CountingSession(raw, counter)
        if spec.anchor_code and spec.anchor_title and spec.direction:
            candidates = await _expand(session, spec.direction, spec.anchor_code, k)
            return graph_items(spec, spec.anchor_code, spec.anchor_title, candidates)[:k]
        result = await session.run(
            _FULLTEXT_CYPHER, {"index": FULLTEXT_INDEX, "query": spec.fulltext_query, "limit": k}
        )
        records = await result.data()
    return [
        RankedItem(
            code=record["code"],
            title=record["title"],
            score=record["score"],
            evidence=[
                f"科目名・トピック名の全文検索で一致（スコア {record['score']:.2f}。一致: {'、'.join(record['via'])}）"
            ],
        )
        for record in records
    ]


@register("hybrid")
async def hybrid(
    spec: QuerySpec, k: int, backends: RetrievalBackends, counter: QueryCounter
) -> list[RankedItem]:
    """C4a: ベクトル上位 m 件を入口に direction へ展開し、RRF で統合する。"""
    vector_items = await pure_vector(spec, k, backends, counter)
    rankings = [[item.code for item in vector_items]]
    titles = {item.code: item.title for item in vector_items}
    evidence = {item.code: list(item.evidence) for item in vector_items}
    if spec.direction is not None:
        async with backends.driver.session() as raw:
            session = _CountingSession(raw, counter)
            for entry in vector_items[:HYBRID_ENTRY_COUNT]:
                candidates = await _expand(session, spec.direction, entry.code, k)
                expanded = graph_items(spec, entry.code, entry.title, candidates)
                rankings.append([item.code for item in expanded])
                for item in expanded:
                    titles.setdefault(item.code, item.title)
                    evidence.setdefault(item.code, []).extend(item.evidence)
    return [
        RankedItem(code=code, title=titles[code], score=score, evidence=evidence[code])
        for code, score in rrf_merge(rankings)[:k]
    ]
