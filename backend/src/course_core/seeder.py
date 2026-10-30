"""データベースの初期シードデータ（courses.json）自動投入モジュール。

FastAPI の lifespan 起動時に呼び出され、PostgreSQL または Neo4j に
科目データが存在しない場合に、`backend/seed/courses.json` から
20件のシラバス・前提関係・トピックを一括投入します。
"""

import json
import logging
import uuid
from pathlib import Path

import asyncpg
from neo4j import AsyncDriver

from course_core.repositories import neo4j_repo, postgres_repo

logger = logging.getLogger(__name__)

_SEED_RELATIVE = Path("seed") / "courses.json"
_PLACEHOLDER_INSTRUCTOR = "未設定"
_PLACEHOLDER_SCHEDULE = "未設定"
_PLACEHOLDER_CREDITS = 0
_PLACEHOLDER_SYLLABUS_TEXT = "プレースホルダー"


def _find_seed_path() -> Path:
    """`backend/seed/courses.json` のパスを探索する。"""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _SEED_RELATIVE
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"{_SEED_RELATIVE} が見つかりません。")


def load_seed_courses() -> list[dict]:
    """`courses.json` をロードして返す。"""
    path = _find_seed_path()
    return json.loads(path.read_text(encoding="utf-8"))


async def is_db_empty(conn: asyncpg.Connection, driver: AsyncDriver) -> bool:
    """PostgreSQL または Neo4j のどちらかに科目データが未登録か確認する。"""
    # 1. PostgreSQL の件数チェック
    row = await conn.fetchrow("SELECT COUNT(*) AS count FROM test_postgres_syllabus")
    pg_count = row["count"] if row else 0

    # 2. Neo4j のノード数チェック
    neo4j_count = 0
    async with driver.session() as session:
        result = await session.run("MATCH (c:Course) RETURN count(c) AS count")
        rec = await result.single()
        if rec:
            neo4j_count = rec["count"]

    logger.info("DB 初期チェック: PostgreSQL=%d 件, Neo4j=%d ノード", pg_count, neo4j_count)
    return pg_count == 0 or neo4j_count == 0


async def seed_initial_data_if_empty(
    pool: asyncpg.Pool, driver: AsyncDriver, *, force: bool = False
) -> None:
    """DB が空の場合、または force=True の場合にシードデータを投入する。"""
    async with pool.acquire() as conn:
        empty = await is_db_empty(conn, driver)
        if not empty and not force:
            logger.info("シードデータは既に投入されています。スキップします。")
            return

        logger.info("シードデータの投入を開始します...")
        courses = load_seed_courses()

        async with conn.transaction():
            # 1. 全科目のコードと新規IDを割り振る
            course_id_map: dict[str, str] = {}
            for item in courses:
                code = item["code"].strip()
                existing_id = await postgres_repo.get_syllabus_id_by_code(conn, code)
                course_id_map[code] = existing_id or str(uuid.uuid4())

            # 2. PostgreSQL への一括挿入/更新
            for item in courses:
                code = item["code"].strip()
                c_id = course_id_map[code]
                title = item["title"].strip()
                instructor = item.get("instructor") or _PLACEHOLDER_INSTRUCTOR
                schedule = item.get("schedule") or _PLACEHOLDER_SCHEDULE
                credits_val = item.get("credits") if item.get("credits") is not None else _PLACEHOLDER_CREDITS
                syllabus_text = item.get("syllabus_text") or _PLACEHOLDER_SYLLABUS_TEXT

                existing_id = await postgres_repo.get_syllabus_id_by_code(conn, code)
                if existing_id:
                    await postgres_repo.update_syllabus(
                        conn,
                        c_id,
                        title,
                        instructor,
                        schedule,
                        credits_val,
                        syllabus_text,
                    )
                else:
                    await postgres_repo.insert_syllabus(
                        conn,
                        c_id,
                        code,
                        title,
                        instructor,
                        schedule,
                        credits_val,
                        syllabus_text,
                    )

            # 3. Neo4j への一括ノード・リレーション投入
            async with driver.session() as session:
                for item in courses:
                    code = item["code"].strip()
                    c_id = course_id_map[code]
                    title = item["title"].strip()
                    prereq_codes = [c.strip() for c in item.get("prerequisite_codes", []) if c.strip()]
                    topics = [t.strip() for t in item.get("topics", []) if t.strip()]

                    # メインノードの作成
                    await neo4j_repo.merge_main_course(session, c_id, code, title)

                    # 前提条件リレーションの作成
                    prereq_ids = [course_id_map[p_code] for p_code in prereq_codes if p_code in course_id_map]
                    if prereq_ids:
                        await neo4j_repo.merge_prerequisites(session, c_id, prereq_ids)

                    # トピックリレーションの作成
                    if topics:
                        await neo4j_repo.merge_topics(session, c_id, topics)

        logger.info("シードデータ投入が完了しました (%d 件)。", len(courses))


async def _run_cli() -> None:
    """CLIから単体実行された際のシード投入処理。

    FastAPI サーバーを起動することなく、スタンドアロンで PostgreSQL および
    Neo4j への接続を確立し、シードデータの強制投入（force=True）を実行して
    安全に接続をクローズします。
    """
    from course_core import config

    # 1. 接続に必要な環境変数の検証
    config.validate_required_env()

    # 2. PostgreSQL 接続プールの作成とテーブル初期化（DDL）
    pool = await asyncpg.create_pool(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
    )
    async with pool.acquire() as conn:
        await postgres_repo.create_tables(conn)

    # 3. Neo4j 非同期ドライバの初期化
    from neo4j import AsyncGraphDatabase

    driver = AsyncGraphDatabase.driver(
        config.NEO4J_URI,
        auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
    )

    # 4. シードデータの投入とコネクションの確実な解放
    try:
        await seed_initial_data_if_empty(pool, driver, force=True)
    finally:
        await pool.close()
        await driver.close()


if __name__ == "__main__":
    # コマンドライン（python -m course_core.seeder）から直接実行された場合のみエントリ
    import asyncio

    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run_cli())


