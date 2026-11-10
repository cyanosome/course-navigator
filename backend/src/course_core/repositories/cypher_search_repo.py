"""Cypher search repository for multi-mode graph search."""

from typing import Any, List, Optional
from neo4j import AsyncSession

from course_core.schemas.search import (
    CourseGraphResponse,
    CoursePrereqItem,
    CourseSearchResultItem,
    GraphEdge,
    GraphNode,
)

_QUERY_HYBRID_TEMPLATE = """
CALL db.index.vector.queryNodes('course_embedding_index', $candidate_limit, $query_embedding)
YIELD node AS seed, score
WITH coalesce(seed.course_code, seed.code, elementId(seed)) AS course_code, seed, score
ORDER BY score DESC
WITH course_code, head(collect(seed)) AS seed, max(score) AS score
ORDER BY score DESC
LIMIT $top_k
OPTIONAL MATCH path = (seed)-[:REQUIRES_PREREQUISITE*1..{max_depth}]->(prereq:Course)
OPTIONAL MATCH (seed)-[:CLASSIFIED_AS]->(req:RequirementCategory)
WITH seed, score,
     collect(DISTINCT req.name) AS req_names,
     collect(DISTINCT {{
         code: coalesce(prereq.course_code, prereq.code, ''),
         title: coalesce(prereq.title, prereq.name, ''),
         credits: prereq.credits,
         term: coalesce(prereq.semester, ''),
         depth: length(path)
     }}) AS raw_prereqs
WITH seed, score,
     head([r IN req_names WHERE r IS NOT NULL]) AS requirement_category,
     [p IN raw_prereqs WHERE p.title <> ''] AS prerequisites
RETURN coalesce(seed.course_code, seed.code, '') AS code,
       coalesce(seed.title, seed.name, '') AS title,
       seed.credits AS credits,
       coalesce(seed.semester, '') AS term,
       coalesce(requirement_category, '') AS category,
       requirement_category,
       score AS score,
       prerequisites
ORDER BY score DESC;
"""

_QUERY_SIMILARITY_TEMPLATE = """
MATCH (seed:Course)
WHERE (seed.syllabus_id = $identifier OR seed.course_code = $identifier OR seed.code = $identifier OR seed.title CONTAINS $identifier OR seed.name CONTAINS $identifier)
MATCH (seed)-[sim:SIMILAR_TO]-(other:Course)
WHERE sim.score >= $min_score
WITH coalesce(other.course_code, other.code, elementId(other)) AS other_code,
     head(collect(other)) AS other,
     max(sim.score) AS score
ORDER BY score DESC
LIMIT $top_k
OPTIONAL MATCH path = (other)-[:REQUIRES_PREREQUISITE*1..{max_depth}]->(prereq:Course)
OPTIONAL MATCH (other)-[:CLASSIFIED_AS]->(req:RequirementCategory)
WITH other, score,
     collect(DISTINCT req.name) AS req_names,
     collect(DISTINCT {{
         code: coalesce(prereq.course_code, prereq.code, ''),
         title: coalesce(prereq.title, prereq.name, ''),
         credits: prereq.credits,
         term: coalesce(prereq.semester, ''),
         depth: length(path)
     }}) AS raw_prereqs
WITH other, score,
     head([r IN req_names WHERE r IS NOT NULL]) AS requirement_category,
     [p IN raw_prereqs WHERE p.title <> ''] AS prerequisites
RETURN coalesce(other.course_code, other.code, '') AS code,
       coalesce(other.title, other.name, '') AS title,
       other.credits AS credits,
       coalesce(other.semester, '') AS term,
       coalesce(requirement_category, '') AS category,
       requirement_category,
       score AS score,
       prerequisites
ORDER BY score DESC;
"""

