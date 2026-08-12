"""グラフ探索・シラバス検索（アンカー特定および多段前提・後続・トピック検索）モジュール。

設計書 実験3-2 §6 の層A。neo4j / asyncpg の例外はこのモジュール内で Envelope に
畳み込み、呼び出し元（ADK 関数ノード = 層B）へは例外を一切投げない。
"""

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import asyncpg
from neo4j import AsyncSession
from neo4j.exceptions import DriverError, Neo4jError

from course_core.repositories import postgres_repo
from course_core.schemas.traversal import AnchorHit, Candidate, Envelope

logger = logging.getLogger(__name__)

# 層A が返す日本語メッセージ（§6 の障害対応表に対応。原因はクライアントに出さない）
_GRAPH_UNAVAILABLE_JA = "履修系統図を参照できませんでした。"
_RDB_UNAVAILABLE_JA = "シラバス情報を参照できませんでした。"

# Neo4j 側の障害。ServiceUnavailable / SessionExpired は DriverError の派生。
_NEO4J_ERRORS = (Neo4jError, DriverError)
# PostgreSQL 側の障害。切断時に素の OSError が上がる経路があるため含める
_POSTGRES_ERRORS = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError)

_AsyncEnvelopeFn = TypeVar("_AsyncEnvelopeFn", bound=Callable[..., Awaitable[Any]])


def _envelope_on_db_error(func: _AsyncEnvelopeFn) -> _AsyncEnvelopeFn:
    """DB 例外を Envelope(ok=False) に変換するデコレータ（§6 層A の契約）。

    例外をここで止めるので、層B は try/except を1つも書かずに済む。
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Envelope[Any]:
        try:
            return await func(*args, **kwargs)
        except _NEO4J_ERRORS:
            logger.exception("%s: Neo4j の参照に失敗", func.__name__)
            return Envelope(
                ok=False,
                error_code="GRAPH_UNAVAILABLE",
                message_ja=_GRAPH_UNAVAILABLE_JA,
            )
        except _POSTGRES_ERRORS:
            logger.exception("%s: PostgreSQL の参照に失敗", func.__name__)
            return Envelope(
                ok=False,
                error_code="RDB_UNAVAILABLE",
                message_ja=_RDB_UNAVAILABLE_JA,
            )

    return wrapper  # type: ignore[return-value]


@_envelope_on_db_error
async def resolve_anchor(conn: asyncpg.Connection, text: str) -> Envelope[AnchorHit]:
    """テキストから対象講義（アンカー）を解決する（§4.1 の但し書き / §4.3）。"""
    records = await postgres_repo.search_syllabus(conn, text)
    if not records:
        return Envelope(
            ok=False,
            error_code="NOT_FOUND",
            message_ja=f"「{text}」に該当する科目が見つかりませんでした。",
        )

    if len(records) > 1:
        return Envelope(
            ok=True,
            data=AnchorHit(
                anchor_status="ambiguous",
                alternatives=[r["code"] for r in records[:3]],
            ),
            message_ja=f"「{text}」に当てはまる科目が複数あります。",
        )

    first = records[0]
    hit = AnchorHit(
        id=str(first["id"]),
        code=first["code"],
        title=first["title"],
        anchor_status="exact",
        instructor=first.get("instructor"),
        schedule=first.get("schedule"),
        credits=first.get("credits"),
        syllabus_text=first.get("syllabus_text"),
    )
    return Envelope(ok=True, data=hit)


_FIND_NEXT_COURSES = """
MATCH path = (c:Course {code: $code})<-[:REQUIRES_PREREQUISITE*1..3]-(next:Course)
WITH next, path, length(path) AS hops
ORDER BY hops ASC, next.code ASC
WITH next, collect({hops: hops, path_codes: [n IN nodes(path) | n.code]})[0] AS best
RETURN next.code AS code, next.title AS title,
       best.hops AS hops, best.path_codes AS path_codes
ORDER BY best.hops ASC, next.code ASC
"""


@_envelope_on_db_error
async def find_next_courses(
    session: AsyncSession, code: str
) -> Envelope[list[Candidate]]:
    """指定講義コードを前提条件とする後続講義（逆方向多段・3段まで）を検索する。"""
    result = await session.run(_FIND_NEXT_COURSES, code=code)
    records = await result.data()
    candidates = [
        Candidate(
            code=r["code"],
            title=r["title"],
            hops=r["hops"],
            path_codes=r["path_codes"],
            reason="prerequisite_of",
        )
        for r in records
    ]
    return Envelope(ok=True, data=candidates)


_FIND_PREREQUISITES = """
MATCH path = (c:Course {code: $code})-[:REQUIRES_PREREQUISITE*1..3]->(p:Course)
WITH p, path, length(path) AS hops
ORDER BY hops ASC, p.code ASC
WITH p, collect({hops: hops, path_codes: [n IN nodes(path) | n.code]})[0] AS best
RETURN p.code AS code, p.title AS title,
       best.hops AS hops, best.path_codes AS path_codes
ORDER BY best.hops DESC, p.code ASC
"""


@_envelope_on_db_error
async def find_prerequisites(
    session: AsyncSession, code: str
) -> Envelope[list[Candidate]]:
    """指定講義コードの前提講義（順方向多段・3段まで）を検索する。"""
    result = await session.run(_FIND_PREREQUISITES, code=code)
    records = await result.data()
    candidates = [
        Candidate(
            code=r["code"],
            title=r["title"],
            hops=r["hops"],
            path_codes=r["path_codes"],
            reason="requires",
        )
        for r in records
    ]
    return Envelope(ok=True, data=candidates)


_FIND_RELATED_BY_TOPIC = """
MATCH (c:Course {code: $code})-[:COVERS_TOPIC]->(t:Topic)<-[:COVERS_TOPIC]-(other:Course)
WHERE other.code <> c.code
WITH other, collect(DISTINCT t.name) AS shared
RETURN other.code AS code, other.title AS title,
       shared AS shared_topics, size(shared) AS shared_count
ORDER BY shared_count DESC, other.code ASC
LIMIT $limit
"""


@_envelope_on_db_error
async def find_related_by_topic(
    session: AsyncSession, code: str, limit: int = 5
) -> Envelope[list[Candidate]]:
    """指定講義コードと共通トピックを持つ関連講義を検索する。"""
    result = await session.run(_FIND_RELATED_BY_TOPIC, code=code, limit=limit)
    records = await result.data()
    candidates = [
        Candidate(
            code=r["code"],
            title=r["title"],
            hops=1,  # トピック検索は経路を辿らないので 1 固定
            shared_topics=r["shared_topics"],
            reason="shares_topic",
        )
        for r in records
    ]
    return Envelope(ok=True, data=candidates)
