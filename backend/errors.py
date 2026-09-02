"""共通の例外ハンドラ。

DB 固有の例外を HTTP ステータスにマッピングする。
- asyncpg.UniqueViolationError -> 409 Conflict
- neo4j ServiceUnavailable      -> 503 Service Unavailable
- その他の Neo4j / ドライバ例外  -> 502 Bad Gateway
"""

import logging

from asyncpg import UniqueViolationError
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from neo4j.exceptions import DriverError, Neo4jError, ServiceUnavailable

logger = logging.getLogger(__name__)

# ハンドラで処理した例外は Starlette がログしないため、ここでサーバ側にだけ
# トレースバックを残す（クライアントへ返す内容には原因を含めない）。
# ログにはメソッドとパスのみを出し、クエリ文字列やボディは出力しない。


async def unique_violation_handler(request: Request, exc: UniqueViolationError) -> JSONResponse:
    logger.exception(
        "一意制約違反により 409 を返します: %s %s",
        request.method, request.url.path, exc_info=exc,
    )
    return JSONResponse(
        status_code=409,
        content={"detail": "一意制約違反により作成できません（既に存在します）。"},
    )


async def neo4j_unavailable_handler(request: Request, exc: ServiceUnavailable) -> JSONResponse:
    logger.exception(
        "Neo4j に接続できないため 503 を返します: %s %s",
        request.method, request.url.path, exc_info=exc,
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "Neo4j サービスに接続できません。時間をおいて再試行してください。"},
    )


async def neo4j_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Neo4j 処理に失敗したため 502 を返します: %s %s",
        request.method, request.url.path, exc_info=exc,
    )
    return JSONResponse(
        status_code=502,
        content={"detail": "グラフDB（Neo4j）への書き込みに失敗しました。"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """例外ハンドラを FastAPI アプリに登録する。

    より具体的な型（ServiceUnavailable）が基底型より優先される。
    """
    app.add_exception_handler(UniqueViolationError, unique_violation_handler)
    app.add_exception_handler(ServiceUnavailable, neo4j_unavailable_handler)
    app.add_exception_handler(Neo4jError, neo4j_error_handler)
    app.add_exception_handler(DriverError, neo4j_error_handler)