_QUERY_PURE_GRAPH_TEMPLATE = """
MATCH (seed:Course)
WHERE (seed.syllabus_id = $identifier OR seed.course_code = $identifier OR seed.code = $identifier OR seed.title CONTAINS $identifier OR seed.name CONTAINS $identifier)
WITH coalesce(seed.course_code, seed.code, elementId(seed)) AS code, head(collect(seed)) AS seed
ORDER BY seed.title ASC
LIMIT $top_k
OPTIONAL MATCH path = (seed)-[:REQUIRES_PREREQUISITE*1..{max_depth}]->(prereq:Course)
OPTIONAL MATCH (seed)-[:CLASSIFIED_AS]->(req:RequirementCategory)
WITH seed,
     collect(DISTINCT req.name) AS req_names,
     collect(DISTINCT {{
         code: coalesce(prereq.course_code, prereq.code, ''),
         title: coalesce(prereq.title, prereq.name, ''),
         credits: prereq.credits,
         term: coalesce(prereq.semester, ''),
         depth: length(path)
     }}) AS raw_prereqs
WITH seed,
     head([r IN req_names WHERE r IS NOT NULL]) AS requirement_category,
     [p IN raw_prereqs WHERE p.title <> ''] AS prerequisites
RETURN coalesce(seed.course_code, seed.code, '') AS code,
       coalesce(seed.title, seed.name, '') AS title,
       seed.credits AS credits,
       coalesce(seed.semester, '') AS term,
       coalesce(requirement_category, '') AS category,
       requirement_category,
       1.0 AS score,
       prerequisites
ORDER BY title ASC;
"""

_QUERY_COURSE_GRAPH = """
MATCH (seed:Course)
WHERE (seed.syllabus_id = $course_code OR seed.course_code = $course_code OR seed.code = $course_code)
WITH seed LIMIT 1
OPTIONAL MATCH path = (seed)-[:REQUIRES_PREREQUISITE*1..3]->(p:Course)
WITH seed, collect(path) AS paths
OPTIONAL MATCH (seed)-[sim:SIMILAR_TO]-(s:Course)
WITH seed, paths, collect(DISTINCT {node: s, score: sim.score}) AS sim_items
RETURN seed, paths, sim_items;
"""


def _sanitize_depth(max_depth: int) -> int:
    return max(1, min(int(max_depth), 5))


async def search_hybrid(
    session: AsyncSession,
    query_embedding: List[float],
    top_k: int = 5,
    max_depth: int = 3,
) -> List[CourseSearchResultItem]:
    """Mode A: Proposed Hybrid - Dynamic vector index search + topology traversal."""
    depth = _sanitize_depth(max_depth)
    query = _QUERY_HYBRID_TEMPLATE.format(max_depth=depth)
    candidate_limit = min(max(top_k * 4, top_k), 100)
    result = await session.run(
        query,
        top_k=top_k,
        candidate_limit=candidate_limit,
        query_embedding=query_embedding,
    )
    records = await result.data()
    return [_map_result_item(r) for r in records]


async def search_by_similarity_edge(
    session: AsyncSession,
    identifier: str,
    top_k: int = 5,
    min_score: float = 0.5,
    max_depth: int = 2,
) -> List[CourseSearchResultItem]:
    """Mode B: Precomputed Similarity - Traverse precomputed [:SIMILAR_TO] edges from seed course."""
    depth = _sanitize_depth(max_depth)
    query = _QUERY_SIMILARITY_TEMPLATE.format(max_depth=depth)
    result = await session.run(
        query,
        identifier=identifier,
        top_k=top_k,
        min_score=float(min_score),
    )
    records = await result.data()
    return [_map_result_item(r) for r in records]


async def search_pure_graph(
    session: AsyncSession,
    identifier: str,
    top_k: int = 5,
    max_depth: int = 3,
) -> List[CourseSearchResultItem]:
    """Mode C: Pure Graph - Keyword match + topology prerequisite traversal."""
    depth = _sanitize_depth(max_depth)
    query = _QUERY_PURE_GRAPH_TEMPLATE.format(max_depth=depth)
    result = await session.run(
        query,
        identifier=identifier,
        top_k=top_k,
    )
    records = await result.data()
    return [_map_result_item(r) for r in records]


