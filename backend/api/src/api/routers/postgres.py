"""PostgreSQL 疎通テスト用ルーター。"""

import uuid
from typing import Any

from fastapi import APIRouter, Request

from course_core.repositories import postgres_repo
from course_core.schemas.postgres import PostgresTestInput

router = APIRouter(tags=["postgres"])


@router.post("/test/postgres")
async def test_postgres_insert(data: PostgresTestInput, request: Request) -> dict[str, Any]:
    pool = request.app.state.db_pool
    record_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await postgres_repo.insert_test_record(conn, record_id, data.title, data.description)
    return {"id": record_id, "title": data.title, "description": data.description}


@router.get("/test/postgres")
async def test_postgres_search(request: Request, q: str = "") -> list[dict[str, Any]]:
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await postgres_repo.search_test_records(conn, q)
    return [
        {
            "id": str(row["id"]),
            "title": row["title"],
            "description": row["description"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
