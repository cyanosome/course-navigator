"""Neo4j への Cypher アクセスを集約するリポジトリ。

Cypher とクエリ実行のみを担当し、HTTP や業務ロジックは持たない。
講義・トピックの一括処理は UNWIND ... MERGE に統一する（N+1 回避）。
"""

from typing import Any

from neo4j import AsyncSession

# --- test_neo4j エンドポイント用 ---

_MERGE_COURSE_WITH_PREREQ = """
MERGE (c:Course {id: $id})
SET c.title = $title, c.description = $description
WITH c
FOREACH (p_title IN CASE WHEN $prerequisite_title <> '' THEN [$prerequisite_title] ELSE [] END |
    MERGE (p:Course {title: p_title})
    ON CREATE SET p.id = $prerequisite_id
    MERGE (c)-[:REQUIRES_PREREQUISITE]->(p)
)
RETURN c.id AS id
"""

_SEARCH_COURSES = """
MATCH (c:Course)
WHERE c.title CONTAINS $q OR (c.description IS NOT NULL AND c.description CONTAINS $q)
OPTIONAL MATCH (c)-[:REQUIRES_PREREQUISITE]->(p:Course)
RETURN c.id AS id, c.title AS title, c.description AS description, collect(p.title) AS prerequisites
ORDER BY c.title ASC
"""


async def merge_course_with_prerequisite(
    session: AsyncSession,
    record_id: str,
    title: str,
    description: str,
    prerequisite_title: str,
    prerequisite_id: str,
) -> None:
    await session.run(
        _MERGE_COURSE_WITH_PREREQ,
        id=record_id,
        title=title,
        description=description,
        prerequisite_title=prerequisite_title,
        prerequisite_id=prerequisite_id,
    )


async def search_courses(session: AsyncSession, q: str) -> list[dict[str, Any]]:
    result = await session.run(_SEARCH_COURSES, q=q)
    return await result.data()


# --- test_integrated エンドポイント用 ---

_MERGE_PLACEHOLDER_COURSES = """
UNWIND $items AS item
MERGE (c:Course {id: item.id})
SET c.code = item.code, c.title = item.title
"""

_MERGE_MAIN_COURSE = """
MERGE (c:Course {id: $id})
SET c.code = $code, c.title = $title
"""

_MERGE_PREREQUISITES = """
MATCH (c:Course {id: $course_id})
UNWIND $prereq_ids AS prereq_id
MATCH (p:Course {id: prereq_id})
MERGE (c)-[:REQUIRES_PREREQUISITE]->(p)
"""

_MERGE_TOPICS = """
MATCH (c:Course {id: $course_id})
UNWIND $topics AS topic_name
MERGE (t:Topic {name: topic_name})
MERGE (c)-[:COVERS_TOPIC]->(t)
"""

_SEARCH_INTEGRATED = """
UNWIND $ids AS course_id
MATCH (c:Course {id: course_id})
OPTIONAL MATCH (c)-[:REQUIRES_PREREQUISITE]->(p:Course)
OPTIONAL MATCH (c)-[:COVERS_TOPIC]->(t:Topic)
OPTIONAL MATCH (t)<-[:COVERS_TOPIC]-(other:Course) WHERE other.id <> c.id
RETURN c.id AS id,
       collect(DISTINCT {id: p.id, code: p.code, title: p.title}) AS prerequisites,
       collect(DISTINCT t.name) AS topics,
       collect(DISTINCT {id: other.id, code: other.code, title: other.title, topic: t.name}) AS related_courses
"""


async def merge_placeholder_courses(
    session: AsyncSession, items: list[dict[str, str]]
) -> None:
    """未登録の前提講義プレースホルダーノードを一括 MERGE する。"""
    if not items:
        return
    await session.run(_MERGE_PLACEHOLDER_COURSES, items=items)


async def merge_main_course(
    session: AsyncSession, course_id: str, code: str, title: str
) -> None:
    await session.run(_MERGE_MAIN_COURSE, id=course_id, code=code, title=title)


async def merge_prerequisites(
    session: AsyncSession, course_id: str, prereq_ids: list[str]
) -> None:
    """前提条件リレーションを一括 MERGE する。"""
    if not prereq_ids:
        return
    await session.run(_MERGE_PREREQUISITES, course_id=course_id, prereq_ids=prereq_ids)


async def merge_topics(
    session: AsyncSession, course_id: str, topics: list[str]
) -> None:
    """トピックリレーションを一括 MERGE する。"""
    if not topics:
        return
    await session.run(_MERGE_TOPICS, course_id=course_id, topics=topics)


async def search_integrated(
    session: AsyncSession, course_ids: list[str]
) -> list[dict[str, Any]]:
    result = await session.run(_SEARCH_INTEGRATED, ids=course_ids)
    return await result.data()