async def get_course_graph(
    session: AsyncSession,
    course_code: str,
) -> CourseGraphResponse:
    """Retrieve prerequisite DAG and similarity edges for course graph visualization."""
    result = await session.run(_QUERY_COURSE_GRAPH, course_code=course_code)
    record = await result.single()

    if not record or not record["seed"]:
        return CourseGraphResponse(
            course_code=course_code,
            title="",
            nodes=[],
            edges=[],
        )

    seed = record["seed"]
    seed_code = seed.get("course_code") or seed.get("code") or course_code
    seed_title = seed.get("title") or seed.get("name") or ""

    nodes_by_id: dict[str, GraphNode] = {}
    edges_list: list[GraphEdge] = []
    seen_edges: set[tuple[str, str, str]] = set()

    # Add seed node
    nodes_by_id[seed_code] = GraphNode(
        id=seed_code,
        code=seed_code,
        title=seed_title,
        credits=seed.get("credits"),
        term=seed.get("term") or seed.get("semester"),
        node_type="seed",
    )

    # Process prerequisite paths
    paths = record["paths"] or []
    for path in paths:
        if not path:
            continue
        for rel in path.relationships:
            start_n = rel.start_node
            end_n = rel.end_node
            s_code = start_n.get("course_code") or start_n.get("code") or ""
            e_code = end_n.get("course_code") or end_n.get("code") or ""

            if not s_code or not e_code:
                continue

            if s_code not in nodes_by_id:
                nodes_by_id[s_code] = GraphNode(
                    id=s_code,
                    code=s_code,
                    title=start_n.get("title") or start_n.get("name") or "",
                    credits=start_n.get("credits"),
                    term=start_n.get("term") or start_n.get("semester"),
                    node_type="seed" if s_code == seed_code else "prerequisite",
                )
            if e_code not in nodes_by_id:
                nodes_by_id[e_code] = GraphNode(
                    id=e_code,
                    code=e_code,
                    title=end_n.get("title") or end_n.get("name") or "",
                    credits=end_n.get("credits"),
                    term=end_n.get("term") or end_n.get("semester"),
                    node_type="prerequisite",
                )

            edge_key = (s_code, e_code, "REQUIRES_PREREQUISITE")
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                edges_list.append(
                    GraphEdge(
                        source=s_code,
                        target=e_code,
                        type="REQUIRES_PREREQUISITE",
                        score=None,
                    )
                )

    # Process similar courses
    sim_items = record["sim_items"] or []
    for item in sim_items:
        sim_node = item.get("node")
        if not sim_node:
            continue
        sim_code = sim_node.get("course_code") or sim_node.get("code") or ""
        if not sim_code or sim_code == seed_code:
            continue
        score = item.get("score")

        if sim_code not in nodes_by_id:
            nodes_by_id[sim_code] = GraphNode(
                id=sim_code,
                code=sim_code,
                title=sim_node.get("title") or sim_node.get("name") or "",
                credits=sim_node.get("credits"),
                term=sim_node.get("term") or sim_node.get("semester"),
                node_type="similar",
            )

        edge_key = (seed_code, sim_code, "SIMILAR_TO")
        if edge_key not in seen_edges:
            seen_edges.add(edge_key)
            edges_list.append(
                GraphEdge(
                    source=seed_code,
                    target=sim_code,
                    type="SIMILAR_TO",
                    score=float(score) if score is not None else None,
                )
            )

    return CourseGraphResponse(
        course_code=seed_code,
        title=seed_title,
        nodes=list(nodes_by_id.values()),
        edges=edges_list,
    )


def _map_result_item(record: dict[str, Any]) -> CourseSearchResultItem:
    prereqs = [
        CoursePrereqItem(
            code=p.get("code", ""),
            title=p.get("title", ""),
            credits=p.get("credits"),
            term=p.get("term"),
            depth=p.get("depth", 1),
        )
        for p in record.get("prerequisites", [])
        if p.get("title")
    ]
    prereqs.sort(key=lambda x: (x.depth, x.title))
    return CourseSearchResultItem(
        code=record.get("code", ""),
        title=record.get("title", ""),
        credits=record.get("credits"),
        term=record.get("term"),
        category=record.get("category"),
        requirement_category=record.get("requirement_category"),
        score=round(float(record.get("score", 0.0)), 4),
        prerequisites=prereqs,
    )
