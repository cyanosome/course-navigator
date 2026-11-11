"""毎晩の完全性の検査（事前登録 6.3。5.1 の F2、5.2 の前提）。

研究者用 CLI の check（course_core.research.store.check_completeness）より細かく、Study 1 の流れに合わせて見る:
- seq が 1 から欠けずに続くか（欠け・重なり。欠けの割合が 10% を超えるセッションは 5.5 の E3）
- 終えたブロック（block_end のあるブロック）ごとに、課題 a・b の task_start と task_submit が1件ずつあるか。
  課題 b の task_submit に読める最終プランがあるか（採点の 3.3 に要る）
- 終えたブロックごとに questionnaire_submit が尺度ごとに1件（既定 SUS・Q11-Q12）
- 同意の後の事前の質問が1件（既定 事前の質問）、閉じたセッションで最後のブロックの後に尺度ごとに1件（既定 二択・振り返り）
- 同意の記録（consent_recorded）の版が --consent-version（既定 v1-diag-ab-202611）か。--study-id を渡せば、
  すべての行がその study のものか
- 5.2 の前提（eventlog.premise_failures: 旗の指紋、同じ答えの初期プランの一致、初期プランの表示が AI を待っていない）
- chat_response の client_event_id が端末の依頼に結べるか、封筒の印（warnings）の数

参考（欠けに数えず、終了コードにも入れない。リンクを送る形では開く順を参加者が決め、開かれないカードは予備に替えるため）:
- 始まった順: 予備（R で始まる pid）を除き、pid の番号の順にセッションが始まっているか（session_start の時刻）。
  後の番号が先に始まった・前の番号がまだ始まっていないのに後の番号が始まった、を挙げる
- 送った順（--sent-order を渡したときだけ）: 研究者が控えた送った順の pid の並びと、始まった順を比べる。
  ファイルは pid だけを1行に1つ（カンマ・空白で区切ってもよい。# で始まる行は読まない）。名前や連絡先は書かない。
  pid の形（英大文字1つと数字。例 P01・R02）でない値があれば止める（終了コード 2）

終えていないブロック・閉じていないセッション（途中の人）は欠けに数えず、状態で分ける。

使い方（書き出しの JSONL に当てる。GMS では export を /tmp に書いた直後にコンテナの中で、または手元に写して）:

    docker compose exec backend uv run --no-sync python -m eval.study1.integrity --events /tmp/study1-events.jsonl

出力は人ごとの表と参考の欄（標準出力。pid と数だけで、自由記述は出さない）。終了コード: 欠けが無ければ 0、
欠けがあれば 1、書き出しか --sent-order のファイルが読めなければ 2。--json-out で同じ中身を JSON に書く（リポの外）。
"""

import argparse
import re
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from eval.study1.eventlog import AI_REQUEST_TYPES, ReadReport, Session, premise_failures, read_events, sessions_of
from eval.study1.files import OutputError, write_private_json
from eval.study1.score import PlanError, TasksError, load_tasks, parse_plan

__all__ = [
    "E3_SEQ_GAP_LIMIT",
    "SentOrderError",
    "SessionReport",
    "check_sessions",
    "distribution_order",
    "main",
    "read_sent_order",
    "sent_order_notes",
]

EXIT_OK: Final = 0
EXIT_DEFECTS: Final = 1
EXIT_UNREADABLE: Final = 2
E3_SEQ_GAP_LIMIT: Final = 0.10  # 5.5 の E3
BLOCKS: Final = (1, 2)
LAST_BLOCK: Final = 2
DEFAULT_BLOCK_SCALES: Final = ("SUS", "Q11-Q12")
DEFAULT_FINAL_SCALES: Final = ("二択", "振り返り")
DEFAULT_PRE_SCALES: Final = ("事前の質問",)
DEFAULT_CONSENT_VERSION: Final = "v1-diag-ab-202611"
_PID_PATTERN: Final = re.compile(r"^([A-Z])(\d+)$")
_SPARE_PREFIX: Final = "R"


@dataclass
class SessionReport:
    pid: str
    session_id: str
    sequence_id: str | None
    mode: str | None
    status: str  # complete・ended_incomplete・in_progress
    last_seq: int
    missing_seq: list[int]
    repeated_seq: list[int]
    defects: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: Counter[str] = field(default_factory=Counter)

    @property
    def gap_ratio(self) -> float:
        return len(self.missing_seq) / self.last_seq if self.last_seq else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "session_id": self.session_id,
            "sequence_id": self.sequence_id,
            "mode": self.mode,
            "status": self.status,
            "last_seq": self.last_seq,
            "missing_seq": self.missing_seq,
            "repeated_seq": self.repeated_seq,
            "gap_ratio": self.gap_ratio,
            "e3": self.gap_ratio > E3_SEQ_GAP_LIMIT,
            "defects": self.defects,
            "notes": self.notes,
            "warnings": dict(self.warnings),
        }


