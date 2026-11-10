"""アプリケーションのエントリポイント。

CI（`uv run python -c "import api.main"`）および起動コマンド
（`fastapi dev src/api/main.py`）が参照するため、`app` をここで公開し続ける。
接続の初期化は lifespan 内に閉じ込め、モジュール読み込みでは副作用を起こさない。
"""

from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from neo4j import AsyncGraphDatabase

from agent import deps as agent_deps
from agent.nodes import mcp_route_enabled
from course_core import config, seeder
from course_core.errors import register_exception_handlers
from course_core.repositories import postgres_repo
from api.routers import (
    agent,
    assist,
    catalog,
    diagnose,
    integrated,
    navi,
    neo4j,
    postgres,
    research,
    search,
)


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

    # --- Agent 依存性注入（実 DB ドライバをエージェントノードへ伝播） ---
    agent_deps.set_backends(pool, neo4j_driver)

    # --- 初期シードデータの自動投入（DBが空の場合のみ） ---
    await seeder.seed_initial_data_if_empty(pool, neo4j_driver)

    # --- AI の口（A1）で使い回す Neo4j の McpToolset（起動に約6秒かかるので1回だけ繋ぐ） ---
    mcp_toolset = None
    if mcp_route_enabled():
        # mcp_agent は mcp パッケージを読み込むので遅延 import（`import api.main` を mcp に依存させない）
        from agent.mcp_agent import open_shared_mcp_toolset

        mcp_toolset = await open_shared_mcp_toolset()
    agent_deps.set_mcp_toolset(mcp_toolset)

    yield

    # --- シャットダウン処理 ---
    agent_deps.set_mcp_toolset(None)
    if mcp_toolset is not None:
        await mcp_toolset.close()
    agent_deps.set_backends(None, None)
    await pool.close()
    await neo4j_driver.close()


app = FastAPI(lifespan=lifespan)

register_exception_handlers(app)

# 登録対象の全 10 ルーター
ALL_ROUTERS = [
    postgres.router,
    neo4j.router,
    integrated.router,
    agent.router,
    catalog.router,
    research.router,
    assist.router,
    diagnose.router,
    search.router,
    navi.router,
]

# Traefik (URLパスから /api を剥離する環境) と、
# Vite プロキシ/直接アクセス (/api を保持してリクエストする環境) の双方に対応
for r in ALL_ROUTERS:
    app.include_router(r)
    app.include_router(r, prefix="/api")
