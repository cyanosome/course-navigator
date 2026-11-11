"""研究のイベントの書き出し（研究者用 CLI の export の JSONL）を読み、セッション・ブロック・課題に分ける。

1行は封筒（course_core.research.store の _envelope）。読めない行（JSON でない・封筒の項目が無い）は捨てずに数えて
ReadReport に残す（呼ぶ側が表に出す）。時刻は ISO 8601（ts_client は端末の時刻、ts_server はサーバーの受付時刻）。
クライアントのイベントの並びは seq（端末で1から振る）、サーバーのイベント（session_start・consent_recorded・
block_start・block_end・chat_response・session_end）は書かれた順（ファイルの行の順）を使う。

ブロックの割り当ては block_start の payload（block・condition_id・task_set_id）と封筒の variant_id・flags。
課題のイベントは封筒の task_id（端末がそのときの課題の ID を付ける）で分ける。chat_response（サーバー）は
payload の client_event_id で、端末の依頼（plan_refine_send・chat_send）の event_id に結ぶ。

5.2 の前提（事前登録）の検査もここに置く（integrity.py と metrics.py が同じものを使う）。
"""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from course_core.research.events import flags_digest

__all__ = [
    "AI_REQUEST_TYPES",
    "BlockInfo",
    "Event",
    "ReadReport",
    "Session",
    "parse_time",
    "premise_failures",
    "read_events",
    "sessions_of",
]

AI_REQUEST_TYPES: Final = frozenset({"plan_refine_send", "chat_send"})
_REQUIRED: Final = ("event_id", "event_type", "origin", "ts_server", "payload")
_ORIGINS: Final = frozenset({"client", "server"})


def parse_time(value: Any) -> datetime | None:
    """ISO 8601 の時刻。時差の無いもの・読めないものは None（呼ぶ側が数える）。"""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


@dataclass(frozen=True)
class Event:
    line: int
    event_id: str
    event_type: str
    origin: str
    seq: int | None
    ts_client: datetime | None
    ts_server: datetime | None
    pid: str | None
    session_id: str | None
    sequence_id: str | None
    study_id: str | None
    condition_id: str | None
    variant_id: str | None
    block: int | None
    task_id: str | None
    flags: Mapping[str, Any] | None
    consent_version: str | None
    mode: str | None
    payload: Mapping[str, Any]
    warnings: tuple[str, ...]

    @property
    def is_client(self) -> bool:
        return self.origin == "client"


@dataclass
class ReadReport:
    path: str
    sha256: str
    lines: int = 0
    blank: int = 0
    events: int = 0
    unreadable: list[tuple[int, str]] = field(default_factory=list)  # (行, 理由)。捨てた行
    problems: list[tuple[int, str]] = field(default_factory=list)  # (行, 理由)。読んだが形の一部が違う行

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "lines": self.lines,
            "blank": self.blank,
            "events": self.events,
            "unreadable": len(self.unreadable),
            "unreadable_examples": [f"{line}: {reason}" for line, reason in self.unreadable[:10]],
            "problems": len(self.problems),
            "problem_kinds": dict(Counter(reason for _, reason in self.problems)),
        }


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _event(raw: Any, number: int, report: ReadReport) -> Event | None:
    if not isinstance(raw, dict):
        report.unreadable.append((number, "オブジェクトでない"))
        return None
    missing = [key for key in _REQUIRED if key not in raw]
    if missing or not isinstance(raw.get("payload"), dict) or raw.get("origin") not in _ORIGINS:
        report.unreadable.append((number, f"封筒の項目が無いか形が違う（{', '.join(missing) or 'payload・origin'}）"))
        return None
    ts_client = parse_time(raw.get("ts_client"))
    seq = _int_or_none(raw.get("seq"))
    if raw["origin"] == "client":
        if ts_client is None:
            report.problems.append((number, "ts_client が読めない"))
        if seq is None:
            report.problems.append((number, "seq が無い"))
    ts_server = parse_time(raw.get("ts_server"))
    if ts_server is None:
        report.problems.append((number, "ts_server が読めない"))
    warnings = raw.get("warnings", [])
    flags = raw.get("flags")
    return Event(
        line=number,
        event_id=str(raw["event_id"]),
        event_type=str(raw["event_type"]),
        origin=raw["origin"],
        seq=seq,
        ts_client=ts_client,
        ts_server=ts_server,
        pid=_str_or_none(raw.get("pid")),
        session_id=_str_or_none(raw.get("session_id")),
        sequence_id=_str_or_none(raw.get("sequence_id")),
        study_id=_str_or_none(raw.get("study_id")),
        condition_id=_str_or_none(raw.get("condition_id")),
        variant_id=_str_or_none(raw.get("variant_id")),
        block=_int_or_none(raw.get("block")),
        task_id=_str_or_none(raw.get("task_id")),
        flags=flags if isinstance(flags, dict) else None,
        consent_version=_str_or_none(raw.get("consent_version")),
        mode=_str_or_none(raw.get("mode")),
        payload=raw["payload"],
        warnings=tuple(w for w in warnings if isinstance(w, str)) if isinstance(warnings, list) else (),
    )