def _scales(session: Session, *, block: int | None, after_line: int | None = None) -> Counter[str]:
    """questionnaire_submit の尺度ごとの数。block が None なら payload の block が null のもの。after_line より後だけ。"""
    out: Counter[str] = Counter()
    for event in session.of_type("questionnaire_submit"):
        if after_line is not None and event.line <= after_line:
            continue
        if event.payload.get("block") != block:
            continue
        out[str(event.payload.get("scale"))] += 1
    return out


def _check_scales(found: Counter[str], expected: Sequence[str], where: str, defects: list[str]) -> None:
    for scale in expected:
        if found.get(scale, 0) != 1:
            defects.append(f"{where}の questionnaire_submit（{scale}）が {found.get(scale, 0)} 件（1件のはず）")


def _status(session: Session) -> str:
    if any(e.event_type == "block_end" and e.payload.get("block") == LAST_BLOCK for e in session.events):
        return "complete"
    return "ended_incomplete" if session.ended else "in_progress"


def check_sessions(
    sessions: Sequence[Session],
    task_ids_of: dict[str, Sequence[str]],
    *,
    block_scales: Sequence[str] = DEFAULT_BLOCK_SCALES,
    final_scales: Sequence[str] = DEFAULT_FINAL_SCALES,
    pre_scales: Sequence[str] = DEFAULT_PRE_SCALES,
    consent_version: str | None = DEFAULT_CONSENT_VERSION,
    study_id: str | None = None,
) -> list[SessionReport]:
    premises = premise_failures(sessions, task_ids_of)
    reports: list[SessionReport] = []
    for session in sessions:
        missing, repeated, last = session.seq_gaps()
        report = SessionReport(
            pid=session.pid or "?",
            session_id=session.session_id,
            sequence_id=session.sequence_id,
            mode=session.mode,
            status=_status(session),
            last_seq=last,
            missing_seq=missing,
            repeated_seq=repeated,
            warnings=Counter(w for e in session.events for w in e.warnings),
        )
        defects = report.defects
        if missing:
            defects.append(
                f"seq の欠け {len(missing)} 件（{report.gap_ratio:.1%}）"
                + ("。E3" if report.gap_ratio > E3_SEQ_GAP_LIMIT else "")
            )
        if repeated:
            defects.append(f"seq の重なり {len(repeated)} 件")
        ids = Counter(e.event_id for e in session.events)
        if any(count > 1 for count in ids.values()):
            defects.append(f"event_id の重なり {sum(count > 1 for count in ids.values())} 件")
        types = {e.event_type for e in session.events}
        if study_id is not None:
            others = sorted({str(e.study_id) for e in session.events if e.study_id != study_id})
            if others:
                defects.append(f"study_id が {study_id} でない行がある（{', '.join(others)}）")
        if consent_version is not None:
            versions = sorted({str(e.payload.get("consent_version")) for e in session.of_type("consent_recorded")})
            if any(version != consent_version for version in versions):
                defects.append(f"同意の版が {consent_version} でない（{', '.join(versions)}）")
        if "session_start" not in types:
            defects.append("session_start が無い")
        if session.blocks and not any(
            e.event_type == "consent_recorded" and e.payload.get("agreed") is True for e in session.events
        ):
            defects.append("同意の記録が無いのにブロックがある")
        if session.blocks:
            _check_scales(
                _scales(session, block=None, after_line=None) - _final_scales(session),
                pre_scales,
                "事前の質問",
                defects,
            )
        for block in BLOCKS:
            info = session.blocks.get(block)
            if info is None or not info.ended:
                continue
            task_ids = list(task_ids_of.get(info.task_set_id or "", ()))
            if len(task_ids) != 2:
                defects.append(f"ブロック {block} の課題セット {info.task_set_id} が tasks.json に無い")
                continue
            for task_id in task_ids:
                events = session.task(task_id)
                for kind in ("task_start", "task_submit"):
                    count = sum(e.event_type == kind for e in events)
                    if count != 1:
                        defects.append(f"ブロック {block} の {task_id} の {kind} が {count} 件（1件のはず）")
            submits = [e for e in session.task(task_ids[1]) if e.event_type == "task_submit"]
            if submits:
                try:
                    parse_plan(submits[-1].payload.get("plan"))
                except PlanError as exc:
                    defects.append(f"ブロック {block} の課題 b の最終プランが読めない（{exc}）")
            _check_scales(_scales(session, block=block), block_scales, f"ブロック {block} ", defects)
        if report.status == "complete" and session.ended:
            _check_scales(_final_scales(session), final_scales, "最後", defects)
        for (session_id, block), reasons in premises.items():
            if session_id == session.session_id:
                defects.append(f"ブロック {block} の 5.2 の前提: {'、'.join(reasons)}（E4）")
        requests = {e.event_id for e in session.client if e.event_type in AI_REQUEST_TYPES}
        unmatched = [r for r in session.of_type("chat_response") if r.payload.get("client_event_id") not in requests]
        if unmatched:
            report.notes.append(f"依頼に結べない chat_response {len(unmatched)} 件")
        lost = [r for r in requests if r not in session.responses]
        if lost:
            report.notes.append(f"chat_response の無い依頼 {len(lost)} 件")
        reports.append(report)
    return reports


