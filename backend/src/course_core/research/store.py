"""研究のログの保存（JSONL）とセッションの状態（api-contract.md 3.9、ab-variants.md 7.1）。

置き方: <RESEARCH_DATA_DIR>/<study_id>/
- study.json            study（作成・腕・mode・撤回。CLI が書く）
- events.jsonl          1イベント1行。封筒（ab-variants.md 7.1）を付けて追記する
- sessions/<id>.json    セッションの状態（今のブロック・最後の seq・同意・受け取った event_id）。
                        `fastapi dev` の再読み込みで消えないようファイルに置く
- .lock                 書き込みの排他

排他: プロセスの中は threading.RLock、サーバーと CLI の間は .lock のファイルロック。書き込みの区間に
await を挟まないので、同じプロセスのコルーチンは割り込まない。イベントの行を先に書き、状態を後に書く
（途中で落ちたときに行が欠けるより、重複の行が残るほうを選ぶ。check が event_id の重なりを見つける）。
封筒の pid・系列・条件・ブロック・旗はサーバーが付け、クライアントの申告を使わない。
氏名・学籍番号・IP は受け取らず、書かない（計画 4.2）。
"""

import json
import os
import re
import secrets
import threading
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Any, Final, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from course_core.research.events import SERVER_EVENT_TYPES, SESSION_END, flags_digest, payload_warnings
from course_core.research.settings import app_commit, research_data_dir
from course_core.research.sink import ServerEventType, SessionVariant
from course_core.research.study import (
    LAST_BLOCK,
    ArmActivation,
    PRACTICE_BLOCK,
    Participant,
    Study,
    StudyError,
    Withdrawal,
    hash_token,
)
from course_core.schemas.research import ClientEvent, SessionOut

__all__ = [
    "BatchResult",
    "JST",
    "JsonlResearchSink",
    "ResearchConflict",
    "ResearchStore",
    "SessionCheck",
    "SessionNotFound",
    "SessionState",
    "StudyNotFound",
    "check_completeness",
    "default_store",
    "to_session_out",
]

JST: Final = timezone(timedelta(hours=9))
ENVELOPE_SCHEMA_VERSION: Final = "1.0"
STUDY_FILE: Final = "study.json"
EVENTS_FILE: Final = "events.jsonl"
SESSIONS_DIR: Final = "sessions"
_LOCK_FILE: Final = ".lock"
_STUDY_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_SESSION_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
_SESSION_ID_BYTES: Final = 24
_UNKNOWN_BACKEND: Final = "unknown"
_PROCESS_LOCK: Final = threading.RLock()


class ResearchConflict(Exception):
    """今のセッション・study の状態では受けられない（API は 409）。"""


class SessionNotFound(LookupError):
    """セッションが無い（撤回で消えたものを含む）。"""


class StudyNotFound(LookupError):
    """study のファイルが無い。"""


class SessionState(BaseModel):
    session_id: str
    study_id: str
    pid: str
    sequence_id: str
    arm: str
    mode: Literal["onsite", "remote"]
    started_at: str
    consent_version: str | None = None  # 同意した版。同意の前は None
    current_block: int | None = None  # 開いているブロック
    completed_blocks: list[int] = Field(default_factory=list)
    last_seq: int = 0
    event_ids: list[str] = Field(default_factory=list)  # 受け取ったクライアントの event_id（重複を捨てる）
    frontend_version: str | None = None  # 最後に受けたヘッダ X-Navi-Frontend
    client_session_end: bool = False  # クライアントの session_end を受け取ったか
    ended_at: str | None = None


@dataclass(frozen=True)
class BatchResult:
    accepted: int
    duplicates: int
    last_seq: int
    warnings: list[str]


def _now() -> datetime:
    return datetime.now(JST)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds")