def read_events(path: Path) -> tuple[list[Event], ReadReport]:
    """JSONL を読む。ファイルが開けなければ OSError（呼ぶ側が止める）。"""
    data = path.read_bytes()
    report = ReadReport(path=str(path), sha256=hashlib.sha256(data).hexdigest())
    events: list[Event] = []
    for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
        report.lines += 1
        if not line.strip():
            report.blank += 1
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            report.unreadable.append((number, f"JSON でない（{exc.msg}）"))
            continue
        event = _event(raw, number, report)
        if event is not None:
            events.append(event)
    report.events = len(events)
    return events, report


@dataclass(frozen=True)
class BlockInfo:
    block: int
    condition_id: str | None
    variant_id: str | None
    task_set_id: str | None
    flags: Mapping[str, Any] | None
    ended: bool


@dataclass
class Session:
    session_id: str
    pid: str | None
    sequence_id: str | None
    mode: str | None
    events: list[Event]  # ファイルの行の順
    blocks: dict[int, BlockInfo] = field(default_factory=dict)

    @property
    def client(self) -> list[Event]:
        """端末のイベント（seq の順。seq の無い行は後ろ）。"""
        return sorted((e for e in self.events if e.is_client), key=lambda e: (e.seq is None, e.seq or 0, e.line))

    def of_type(self, *event_types: str) -> list[Event]:
        return [e for e in self.events if e.event_type in event_types]

    def task(self, task_id: str) -> list[Event]:
        return [e for e in self.client if e.task_id == task_id]

    @property
    def responses(self) -> dict[str, Event]:
        """chat_response を client_event_id で引く（同じ依頼に2つあれば後のもの）。"""
        out: dict[str, Event] = {}
        for event in self.of_type("chat_response"):
            key = event.payload.get("client_event_id")
            if isinstance(key, str):
                out[key] = event
        return out

    @property
    def seq_numbers(self) -> list[int]:
        return [e.seq for e in self.events if e.is_client and e.seq is not None]

    def seq_gaps(self) -> tuple[list[int], list[int], int]:
        """(欠けた seq, 重なった seq, 最後の seq)。"""
        counts = Counter(self.seq_numbers)
        last = max(counts, default=0)
        missing = [n for n in range(1, last + 1) if n not in counts]
        repeated = sorted(n for n, count in counts.items() if count > 1)
        return missing, repeated, last

    @property
    def ended(self) -> bool:
        return any(e.event_type == "session_end" for e in self.events)

    @property
    def started_at(self) -> datetime | None:
        start = next((e for e in self.events if e.event_type == "session_start"), None)
        return start.ts_server if start is not None else None


def sessions_of(events: Iterable[Event]) -> list[Session]:
    """セッションごとに分ける（session_id の無い行 = study_arm_activated などは入れない）。pid の順。"""
    grouped: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if event.session_id is not None:
            grouped[event.session_id].append(event)
    sessions: list[Session] = []
    for session_id, items in grouped.items():
        first = next((e for e in items if e.pid is not None), items[0])
        session = Session(
            session_id=session_id, pid=first.pid, sequence_id=first.sequence_id, mode=first.mode, events=items
        )
        ended_blocks = {e.payload.get("block") for e in items if e.event_type == "block_end"}
        for event in items:
            if event.event_type != "block_start":
                continue
            block = _int_or_none(event.payload.get("block"))
            if block is None:
                continue
            session.blocks[block] = BlockInfo(
                block=block,
                condition_id=_str_or_none(event.payload.get("condition_id")),
                variant_id=event.variant_id,
                task_set_id=_str_or_none(event.payload.get("task_set_id")),
                flags=event.flags,
                ended=block in ended_blocks,
            )
        sessions.append(session)
    return sorted(sessions, key=lambda s: (s.pid or "", s.session_id))


# --- 5.2 の前提 --------------------------------------------------------------------------------


