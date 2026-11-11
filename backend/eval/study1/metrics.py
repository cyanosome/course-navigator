"""Study 1 の指標（事前登録 4章）を、参加者 × 条件（ブロック 1・2）で出す。判定と表は report.py。

入力: 研究者用 CLI の export の JSONL、科目のスナップショット（catalog_snapshot.py）、tasks.json。
出力: JSON（リポの外。--out）。人ごとに、事前の質問・二択・所要時間（F4）・seq の欠け（E3）と、ブロックごとの指標。
自由記述（Q11-Q12 の free、二択の reason、振り返り）は書かない（答えたかどうかだけ）。

ブロックごとの指標（課題 b の値。課題の ID は tasks.json の task_ids、ブロックの課題セットは block_start の task_set_id）:
- 4.1: 最終プラン（課題 b の最後の task_submit の plan）の採点 y・a と K1〜K6、初期プラン（課題 a の最初の plan_shown、
  無ければ課題 a の task_submit の plan）の a0、伸び a − a0
- 4.2: t_b = ts_client(task_submit) − ts_client(task_start) − 画面が隠れていた時間（page_hidden から page_visible。
  課題の区間と重なる分）。task_start が2件以上あるときは、使う task_submit より前の最後の task_start を使う（注に残す）。
  W = 課題 b の依頼（plan_refine_send・chat_send）ごとの [ts_client, ts_client + latency_ms] の和集合のうち課題の区間に
  入る長さ（chat_response の無い依頼は区間を作れないので数え、W に入れない）。t_b' = t_b − W。
  課題 a の時間 = 課題 a の最初の diag_start から最初の plan_shown まで
- 4.3: B1 status_open の数、B2 from が status の syllabus_open の数、B3 checkpoint_add の数、B4 original_open の数、
  B = B1 + B2。B5（V31 だけ）= 案を採った（plan_refine_decide の action が apply で accepted が空でない）あと、
  次の依頼か task_submit までに B1 か B2 があった割合
- 4.4: D = plan_course_add と plan_course_remove の数。同じ学期で同じ名前の科目を外して足した組は「移す」1回と数える
  （先に payload の moved_from・moved_to の組、次に科目名で組む。同じ syllabus_id を外して戻した組も名前が同じなので
  移すに数え、別に readded に数える）。出どころ（from: manual・search・check_fix・refine）ごとにも数える（組は足した側の
  出どころ）。効率 = tasks.json の最小の変更の数 ÷ D
- 4.4 の V31 だけ: 依頼の数、AI を使ったか、案の行（plan_refine_decide の shown・accepted）の受け入れ率と、案ごとの
  全部・一部・採らなかった・判断の記録なしの数、誤りへの依存（案の行を1つずつ、依頼のときのプランに当てて、満たしていた
  条件を満たさなくする行のうち採られた割合。入れる行の学期は、採ったなら plan_course_add の学期、採らなかったなら
  画面の既定の置き場所 coursePlace）、案と回答に出た syllabus_id のうちスナップショットに無いものの数
- 5.6 の AI の失敗（ブロックの課題 a・b の全部の依頼）: chat_response の error がある、plan_delivery が not_delivered か
  static_fallback（プランが AI に届かなかった）、chat_response が無い。空の応答（案も出典も無い）は別に数える。
  課題 b で失敗が2回続いたら system_failure（E5）
- 4.5: SUS = 2.5 ×（奇数の項目の「答え − 1」の和 ＋ 偶数の項目の「5 − 答え」の和）。Q11・Q12 はそのまま
- 5.5・5.7 に使う印: 5.2 の前提の外れ（E4）、課題 a の diag_submit の答えが参照の答えと違うか、課題 b の diag_retake の数

使い方:

    python -m eval.study1.metrics --events study1-events.jsonl --catalog study1-catalog.json --out study1-metrics.json
"""

import argparse
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from eval.study1.catalog_snapshot import CatalogError, CourseCatalog, load_course_catalog
from eval.study1.eventlog import AI_REQUEST_TYPES, Event, Session, premise_failures, read_events, sessions_of
from eval.study1.files import OutputError, write_private_json
from eval.study1.integrity import E3_SEQ_GAP_LIMIT
from eval.study1.score import (
    Plan,
    PlanError,
    Score,
    TaskSet,
    Tasks,
    TasksError,
    Term,
    add_course,
    default_place,
    load_tasks,
    move_course,
    parse_plan,
    remove_course,
    score_plan,
)