def _client_ts(moment: datetime) -> tuple[str, list[str]]:
    """クライアントの時刻を +09:00 にそろえる。時差の無い時刻はそのまま書いて印を付ける。"""
    if moment.tzinfo is None:
        return moment.isoformat(timespec="milliseconds"), ["ts_client_naive"]
    return _iso(moment.astimezone(JST)), []


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def _lock_handle(handle: IO[bytes]) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_handle(handle: IO[bytes]) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def to_session_out(study: Study, state: SessionState) -> SessionOut:
    variant = None
    if state.current_block is not None:
        variant = study.variant_out(state.sequence_id, state.arm, state.current_block)
    return SessionOut(
        session_id=state.session_id,
        pid=state.pid,
        study_id=state.study_id,
        sequence_id=state.sequence_id,
        mode=state.mode,
        department_id=study.department_id,
        consent_version=study.consent_version,
        consent_recorded=state.consent_version is not None,
        blocks=study.block_plans(state.sequence_id, state.arm),
        current_block=state.current_block,
        variant=variant,
        backend_version=app_commit() or _UNKNOWN_BACKEND,
        completed_blocks=list(state.completed_blocks),
        last_seq=state.last_seq,
    )


class ResearchStore:
    """study・セッションの状態・イベントのファイルの読み書き。メソッドは同期（区間に await を挟まない）。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    # --- study ----------------------------------------------------------------

    def study_dir(self, study_id: str) -> Path:
        if not _STUDY_ID_PATTERN.fullmatch(study_id):
            raise StudyNotFound(f"study_id {study_id!r} の形が違います。")
        return self.root / study_id

    def load_study(self, study_id: str) -> Study:
        path = self.study_dir(study_id) / STUDY_FILE
        if not path.is_file():
            raise StudyNotFound(f"study {study_id} がありません（{path}）。")
        return Study.model_validate_json(path.read_text(encoding="utf-8"))

    def study_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.parent.name for p in self.root.glob(f"*/{STUDY_FILE}"))

    def create_study(self, study: Study) -> Path:
        """study のディレクトリを作って study.json を書く。同じ ID があれば止める（上書きしない）。"""
        directory = self.study_dir(study.study_id)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            directory.mkdir()
        except FileExistsError as exc:
            raise StudyError(f"study {study.study_id} は既にあります（{directory}）。") from exc
        (directory / SESSIONS_DIR).mkdir()
        with self._exclusive(study.study_id):
            self._save_study(study)
        return directory / STUDY_FILE

    def find_by_token(self, token: str) -> tuple[Study, Participant] | None:
        token_sha256 = hash_token(token)
        for study_id in self.study_ids():
            study = self.load_study(study_id)
            participant = study.participant_by_token_hash(token_sha256)
            if participant is not None:
                return study, participant
        return None

    def activate_arm(self, study_id: str, arm: str, note: str) -> Study:
        """腕を有効にし、study_arm_activated を書く。最初のセッションの後は拒む。"""
        with self._exclusive(study_id):
            study = self.load_study(study_id)
            if arm not in study.arms:
                raise StudyError(f"腕 {arm!r} は study {study_id} にありません（{', '.join(study.arms)}）。")
            if self._session_paths(study_id) or study.withdrawals:
                raise StudyError("セッションが始まった後は腕を切り替えられません。")
            at = _iso(_now())
            study.active_arm = arm
            study.arm_activations.append(ArmActivation(arm=arm, note=note, at=at))
            line = self._envelope(
                study,
                None,
                event_type="study_arm_activated",
                origin="server",
                payload={"arm": arm, "note": note, "at": at},
            )
            self._append_lines(study_id, [line])
            self._save_study(study)
            return study

    def set_mode(self, study_id: str, pid: str, mode: Literal["onsite", "remote"]) -> Study:
        with self._exclusive(study_id):
            study = self.load_study(study_id)
            participant = study.participant(pid)
            if participant is None:
                raise StudyError(f"pid {pid} は study {study_id} にありません。")
            if self._session_for_pid(study_id, pid) is not None:
                raise StudyError(f"pid {pid} のセッションは始まっています。mode は始まる前に変えてください。")
            participant.mode = mode
            self._save_study(study)
            return study

    def withdraw(self, study_id: str, pid: str) -> Withdrawal:
        """pid の行を除いて JSONL を書き直し、セッションの状態も消す。消した数と時刻を study に残す。"""
        with self._exclusive(study_id):
            study = self.load_study(study_id)
            participant = study.participant(pid)
            if participant is None:
                raise StudyError(f"pid {pid} は study {study_id} にありません。")
            events_path = self.study_dir(study_id) / EVENTS_FILE
            removed_lines = 0
            if events_path.is_file():
                kept: list[str] = []
                for number, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), 1):
                    if not line.strip():
                        continue
                    try:
                        line_pid = json.loads(line).get("pid")
                    except json.JSONDecodeError as exc:
                        raise StudyError(f"{events_path} の {number} 行目を読めません。直してから撤回してください。") from exc
                    if line_pid == pid:
                        removed_lines += 1
                    else:
                        kept.append(line)
                _write_atomic(events_path, "".join(f"{line}\n" for line in kept))
            removed_sessions = 0
            for path in self._session_paths(study_id):
                if self._read_session(path).pid == pid:
                    path.unlink()
                    removed_sessions += 1
            participant.withdrawn = True
            record = Withdrawal(
                pid=pid, removed_lines=removed_lines, removed_sessions=removed_sessions, at=_iso(_now())
            )
            study.withdrawals.append(record)
            self._save_study(study)
            return record

    def read_events(self, study_id: str) -> list[dict[str, Any]]:
        with self._exclusive(study_id):
            path = self.study_dir(study_id) / EVENTS_FILE
            if not path.is_file():
                return []
            lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def sessions(self, study_id: str) -> list[SessionState]:
        return [self._read_session(path) for path in self._session_paths(study_id)]

    # --- セッション --------------------------------------------------------------

    def session(self, session_id: str) -> SessionState | None:
        path = self._locate(session_id)
        return self._read_session(path) if path is not None else None

    def session_for_pid(self, study_id: str, pid: str) -> SessionState | None:
        return self._session_for_pid(study_id, pid)

    def start_session(
        self,
        study_id: str,
        pid: str,
        *,
        data_status: Mapping[str, Any],
        frontend_version: str | None,
    ) -> SessionState:
        """セッションを作り session_start を書く。同じ pid のセッションがあればそれを返す（書かない）。"""
        with self._exclusive(study_id):
            study = self.load_study(study_id)
            participant = study.participant(pid)
            if participant is None:
                raise SessionNotFound(f"pid {pid} は study {study_id} にありません。")
            if participant.withdrawn:
                raise ResearchConflict("このカードは撤回済みです。")
            if study.active_arm is None:
                raise ResearchConflict("study の腕が未決定です。")
            existing = self._session_for_pid(study_id, pid)
            if existing is not None:
                return existing
            state = SessionState(
                session_id=secrets.token_urlsafe(_SESSION_ID_BYTES),
                study_id=study_id,
                pid=pid,
                sequence_id=participant.sequence_id,
                arm=study.active_arm,
                mode=participant.mode,
                started_at=_iso(_now()),
                frontend_version=frontend_version,
            )
            line = self._envelope(
                study, state, event_type="session_start", origin="server", payload={"data_status": dict(data_status)}
            )
            self._append_lines(study_id, [line])
            self._save_session(state)
            return state

    def record_consent(
        self,
        session_id: str,
        *,
        consent_version: str,
        form_serial: str,
        agreed: bool,
        frontend_version: str | None,
    ) -> SessionState:
        """consent_recorded を書く。同意しないときも記録する（先へは進めない）。同意の後の2回目は書かない。"""
        with self._transaction(session_id) as (study, state):
            self._require_open(state)
            if consent_version != study.consent_version:
                raise ResearchConflict(
                    f"同意書の版 {consent_version} は study の版 {study.consent_version} と違います。"
                )
            if state.consent_version is not None:
                return state
            self._touch_frontend(state, frontend_version)
            if agreed:
                state.consent_version = consent_version
            payload = {"consent_version": consent_version, "form_serial": form_serial, "agreed": agreed}
            line = self._envelope(study, state, event_type="consent_recorded", origin="server", payload=payload)
            self._append_lines(study.study_id, [line])
            self._save_session(state)
            return state

    def start_block(self, session_id: str, block: int, *, frontend_version: str | None) -> SessionState:
        """前のブロックを終えていて block が次の番号のときだけ始める。開いているブロックの2回目は書かない。"""
        with self._transaction(session_id) as (study, state):
            self._require_open(state)
            if state.consent_version is None:
                raise ResearchConflict("同意の前はブロックを始められません。")
            if state.current_block == block:
                return state
            if state.current_block is not None:
                raise ResearchConflict(f"ブロック {state.current_block} が終わっていません。")
            expected = max(state.completed_blocks, default=PRACTICE_BLOCK - 1) + 1
            if expected > LAST_BLOCK:
                raise ResearchConflict("すべてのブロックを終えています。")
            if block != expected:
                raise ResearchConflict(f"次に始められるのはブロック {expected} です（{block} は受けられません）。")
            self._touch_frontend(state, frontend_version)
            state.current_block = block
            line = self._envelope(
                study, state, event_type="block_start", origin="server", payload=self._block_payload(study, state)
            )
            self._append_lines(study.study_id, [line])
            self._save_session(state)
            return state

    def end_block(self, session_id: str, block: int, *, frontend_version: str | None) -> SessionState:
        """開いているブロックを終える。終えたブロックの2回目は書かない。"""
        with self._transaction(session_id) as (study, state):
            self._require_open(state)
            if block in state.completed_blocks and state.current_block is None:
                return state
            if state.current_block != block:
                raise ResearchConflict(f"ブロック {block} は開いていません。")
            self._touch_frontend(state, frontend_version)
            line = self._envelope(
                study, state, event_type="block_end", origin="server", payload=self._block_payload(study, state)
            )
            state.completed_blocks.append(block)
            state.current_block = None
            self._append_lines(study.study_id, [line])
            self._save_session(state)
            return state

    def end_session(self, session_id: str, *, frontend_version: str | None) -> SessionState:
        """セッションを閉じる。クライアントの session_end が届いていなければサーバーが session_end を書く。"""
        with self._transaction(session_id) as (study, state):
            if state.ended_at is not None:
                return state
            self._touch_frontend(state, frontend_version)
            if not state.client_session_end:
                payload = {"completed_blocks": list(state.completed_blocks), "open_block": state.current_block}
                line = self._envelope(study, state, event_type=SESSION_END, origin="server", payload=payload)
                self._append_lines(study.study_id, [line])
            state.ended_at = _iso(_now())
            self._save_session(state)
            return state

    def append_client_events(
        self, session_id: str, events: Sequence[ClientEvent], *, frontend_version: str | None
    ) -> BatchResult:
        """クライアントのイベントに封筒を付けて追記する。同じ event_id の2回目は数えて捨てる。"""
        with self._transaction(session_id) as (study, state):
            self._require_open(state)
            self._touch_frontend(state, frontend_version)
            seen = set(state.event_ids)
            task_ids: set[str] = set()
            expected_digest: str | None = None
            if state.current_block is not None:
                task_ids = set(study.block_plan(state.sequence_id, state.arm, state.current_block).task_ids)
                variant = study.variant_out(state.sequence_id, state.arm, state.current_block)
                expected_digest = flags_digest(variant.flags.model_dump())
            lines: list[dict[str, Any]] = []
            duplicates = 0
            batch_warnings: list[str] = []
            for event in sorted(events, key=lambda item: item.seq):
                event_id = str(event.event_id)
                if event_id in seen:
                    duplicates += 1
                    continue
                seen.add(event_id)
                warnings = self._client_event_warnings(event, state, task_ids, expected_digest)
                state.last_seq = max(state.last_seq, event.seq)
                ts_client, ts_warnings = _client_ts(event.ts_client)
                warnings += ts_warnings
                if event.event_type == SESSION_END:
                    state.client_session_end = True
                lines.append(
                    self._envelope(
                        study,
                        state,
                        event_type=event.event_type,
                        origin="client",
                        payload=event.payload,
                        event_id=event_id,
                        ts_client=ts_client,
                        seq=event.seq,
                        task_id=event.task_id,
                        warnings=warnings,
                    )
                )
                state.event_ids.append(event_id)
                batch_warnings += [w for w in warnings if w not in batch_warnings]
            self._append_lines(study.study_id, lines)
            self._save_session(state)
            return BatchResult(
                accepted=len(lines), duplicates=duplicates, last_seq=state.last_seq, warnings=batch_warnings
            )

    def append_server_event(self, session_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
        """サーバーのイベント（例 chat_response）を書く。終わったセッションにも書く（応答が終了の後に返る場合）。"""
        if event_type not in SERVER_EVENT_TYPES:
            raise ValueError(f"サーバーのイベントの種類ではありません: {event_type!r}")
        with self._transaction(session_id) as (study, state):
            line = self._envelope(study, state, event_type=event_type, origin="server", payload=dict(payload))
            self._append_lines(study.study_id, [line])

    def session_context(self, session_id: str) -> tuple[Study, SessionState] | None:
        """続いているセッションと study（読むだけ）。無いか終わっていれば None。"""
        state = self.session(session_id)
        if state is None or state.ended_at is not None:
            return None
        return self.load_study(state.study_id), state

    # --- 中身 --------------------------------------------------------------------

    @contextmanager
    def _exclusive(self, study_id: str) -> Iterator[None]:
        directory = self.study_dir(study_id)
        if not directory.is_dir():
            raise StudyNotFound(f"study {study_id} がありません（{directory}）。")
        with _PROCESS_LOCK, (directory / _LOCK_FILE).open("a+b") as handle:
            _lock_handle(handle)
            try:
                yield
            finally:
                _unlock_handle(handle)

    @contextmanager
    def _transaction(self, session_id: str) -> Iterator[tuple[Study, SessionState]]:
        path = self._locate(session_id)
        if path is None:
            raise SessionNotFound(session_id)
        study_id = path.parent.parent.name
        with self._exclusive(study_id):
            if not path.is_file():
                raise SessionNotFound(session_id)
            yield self.load_study(study_id), self._read_session(path)

    def _locate(self, session_id: str) -> Path | None:
        if not _SESSION_ID_PATTERN.fullmatch(session_id) or not self.root.is_dir():
            return None
        return next(self.root.glob(f"*/{SESSIONS_DIR}/{session_id}.json"), None)

    def _session_paths(self, study_id: str) -> list[Path]:
        return sorted((self.study_dir(study_id) / SESSIONS_DIR).glob("*.json"))

    def _session_for_pid(self, study_id: str, pid: str) -> SessionState | None:
        return next((s for s in self.sessions(study_id) if s.pid == pid), None)

    @staticmethod
    def _read_session(path: Path) -> SessionState:
        return SessionState.model_validate_json(path.read_text(encoding="utf-8"))

    def _save_session(self, state: SessionState) -> None:
        directory = self.study_dir(state.study_id) / SESSIONS_DIR
        directory.mkdir(exist_ok=True)
        _write_atomic(directory / f"{state.session_id}.json", state.model_dump_json(indent=1))

    def _save_study(self, study: Study) -> None:
        _write_atomic(self.study_dir(study.study_id) / STUDY_FILE, study.model_dump_json(indent=2))

    def _append_lines(self, study_id: str, lines: Sequence[Mapping[str, Any]]) -> None:
        if not lines:
            return
        # 先に全部を文字列にする（書けない値があれば1行も書かずに止める）。
        text = "".join(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n" for line in lines)
        with (self.study_dir(study_id) / EVENTS_FILE).open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _require_open(state: SessionState) -> None:
        if state.ended_at is not None:
            raise ResearchConflict("セッションは終了しています。")

    @staticmethod
    def _touch_frontend(state: SessionState, frontend_version: str | None) -> None:
        if frontend_version:
            state.frontend_version = frontend_version

    @staticmethod
    def _block_payload(study: Study, state: SessionState) -> dict[str, Any]:
        assert state.current_block is not None
        plan = study.block_plan(state.sequence_id, state.arm, state.current_block)
        return {"block": plan.block, "condition_id": plan.condition_id, "task_set_id": plan.task_set_id}

    @staticmethod
    def _client_event_warnings(
        event: ClientEvent, state: SessionState, task_ids: set[str], expected_digest: str | None
    ) -> list[str]:
        warnings: list[str] = []
        if event.seq > state.last_seq + 1:
            warnings.append("seq_gap")
        elif event.seq <= state.last_seq:
            warnings.append("seq_out_of_order")
        if event.task_id is not None and event.task_id not in task_ids:
            warnings.append("task_not_in_block")
        warnings += payload_warnings(event.event_type, event.task_id, event.payload)
        digest = event.payload.get("flags_digest")
        if event.event_type == "variant_applied" and isinstance(digest, str) and expected_digest is not None:
            if digest != expected_digest:
                warnings.append("flags_mismatch")
        return warnings

    @staticmethod
    def _envelope(
        study: Study,
        state: SessionState | None,
        *,
        event_type: str,
        origin: Literal["client", "server"],
        payload: Mapping[str, Any],
        event_id: str | None = None,
        ts_client: str | None = None,
        seq: int | None = None,
        task_id: str | None = None,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        """封筒（ab-variants.md 7.1）。ブロックの外なら condition_id・variant_id・flags・block は null。"""
        block = condition_id = variant_id = flags = None
        if state is not None and state.current_block is not None:
            variant = study.variant_out(state.sequence_id, state.arm, state.current_block)
            block = state.current_block
            condition_id, variant_id, flags = variant.condition_id, variant.variant_id, variant.flags.model_dump()
        return {
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "event_id": event_id or str(uuid4()),
            "event_type": event_type,
            "origin": origin,
            "ts_client": ts_client,
            "ts_server": _iso(_now()),
            "seq": seq,
            "pid": state.pid if state else None,
            "session_id": state.session_id if state else None,
            "sequence_id": state.sequence_id if state else None,
            "study_id": study.study_id,
            "arm": state.arm if state else study.active_arm,
            "condition_id": condition_id,
            "variant_id": variant_id,
            "flags": flags,
            "flags_version": study.flags_version,
            "block": block,
            "task_id": task_id,
            "app_version": {
                "frontend": state.frontend_version if state else None,
                "backend": app_commit(),
            },
            "consent_version": state.consent_version if state else None,
            "mode": state.mode if state else None,
            "payload": dict(payload),
            "warnings": list(warnings or []),
        }


def default_store() -> ResearchStore:
    """環境変数 RESEARCH_DATA_DIR（既定 backend/logs/research）の store。呼ぶたびに環境変数を読む。"""
    return ResearchStore(research_data_dir())


class JsonlResearchSink:
    """sink.ResearchSink の実装（JSONL）。AI の口などサーバーの別の場所が使う。"""

    def __init__(self, store: ResearchStore) -> None:
        self._store = store

    async def current_variant(self, session_id: str) -> SessionVariant | None:
        context = self._store.session_context(session_id)
        if context is None:
            return None
        study, state = context
        if state.current_block is None:
            return SessionVariant(session_id=session_id, block=None, condition_id=None, variant_id=None, flags=None)
        variant = study.variant_out(state.sequence_id, state.arm, state.current_block)
        return SessionVariant(
            session_id=session_id,
            block=state.current_block,
            condition_id=variant.condition_id,
            variant_id=variant.variant_id,
            flags=variant.flags,
        )

    async def append_server_event(
        self, session_id: str, event_type: ServerEventType, payload: Mapping[str, Any]
    ) -> None:
        self._store.append_server_event(session_id, event_type, payload)


# --- 完全性の検査（CLI の check。計画 4.2、ab-variants.md 7.3 の F2） ---------------------------


@dataclass
class SessionCheck:
    session_id: str
    pid: str
    sequence_id: str
    status: Literal["complete", "ended_incomplete", "in_progress"]
    last_seq: int
    defects: list[str] = field(default_factory=list)
    warnings: Counter[str] = field(default_factory=Counter)


def _short_list(values: Sequence[int], limit: int = 20) -> str:
    shown = ", ".join(str(v) for v in values[:limit])
    return shown + (f" ほか {len(values) - limit} 件" if len(values) > limit else "")


def check_completeness(study: Study, events: Iterable[Mapping[str, Any]]) -> list[SessionCheck]:
    """セッションごとの欠け: seq の連続、event_id の重なり、終えたブロックの task_start・task_submit の数と質問票の数。

    終えていないブロック（途中でやめた人）は欠けに数えず、status で分ける。
    """
    by_session: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("session_id"):
            by_session[event["session_id"]].append(event)
    results: list[SessionCheck] = []
    for session_id, items in by_session.items():
        first = items[0]
        defects: list[str] = []
        seqs = [e["seq"] for e in items if e["origin"] == "client"]
        seq_counts = Counter(seqs)
        last_seq = max(seqs, default=0)
        missing = [n for n in range(1, last_seq + 1) if n not in seq_counts]
        if missing:
            defects.append(f"seq の欠け: {_short_list(missing)}")
        repeated = sorted(n for n, count in seq_counts.items() if count > 1)
        if repeated:
            defects.append(f"seq の重なり: {_short_list(repeated)}")
        repeated_ids = sorted(i for i, count in Counter(e["event_id"] for e in items).items() if count > 1)
        if repeated_ids:
            defects.append(f"event_id の重なり: {len(repeated_ids)} 件")
        kinds = Counter((e["event_type"], e["block"]) for e in items)
        types = {e["event_type"] for e in items}
        if "session_start" not in types:
            defects.append("session_start が無い")
        agreed = any(e["event_type"] == "consent_recorded" and e["payload"].get("agreed") is True for e in items)
        started_blocks = sorted(b for (t, b) in kinds if t == "block_start")
        if started_blocks and not agreed:
            defects.append("同意の記録が無いのにブロックがある")
        ended_blocks = sorted(b for (t, b) in kinds if t == "block_end")
        for block in ended_blocks:
            if block == PRACTICE_BLOCK:
                continue
            expected = len(study.block_plan(first["sequence_id"], first["arm"], block).task_ids)
            for event_type in ("task_start", "task_submit"):
                count = kinds[(event_type, block)]
                if count != expected:
                    defects.append(f"ブロック {block} の {event_type} が {count} 件（{expected} 件のはず）")
            questionnaires = kinds[("questionnaire_submit", block)]
            if questionnaires < study.questionnaires_per_block:
                defects.append(
                    f"ブロック {block} の questionnaire_submit が {questionnaires} 件"
                    f"（{study.questionnaires_per_block} 件以上のはず）"
                )
        if LAST_BLOCK in ended_blocks:
            status: Literal["complete", "ended_incomplete", "in_progress"] = "complete"
        elif SESSION_END in types:
            status = "ended_incomplete"
        else:
            status = "in_progress"
        results.append(
            SessionCheck(
                session_id=session_id,
                pid=first["pid"],
                sequence_id=first["sequence_id"],
                status=status,
                last_seq=last_seq,
                defects=defects,
                warnings=Counter(w for e in items for w in e.get("warnings", [])),
            )
        )
    return sorted(results, key=lambda result: result.pid)
