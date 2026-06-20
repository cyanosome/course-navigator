import os
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncpg
from neo4j import AsyncGraphDatabase

# PostgreSQL Configurations
DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "coursenavigator")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "secure_password_please_change")

# Neo4j Configurations
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "secure_password_please_change")

# Input Schemas
class PostgresTestInput(BaseModel):
    title: str
    description: str | None = None

class Neo4jTestInput(BaseModel):
    title: str
    description: str | None = None
    prerequisite_title: str | None = None

class IntegratedSyllabusInput(BaseModel):
    code: str
    title: str
    instructor: str
    schedule: str
    credits: int
    syllabus_text: str | None = None
    prerequisite_codes: list[str] = []
    topics: list[str] = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- PostgreSQL 接続プールの初期化 ---
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
        
        # 複合シラバス検証用テーブルの作成
        await conn.execute("""
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
        """)

    # --- Neo4j ドライバ初期化 ---
    neo4j_driver = AsyncGraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USER, NEO4J_PASSWORD)
    )
    app.state.neo4j_driver = neo4j_driver

    yield

    # --- シャットダウン処理 ---
    await pool.close()
    await neo4j_driver.close()

app = FastAPI(lifespan=lifespan)

# --- PostgreSQL エンドポイント ---

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

# --- Neo4j エンドポイント ---

@app.post("/test/neo4j")
async def test_neo4j_insert(data: Neo4jTestInput):
    driver = app.state.neo4j_driver
    record_id = str(uuid.uuid4())
    prereq_id = str(uuid.uuid4())
    
    query = """
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
    
    async with driver.session() as session:
        await session.run(
            query,
            id=record_id,
            title=data.title,
            description=data.description or "",
            prerequisite_title=data.prerequisite_title or "",
            prerequisite_id=prereq_id
        )
    return {
        "id": record_id,
        "title": data.title,
        "description": data.description,
        "prerequisite_title": data.prerequisite_title
    }

@app.get("/test/neo4j")
async def test_neo4j_search(q: str = ""):
    driver = app.state.neo4j_driver
    
    query = """
    MATCH (c:Course)
    WHERE c.title CONTAINS $q OR (c.description IS NOT NULL AND c.description CONTAINS $q)
    OPTIONAL MATCH (c)-[:REQUIRES_PREREQUISITE]->(p:Course)
    RETURN c.id AS id, c.title AS title, c.description AS description, collect(p.title) AS prerequisites
    ORDER BY c.title ASC
    """
    
    async with driver.session() as session:
        result = await session.run(query, q=q)
        records = await result.data()
        
    return [
        {
            "id": record["id"],
            "title": record["title"],
            "description": record["description"],
            "prerequisites": record["prerequisites"]
        } for record in records
    ]

# --- 複合疎通テスト用（Postgres + Neo4j）エンドポイント ---

@app.post("/test/integrated")
async def test_integrated_insert(data: IntegratedSyllabusInput):
    pool = app.state.db_pool
    driver = app.state.neo4j_driver
    
    course_id = str(uuid.uuid4())
    
    async with pool.acquire() as conn:
        # 1. 前提講義コードが未登録の場合、自動的にプレースホルダーを作成して同期
        prereq_id_map = {}
        for p_code in data.prerequisite_codes:
            if not p_code.strip():
                continue
            row = await conn.fetchrow("SELECT id FROM test_postgres_syllabus WHERE code = $1", p_code.strip())
            if row:
                prereq_id_map[p_code.strip()] = str(row["id"])
            else:
                p_id = str(uuid.uuid4())
                await conn.execute(
                    "INSERT INTO test_postgres_syllabus (id, code, title, instructor, schedule, credits, syllabus_text) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    uuid.UUID(p_id), p_code.strip(), f"{p_code.strip()} (未登録)", "未設定", "未設定", 0, "プレースホルダー"
                )
                async with driver.session() as session:
                    await session.run("MERGE (c:Course {id: $id}) SET c.code = $code, c.title = $title", id=p_id, code=p_code.strip(), title=f"{p_code.strip()} (未登録)")
                prereq_id_map[p_code.strip()] = p_id

        # 2. メイン講義情報を PostgreSQL に挿入、またはプレースホルダーを更新
        existing_row = await conn.fetchrow("SELECT id FROM test_postgres_syllabus WHERE code = $1", data.code.strip())
        if existing_row:
            course_id = str(existing_row["id"])
            await conn.execute(
                """UPDATE test_postgres_syllabus 
                   SET title = $2, instructor = $3, schedule = $4, credits = $5, syllabus_text = $6 
                   WHERE id = $1""",
                uuid.UUID(course_id), data.title, data.instructor, data.schedule, data.credits, data.syllabus_text
            )
        else:
            await conn.execute(
                """INSERT INTO test_postgres_syllabus (id, code, title, instructor, schedule, credits, syllabus_text) 
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                uuid.UUID(course_id), data.code.strip(), data.title, data.instructor, data.schedule, data.credits, data.syllabus_text
            )
            
    # 3. Neo4j にノードおよび関係性を接続
    async with driver.session() as session:
        # メインノードの作成/更新
        await session.run(
            "MERGE (c:Course {id: $id}) SET c.code = $code, c.title = $title",
            id=course_id, code=data.code.strip(), title=data.title
        )
        
        # 前提条件関係の接続
        for p_code, p_id in prereq_id_map.items():
            await session.run(
                """MATCH (c:Course {id: $course_id}), (p:Course {id: $prereq_id})
                   MERGE (c)-[:REQUIRES_PREREQUISITE]->(p)""",
                course_id=course_id, prereq_id=p_id
            )
            
        # トピックの接続
        for topic in data.topics:
            if not topic.strip():
                continue
            await session.run(
                """MATCH (c:Course {id: $course_id})
                   MERGE (t:Topic {name: $topic_name})
                   MERGE (c)-[:COVERS_TOPIC]->(t)""",
                course_id=course_id, topic_name=topic.strip()
            )
            
    return {"id": course_id, "code": data.code, "title": data.title}

