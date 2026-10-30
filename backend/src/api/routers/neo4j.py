"""Neo4j 疎通テスト用ルーター。"""

import uuid
from typing import Any

from fastapi import APIRouter, Request

from course_core.repositories import neo4j_repo
from course_core.schemas.neo4j import Neo4jTestInput

router = APIRouter(tags=["neo4j"])


@router.post("/test/neo4j")
async def test_neo4j_insert(data: Neo4jTestInput, request: Request) -> dict[str, Any]:
    driver = request.app.state.neo4j_driver
    record_id = str(uuid.uuid4())
    prereq_id = str(uuid.uuid4())

    async with driver.session() as session:
        await neo4j_repo.merge_course_with_prerequisite(
            session,
            record_id=record_id,
            title=data.title,
            description=data.description or "",
            prerequisite_title=data.prerequisite_title or "",
            prerequisite_id=prereq_id,
        )
    return {
        "id": record_id,
        "title": data.title,
        "description": data.description,
        "prerequisite_title": data.prerequisite_title,
    }


@router.get("/test/neo4j")
async def test_neo4j_search(request: Request, q: str = "") -> list[dict[str, Any]]:
    driver = request.app.state.neo4j_driver
    async with driver.session() as session:
        records = await neo4j_repo.search_courses(session, q)
    return [
        {
            "id": record["id"],
            "title": record["title"],
            "description": record["description"],
            "prerequisites": record["prerequisites"],
        }
        for record in records
    ]