__all__ = ["METRICS_FORMAT", "block_metrics", "build_metrics", "participant_metrics", "sus_score"]

METRICS_FORMAT: Final = "study1-metrics-v1"
BLOCKS: Final = (1, 2)
LAST_BLOCK: Final = 2
AI_VARIANT: Final = "V31"
SUS_ITEMS: Final = 10
LIKERT_MIN: Final = 1
LIKERT_MAX: Final = 5
SUS_FACTOR: Final = 2.5
MS_PER_SECOND: Final = 1000.0
SECONDS_PER_MINUTE: Final = 60.0
SCALE_SUS: Final = "SUS"
SCALE_Q11_Q12: Final = "Q11-Q12"
SCALE_PREFERENCE: Final = "二択"
SCALE_REFLECTION: Final = "振り返り"
SCALE_PRE: Final = "事前の質問"
FAILED_DELIVERY: Final = frozenset({"not_delivered", "static_fallback"})
SYSTEM_FAILURE_RUN: Final = 2  # 5.6: 課題 b で2回続けて失敗
_STATUS_FROM: Final = "status"
_REFINE: Final = "refine"
_EDIT_TYPES: Final = ("plan_course_add", "plan_course_remove")


def _ms(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() * MS_PER_SECOND


def _overlap(intervals: Iterable[tuple[float, float]], lo: float, hi: float) -> float:
    """区間の和集合のうち [lo, hi] に入る長さ（秒の時刻で）。"""
    clipped = sorted((max(a, lo), min(b, hi)) for a, b in intervals if min(b, hi) > max(a, lo))
    total = 0.0
    current: tuple[float, float] | None = None
    for a, b in clipped:
        if current is None or a > current[1]:
            if current is not None:
                total += current[1] - current[0]
            current = (a, b)
        else:
            current = (current[0], max(current[1], b))
    if current is not None:
        total += current[1] - current[0]
    return total


def _hidden_intervals(session: Session) -> list[tuple[float, float]]:
    """画面が隠れていた区間（page_hidden → 次の page_visible。閉じていなければ無限まで）。"""
    intervals: list[tuple[float, float]] = []
    hidden_at: float | None = None
    for event in session.client:
        if event.ts_client is None:
            continue
        if event.event_type == "page_hidden" and hidden_at is None:
            hidden_at = event.ts_client.timestamp()
        elif event.event_type == "page_visible":
            if hidden_at is not None:
                intervals.append((hidden_at, event.ts_client.timestamp()))
            hidden_at = None
    if hidden_at is not None:
        intervals.append((hidden_at, float("inf")))
    return intervals


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def sus_score(values: Mapping[str, Any]) -> float | None:
    """SUS（4.5）。10項目のどれかが 1〜5 で読めなければ None。"""
    answers = [_number(values.get(f"sus{i}")) for i in range(1, SUS_ITEMS + 1)]
    if any(a is None or not LIKERT_MIN <= a <= LIKERT_MAX for a in answers):
        return None
    odd = sum(a - LIKERT_MIN for i, a in enumerate(answers, 1) if i % 2 == 1 and a is not None)
    even = sum(LIKERT_MAX - a for i, a in enumerate(answers, 1) if i % 2 == 0 and a is not None)
    return SUS_FACTOR * (odd + even)


def _likert(values: Mapping[str, Any], key: str) -> float | None:
    value = _number(values.get(key))
    return value if value is not None and LIKERT_MIN <= value <= LIKERT_MAX else None


def _questionnaire(session: Session, scale: str, block: int | None) -> tuple[Mapping[str, Any] | None, int]:
    """その尺度の最後の答えと件数。"""
    items = [
        e
        for e in session.of_type("questionnaire_submit")
        if e.payload.get("scale") == scale and e.payload.get("block") == block
    ]
    if not items:
        return None, 0
    values = items[-1].payload.get("values")
    return (values if isinstance(values, dict) else {}), len(items)


# --- 変更の数 D（4.4） --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Edit:
    event: Event
    kind: str  # add・remove
    syllabus_id: str
    term: Term | None
    source: str

    @property
    def moved(self) -> tuple[str, str] | None:
        moved_from, moved_to = self.event.payload.get("moved_from"), self.event.payload.get("moved_to")
        if isinstance(moved_from, str) and isinstance(moved_to, str):
            return moved_from, moved_to
        return None


def _edits(events: Sequence[Event]) -> list[_Edit]:
    out: list[_Edit] = []
    for event in events:
        if event.event_type not in _EDIT_TYPES:
            continue
        year, half = event.payload.get("year"), event.payload.get("term")
        term = Term(year, half) if isinstance(year, int) and half in ("春", "秋") else None
        out.append(
            _Edit(
                event=event,
                kind="add" if event.event_type == "plan_course_add" else "remove",
                syllabus_id=str(event.payload.get("syllabus_id")),
                term=term,
                source=str(event.payload.get("from")),
            )
        )
    return out


def change_count(events: Sequence[Event], catalog: CourseCatalog) -> dict[str, Any]:
    """D と、移すの数、出どころごとの数。"""
    edits = _edits(events)
    paired: set[int] = set()
    pairs: list[tuple[_Edit, _Edit]] = []

    def pair(remove: _Edit, add: _Edit) -> None:
        paired.update({id(remove), id(add)})
        pairs.append((remove, add))

    for remove in edits:
        if remove.kind != "remove" or id(remove) in paired or remove.moved is None:
            continue
        add = next((a for a in edits if a.kind == "add" and id(a) not in paired and a.moved == remove.moved), None)
        if add is not None:
            pair(remove, add)

    def name(edit: _Edit) -> str | None:
        info = catalog.get(edit.syllabus_id)
        return info.name if info is not None else None

    for remove in edits:
        if remove.kind != "remove" or id(remove) in paired or name(remove) is None:
            continue
        add = next(
            (
                a
                for a in edits
                if a.kind == "add" and id(a) not in paired and a.term == remove.term and name(a) == name(remove)
            ),
            None,
        )
        if add is not None:
            pair(remove, add)
    by_source: Counter[str] = Counter()
    for _, add in pairs:
        by_source[add.source] += 1
    for edit in edits:
        if id(edit) not in paired:
            by_source[edit.source] += 1
    unknown_names = sum(1 for e in edits if catalog.get(e.syllabus_id) is None)
    return {
        "D": len(edits) - len(pairs),
        "adds": sum(e.kind == "add" for e in edits),
        "removes": sum(e.kind == "remove" for e in edits),
        "moves": len(pairs),
        "readded": sum(r.syllabus_id == a.syllabus_id for r, a in pairs),
        "by_source": dict(sorted(by_source.items())),
        "unknown_courses": unknown_names,
    }


# --- AI の依頼（4.4・5.6） ----------------------------------------------------------------------


def _outcome(response: Event | None) -> str:
    """ok・empty（空の応答。失敗に数えない）・失敗の種類。"""
    if response is None:
        return "no_response"
    payload = response.payload
    error = payload.get("error")
    if isinstance(error, str) and error:
        return f"error:{error}"
    if payload.get("plan_delivery") in FAILED_DELIVERY:
        return f"delivery:{payload.get('plan_delivery')}"
    suggestions = payload.get("plan_suggestions")
    has_lines = isinstance(suggestions, dict) and bool(suggestions.get("add") or suggestions.get("remove"))
    has_sources = bool(payload.get("source_codes"))
    return "ok" if has_lines or has_sources else "empty"


def _is_failure(outcome: str) -> bool:
    return outcome not in ("ok", "empty")


def ai_requests(session: Session, events: Sequence[Event]) -> list[dict[str, Any]]:
    """依頼ごとの {event, kind, outcome, latency_ms, response}（seq の順）。"""
    responses = session.responses
    out: list[dict[str, Any]] = []
    for event in events:
        if event.event_type not in AI_REQUEST_TYPES:
            continue
        response = responses.get(event.event_id)
        latency = _number(response.payload.get("latency_ms")) if response is not None else None
        out.append(
            {
                "event": event,
                "kind": event.event_type,
                "outcome": _outcome(response),
                "latency_ms": latency,
                "response": response,
            }
        )
    return out


def _wait_ms(requests: Sequence[Mapping[str, Any]], lo: float, hi: float) -> tuple[float, int]:
    intervals = []
    missing = 0
    for request in requests:
        event: Event = request["event"]
        latency = request["latency_ms"]
        if event.ts_client is None or latency is None:
            missing += 1
            continue
        start = event.ts_client.timestamp()
        intervals.append((start, start + latency / MS_PER_SECOND))
    return _overlap(intervals, lo, hi) * MS_PER_SECOND, missing


def _system_failure(requests: Sequence[Mapping[str, Any]]) -> bool:
    run = 0
    for request in requests:
        run = run + 1 if _is_failure(request["outcome"]) else 0
        if run >= SYSTEM_FAILURE_RUN:
            return True
    return False


def _line_change(line: Mapping[str, Any]) -> tuple[str, str | None, str | None]:
    """案の行 → (種類, 入れる科目, 外す科目)。"""
    kind = str(line.get("kind"))
    if kind == "move":
        return kind, _str(line.get("moved_to")), _str(line.get("moved_from"))
    if kind == "remove":
        return kind, None, _str(line.get("syllabus_id"))
    return kind, _str(line.get("syllabus_id")), None


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _apply_line(
    plan: Plan, line: Mapping[str, Any], placed_at: Mapping[str, Term], catalog: CourseCatalog
) -> Plan | None:
    kind, add, remove = _line_change(line)
    if kind == "move" and add is not None and remove is not None:
        return move_course(plan, remove, add)
    if kind == "remove" and remove is not None:
        return remove_course(plan, remove)
    if add is None:
        return None
    term = placed_at.get(add)
    if term is None:
        info = catalog.get(add)
        term = default_place(info) if info is not None else None
    return None if term is None else add_course(plan, add, term)


def _breaks(before: Score, after: Score) -> bool:
    return any(b.status == "met" and a.status != "met" for b, a in zip(before.results, after.results, strict=True))


def ai_metrics(
    session: Session,
    events: Sequence[Event],
    requests: Sequence[Mapping[str, Any]],
    task_set: TaskSet,
    catalog: CourseCatalog,
) -> dict[str, Any]:
    """V31 の課題 b の AI の利用（4.4）。"""
    decides = [e for e in events if e.event_type == "plan_refine_decide"]
    sends = [e for e in events if e.event_type == "plan_refine_send"]
    placed_at: dict[str, Term] = {}
    for edit in _edits(events):
        if edit.kind == "add" and edit.source == _REFINE and edit.term is not None:
            placed_at.setdefault(edit.syllabus_id, edit.term)
    shown_total = accepted_total = 0
    categories: Counter[str] = Counter()
    breaking_shown = breaking_accepted = unevaluable = 0
    decided_ids: set[str] = set()
    for decide in decides:
        payload = decide.payload
        shown = [x for x in payload.get("shown", []) if isinstance(x, dict)]
        accepted = [x for x in payload.get("accepted", []) if isinstance(x, dict)]
        decided_ids.add(str(payload.get("refine_local_id")))
        shown_total += len(shown)
        accepted_total += len(accepted)
        if shown:
            categories["all" if len(accepted) == len(shown) else "partial" if accepted else "none"] += 1
        send = next(
            (
                s
                for s in reversed(sends)
                if s.payload.get("refine_local_id") == payload.get("refine_local_id")
                and (s.seq or 0) < (decide.seq or 0)
            ),
            None,
        )
        try:
            before_plan = parse_plan(send.payload.get("plan")) if send is not None else None
        except PlanError:
            before_plan = None
        if before_plan is None:
            unevaluable += len(shown)
            continue
        before = score_plan(before_plan, task_set, catalog)
        accepted_keys = {_line_change(x) for x in accepted}
        for line in shown:
            after_plan = _apply_line(before_plan, line, placed_at, catalog)
            if after_plan is None:
                unevaluable += 1
                continue
            if _breaks(before, score_plan(after_plan, task_set, catalog)):
                breaking_shown += 1
                breaking_accepted += _line_change(line) in accepted_keys
    proposals = {str(s.payload.get("refine_local_id")) for s in sends}
    with_lines = set()
    for request in requests:
        response = request["response"]
        event: Event = request["event"]
        suggestions = response.payload.get("plan_suggestions") if response is not None else None
        if (
            event.event_type == "plan_refine_send"
            and isinstance(suggestions, dict)
            and (suggestions.get("add") or suggestions.get("remove"))
        ):
            with_lines.add(str(event.payload.get("refine_local_id")))
    categories["no_decision"] = len(with_lines - decided_ids)
    ids: set[str] = set()
    unverified = 0
    for request in requests:
        response = request["response"]
        if response is None:
            continue
        payload = response.payload
        suggestions = payload.get("plan_suggestions") if isinstance(payload.get("plan_suggestions"), dict) else {}
        for key in ("add", "remove"):
            ids.update(str(x) for x in suggestions.get(key, []) or [])
        for key in ("cited_codes", "source_codes"):
            ids.update(str(x) for x in payload.get(key, []) or [])
        unverified += len(payload.get("unverified_codes", []) or [])
    return {
        "requests": len(requests),
        "refine_requests": sum(r["kind"] == "plan_refine_send" for r in requests),
        "chat_requests": sum(r["kind"] == "chat_send" for r in requests),
        "used": bool(requests),
        "proposals": len(proposals),
        "lines_shown": shown_total,
        "lines_accepted": accepted_total,
        "acceptance_rate": accepted_total / shown_total if shown_total else None,
        "decisions": dict(categories),
        "breaking_lines_shown": breaking_shown,
        "breaking_lines_accepted": breaking_accepted,
        "error_reliance": breaking_accepted / breaking_shown if breaking_shown else None,
        "lines_unevaluable": unevaluable,
        "ids_not_in_catalog": len([sid for sid in ids if catalog.get(sid) is None]),
        "ids_seen": len(ids),
        "unverified_codes": unverified,
    }


# --- ブロック ------------------------------------------------------------------------------------


def _score_or_none(value: Any, task_set: TaskSet, catalog: CourseCatalog, notes: list[str], what: str) -> Score | None:
    try:
        return score_plan(parse_plan(value), task_set, catalog)
    except PlanError as exc:
        notes.append(f"{what}を採点できない（{exc}）")
        return None


def _answers_deviate(events: Sequence[Event], task_set: TaskSet) -> bool | None:
    """課題 a の最後の diag_submit の答えが参照の答えと違うか（質問ごとに選んだ選択肢の集合で比べる）。"""
    submits = [e for e in events if e.event_type == "diag_submit"]
    if not submits:
        return None
    answers = submits[-1].payload.get("answers")
    if not isinstance(answers, dict):
        return None
    for question, expected in task_set.reference_answers.items():
        given = answers.get(question)
        if not isinstance(given, list) or set(map(str, given)) != set(expected):
            return True
    return False


def block_metrics(
    session: Session,
    block: int,
    tasks: Tasks,
    catalog: CourseCatalog,
    premises: Mapping[tuple[str, int], Sequence[str]],
) -> dict[str, Any]:
    info = session.blocks[block]
    task_set = tasks.task_sets.get(info.task_set_id or "")
    out: dict[str, Any] = {
        "block": block,
        "condition_id": info.condition_id,
        "variant_id": info.variant_id,
        "task_set": info.task_set_id,
        "ended": info.ended,
        "notes": [],
        "premise_failures": list(premises.get((session.session_id, block), [])),
    }
    notes: list[str] = out["notes"]
    if task_set is None or len(task_set.task_ids) != 2:
        notes.append(f"課題セット {info.task_set_id} が tasks.json に無い")
        return out
    a_id, b_id = task_set.task_ids
    a_events, b_events = session.task(a_id), session.task(b_id)

    # 4.1 成否と達成度
    submits = [e for e in b_events if e.event_type == "task_submit"]
    final = submits[-1] if submits else None
    if len(submits) > 1:
        notes.append(f"課題 b の task_submit が {len(submits)} 件（最後のものを使った）")
    score = _score_or_none(final.payload.get("plan"), task_set, catalog, notes, "最終プラン") if final else None
    shown = next((e for e in a_events if e.event_type == "plan_shown"), None)
    a_submit = next((e for e in a_events if e.event_type == "task_submit"), None)
    initial_source = shown or a_submit
    score0 = (
        _score_or_none(initial_source.payload.get("plan"), task_set, catalog, notes, "初期プラン")
        if initial_source
        else None
    )
    out.update(
        {
            "submitted_b": final is not None,
            "y": score.y if score else None,
            "a": score.a if score else None,
            "a0": score0.a if score0 else None,
            "gain": score.a - score0.a if score and score0 else None,
            "conditions": {r.id: r.status for r in score.results} if score else None,
            "conditions_initial": {r.id: r.status for r in score0.results} if score0 else None,
            "unknown_courses": len(score.unknown_courses) if score else None,
        }
    )

    # 4.2 時間
    starts = [e for e in b_events if e.event_type == "task_start"]
    start = None
    if final is not None:
        before = [e for e in starts if (e.seq or 0) < (final.seq or 0)]
        start = before[-1] if before else None
    if len(starts) > 1:
        notes.append(f"課題 b の task_start が {len(starts)} 件（最終の task_submit の前の最後のものを使った）")
    requests_b = ai_requests(session, b_events)
    if start is not None and final is not None and start.ts_client is not None and final.ts_client is not None:
        lo, hi = start.ts_client.timestamp(), final.ts_client.timestamp()
        hidden = _overlap(_hidden_intervals(session), lo, hi) * MS_PER_SECOND
        wait, missing = _wait_ms(requests_b, lo, hi)
        t_b = _ms(start.ts_client, final.ts_client) - hidden
        out.update(
            {
                "t_b_ms": t_b,
                "hidden_ms": hidden,
                "W_ms": wait,
                "t_b_prime_ms": t_b - wait,
                "wait_unknown_requests": missing,
            }
        )
    else:
        out.update(
            {"t_b_ms": None, "hidden_ms": None, "W_ms": None, "t_b_prime_ms": None, "wait_unknown_requests": None}
        )
    diag_start = next((e for e in a_events if e.event_type == "diag_start"), None)
    out["t_a_ms"] = (
        _ms(diag_start.ts_client, shown.ts_client)
        if diag_start and shown and diag_start.ts_client and shown.ts_client
        else None
    )

    # 4.3 確かめる行動
    b1 = sum(e.event_type == "status_open" for e in b_events)
    b2 = sum(e.event_type == "syllabus_open" and e.payload.get("from") == _STATUS_FROM for e in b_events)
    out.update(
        {
            "B1": b1,
            "B2": b2,
            "B3": sum(e.event_type == "checkpoint_add" for e in b_events),
            "B4": sum(e.event_type == "original_open" for e in b_events),
            "B": b1 + b2,
            "B5": _b5(b_events) if info.variant_id == AI_VARIANT else None,
        }
    )

    # 4.4 変更の数
    changes = change_count(b_events, catalog)
    minimum = task_set.registered.get("min_changes")
    out["changes"] = changes
    out["efficiency"] = minimum / changes["D"] if isinstance(minimum, (int, float)) and changes["D"] else None

    # 5.6 AI の失敗（課題 a・b の全部の依頼）と、V31 の AI の利用
    requests_block = ai_requests(session, [e for e in session.client if e.task_id in (a_id, b_id)])
    outcomes = Counter(r["outcome"] for r in requests_block)
    out["ai_failures"] = {
        "requests": len(requests_block),
        "failures": sum(count for outcome, count in outcomes.items() if _is_failure(outcome)),
        "empty": outcomes.get("empty", 0),
        "by_outcome": dict(sorted(outcomes.items())),
        "retries": sum(r["event"].payload.get("retry") is True for r in requests_block),
    }
    out["system_failure"] = _system_failure(requests_b)
    out["ai"] = ai_metrics(session, b_events, requests_b, task_set, catalog) if info.variant_id == AI_VARIANT else None

    # 4.5 質問票
    sus_values, sus_count = _questionnaire(session, SCALE_SUS, block)
    fit_values, fit_count = _questionnaire(session, SCALE_Q11_Q12, block)
    out.update(
        {
            "SUS": sus_score(sus_values) if sus_values is not None else None,
            "Q11": _likert(fit_values, "q11") if fit_values is not None else None,
            "Q12": _likert(fit_values, "q12") if fit_values is not None else None,
            "questionnaire_counts": {SCALE_SUS: sus_count, SCALE_Q11_Q12: fit_count},
        }
    )

    # 5.5・5.7 の印
    out["answers_deviate"] = _answers_deviate(a_events, task_set)
    out["retakes_in_b"] = sum(e.event_type == "diag_retake" for e in b_events)
    return out


def _b5(events: Sequence[Event]) -> float | None:
    """案を採ったあと、次の依頼か task_submit までに B1 か B2 があった割合。"""
    adopted = [
        i
        for i, e in enumerate(events)
        if e.event_type == "plan_refine_decide" and e.payload.get("action") == "apply" and e.payload.get("accepted")
    ]
    if not adopted:
        return None
    checked = 0
    for index in adopted:
        for event in events[index + 1 :]:
            if event.event_type in AI_REQUEST_TYPES or event.event_type == "task_submit":
                break
            if event.event_type == "status_open" or (
                event.event_type == "syllabus_open" and event.payload.get("from") == _STATUS_FROM
            ):
                checked += 1
                break
    return checked / len(adopted)


# --- 人 ------------------------------------------------------------------------------------------


def participant_metrics(
    session: Session, tasks: Tasks, catalog: CourseCatalog, premises: Mapping[tuple[str, int], Sequence[str]]
) -> dict[str, Any]:
    missing, repeated, last = session.seq_gaps()
    gap_ratio = len(missing) / last if last else 0.0
    pre, _ = _questionnaire(session, SCALE_PRE, None)
    preference, preference_count = _questionnaire(session, SCALE_PREFERENCE, None)
    reflection, _ = _questionnaire(session, SCALE_REFLECTION, None)
    blocks = [block_metrics(session, block, tasks, catalog, premises) for block in BLOCKS if block in session.blocks]
    by_block = {b["block"]: b for b in blocks}
    prefer = preference.get("prefer") if preference is not None else None
    screen = str(prefer) if prefer is not None else None
    chosen = by_block.get(int(screen)) if screen in ("1", "2") else None
    times = [e.ts_client for e in session.client if e.ts_client is not None]
    last_questionnaire = max(
        (e.ts_client for e in session.client if e.event_type == "questionnaire_submit" and e.ts_client is not None),
        default=None,
    )
    completed = any(e.event_type == "block_end" and e.payload.get("block") == LAST_BLOCK for e in session.events)
    f4 = (
        (last_questionnaire - min(times)).total_seconds() / SECONDS_PER_MINUTE
        if completed and preference is not None and last_questionnaire is not None and times
        else None
    )
    return {
        "pid": session.pid,
        "session_id": session.session_id,
        "sequence_id": session.sequence_id,
        "mode": session.mode,
        "spare": (session.pid or "").startswith("R"),
        "grade": pre.get("grade") if pre else None,
        "faculty": pre.get("faculty") if pre else None,
        "seen_before": pre.get("seen_before") if pre else None,
        "prefer_screen": screen,
        "prefer_condition_id": chosen["condition_id"] if chosen else None,
        "prefer_variant_id": chosen["variant_id"] if chosen else None,
        "preference_answers": preference_count,
        "reflection_answered": sum(1 for v in (reflection or {}).values() if isinstance(v, str) and v.strip()),
        "completed": completed,
        "f4_minutes": f4,
        "seq_last": last,
        "seq_missing": len(missing),
        "seq_repeated": len(repeated),
        "seq_gap_ratio": gap_ratio,
        "e3": gap_ratio > E3_SEQ_GAP_LIMIT,
        "both_b_submitted": all(by_block.get(b, {}).get("submitted_b") for b in BLOCKS),
        "blocks": blocks,
    }


def build_metrics(events_path: Path, catalog_path: Path, tasks: Tasks) -> dict[str, Any]:
    events, read = read_events(events_path)
    catalog = load_course_catalog(catalog_path)
    if catalog.department_id != tasks.department_id:
        raise CatalogError(
            f"スナップショットの学科 {catalog.department_id} が tasks.json の {tasks.department_id} と違います。"
        )
    sessions = sessions_of(events)
    task_ids_of = {set_id: ts.task_ids for set_id, ts in tasks.task_sets.items()}
    premises = premise_failures(sessions, task_ids_of)
    participants = [participant_metrics(session, tasks, catalog, premises) for session in sessions]
    practice = _practice_failures(sessions, tasks)
    return {
        "format": METRICS_FORMAT,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "inputs": {
            "events": read.as_dict(),
            "catalog": {"source": catalog.source, "fingerprint": catalog.fingerprint, "courses": len(catalog.courses)},
            "tasks": {"path": tasks.path, "sha256": tasks.sha256, "config_version": tasks.config_version},
        },
        "sessions": len(sessions),
        "sessions_without_pid": sum(1 for s in sessions if s.pid is None),
        "practice_ai": practice,
        "participants": participants,
    }


def _practice_failures(sessions: Sequence[Session], tasks: Tasks) -> dict[str, int]:
    """練習（ブロック 0）の AI の依頼と失敗（F3 の分母には入れず、別に出す）。"""
    practice_ids = {task_id for ts in tasks.task_sets.values() if not ts.scored for task_id in ts.task_ids}
    requests = failures = 0
    for session in sessions:
        for request in ai_requests(session, [e for e in session.client if e.task_id in practice_ids]):
            requests += 1
            failures += _is_failure(request["outcome"])
    return {"requests": requests, "failures": failures}


def _print_summary(data: Mapping[str, Any]) -> None:
    rows = [
        "| pid | 系列 | ブロック | 条件 | セット | y | a | a0 | t_b 分 | W 秒 | B | D | SUS |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    def fmt(value: Any, digits: int = 2) -> str:
        return "—" if value is None else f"{value:.{digits}f}" if isinstance(value, float) else str(value)

    for person in data["participants"]:
        for block in person["blocks"]:
            t_b = block.get("t_b_ms")
            wait = block.get("W_ms")
            rows.append(
                f"| {person['pid']} | {person['sequence_id']} | {block['block']} | {block['condition_id']}/{block['variant_id']} | "
                f"{block['task_set']} | {fmt(block.get('y'))} | {fmt(block.get('a'))} | {fmt(block.get('a0'))} | "
                f"{fmt(t_b / MS_PER_SECOND / SECONDS_PER_MINUTE if t_b is not None else None, 1)} | "
                f"{fmt(wait / MS_PER_SECOND if wait is not None else None, 0)} | {fmt(block.get('B'))} | "
                f"{fmt((block.get('changes') or {}).get('D'))} | {fmt(block.get('SUS'), 1)} |"
            )
    print("\n".join(rows))
    durations = [p["f4_minutes"] for p in data["participants"] if p["f4_minutes"] is not None]
    print(
        f"F4 の所要時間の中央値: {statistics.median(durations):.1f} 分（{len(durations)} 人）"
        if durations
        else "F4: 終えた人がいない"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Study 1 の指標（事前登録 4章）を参加者 × 条件で出す")
    parser.add_argument("--events", type=Path, required=True, help="CLI の export の JSONL")
    parser.add_argument("--catalog", type=Path, required=True, help="catalog_snapshot.py の出力か diag-catalog-v1")
    parser.add_argument("--tasks", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True, help="指標の JSON（リポの外）")
    args = parser.parse_args(argv)
    try:
        tasks = load_tasks(args.tasks) if args.tasks is not None else load_tasks()
        data = build_metrics(args.events, args.catalog, tasks)
        digest = write_private_json(args.out, data, "指標")
    except (TasksError, CatalogError, OutputError, OSError) as exc:
        print(f"止めました: {exc}", file=sys.stderr)
        return 1
    read: Mapping[str, Any] = data["inputs"]["events"]
    print(
        f"{read['path']}: イベント {read['events']}・読めない行 {read['unreadable']}・形の一部が違う行 {read['problems']}"
    )
    _print_summary(data)
    print(f"JSON: {args.out}（SHA-256 {digest}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