@app.get("/test/integrated")
async def test_integrated_search(q: str = ""):
    pool = app.state.db_pool
    driver = app.state.neo4j_driver
    
    # 1. PostgreSQLからあいまい検索でデータを取得
    async with pool.acquire() as conn:
        if q:
            rows = await conn.fetch(
                """SELECT id, code, title, instructor, schedule, credits, syllabus_text 
                   FROM test_postgres_syllabus 
                   WHERE title ILIKE $1 OR code ILIKE $1 OR syllabus_text ILIKE $1 
                   ORDER BY code ASC""",
                f"%{q}%"
            )
        else:
            rows = await conn.fetch(
                """SELECT id, code, title, instructor, schedule, credits, syllabus_text 
                   FROM test_postgres_syllabus 
                   ORDER BY code ASC"""
            )
            
    if not rows:
        return []
        
    course_list = [dict(row) for row in rows]
    course_ids = [str(c["id"]) for c in course_list]
    
    # 2. Neo4jから関係データを取得
    graph_data_map = {}
    async with driver.session() as session:
        result = await session.run(
            """UNWIND $ids AS course_id
               MATCH (c:Course {id: course_id})
               OPTIONAL MATCH (c)-[:REQUIRES_PREREQUISITE]->(p:Course)
               OPTIONAL MATCH (c)-[:COVERS_TOPIC]->(t:Topic)
               OPTIONAL MATCH (t)<-[:COVERS_TOPIC]-(other:Course) WHERE other.id <> c.id
               RETURN c.id AS id,
                      collect(DISTINCT {id: p.id, code: p.code, title: p.title}) AS prerequisites,
                      collect(DISTINCT t.name) AS topics,
                      collect(DISTINCT {id: other.id, code: other.code, title: other.title, topic: t.name}) AS related_courses""",
            ids=course_ids
        )
        graph_records = await result.data()
        for rec in graph_records:
            graph_data_map[rec["id"]] = rec

    # 3. データをマージ
    merged_results = []
    for course in course_list:
        c_id = str(course["id"])
        g_data = graph_data_map.get(c_id, {"prerequisites": [], "topics": [], "related_courses": []})
        
        prereqs = [p for p in g_data.get("prerequisites", []) if p.get("id")]
        related = [r for r in g_data.get("related_courses", []) if r.get("id")]
        
        merged_results.append({
            "id": c_id,
            "code": course["code"],
            "title": course["title"],
            "instructor": course["instructor"],
            "schedule": course["schedule"],
            "credits": course["credits"],
            "syllabus_text": course["syllabus_text"],
            "prerequisites": prereqs,
            "topics": [t for t in g_data.get("topics", []) if t],
            "related_courses": related
        })
        
    return merged_results