def _final_scales(session: Session) -> Counter[str]:
    """最後のブロックの後の質問票（block_end block=2 の行より後で、payload の block が null）。"""
    ends = [e.line for e in session.events if e.event_type == "block_end" and e.payload.get("block") == LAST_BLOCK]
    if not ends:
        return Counter()
    return _scales(session, block=None, after_line=max(ends))


class SentOrderError(ValueError):
    """--sent-order のファイルが読めない・pid の形でない値がある。"""


def distribution_order(sessions: Sequence[Session]) -> list[str]:
    """予備を除き、pid の番号の順にセッションが始まっているか。外れを文で返す（参考。欠けに数えない）。"""
    started: list[tuple[int, str, Any]] = []
    for session in sessions:
        match = _PID_PATTERN.fullmatch(session.pid or "")
        if match is None or match.group(1) == _SPARE_PREFIX:
            continue
        started.append((int(match.group(2)), session.pid or "", session.started_at))
    started.sort()
    problems: list[str] = []
    numbers = [number for number, _, _ in started]
    skipped = [n for n in range(1, max(numbers, default=0) + 1) if n not in numbers]
    if skipped:
        problems.append(
            f"始まっていない番号の後の番号が始まっている（抜けた番号 {', '.join(str(n) for n in skipped)}）"
        )
    times = [(pid, at) for _, pid, at in started if at is not None]
    for (before, at_before), (after, at_after) in zip(times, times[1:], strict=False):
        if at_after < at_before:
            problems.append(f"{after} が {before} より先に始まった")
    return problems


