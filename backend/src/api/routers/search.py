"""Search router for multi-mode course search and graph retrieval."""

import time
from typing import Any
from fastapi import APIRouter, HTTPException, Request

from course_core.repositories import cypher_search_repo
from course_core.schemas.search import (
    CourseGraphResponse,
    CourseSearchRequest,
    CourseSearchResponse,
    SearchMode,
)
from services import embedding

router = APIRouter(tags=["search"])


@router.post("/search/courses", response_model=CourseSearchResponse)
async def search_courses(request_data: CourseSearchRequest, request: Request) -> CourseSearchResponse:
    """Multi-mode course search endpoint.

    Modes:
    - hybrid: Dynamic Neo4j vector index search + topology prerequisite traversal
    - similarity: Traverse precomputed [:SIMILAR_TO] edges
    - pure_graph: Keyword lookup + prerequisite DAG traversal
    """
    driver = getattr(request.app.state, "neo4j_driver", None)
    if not driver:
        raise HTTPException(status_code=503, detail="Neo4j driver is not initialized")

    start_time = time.perf_counter()

    async with driver.session() as session:
        if request_data.mode == SearchMode.HYBRID:
            try:
                query_embedding = await embedding.get_embedding(request_data.query)
            except embedding.GeminiApiUnavailableError as e:
                raise HTTPException(status_code=503, detail=str(e))
            results = await cypher_search_repo.search_hybrid(
                session=session,
                query_embedding=query_embedding,
                top_k=request_data.top_k,
                max_depth=request_data.max_depth,
            )
        elif request_data.mode == SearchMode.SIMILARITY_EDGE:
            results = await cypher_search_repo.search_by_similarity_edge(
                session=session,
                identifier=request_data.query,
                top_k=request_data.top_k,
                max_depth=request_data.max_depth,
            )
        elif request_data.mode == SearchMode.PURE_GRAPH:
            results = await cypher_search_repo.search_pure_graph(
                session=session,
                identifier=request_data.query,
                top_k=request_data.top_k,
                max_depth=request_data.max_depth,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported search mode: {request_data.mode}")

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return CourseSearchResponse(
        mode=request_data.mode,
        query=request_data.query,
        total_hits=len(results),
        execution_time_ms=elapsed_ms,
        results=results,
    )


@router.get("/courses/{code}/graph", response_model=CourseGraphResponse)
async def get_course_graph(code: str, request: Request) -> CourseGraphResponse:
    """Retrieve course prerequisite DAG and similarity edges for graph visualization."""
    driver = getattr(request.app.state, "neo4j_driver", None)
    if not driver:
        raise HTTPException(status_code=503, detail="Neo4j driver is not initialized")

    async with driver.session() as session:
        return await cypher_search_repo.get_course_graph(session=session, course_code=code)
