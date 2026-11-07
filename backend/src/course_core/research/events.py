"""イベントの種類（ab-variants.md 7.2）と、payload の軽い検査・旗の指紋。

検査で外れたイベントも捨てずに、封筒の warnings に印を付けて残す（ab-variants.md 7.1）。
受け付けないのは種類が一覧に無いときだけ（R6 が 422 を返す）。
印は3つ: payload_missing:<項目>（要る項目が無いか型が違う）、payload_invalid:<項目>（任意の項目の形が違う）、
payload_unknown:<項目>（決まった値の一覧に無い値）。
診断と微修正・履修状況のイベント（11/7）の要る項目は、事前登録 Study 1
（docs/experiments/2026-11-07_prereg_study1_diag-ab.md）の 4章・6.2 の指標に要るものにした。
"""

import json
from collections.abc import Mapping
from typing import Any, Final, Literal, get_args

from course_core.research.sink import ServerEventType

__all__ = [
    "CLIENT_EVENT_TYPES",
    "ClientEventType",
    "LIST_SOURCES",
    "PLAN_EDIT_FROM",
    "SERVER_EVENT_TYPES",
    "SESSION_END",
    "SHORTLIST_FROM",
    "flags_digest",
    "payload_warnings",
]

# クライアントが送る種類。frontend/src/navi/apiTypes.ts の CLIENT_EVENT_TYPES と同じ並びに、
# frontend がまだ送らない plan_refine_decide（事前登録 Study 1 の 6.2 の5）を足したもの。
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
    # 診断（diagnose=quiz）と、プランの微修正
    "diag_start",
    "diag_answer",
    "diag_submit",
    "diag_retake",
    "plan_shown",
    "plan_course_add",
    "plan_course_remove",
    "plan_refine_send",
    "plan_refine_decide",  # 「この案にする」「やめる」で1件（採った行・採らなかった行）
    # 履修状況のチェック
    "checkpoint_add",
    "checkpoint_remove",
    "status_open",
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
    "diag_start": ("config_version",),
    "diag_answer": ("config_version", "question_id"),
    "diag_submit": ("config_version",),
    "diag_retake": ("config_version",),
    "plan_shown": ("config_version", "answers_digest"),
    "plan_course_add": ("syllabus_id", "from"),
    "plan_course_remove": ("syllabus_id", "from"),
    "plan_refine_send": ("refine_local_id",),
    "plan_refine_decide": ("refine_local_id",),
}
# 文字列でない要る項目（項目 → 形）。plan は学期ごとの syllabus_id（frontend の planPayload の形）。
_Shape = Literal["object", "list", "plan"]
_REQUIRED_PAYLOAD_SHAPES: Final[Mapping[str, tuple[tuple[str, _Shape], ...]]] = {
    "diag_submit": (("answers", "object"),),
    "plan_shown": (("plan", "plan"),),
    "plan_refine_send": (("plan", "plan"),),
    "plan_refine_decide": (("accepted", "list"), ("rejected", "list")),
    "checkpoint_add": (("checkpoint", "object"),),
    "checkpoint_remove": (("checkpoint", "object"),),
}
# result_click の「どの一覧か」（frontend の research.ts の ListSource。plan は診断のプラン、refine は微修正の AI の回答）
LIST_SOURCES: Final = frozenset({"search", "recommend", "interest", "ask", "group", "similar", "plan", "refine"})
# shortlist_add・shortlist_remove の「どこから」（frontend の ShortlistFrom）
SHORTLIST_FROM: Final = LIST_SOURCES | {"detail", "timetable", "undo", "unknown"}
# plan_course_add・plan_course_remove の「どこから」（事前登録 Study 1 の 6.2 の4。refine のときは refine_local_id も要る）
PLAN_EDIT_FROM: Final = frozenset({"manual", "search", "check_fix", "refine"})
_REFINE: Final = "refine"
_PAYLOAD_VALUES: Final[Mapping[str, tuple[tuple[str, frozenset[str]], ...]]] = {
    "result_click": (("list", LIST_SOURCES),),
    "shortlist_add": (("from", SHORTLIST_FROM),),
    "shortlist_remove": (("from", SHORTLIST_FROM),),
    "plan_course_add": (("from", PLAN_EDIT_FROM),),
    "plan_course_remove": (("from", PLAN_EDIT_FROM),),
}
_PLAN_EDIT_EVENTS: Final = frozenset({"plan_course_add", "plan_course_remove"})
_TASK_SUBMIT: Final = "task_submit"
_PLAN_TERMS: Final = frozenset({"春", "秋"})

_FNV_OFFSET: Final = 0x811C9DC5
_FNV_PRIME: Final = 0x01000193
_UINT32_MASK: Final = 0xFFFFFFFF


def _is_plan(value: Any) -> bool:
    """学期ごとの syllabus_id の配列（[{"year": 1, "term": "春", "syllabus_ids": ["…"]}, …]）か。"""
    if not isinstance(value, list):
        return False
    return all(
        isinstance(term, dict)
        and isinstance(term.get("year"), int)
        and not isinstance(term.get("year"), bool)
        and term.get("term") in _PLAN_TERMS
        and isinstance(term.get("syllabus_ids"), list)
        and all(isinstance(syllabus_id, str) for syllabus_id in term["syllabus_ids"])
        for term in value
    )


def _has_shape(value: Any, shape: _Shape) -> bool:
    if shape == "object":
        return isinstance(value, dict)
    if shape == "list":
        return isinstance(value, list)
    return _is_plan(value)


def payload_warnings(
    event_type: str, task_id: str | None, payload: Mapping[str, Any], *, diagnose: bool = False
) -> list[str]:
    """イベントの欠けている項目と、決まった値の外の値を warnings の印にする（受け付けは止めない）。

    diagnose はそのブロックの旗が diagnose=quiz か。真なら task_submit に最終プラン（plan）を求める
    （事前登録 Study 1 の 6.2 の3。採点は task_submit のプランだけで行う）。
    """
    warnings: list[str] = []
    if event_type in _TASK_EVENTS and task_id is None:
        warnings.append("task_id_missing")
    for key in _REQUIRED_PAYLOAD_KEYS.get(event_type, ()):
        if not isinstance(payload.get(key), str):
            warnings.append(f"payload_missing:{key}")
    for key, shape in _REQUIRED_PAYLOAD_SHAPES.get(event_type, ()):
        if not _has_shape(payload.get(key), shape):
            warnings.append(f"payload_missing:{key}")
    for key, allowed in _PAYLOAD_VALUES.get(event_type, ()):
        value = payload.get(key)
        if isinstance(value, str) and value not in allowed:
            warnings.append(f"payload_unknown:{key}")
    if (
        event_type in _PLAN_EDIT_EVENTS
        and payload.get("from") == _REFINE
        and not isinstance(payload.get("refine_local_id"), str)
    ):
        warnings.append("payload_missing:refine_local_id")
    if event_type == _TASK_SUBMIT:
        if "plan" in payload and not _is_plan(payload["plan"]):
            warnings.append("payload_invalid:plan")
        elif diagnose and "plan" not in payload:
            warnings.append("payload_missing:plan")
        if "checkpoints" in payload and not isinstance(payload["checkpoints"], list):
            warnings.append("payload_invalid:checkpoints")
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