def read_sent_order(path: Path) -> list[str]:
    """送った順の pid の並び。pid の形でない値・重なった pid があれば SentOrderError（名前などを読み込まないため）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SentOrderError(f"{path} を読めません: {exc}") from exc
    pids: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        for token in line.replace(",", " ").split():
            if _PID_PATTERN.fullmatch(token) is None:
                raise SentOrderError(
                    f"{path} の {number} 行目に pid の形でない値があります（pid だけを書いてください）。"
                )
            if token in pids:
                raise SentOrderError(f"{path} の {number} 行目の {token} が2回目です。")
            pids.append(token)
    return pids


def sent_order_notes(sessions: Sequence[Session], sent: Sequence[str]) -> list[str]:
    """送った順と始まった順（session_start の時刻）を比べる。違いを文で返す（参考。欠けに数えない）。"""
    started = {session.pid: session.started_at for session in sessions if session.pid is not None}
    notes: list[str] = []
    unsent = sorted(pid for pid in started if pid not in sent)
    if unsent:
        notes.append(f"送った順に無い pid が始まっている（{', '.join(unsent)}）")
    waiting = [pid for pid in sent if pid not in started]
    if waiting:
        notes.append(f"送ったがまだ始まっていない（{', '.join(waiting)}）")
    rank = {pid: index for index, pid in enumerate(sent, 1)}
    timed = sorted(((at, pid) for pid, at in started.items() if pid in rank and at is not None), key=lambda x: x[0])
    for (_, first), (_, second) in zip(timed, timed[1:], strict=False):
        if rank[second] < rank[first]:
            notes.append(f"{first}（送った順 {rank[first]}）が {second}（送った順 {rank[second]}）より先に始まった")
    return notes


def _table(reports: Sequence[SessionReport]) -> list[str]:
    lines = [
        "| pid | 系列 | mode | 状態 | seq | 欠け | 重なり | 欠けの割合 | 欠け・前提 | 注 | 印 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        warnings = ", ".join(f"{k}×{v}" for k, v in sorted(r.warnings.items())) or "なし"
        lines.append(
            f"| {r.pid} | {r.sequence_id} | {r.mode} | {r.status} | 1..{r.last_seq} | {len(r.missing_seq)} | {len(r.repeated_seq)} | "
            f"{r.gap_ratio:.1%} | {'; '.join(r.defects) or 'なし'} | {'; '.join(r.notes) or ''} | {warnings} |"
        )
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Study 1 の完全性の検査（事前登録 6.3）")
    parser.add_argument("--events", type=Path, required=True, help="CLI の export の JSONL")
    parser.add_argument("--tasks", type=Path, default=None)
    parser.add_argument("--block-scales", default=",".join(DEFAULT_BLOCK_SCALES))
    parser.add_argument("--final-scales", default=",".join(DEFAULT_FINAL_SCALES))
    parser.add_argument("--pre-scales", default=",".join(DEFAULT_PRE_SCALES))
    parser.add_argument("--consent-version", default=DEFAULT_CONSENT_VERSION, help="同意の版（空なら見ない）")
    parser.add_argument("--study-id", default=None, help="渡せば、すべての行がこの study のものかを見る")
    parser.add_argument("--sent-order", type=Path, help="送った順の pid の並び（1行に1つ。名前は書かない）。参考に出す")
    parser.add_argument("--json-out", type=Path, help="結果の JSON（リポの外）")
    args = parser.parse_args(argv)
    try:
        tasks = load_tasks(args.tasks) if args.tasks is not None else load_tasks()
        events, read = read_events(args.events)
        sent = read_sent_order(args.sent_order) if args.sent_order is not None else None
    except (OSError, TasksError, SentOrderError) as exc:
        print(f"止めました: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE
    split = [s.strip() for s in args.block_scales.split(",") if s.strip()]
    finals = [s.strip() for s in args.final_scales.split(",") if s.strip()]
    pres = [s.strip() for s in args.pre_scales.split(",") if s.strip()]
    sessions = sessions_of(events)
    task_ids_of = {set_id: ts.task_ids for set_id, ts in tasks.task_sets.items()}
    reports = check_sessions(
        sessions,
        task_ids_of,
        block_scales=split,
        final_scales=finals,
        pre_scales=pres,
        consent_version=args.consent_version or None,
        study_id=args.study_id,
    )
    started_order = distribution_order(sessions)
    sent_notes = sent_order_notes(sessions, sent) if sent is not None else None
    statuses = Counter(r.status for r in reports)
    defects = sum(len(r.defects) for r in reports) + len(read.unreadable)
    print(_summary(read, reports, statuses, defects))
    print("\n".join(_table(reports)))
    print("参考（欠けに数えず、終了コードにも入れない）:")
    print("- 始まった順（pid の番号の順か）: " + ("; ".join(started_order) or "番号の順"))
    if sent_notes is not None:
        print("- 送った順との比べ: " + ("; ".join(sent_notes) or "送った順"))
    if args.json_out is not None:
        try:
            digest = write_private_json(
                args.json_out,
                {
                    "read": read.as_dict(),
                    "sessions": [r.as_dict() for r in reports],
                    "reference": {"started_order": started_order, "sent_order": sent_notes},
                    "defects": defects,
                },
                "完全性の検査の結果",
            )
        except OutputError as exc:
            print(f"止めました: {exc}", file=sys.stderr)
            return EXIT_UNREADABLE
        print(f"JSON: {args.json_out}（SHA-256 {digest}）")
    return EXIT_OK if defects == 0 else EXIT_DEFECTS


def _summary(read: ReadReport, reports: Sequence[SessionReport], statuses: Counter[str], defects: int) -> str:
    gaps = sum(1 for r in reports if not r.missing_seq)
    return (
        f"{read.path}（SHA-256 {read.sha256}）: 行 {read.lines}・イベント {read.events}・読めない行 {len(read.unreadable)}・"
        f"形の一部が違う行 {len(read.problems)}\n"
        f"セッション {len(reports)}（完了 {statuses['complete']}・途中で終了 {statuses['ended_incomplete']}・"
        f"進行中 {statuses['in_progress']}）、seq の欠けの無いセッション {gaps}、欠け・前提の外れ・読めない行 {defects}"
    )


if __name__ == "__main__":
    sys.exit(main())
