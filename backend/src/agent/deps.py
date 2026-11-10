"""層B（ADK 関数ノード）へ DB ハンドルを渡す注入口（設計書 実験3-2 §4.6）。

ADK のノードは `ctx` しか受け取らないため、Neo4j ドライバと asyncpg プールを
モジュール変数で受け渡す。`.claude/rules/backend.md` の「接続の初期化は lifespan 内に
閉じ込め、モジュールトップレベルで DB 接続を行わない」を守るため、ここでは接続を
一切作らず、FastAPI の lifespan / pytest fixture から `set_backends` で注入する。
"""

from typing import Any

__all__ = ["db_pool", "mcp_toolset", "neo4j_driver", "set_backends", "set_mcp_toolset"]

_db_pool: Any | None = None
_neo4j_driver: Any | None = None
# A1 で使い回す Neo4j の McpToolset（lifespan で1回だけ作る。無ければ A1 は1問ごとに作って閉じる）。
_mcp_toolset: Any | None = None


def set_backends(pool: Any | None, driver: Any | None) -> None:
    """FastAPI の lifespan / pytest fixture から呼ぶ。"""
    global _db_pool, _neo4j_driver
    _db_pool, _neo4j_driver = pool, driver


def set_mcp_toolset(toolset: Any | None) -> None:
    """FastAPI の lifespan から呼ぶ（閉じるのも lifespan）。"""
    global _mcp_toolset
    _mcp_toolset = toolset


def db_pool() -> Any | None:
    return _db_pool


def neo4j_driver() -> Any | None:
    return _neo4j_driver


def mcp_toolset() -> Any | None:
    return _mcp_toolset
