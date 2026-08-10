"""グラフ探索・シラバス検索（アンカー特定および多段前提・後続・トピック検索）モジュール。"""

import asyncpg
from neo4j import AsyncSession

from repositories import postgres_repo
from schemas.traversal import AnchorHit, Candidate, Envelope


async def resolve_anchor(
    conn: asyncpg.Connection, text: str
) -> Envelope[AnchorHit | None]:
    """テキストから対象講義（アンカー）を解決する。

    postgres_repo.search_syllabus を用いて検索を行い、ヒットした最上位レコードを返す。
    """
    records = await postgres_repo.search_syllabus(conn, text)
    if not records:
        return Envelope(
            data=None, status="not_found", message=f"No syllabus found for '{text}'"
        )

    first = records[0]
    hit = AnchorHit(
        id=str(first["id"]),
        code=first["code"],
        title=first["title"],
        instructor=first.get("instructor"),
        schedule=first.get("schedule"),
        credits=first.get("credits"),
        syllabus_text=first.get("syllabus_text"),
    )
    return Envelope(data=hit)


_FIND_NEXT_COURSES = """
MATCH (c:Course {code: $code})
MATCH path = (next:Course)-[:REQUIRES_PREREQUISITE*1..]->(c)
RETURN DISTINCT next.id AS id, next.code AS code, next.title AS title, min(length(path)) AS distance
ORDER BY distance ASC, next.code ASC
"""


async def find_next_courses(
    session: AsyncSession, code: str
) -> Envelope[list[Candidate]]:
    """指定講義コードを前提条件とする後続講義（逆方向多段）を検索する。"""
    result = await session.run(_FIND_NEXT_COURSES, code=code)
    records = await result.data()
    candidates = [
        Candidate(
            id=r.get("id"),
            code=r.get("code"),
            title=r.get("title"),
            distance=r.get("distance"),
        )
        for r in records
    ]
    return Envelope(data=candidates)


_FIND_PREREQUISITES = """
MATCH (c:Course {code: $code})
MATCH path = (c)-[:REQUIRES_PREREQUISITE*1..]->(p:Course)
RETURN DISTINCT p.id AS id, p.code AS code, p.title AS title, min(length(path)) AS distance
ORDER BY distance ASC, p.code ASC
"""


async def find_prerequisites(
    session: AsyncSession, code: str
) -> Envelope[list[Candidate]]:
    """指定講義コードの前提講義（順方向多段）を検索する。"""
    result = await session.run(_FIND_PREREQUISITES, code=code)
    records = await result.data()
    candidates = [
        Candidate(
            id=r.get("id"),
            code=r.get("code"),
            title=r.get("title"),
            distance=r.get("distance"),
        )
        for r in records
    ]
    return Envelope(data=candidates)


_FIND_RELATED_BY_TOPIC = """
MATCH (c:Course {code: $code})-[:COVERS_TOPIC]->(t:Topic)<-[:COVERS_TOPIC]-(other:Course)
WHERE (other.code IS NOT NULL AND other.code <> $code) OR (other.code IS NULL AND other.id <> c.id)
WITH other, collect(DISTINCT t.name) AS topics
RETURN other.id AS id, other.code AS code, other.title AS title, topics
LIMIT $limit
"""


async def find_related_by_topic(
    session: AsyncSession, code: str, limit: int = 5
) -> Envelope[list[Candidate]]:
    """指定講義コードと共通トピックを持つ関連講義を検索する。"""
    result = await session.run(_FIND_RELATED_BY_TOPIC, code=code, limit=limit)
    records = await result.data()
    candidates = [
        Candidate(
            id=r.get("id"),
            code=r.get("code"),
            title=r.get("title"),
            topics=r.get("topics", []),
        )
        for r in records
    ]
    return Envelope(data=candidates)
