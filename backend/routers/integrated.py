"""複合（PostgreSQL + Neo4j）疎通テスト用ルーター。

挿入系は Postgres 側を単一トランザクションで一括化する。Neo4j 書き込みは
その Postgres トランザクションのブロック内で実行するが、`session.run()` は
auto-commit であり両者は同一トランザクションではない。Neo4j 書き込みが
失敗した場合は例外が伝播して Postgres 側だけがロールバックされる片方向の
補償であり、Neo4j 側の部分的な書き込みは残りうる（Postgres のロールバックは
Neo4j に波及しない）。例外は共通例外ハンドラが 502/503 に変換する。
"""

import uuid
from typing import Any

from fastapi import APIRouter, Request

from repositories import neo4j_repo, postgres_repo
from schemas.integrated import IntegratedSyllabusInput

router = APIRouter(tags=["integrated"])

_PLACEHOLDER_INSTRUCTOR = "未設定"
_PLACEHOLDER_SCHEDULE = "未設定"
_PLACEHOLDER_CREDITS = 0
_PLACEHOLDER_SYLLABUS_TEXT = "プレースホルダー"


@router.post("/test/integrated")
async def test_integrated_insert(
    data: IntegratedSyllabusInput, request: Request
) -> dict[str, Any]:
    pool = request.app.state.db_pool
    driver = request.app.state.neo4j_driver

    code = data.code.strip()
    # 入力順を保ったまま重複を除去する（同一コードの重複指定で一括 INSERT が
    # UNIQUE 制約に衝突し 409 になるのを防ぐ）
    prereq_codes = list(dict.fromkeys(c.strip() for c in data.prerequisite_codes if c.strip()))
    topics = list(dict.fromkeys(t.strip() for t in data.topics if t.strip()))
    course_id = str(uuid.uuid4())

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. 前提講義コードの既存分を一括取得（N+1 回避）
            prereq_id_map = await postgres_repo.get_syllabus_ids_by_codes(conn, prereq_codes)

            # 2. 未登録の前提講義プレースホルダーを一括作成（Postgres / Neo4j）
            new_codes = [c for c in prereq_codes if c not in prereq_id_map]
            pg_placeholders: list[tuple] = []
            neo4j_placeholders: list[dict[str, str]] = []
            for p_code in new_codes:
                p_id = str(uuid.uuid4())
                prereq_id_map[p_code] = p_id
                placeholder_title = f"{p_code} (未登録)"
                pg_placeholders.append(
                    (
                        uuid.UUID(p_id),
                        p_code,
                        placeholder_title,
                        _PLACEHOLDER_INSTRUCTOR,
                        _PLACEHOLDER_SCHEDULE,
                        _PLACEHOLDER_CREDITS,
                        _PLACEHOLDER_SYLLABUS_TEXT,
                    )
                )
                neo4j_placeholders.append(
                    {"id": p_id, "code": p_code, "title": placeholder_title}
                )
            await postgres_repo.bulk_insert_syllabus_placeholders(conn, pg_placeholders)

            # 3. メイン講義情報を挿入、または既存（プレースホルダー含む）を更新
            existing_id = await postgres_repo.get_syllabus_id_by_code(conn, code)
            if existing_id:
                course_id = existing_id
                await postgres_repo.update_syllabus(
                    conn,
                    course_id,
                    data.title,
                    data.instructor,
                    data.schedule,
                    data.credits,
                    data.syllabus_text,
                )
            else:
                await postgres_repo.insert_syllabus(
                    conn,
                    course_id,
                    code,
                    data.title,
                    data.instructor,
                    data.schedule,
                    data.credits,
                    data.syllabus_text,
                )

            # 4. Neo4j 書き込み（トランザクション内。失敗時は Postgres をロールバック）
            async with driver.session() as session:
                await neo4j_repo.merge_placeholder_courses(session, neo4j_placeholders)
                await neo4j_repo.merge_main_course(session, course_id, code, data.title)
                await neo4j_repo.merge_prerequisites(
                    session, course_id, list(prereq_id_map.values())
                )
                await neo4j_repo.merge_topics(session, course_id, topics)

    return {"id": course_id, "code": data.code, "title": data.title}


@router.get("/test/integrated")
async def test_integrated_search(request: Request, q: str = "") -> list[dict[str, Any]]:
    pool = request.app.state.db_pool
    driver = request.app.state.neo4j_driver

    # 1. PostgreSQL からあいまい検索でデータを取得
    async with pool.acquire() as conn:
        rows = await postgres_repo.search_syllabus(conn, q)

    if not rows:
        return []

    course_list = [dict(row) for row in rows]
    course_ids = [str(c["id"]) for c in course_list]

    # 2. Neo4j から関係データを取得
    graph_data_map: dict[str, Any] = {}
    async with driver.session() as session:
        graph_records = await neo4j_repo.search_integrated(session, course_ids)
    for rec in graph_records:
        graph_data_map[rec["id"]] = rec

    # 3. データをマージ
    merged_results: list[dict[str, Any]] = []
    for course in course_list:
        c_id = str(course["id"])
        g_data = graph_data_map.get(
            c_id, {"prerequisites": [], "topics": [], "related_courses": []}
        )

        prereqs = [p for p in g_data.get("prerequisites", []) if p.get("id")]
        related = [r for r in g_data.get("related_courses", []) if r.get("id")]

        merged_results.append(
            {
                "id": c_id,
                "code": course["code"],
                "title": course["title"],
                "instructor": course["instructor"],
                "schedule": course["schedule"],
                "credits": course["credits"],
                "syllabus_text": course["syllabus_text"],
                "prerequisites": prereqs,
                "topics": [t for t in g_data.get("topics", []) if t],
                "related_courses": related,
            }
        )

    return merged_results
