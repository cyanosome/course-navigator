"""アプリケーションのエントリポイント。

CI（`uv run python -c "import api.main"`）および起動コマンド
（`fastapi dev src/api/main.py`）が参照するため、`app` をここで公開し続ける。
接続の初期化は lifespan 内に閉じ込め、モジュール読み込みでは副作用を起こさない。
"""

from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from neo4j import AsyncGraphDatabase

from course_core import config
from course_core.errors import register_exception_handlers
from course_core.repositories import postgres_repo
from api.routers import integrated, neo4j, postgres


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 必須の秘密環境変数を起動時に検証（未設定なら明示的に失敗）
    config.validate_required_env()

    # --- PostgreSQL 接続プールの初期化 ---
    pool = await asyncpg.create_pool(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
    )
    app.state.db_pool = pool

    # テスト用テーブルの作成
    async with pool.acquire() as conn:
        await postgres_repo.create_tables(conn)

    # --- Neo4j ドライバ初期化 ---
    neo4j_driver = AsyncGraphDatabase.driver(
        config.NEO4J_URI,
        auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
    )
    app.state.neo4j_driver = neo4j_driver

    yield

    # --- シャットダウン処理 ---
    await pool.close()
    await neo4j_driver.close()


app = FastAPI(lifespan=lifespan)

register_exception_handlers(app)

app.include_router(postgres.router)
app.include_router(neo4j.router)
app.include_router(integrated.router)
