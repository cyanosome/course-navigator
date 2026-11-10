"""Cypher search tools for Google ADK / MCP Agent.

Provides callable functions for LLM agents to autonomously explore the Neo4j knowledge graph:
- search_courses_hybrid: Dynamic semantic search + prerequisites
- get_course_prerequisites: Detailed prerequisite chain
- get_similar_courses: Related courses based on precomputed embeddings
"""

from typing import Any, List, Optional
from pydantic import BaseModel, Field

from agent import deps
from course_core.repositories import cypher_search_repo
from services import embedding

__all__ = [
    "search_courses_hybrid",
    "get_course_prerequisites",
    "get_similar_courses",
]


async def search_courses_hybrid(query: str, top_k: int = 5) -> dict[str, Any]:
    """自然言語クエリから意味的に合致する科目と、その履修に必要な前提条件をまとめて取得する。

    シード科目の類似度スコア順にソートされ、各科目が要求する前提科目チェーン（最大3ホップ）
    および卒業要件区分が同時に返されます。履修アドバイスを行う最初の探索ステップに適しています。

    Args:
        query: ユーザーの学習関心や学びたいテーマ（例: 「機械学習とデータ分析」「コンピュータグラフィックス」）。
        top_k: 取得する最大科目数（デフォルト5）。

    Returns:
        results: 適合科目のリスト（code, title, credits, term, requirement_category, score, prerequisites）。
        error: 接続や実行エラー時のメッセージ。
    """
    driver = deps.neo4j_driver()
    if driver is None:
        return {"results": [], "error": "Neo4j ドライバが初期化されていません。"}

    try:
        query_embedding = await embedding.get_embedding(query)
        async with driver.session() as session:
            items = await cypher_search_repo.search_hybrid(
                session=session,
                query_embedding=query_embedding,
                top_k=min(max(1, top_k), 20),
                max_depth=3,
            )
        return {"results": [item.model_dump() for item in items]}
    except Exception as e:
        return {"results": [], "error": f"検索処理中にエラーが発生しました: {e}"}


async def get_course_prerequisites(course_code: str) -> dict[str, Any]:
    """指定された科目コードの履修に必要な前提科目（最大3階層の依存チェーン）を取得する。

    特定の科目を受講するために事前に履修しておくべき講義を調べる際に使用します。

    Args:
        course_code: 科目コード（例: "062620"）。

    Returns:
        course_code: 問い合わせた科目コード。
        prerequisites: 前提科目のリスト（code, title, credits, term, depth）。
        error: 接続や実行エラー時のメッセージ。
    """
    driver = deps.neo4j_driver()
    if driver is None:
        return {"course_code": course_code, "prerequisites": [], "error": "Neo4j ドライバが初期化されていません。"}

    try:
        async with driver.session() as session:
            items = await cypher_search_repo.search_pure_graph(
                session=session,
                identifier=course_code,
                top_k=1,
                max_depth=3,
            )
        if not items:
            return {"course_code": course_code, "prerequisites": [], "error": "該当科目が存在しません。"}

        prereqs = [p.model_dump() for p in items[0].prerequisites]
        return {
            "course_code": items[0].code,
            "title": items[0].title,
            "prerequisites": prereqs,
        }
    except Exception as e:
        return {"course_code": course_code, "prerequisites": [], "error": f"前提科目取得中にエラーが発生しました: {e}"}


async def get_similar_courses(course_code: str, min_score: float = 0.5) -> dict[str, Any]:
    """事前計算された類似度エッジ（SIMILAR_TO）を辿り、関連する上位科目を探索する。

    ある科目に興味を持った学生に対して、同じ分野やテーマの別科目を提案する際に使用します。

    Args:
        course_code: 起点となる科目コード（例: "102878"）。
        min_score: 類似度スコアの最小閾値（0.0〜1.0、デフォルト0.5）。

    Returns:
        course_code: 起点科目コード。
        similar_courses: 類似科目のリスト（code, title, score, prerequisites）。
        error: 接続や実行エラー時のメッセージ。
    """
    driver = deps.neo4j_driver()
    if driver is None:
        return {"course_code": course_code, "similar_courses": [], "error": "Neo4j ドライバが初期化されていません。"}

    try:
        async with driver.session() as session:
            items = await cypher_search_repo.search_by_similarity_edge(
                session=session,
                identifier=course_code,
                top_k=5,
                min_score=min_score,
                max_depth=2,
            )
        return {
            "course_code": course_code,
            "similar_courses": [item.model_dump() for item in items],
        }
    except Exception as e:
        return {"course_code": course_code, "similar_courses": [], "error": f"類似科目取得中にエラーが発生しました: {e}"}
