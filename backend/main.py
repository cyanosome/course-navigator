import os
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncpg

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "coursenavigator")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "secure_password_please_change")

class PostgresTestInput(BaseModel):
    title: str
    description: str | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 接続プールの初期化
    pool = await asyncpg.create_pool(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )
    app.state.db_pool = pool
    
    # テスト用テーブルの作成
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS test_postgres (
                id UUID PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
    yield
    # プールのクローズ
    await pool.close()

app = FastAPI(lifespan=lifespan)

@app.post("/test/postgres")
async def test_postgres_insert(data: PostgresTestInput):
    pool = app.state.db_pool
    record_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO test_postgres (id, title, description) VALUES ($1, $2, $3)",
            record_id, data.title, data.description
        )
    return {"id": record_id, "title": data.title, "description": data.description}

@app.get("/test/postgres")
async def test_postgres_search(q: str = ""):
    pool = app.state.db_pool
    async with pool.acquire() as conn:
        if q:
            rows = await conn.fetch(
                "SELECT id, title, description, created_at FROM test_postgres WHERE title ILIKE $1 ORDER BY created_at DESC",
                f"%{q}%"
            )
        else:
            rows = await conn.fetch(
                "SELECT id, title, description, created_at FROM test_postgres ORDER BY created_at DESC"
            )
    return [
        {
            "id": str(row["id"]),
            "title": row["title"],
            "description": row["description"],
            "created_at": row["created_at"]
        } for row in rows
    ]
