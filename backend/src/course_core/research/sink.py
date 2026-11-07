"""サーバーのイベントを研究のログに書く口（型だけ。中身の JSONL の保存は研究のログの実装が埋める）。

AI の口（api/routers/assist.py）など、研究のログ以外の場所はこの型だけを使う:
- session_id_from_request でリクエストから調査のセッションの ID を取り出す。
- get_research_sink（FastAPI の依存）で口を受け取り、current_variant で今のブロックの変種を、
  append_server_event でサーバーのイベント（例 chat_response）を書く。
テストは app.dependency_overrides[get_research_sink] で偽の口を差し込む。
"""

from collections.abc import Mapping
from typing import Any, Final, Literal, Protocol

from fastapi import Request
from pydantic import BaseModel, ConfigDict

from course_core.research.variants import VariantFlags

__all__ = [
    "SESSION_COOKIE",
    "SESSION_HEADER",
    "ResearchSink",
    "ServerEventType",
    "SessionVariant",
    "get_research_sink",
    "session_id_from_request",
]

# api-contract.md 3.1: HttpOnly のクッキーと、クッキーが届かない環境のためのヘッダ。
SESSION_COOKIE: Final = "navi_sid"
SESSION_HEADER: Final = "X-Navi-Session"

# サーバーが書くイベント（ab-variants.md 7.2 の「側」がサーバーのもの）。
ServerEventType = Literal[
    "session_start",
    "consent_recorded",
    "block_start",
    "block_end",
    "chat_response",
    "study_arm_activated",
]


class SessionVariant(BaseModel):
    """調査のセッションの今のブロックと、その変種。ブロックの外なら block 以下が None。"""

    model_config = ConfigDict(frozen=True)

    session_id: str
    block: int | None
    condition_id: str | None
    variant_id: str | None
    flags: VariantFlags | None


class ResearchSink(Protocol):
    """研究のログの口。実装は研究のログの側（study・セッションの状態・JSONL の追記）。"""

    async def current_variant(self, session_id: str) -> SessionVariant | None:
        """セッションの今のブロックの変種。セッションが無ければ None。"""
        ...

    async def append_server_event(
        self,
        session_id: str,
        event_type: ServerEventType,
        payload: Mapping[str, Any],
    ) -> None:
        """サーバーのイベント1件に封筒（ab-variants.md 7.1）を付けて JSONL に追記する。"""
        ...


class _NotImplementedSink:
    """研究のログの実装が入るまでの口。呼ばれたら止める（記録したふりをしない）。"""

    async def current_variant(self, session_id: str) -> SessionVariant | None:
        raise NotImplementedError("研究のログ（セッションの状態）はまだ実装されていません。")

    async def append_server_event(
        self,
        session_id: str,
        event_type: ServerEventType,
        payload: Mapping[str, Any],
    ) -> None:
        raise NotImplementedError("研究のログ（JSONL の追記）はまだ実装されていません。")


_NOT_IMPLEMENTED_SINK: Final = _NotImplementedSink()


def get_research_sink() -> ResearchSink:
    """FastAPI の依存。研究のログの実装が、本物の口を返すように中身を埋める。"""
    return _NOT_IMPLEMENTED_SINK


def session_id_from_request(request: Request) -> str | None:
    """クッキー（先）かヘッダから調査のセッションの ID を取り出す。無ければ None。"""
    value = request.cookies.get(SESSION_COOKIE) or request.headers.get(SESSION_HEADER)
    if value is None:
        return None
    value = value.strip()
    return value or None
