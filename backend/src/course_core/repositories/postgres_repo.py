"""PostgreSQL への SQL アクセスを集約するリポジトリ。

SQL 文とクエリ実行のみを担当し、HTTP や業務ロジックは持たない。
"""

import uuid

import asyncpg

# --- スキーマ定義（lifespan から呼び出す） ---

CREATE_TEST_POSTGRES = """
CREATE TABLE IF NOT EXISTS test_postgres (
    id UUID PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_TEST_POSTGRES_SYLLABUS = """
CREATE TABLE IF NOT EXISTS test_postgres_syllabus (
    id UUID PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    instructor VARCHAR(255),
    schedule VARCHAR(255),
    credits INTEGER,
    syllabus_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


async def create_tables(conn: asyncpg.Connection) -> None:
    """テスト用テーブルを作成する（存在しない場合のみ）。"""
    await conn.execute(CREATE_TEST_POSTGRES)
    await conn.execute(CREATE_TEST_POSTGRES_SYLLABUS)


# --- test_postgres エンドポイント用 ---

async def insert_test_record(
    conn: asyncpg.Connection,
    record_id: uuid.UUID,
    title: str,
    description: str | None,
) -> None:
    await conn.execute(
        "INSERT INTO test_postgres (id, title, description) VALUES ($1, $2, $3)",
        record_id, title, description,
    )


async def search_test_records(conn: asyncpg.Connection, q: str) -> list[asyncpg.Record]:
    if q:
        return await conn.fetch(
            "SELECT id, title, description, created_at FROM test_postgres "
            "WHERE title ILIKE $1 ORDER BY created_at DESC",
            f"%{q}%",
        )
    return await conn.fetch(
        "SELECT id, title, description, created_at FROM test_postgres ORDER BY created_at DESC"
    )


# --- test_postgres_syllabus（複合テスト）用 ---

async def get_syllabus_ids_by_codes(
    conn: asyncpg.Connection, codes: list[str]
) -> dict[str, str]:
    """指定コード群のうち既存レコードを一括取得し {code: id} で返す（N+1 回避）。"""
    if not codes:
        return {}
    rows = await conn.fetch(
        "SELECT id, code FROM test_postgres_syllabus WHERE code = ANY($1)",
        codes,
    )
    return {row["code"]: str(row["id"]) for row in rows}


async def get_syllabus_id_by_code(conn: asyncpg.Connection, code: str) -> str | None:
    row = await conn.fetchrow(
        "SELECT id FROM test_postgres_syllabus WHERE code = $1", code
    )
    return str(row["id"]) if row else None


async def bulk_insert_syllabus_placeholders(
    conn: asyncpg.Connection, records: list[tuple]
) -> None:
    """未登録の前提講義プレースホルダーを一括 INSERT する（N+1 回避）。

    records の各要素は
    (id, code, title, instructor, schedule, credits, syllabus_text)。
    """
    if not records:
        return
    await conn.executemany(
        "INSERT INTO test_postgres_syllabus "
        "(id, code, title, instructor, schedule, credits, syllabus_text) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        records,
    )


async def insert_syllabus(
    conn: asyncpg.Connection,
    course_id: str,
    code: str,
    title: str,
    instructor: str,
    schedule: str,
    credits: int,
    syllabus_text: str | None,
) -> None:
    await conn.execute(
        "INSERT INTO test_postgres_syllabus "
        "(id, code, title, instructor, schedule, credits, syllabus_text) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        uuid.UUID(course_id), code, title, instructor, schedule, credits, syllabus_text,
    )


async def update_syllabus(
    conn: asyncpg.Connection,
    course_id: str,
    title: str,
    instructor: str,
    schedule: str,
    credits: int,
    syllabus_text: str | None,
) -> None:
    await conn.execute(
        "UPDATE test_postgres_syllabus "
        "SET title = $2, instructor = $3, schedule = $4, credits = $5, syllabus_text = $6 "
        "WHERE id = $1",
        uuid.UUID(course_id), title, instructor, schedule, credits, syllabus_text,
    )


async def search_syllabus(conn: asyncpg.Connection, q: str) -> list[asyncpg.Record]:
    if q:
        return await conn.fetch(
            "SELECT id, code, title, instructor, schedule, credits, syllabus_text "
            "FROM test_postgres_syllabus "
            "WHERE title ILIKE $1 OR code ILIKE $1 OR syllabus_text ILIKE $1 "
            "ORDER BY code ASC",
            f"%{q}%",
        )
    return await conn.fetch(
        "SELECT id, code, title, instructor, schedule, credits, syllabus_text "
        "FROM test_postgres_syllabus ORDER BY code ASC"
    )
