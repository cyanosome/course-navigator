"""研究者用の CLI（api-contract.md 3.8）。画面は作らない。

使い方（backend で）: `uv run python -m course_core.research.cli <命令> …`
置き場所は環境変数 RESEARCH_DATA_DIR（既定 backend/logs/research。git の対象外）。

トークンの平文は create-study の --cards-out に1度だけ書く。study のファイルには SHA-256 だけを残す。
カードの CSV と書き出しは git の作業ツリーの中には書かない（公開リポにコミットしないため）。
"""

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Final

from course_core.research.store import JST, ResearchStore, StudyNotFound, check_completeness, default_store
from course_core.research.study import (
    LAST_BLOCK,
    SEQUENCES,
    StudyError,
    build_study,
    parse_arm_spec,
)
from course_core.research.variants import VARIANT_NAMES, VARIANTS, human_study_violations

_EXIT_OK: Final = 0
_EXIT_FAILED: Final = 1
_CARD_FIELDS: Final = ("pid", "sequence_id", "spare", "token", "url")
# 質問票の組 ibuki_sus（事前登録 Study 1 の 4.5・6.2 の9）: ブロックごとに SUS と Q11・Q12（＋自由記述）の2件、
# 最後のブロックの後に二択と理由の1件（questionnaire_submit は尺度ごとに1件）
_DEFAULT_QUESTIONNAIRES_PER_BLOCK: Final = 2
_DEFAULT_FINAL_QUESTIONNAIRES: Final = 1


def _inside_git_worktree(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in path.resolve().parents)


def _private_output(path: Path, what: str) -> None:
    """研究者の手元にだけ置くファイルの書き先を検査する（上書きしない・git の作業ツリーの外）。"""
    if path.exists():
        raise StudyError(f"{what} の書き先 {path} は既にあります（上書きしません）。")
    if _inside_git_worktree(path):
        raise StudyError(f"{what} を git の作業ツリーの中（{path}）には書きません。リポの外を指定してください。")


def _card_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/s/{token}"


def _cmd_list_variants(_: argparse.Namespace, __: ResearchStore) -> int:
    for variant_id, flags in VARIANTS.items():
        violations = human_study_violations(flags)
        human = "可" if not violations else "不可（" + "、".join(v.split(":")[0] for v in violations) + "）"
        values = " ".join(f"{name}={value}" for name, value in flags.model_dump().items())
        print(f"{variant_id} {VARIANT_NAMES[variant_id]:<20} 人の study: {human}\n    {values}")
    return _EXIT_OK


def _cmd_create_study(args: argparse.Namespace, store: ResearchStore) -> int:
    cards_out = Path(args.cards_out)
    _private_output(cards_out, "カードの CSV")
    arms = dict(parse_arm_spec(spec) for spec in args.arm)
    if len(arms) != len(args.arm):
        raise StudyError("同じ名前の腕が2つあります。")
    study, cards = build_study(
        study_id=args.study_id,
        department_id=args.department,
        arms=arms,
        task_sets=[name.strip() for name in args.task_sets.split(",")],
        n=args.n,
        spares=args.spares,
        consent_version=args.consent_version,
        questionnaires_per_block=args.questionnaires_per_block,
        final_questionnaires=args.final_questionnaires,
        now=datetime.now(JST),
    )
    cards_out.parent.mkdir(parents=True, exist_ok=True)
    with cards_out.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(_CARD_FIELDS)
        for card in cards:
            writer.writerow([card.pid, card.sequence_id, card.spare, card.token, _card_url(args.base_url, card.token)])
    try:
        study_path = store.create_study(study)
    except Exception:
        cards_out.unlink()  # study の無いトークンを残さない
        raise
    print(f"study を作りました: {study_path}")
    print(f"カードの CSV（トークンの平文。ここにだけあります）: {cards_out}")
    print("割り付けの表（トークンなし。事前登録と一緒に公開してよい）:")
    print("pid,sequence_id,spare,block1,block2")
    for participant in study.participants:
        sets = [study.task_set_id(participant.sequence_id, block) for block in range(1, LAST_BLOCK + 1)]
        print(f"{participant.pid},{participant.sequence_id},{participant.spare},{','.join(sets)}")
    print("腕はまだ有効ではありません。E1 の判定の後に activate-arm を打ってください。")
    return _EXIT_OK


def _cmd_activate_arm(args: argparse.Namespace, store: ResearchStore) -> int:
    study = store.activate_arm(args.study_id, args.arm, args.note)
    conditions = ", ".join(f"{role}={c.condition_id}:{c.variant_id}" for role, c in study.arms[args.arm].items())
    print(f"study {study.study_id} の腕 {args.arm}（{conditions}）を有効にしました。")
    return _EXIT_OK


def _cmd_set_mode(args: argparse.Namespace, store: ResearchStore) -> int:
    store.set_mode(args.study_id, args.pid, args.mode)
    print(f"study {args.study_id} の {args.pid} の mode を {args.mode} にしました。")
    return _EXIT_OK


