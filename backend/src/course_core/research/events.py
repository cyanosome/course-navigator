"""イベントの種類（ab-variants.md 7.2）と、payload の軽い検査・旗の指紋。

検査で外れたイベントも捨てずに、封筒の warnings に印を付けて残す（ab-variants.md 7.1）。
受け付けないのは種類が一覧に無いときだけ（R6 が 422 を返す）。
"""

import json
from collections.abc import Mapping
from typing import Any, Final, Literal, get_args

from course_core.research.sink import ServerEventType

__all__ = [
    "CLIENT_EVENT_TYPES",
    "ClientEventType",
    "SERVER_EVENT_TYPES",
    "SESSION_END",
    "flags_digest",
    "payload_warnings",
]

# クライアントが送る種類。frontend/src/navi/apiTypes.ts の CLIENT_EVENT_TYPES と同じ並び。
ClientEventType = Literal[
    "session_end",
    "variant_applied",
    "task_start",
    "task_submit",
    "search_query",
    "result_click",
    "recommend_shown",
    "interest_select",
    "group_open",
    "sequence_click",
    "syllabus_open",
    "syllabus_close",
    "original_open",
    "shortlist_add",
    "shortlist_remove",
    "timetable_open",
    "chat_send",
    "ai_full_open",
    "citation_click",
    "questionnaire_submit",
    "page_hidden",
    "page_visible",
    "client_error",
]
CLIENT_EVENT_TYPES: Final = frozenset(get_args(ClientEventType))

SESSION_END: Final = "session_end"
# サーバーが書く種類。sink の ServerEventType に、R7 がクライアントの session_end を
# 受け取らずにセッションを閉じたときの session_end を足したもの。
SERVER_EVENT_TYPES: Final = frozenset(get_args(ServerEventType)) | {SESSION_END}

_TASK_EVENTS: Final = frozenset({"task_start", "task_submit"})
_SYLLABUS_EVENTS: Final = (
    "syllabus_open",
    "syllabus_close",
    "original_open",
    "shortlist_add",
    "shortlist_remove",
    "citation_click",
    "result_click",
)
# 指標の計算（ab-variants.md 7.3）に欠かせない payload の項目。値は文字列。
_REQUIRED_PAYLOAD_KEYS: Final[Mapping[str, tuple[str, ...]]] = {
    **{event_type: ("syllabus_id",) for event_type in _SYLLABUS_EVENTS},
    "search_query": ("q",),
    "interest_select": ("interest_id",),
    "group_open": ("group_id",),
    "questionnaire_submit": ("scale",),
    "variant_applied": ("flags_digest",),
}

_FNV_OFFSET: Final = 0x811C9DC5
_FNV_PRIME: Final = 0x01000193
_UINT32_MASK: Final = 0xFFFFFFFF


def payload_warnings(event_type: str, task_id: str | None, payload: Mapping[str, Any]) -> list[str]:
    """イベントの欠けている項目を warnings の印にする（受け付けは止めない）。"""
    warnings: list[str] = []
    if event_type in _TASK_EVENTS and task_id is None:
        warnings.append("task_id_missing")
    for key in _REQUIRED_PAYLOAD_KEYS.get(event_type, ()):
        if not isinstance(payload.get(key), str):
            warnings.append(f"payload_missing:{key}")
    return warnings


def flags_digest(flags: Mapping[str, str | None]) -> str:
    """旗の指紋。frontend/src/navi/variant.ts の flagsDigest と同じ計算（キー順・空白なしの JSON に FNV-1a 32 ビット）。

    画面とサーバーの旗が同じかを確かめるためのもので、安全のためのハッシュではない。
    """
    data = json.dumps(dict(flags), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    value = _FNV_OFFSET
    for byte in data.encode("utf-8"):
        value ^= byte
        value = (value * _FNV_PRIME) & _UINT32_MASK
    return f"fnv1a32:{value:08x}"
