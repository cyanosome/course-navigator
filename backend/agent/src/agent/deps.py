"""層B（ADK 関数ノード）へ DB ハンドルを渡す注入口（設計書 実験3-2 §4.6）。

ADK のノードは `ctx` しか受け取らないため、Neo4j ドライバと asyncpg プールを
モジュール変数で受け渡す。`.claude/rules/backend.md` の「接続の初期化は lifespan 内に
閉じ込め、モジュールトップレベルで DB 接続を行わない」を守るため、ここでは接続を
一切作らず、FastAPI の lifespan / pytest fixture から `set_backends` で注入する。
"""

from typing import Any

__all__ = ["db_pool", "neo4j_driver", "set_backends"]

_db_pool: Any | None = None
_neo4j_driver: Any | None = None


def set_backends(pool: Any | None, driver: Any | None) -> None:
    """FastAPI の lifespan / pytest fixture から呼ぶ。"""
    global _db_pool, _neo4j_driver
    _db_pool, _neo4j_driver = pool, driver


def db_pool() -> Any | None:
    return _db_pool


def neo4j_driver() -> Any | None:
    return _neo4j_driver
