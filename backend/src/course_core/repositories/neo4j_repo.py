"""Neo4j への Cypher アクセスを集約するリポジトリ。

Cypher とクエリ実行のみを担当し、HTTP や業務ロジックは持たない。
講義・トピックの一括処理は UNWIND ... MERGE に統一する（N+1 回避）。
syllabus_id を直接結合キー・主キーとして優先採用し、
未設定ノードに対しては id, course_code, code, elementId への決定論的フォールバックを行う。
"""

from typing import Any

from neo4j import AsyncSession

# --- test_neo4j エンドポイント用 ---

_MERGE_COURSE_WITH_PREREQ = """
MERGE (c:Course {id: $id})
SET c.syllabus_id = coalesce(c.syllabus_id, $id),
    c.title = $title,
    c.name = coalesce(c.name, $title),
    c.description = $description
WITH c
FOREACH (p_title IN CASE WHEN $prerequisite_title <> '' THEN [$prerequisite_title] ELSE [] END |
    MERGE (p:Course {title: p_title})
    ON CREATE SET p.id = $prerequisite_id, p.syllabus_id = $prerequisite_id, p.name = p_title
    MERGE (c)-[:REQUIRES_PREREQUISITE]->(p)
)
RETURN coalesce(c.syllabus_id, c.id) AS id
"""

_SEARCH_COURSES = """
MATCH (c:Course)
WHERE ($q = '' 
       OR coalesce(c.title, c.name, '') CONTAINS $q 
       OR coalesce(c.syllabus_id, '') CONTAINS $q 
       OR coalesce(c.course_code, '') CONTAINS $q
       OR coalesce(c.class_name, '') CONTAINS $q)
OPTIONAL MATCH (c)-[:REQUIRES_PREREQUISITE]->(p:Course)
RETURN coalesce(c.syllabus_id, c.id, c.course_code, elementId(c)) AS id,
       coalesce(c.title, c.name, '') AS title,
       coalesce(c.class_name, c.subtitle, '') AS description,
       c.syllabus_id AS syllabus_id,
       coalesce(c.course_code, '') AS code,
       [p_name IN collect(DISTINCT coalesce(p.title, p.name, '')) WHERE p_name <> ''] AS prerequisites
ORDER BY title ASC
"""


async def merge_course_with_prerequisite(
    session: AsyncSession,
    record_id: str,
    title: str,
    description: str,
    prerequisite_title: str,
    prerequisite_id: str,
) -> None:
    result = await session.run(
        _MERGE_COURSE_WITH_PREREQ,
        id=record_id,
        title=title,
        description=description,
        prerequisite_title=prerequisite_title,
        prerequisite_id=prerequisite_id,
    )
    await result.consume()


async def search_courses(session: AsyncSession, q: str) -> list[dict[str, Any]]:
    result = await session.run(_SEARCH_COURSES, q=q)
    return await result.data()


# --- test_integrated エンドポイント用 ---

_MERGE_PLACEHOLDER_COURSES = """
UNWIND $items AS item
MERGE (c:Course {id: item.id})
SET c.syllabus_id = coalesce(c.syllabus_id, item.id),
    c.code = item.code,
    c.course_code = coalesce(c.course_code, item.code),
    c.title = item.title,
    c.name = coalesce(c.name, item.title)
"""

_MERGE_MAIN_COURSE = """
MERGE (c:Course {id: $id})
SET c.syllabus_id = coalesce(c.syllabus_id, $id),
    c.code = $code,
    c.course_code = coalesce(c.course_code, $code),
    c.title = $title,
    c.name = coalesce(c.name, $title)
"""

_MERGE_PREREQUISITES = """
MATCH (c:Course)
WHERE c.syllabus_id = $course_id OR c.id = $course_id
UNWIND $prereq_ids AS prereq_id
MATCH (p:Course)
WHERE p.syllabus_id = prereq_id OR p.id = prereq_id
MERGE (c)-[:REQUIRES_PREREQUISITE]->(p)
"""

_MERGE_TOPICS = """
MATCH (c:Course)
WHERE c.syllabus_id = $course_id OR c.id = $course_id
UNWIND $topics AS topic_name
MERGE (t:Topic {name: topic_name})
MERGE (c)-[:COVERS_TOPIC]->(t)
"""

_SEARCH_INTEGRATED = """
UNWIND $ids AS course_id
MATCH (c:Course)
WHERE c.syllabus_id = course_id OR c.id = course_id OR c.course_code = course_id OR c.code = course_id
OPTIONAL MATCH (c)-[:REQUIRES_PREREQUISITE]->(p:Course)
OPTIONAL MATCH (c)-[:COVERS_TOPIC]->(t:Topic)
OPTIONAL MATCH (t)<-[:COVERS_TOPIC]-(other:Course) WHERE other <> c
RETURN coalesce(c.syllabus_id, c.id, c.course_code, c.code, elementId(c)) AS id,
       c.syllabus_id AS syllabus_id,
       collect(DISTINCT {
           id: coalesce(p.syllabus_id, p.id, p.course_code, p.code, elementId(p)),
           code: coalesce(p.course_code, p.code, ''),
           title: coalesce(p.title, p.name, '')
       }) AS prerequisites,
       collect(DISTINCT t.name) AS topics,
       collect(DISTINCT {
           id: coalesce(other.syllabus_id, other.id, other.course_code, other.code, elementId(other)),
           code: coalesce(other.course_code, other.code, ''),
           title: coalesce(other.title, other.name, ''),
           topic: t.name
       }) AS related_courses
"""


async def merge_placeholder_courses(
    session: AsyncSession, items: list[dict[str, str]]
) -> None:
    """未登録の前提講義プレースホルダーノードを一括 MERGE する。"""
    if not items:
        return
    result = await session.run(_MERGE_PLACEHOLDER_COURSES, items=items)
    await result.consume()


async def merge_main_course(
    session: AsyncSession, course_id: str, code: str, title: str
) -> None:
    result = await session.run(_MERGE_MAIN_COURSE, id=course_id, code=code, title=title)
    await result.consume()


async def merge_prerequisites(
    session: AsyncSession, course_id: str, prereq_ids: list[str]
) -> None:
    """前提条件リレーションを一括 MERGE する。"""
    if not prereq_ids:
        return
    result = await session.run(
        _MERGE_PREREQUISITES, course_id=course_id, prereq_ids=prereq_ids
    )
    await result.consume()


async def merge_topics(
    session: AsyncSession, course_id: str, topics: list[str]
) -> None:
    """トピックリレーションを一括 MERGE する。"""
    if not topics:
        return
    result = await session.run(_MERGE_TOPICS, course_id=course_id, topics=topics)
    await result.consume()


async def search_integrated(
    session: AsyncSession, course_ids: list[str]
) -> list[dict[str, Any]]:
    result = await session.run(_SEARCH_INTEGRATED, ids=course_ids)
    return await result.data()