def _plan_key(plan: Any) -> tuple[tuple[int, str, tuple[str, ...]], ...] | None:
    """プランの比べる形（学期ごとの syllabus_id の集合。並びは見ない）。読めなければ None。"""
    if not isinstance(plan, list):
        return None
    out = []
    for term in plan:
        if not isinstance(term, dict) or not isinstance(term.get("syllabus_ids"), list):
            return None
        out.append((term.get("year"), term.get("term"), tuple(sorted(str(s) for s in term["syllabus_ids"]))))
    return tuple(sorted(out, key=lambda item: (str(item[0]), str(item[1]))))


def _block_of(session: Session, event: Event, task_blocks: Mapping[str, int]) -> int | None:
    if event.task_id is not None and event.task_id in task_blocks:
        return task_blocks[event.task_id]
    return event.block


def task_blocks(session: Session, task_ids_of: Mapping[str, Sequence[str]]) -> dict[str, int]:
    """課題の ID → ブロック（block_start の task_set_id から。task_ids_of は課題セット → 課題の ID）。"""
    out: dict[str, int] = {}
    for block, info in session.blocks.items():
        for task_id in task_ids_of.get(info.task_set_id or "", ()):
            out[task_id] = block
    return out


def premise_failures(
    sessions: Sequence[Session], task_ids_of: Mapping[str, Sequence[str]]
) -> dict[tuple[str, int], list[str]]:
    """5.2 の前提が外れたブロックと理由。キーは (session_id, block)。前提を確かめられないブロックも外れに数える。

    (1) variant_applied の旗の指紋が、封筒の旗（サーバーが付けたもの）の指紋と一致する。終えたブロックに variant_applied が
        無いときも外れ（確かめられない）。
    (2) 同じ（設定の版, answers_digest）の plan_shown のプランが、条件と人によらず一致する。違うプランがあれば、
        いちばん多いプラン（同数ならどれも基準にしない）と違う plan_shown のあるブロックを外れにする。
    (3) diag_submit から次の plan_shown までの間に chat_response が無い。chat_response の時刻は、対応する依頼の
        ts_client に latency_ms を足したもの（端末の時計にそろえる）。対応する依頼の無い応答は確かめられないので数えない。
    """
    failures: dict[tuple[str, int], list[str]] = defaultdict(list)
    shown: dict[tuple[str, str], list[tuple[Session, int, Any]]] = defaultdict(list)
    for session in sessions:
        blocks = task_blocks(session, task_ids_of)
        started = sorted(session.blocks)
        for block in started:
            applied = [e for e in session.of_type("variant_applied") if _block_of(session, e, blocks) == block]
            if not applied and session.blocks[block].ended:  # 終えたブロックだけ（途中の人はまだ画面を開いていない）
                failures[(session.session_id, block)].append("variant_applied が無い")
            for event in applied:
                server = event.flags if event.flags is not None else session.blocks[block].flags
                expected = flags_digest(server) if server is not None else None
                if event.payload.get("flags_digest") != expected or "flags_mismatch" in event.warnings:
                    failures[(session.session_id, block)].append("旗の指紋が違う")
        for event in session.of_type("plan_shown"):
            block = _block_of(session, event, blocks)
            key = (str(event.payload.get("config_version")), str(event.payload.get("answers_digest")))
            if block is not None:
                shown[key].append((session, block, _plan_key(event.payload.get("plan"))))
        requests = {e.event_id: e for e in session.client if e.event_type in AI_REQUEST_TYPES}
        response_times = []
        for response in session.of_type("chat_response"):
            request = requests.get(str(response.payload.get("client_event_id")))
            latency = response.payload.get("latency_ms")
            if request is None or request.ts_client is None or not isinstance(latency, (int, float)):
                continue
            response_times.append(request.ts_client.timestamp() + latency / 1000)
        pending_submit: Event | None = None
        for event in session.client:
            if event.event_type == "diag_submit":
                pending_submit = event
            elif event.event_type == "plan_shown" and pending_submit is not None:
                start, end = pending_submit.ts_client, event.ts_client
                block = _block_of(session, event, blocks)
                waited = (
                    start is not None
                    and end is not None
                    and any(start.timestamp() < t < end.timestamp() for t in response_times)
                )
                if waited and block is not None:
                    failures[(session.session_id, block)].append("診断の送信からプランの表示までに AI の応答がある")
                pending_submit = None
    for items in shown.values():
        plans = Counter(plan for _, _, plan in items)
        if len(plans) <= 1:
            continue
        ranked = plans.most_common()
        reference = ranked[0][0] if ranked[0][1] > ranked[1][1] else None
        for session, block, plan in items:
            if plan != reference:
                failures[(session.session_id, block)].append("同じ答えの初期プランが他と違う")
    return {key: sorted(set(reasons)) for key, reasons in failures.items()}