def _cmd_status(args: argparse.Namespace, store: ResearchStore) -> int:
    study = store.load_study(args.study_id)
    sessions = {state.pid: state for state in store.sessions(args.study_id)}
    print(f"study {study.study_id}（学科 {study.department_id}、腕 {study.active_arm or '未決定'}）")
    print("系列  割り当て  開始  完了  予備の使用")
    for sequence_id in SEQUENCES:
        members = [p for p in study.participants if p.sequence_id == sequence_id]
        regular = [p for p in members if not p.spare]
        started = [p for p in members if p.pid in sessions]
        completed = [p for p in started if LAST_BLOCK in sessions[p.pid].completed_blocks]
        spares_used = [p.pid for p in members if p.spare and p.pid in sessions]
        print(
            f"{sequence_id:<5} {len(regular):>8}  {len(started):>4}  {len(completed):>4}  "
            f"{', '.join(spares_used) or '-'}"
        )
    withdrawn = [p.pid for p in study.participants if p.withdrawn]
    print(f"撤回: {', '.join(withdrawn) or 'なし'}")
    return _EXIT_OK


def _cmd_check(args: argparse.Namespace, store: ResearchStore) -> int:
    study = store.load_study(args.study_id)
    results = check_completeness(study, store.read_events(args.study_id))
    statuses = Counter(result.status for result in results)
    defects = sum(len(result.defects) for result in results)
    print(
        f"study {study.study_id}: セッション {len(results)}（完了 {statuses['complete']}・"
        f"途中で終了 {statuses['ended_incomplete']}・進行中 {statuses['in_progress']}）、欠け {defects}"
    )
    for result in results:
        warnings = ", ".join(f"{name}×{count}" for name, count in sorted(result.warnings.items())) or "なし"
        print(f"  {result.pid}（{result.sequence_id}）{result.status} seq 1..{result.last_seq} 印: {warnings}")
        for defect in result.defects:
            print(f"    欠け: {defect}")
    return _EXIT_OK if defects == 0 else _EXIT_FAILED


def _cmd_export(args: argparse.Namespace, store: ResearchStore) -> int:
    out = Path(args.out)
    _private_output(out, "書き出し")
    study = store.load_study(args.study_id)
    withdrawn = {p.pid for p in study.participants if p.withdrawn}
    events = [event for event in store.read_events(args.study_id) if event.get("pid") not in withdrawn]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as stream:
        for event in events:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(events)} 行を {out} に書き出しました（撤回済みの pid は入れていません）。")
    return _EXIT_OK


def _cmd_withdraw(args: argparse.Namespace, store: ResearchStore) -> int:
    record = store.withdraw(args.study_id, args.pid)
    print(
        f"study {args.study_id} の {record.pid} を撤回しました: 行 {record.removed_lines}・"
        f"セッション {record.removed_sessions} を消しました（{record.at}）。"
        "書き出し済みのファイルは別に消してください。"
    )
    return _EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="course_core.research.cli", description="研究のログと study の CLI")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list-variants", help="変種の表と、人の study に使えるか")

    create = commands.add_parser("create-study", help="釣り合いの表とトークンを作る")
    create.add_argument("--study-id", required=True)
    create.add_argument("--department", required=True)
    create.add_argument("--arm", action="append", required=True, help="例 branchA=N:K:V01,A:M:V00（複数可）")
    create.add_argument("--task-sets", required=True, help="課題セット2つ。例 P1,P2")
    create.add_argument("--n", type=int, required=True)
    create.add_argument("--spares", type=int, default=0)
    create.add_argument("--consent-version", required=True)
    create.add_argument("--cards-out", required=True, help="カードの CSV（トークンの平文）。リポの外")
    create.add_argument("--base-url", default="", help="カードの URL の前半。例 https://example.org")
    create.add_argument(
        "--questionnaires-per-block",
        type=int,
        default=_DEFAULT_QUESTIONNAIRES_PER_BLOCK,
        help="check でブロックごとに求める questionnaire_submit の数",
    )
    create.add_argument(
        "--final-questionnaires",
        type=int,
        default=_DEFAULT_FINAL_QUESTIONNAIRES,
        help="check で最後のブロックの後に求める questionnaire_submit の数（0 なら見ない）",
    )

    activate = commands.add_parser("activate-arm", help="腕を有効にする（最初のセッションの前だけ）")
    activate.add_argument("--study-id", required=True)
    activate.add_argument("--arm", required=True)
    activate.add_argument("--note", required=True, help="E1 の判定の結果など")

    mode = commands.add_parser("set-mode", help="遠隔の人の mode を変える（セッションの前だけ）")
    mode.add_argument("--study-id", required=True)
    mode.add_argument("--pid", required=True)
    mode.add_argument("--mode", required=True, choices=("onsite", "remote"))

    for name, help_text in (("status", "系列ごとの開始・完了の人数"), ("check", "完全性の検査（欠けがあれば終了コード 1）")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--study-id", required=True)

    export = commands.add_parser("export", help="イベントを分析用の場所に書き出す（撤回済みは入れない）")
    export.add_argument("--study-id", required=True)
    export.add_argument("--out", required=True, help="リポの外")

    withdraw = commands.add_parser("withdraw", help="pid の行を消し、消した数と時刻を残す")
    withdraw.add_argument("--study-id", required=True)
    withdraw.add_argument("--pid", required=True)
    return parser


_COMMANDS: Final = {
    "list-variants": _cmd_list_variants,
    "create-study": _cmd_create_study,
    "activate-arm": _cmd_activate_arm,
    "set-mode": _cmd_set_mode,
    "status": _cmd_status,
    "check": _cmd_check,
    "export": _cmd_export,
    "withdraw": _cmd_withdraw,
}


def main(argv: Sequence[str] | None = None, store: ResearchStore | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _COMMANDS[args.command](args, store if store is not None else default_store())
    except (StudyError, StudyNotFound) as exc:
        print(f"止めました: {exc}", file=sys.stderr)
        return _EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
