"""study（割り当ての単位）: 釣り合いの表・トークンのハッシュ・腕（ab-variants.md 6 章）。

- 系列は計画 4.1 の4つ（Q1＝N+P1→A+P2、Q2＝A+P1→N+P2、Q3＝N+P2→A+P1、Q4＝A+P2→N+P1）。
  pid に Q1〜Q4 を順に繰り返して割り付ける（乱数は使わない。ab-variants.md 6.2）。
- study のファイルにはトークンの SHA-256 だけを残す。平文はカードの CSV に1度だけ書く（cli.py）。
- 腕（分岐 A・B）は「役割 N・A → 伏せた記号と変種」。有効にする腕は E1 の判定のあとに CLI で決める。
- ブロック 0 は練習。伏せた記号は "P"、旗はブロック 1 と同じ（最初に使う画面で練習する）。

I/O は持たない（読み書きは store.py）。
"""

import hashlib
import re
import secrets
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel, Field

from course_core.research.variants import (
    FLAGS_VERSION,
    VARIANTS,
    embedding_violations,
    human_study_violations,
    study_ai_edges_violations,
    task_set_violations,
)
from course_core.schemas.research import BlockPlan, VariantOut

__all__ = [
    "ArmActivation",
    "ArmCondition",
    "Card",
    "LAST_BLOCK",
    "PRACTICE_BLOCK",
    "Participant",
    "Role",
    "SEQUENCES",
    "Study",
    "StudyError",
    "Withdrawal",
    "balanced_sequences",
    "build_study",
    "hash_token",
    "new_token",
    "parse_arm_spec",
    "start_violations",
]

Role = Literal["N", "A"]
Mode = Literal["onsite", "remote"]

STUDY_SCHEMA_VERSION: Final = "1.0"
SEQUENCES: Final = ("Q1", "Q2", "Q3", "Q4")
# 系列ごとの (役割, 課題セットの位置) をブロック 1・2 の順に。位置 0 が --task-sets の1つ目（P1）。
_SEQUENCE_ORDER: Final[Mapping[str, tuple[tuple[Role, int], tuple[Role, int]]]] = {
    "Q1": (("N", 0), ("A", 1)),
    "Q2": (("A", 0), ("N", 1)),
    "Q3": (("N", 1), ("A", 0)),
    "Q4": (("A", 1), ("N", 0)),
}
_ROLES: Final[tuple[Role, ...]] = ("N", "A")
PRACTICE_BLOCK: Final = 0
LAST_BLOCK: Final = 2  # 被験者内2ブロック（計画 4.1）
PRACTICE_CONDITION_ID: Final = "P"
PRACTICE_TASK_SET_ID: Final = "practice"
_PRACTICE_TASK_IDS: Final = ("practice",)
# 課題セットの中の課題: a（系統図＋時間割）と b（シラバスの中身。成績のつけ方を答える。計画 4.1）。
_TASK_SUFFIXES: Final = ("a", "b")
# どの課題セットも課題 b を含むので、detail=core は使えない（制約 C6）。
_SETS_HAVE_GRADING_TASK: Final = True
_TOKEN_BYTES: Final = 12  # secrets.token_urlsafe(12) で 16 文字（ab-variants.md 6.1）
_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{1,32}$")  # study_id はディレクトリ名になる
_CONDITION_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9]{0,7}$")
_TASK_SET_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{1,16}$")


class StudyError(ValueError):
    """study の作成・操作の条件を満たさない。"""


class ArmCondition(BaseModel):
    condition_id: str
    variant_id: str


class Participant(BaseModel):
    pid: str
    sequence_id: str
    token_sha256: str
    spare: bool = False
    mode: Mode = "onsite"
    withdrawn: bool = False


class ArmActivation(BaseModel):
    arm: str
    note: str
    at: str


class Withdrawal(BaseModel):
    pid: str
    removed_lines: int
    removed_sessions: int
    at: str


class Card(BaseModel):
    """カードの CSV の1行（トークンの平文を持つ。study のファイルには書かない）。"""

    pid: str
    sequence_id: str
    spare: bool
    token: str


class Study(BaseModel):
    schema_version: str = STUDY_SCHEMA_VERSION
    study_id: str
    department_id: str
    consent_version: str
    flags_version: str = FLAGS_VERSION
    created_at: str
    task_sets: list[str] = Field(..., min_length=2, max_length=2)
    questionnaires_per_block: int = Field(..., ge=0)
    arms: dict[str, dict[Role, ArmCondition]]
    active_arm: str | None = None
    arm_activations: list[ArmActivation] = Field(default_factory=list)
    participants: list[Participant]
    withdrawals: list[Withdrawal] = Field(default_factory=list)

    def participant(self, pid: str) -> Participant | None:
        return next((p for p in self.participants if p.pid == pid), None)

    def participant_by_token_hash(self, token_sha256: str) -> Participant | None:
        return next((p for p in self.participants if p.token_sha256 == token_sha256), None)

    def block_plans(self, sequence_id: str, arm: str) -> list[BlockPlan]:
        """練習（0）とブロック 1・2 の計画。"""
        return [self.block_plan(sequence_id, arm, block) for block in range(LAST_BLOCK + 1)]

    def block_plan(self, sequence_id: str, arm: str, block: int) -> BlockPlan:
        if block == PRACTICE_BLOCK:
            return BlockPlan(
                block=block,
                condition_id=PRACTICE_CONDITION_ID,
                task_set_id=PRACTICE_TASK_SET_ID,
                task_ids=list(_PRACTICE_TASK_IDS),
            )
        role, _ = self._order(sequence_id, block)
        task_set_id = self.task_set_id(sequence_id, block)
        return BlockPlan(
            block=block,
            condition_id=self._arm(arm)[role].condition_id,
            task_set_id=task_set_id,
            task_ids=[f"{task_set_id}-{suffix}" for suffix in _TASK_SUFFIXES],
        )

    def task_set_id(self, sequence_id: str, block: int) -> str:
        """ブロック 1・2 の課題セット（腕に依らない。割り付けの表に載せる）。"""
        _, set_index = self._order(sequence_id, block)
        return self.task_sets[set_index]

    def variant_out(self, sequence_id: str, arm: str, block: int) -> VariantOut:
        """ブロックの旗。練習はブロック 1 の旗で、伏せた記号だけ "P"。"""
        source_block = PRACTICE_BLOCK + 1 if block == PRACTICE_BLOCK else block
        role, _ = self._order(sequence_id, source_block)
        condition = self._arm(arm)[role]
        condition_id = PRACTICE_CONDITION_ID if block == PRACTICE_BLOCK else condition.condition_id
        return VariantOut(
            variant_id=condition.variant_id,
            condition_id=condition_id,
            flags=VARIANTS[condition.variant_id],
            flags_version=self.flags_version,
        )

    def _order(self, sequence_id: str, block: int) -> tuple[Role, int]:
        if sequence_id not in _SEQUENCE_ORDER:
            raise StudyError(f"系列 {sequence_id!r} は表にありません。")
        if not PRACTICE_BLOCK < block <= LAST_BLOCK:
            raise StudyError(f"ブロック {block} は計画にありません（{PRACTICE_BLOCK}〜{LAST_BLOCK}）。")
        return _SEQUENCE_ORDER[sequence_id][block - 1]

    def _arm(self, arm: str) -> dict[Role, ArmCondition]:
        if arm not in self.arms:
            raise StudyError(f"腕 {arm!r} は study {self.study_id} にありません。")
        return self.arms[arm]


def new_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def balanced_sequences(count: int) -> list[str]:
    """来た順の i 番目に SEQUENCES[i mod 4]。最初の2人で順序が、最初の4人で全系列がそろう。"""
    return [SEQUENCES[index % len(SEQUENCES)] for index in range(count)]


def parse_arm_spec(spec: str) -> tuple[str, dict[Role, ArmCondition]]:
    """`branchA=N:K:V01,A:M:V00` を (腕の名前, {役割: 伏せた記号と変種}) に。"""
    name, sep, body = spec.partition("=")
    if not sep or not _ID_PATTERN.fullmatch(name):
        raise StudyError(f"腕の書き方が違います: {spec!r}（例 branchA=N:K:V01,A:M:V00）")
    conditions: dict[Role, ArmCondition] = {}
    for item in body.split(","):
        parts = item.split(":")
        if len(parts) != 3:
            raise StudyError(f"腕 {name} の {item!r} は「役割:記号:変種」ではありません。")
        role, condition_id, variant_id = parts
        if role not in _ROLES or role in conditions:
            raise StudyError(f"腕 {name} の役割 {role!r} が違うか重なっています（N と A を1つずつ）。")
        conditions[role] = ArmCondition(condition_id=condition_id, variant_id=variant_id)
    if set(conditions) != set(_ROLES):
        raise StudyError(f"腕 {name} に N と A の両方がありません。")
    return name, conditions


def _arm_violations(arms: Mapping[str, Mapping[Role, ArmCondition]]) -> list[str]:
    violations: list[str] = []
    seen_conditions: dict[str, str] = {}
    for name, conditions in arms.items():
        for role, condition in conditions.items():
            where = f"腕 {name} の {role}"
            if not _CONDITION_PATTERN.fullmatch(condition.condition_id):
                violations.append(f"{where}: 記号 {condition.condition_id!r} は英大文字で始めてください")
            elif condition.condition_id == PRACTICE_CONDITION_ID:
                violations.append(f"{where}: 記号 {PRACTICE_CONDITION_ID} は練習のために取ってあります")
            elif condition.condition_id in seen_conditions:
                violations.append(
                    f"{where}: 記号 {condition.condition_id} が {seen_conditions[condition.condition_id]} と重なっています"
                )
            seen_conditions.setdefault(condition.condition_id, where)
            flags = VARIANTS.get(condition.variant_id)
            if flags is None:
                violations.append(f"{where}: 変種 {condition.variant_id!r} は表にありません")
                continue
            hits = human_study_violations(flags)
            hits += task_set_violations(flags, has_grading_task=_SETS_HAVE_GRADING_TASK)
            violations += [f"{where}（{condition.variant_id}）: {hit}" for hit in hits]
        if conditions["N"].variant_id == conditions["A"].variant_id:
            violations.append(f"腕 {name}: N と A が同じ変種です")
    all_flags = [
        VARIANTS[c.variant_id] for conds in arms.values() for c in conds.values() if c.variant_id in VARIANTS
    ]
    violations += study_ai_edges_violations(all_flags, human_study=True)
    return violations


def build_study(
    *,
    study_id: str,
    department_id: str,
    arms: Mapping[str, Mapping[Role, ArmCondition]],
    task_sets: list[str],
    n: int,
    spares: int,
    consent_version: str,
    questionnaires_per_block: int,
    now: datetime,
    token_factory: Callable[[], str] = new_token,
) -> tuple[Study, list[Card]]:
    """study とカードを作る。制約を外れたら StudyError（外れた理由をすべて並べる）。"""
    violations: list[str] = []
    if not _ID_PATTERN.fullmatch(study_id):
        violations.append(f"study_id {study_id!r} は英数字・_・- の 32 文字までにしてください")
    if len(task_sets) != 2 or len(set(task_sets)) != 2:
        violations.append(f"課題セットは異なる2つを書いてください: {task_sets}")
    violations += [
        f"課題セット {name!r} の名前が使えません"
        for name in task_sets
        if not _TASK_SET_PATTERN.fullmatch(name) or name == PRACTICE_TASK_SET_ID
    ]
    if n < 1 or spares < 0:
        violations.append(f"人数 n={n}・予備 spares={spares} が範囲の外です（n ≥ 1、spares ≥ 0）")
    if not arms:
        violations.append("腕が1つもありません")
    violations += _arm_violations(arms)
    if violations:
        raise StudyError("study を作れません: " + " / ".join(violations))

    width = max(2, len(str(max(n, spares))))
    rows = [(f"P{i + 1:0{width}d}", seq, False) for i, seq in enumerate(balanced_sequences(n))]
    rows += [(f"R{i + 1:0{width}d}", seq, True) for i, seq in enumerate(balanced_sequences(spares))]
    cards: list[Card] = []
    participants: list[Participant] = []
    for pid, sequence_id, spare in rows:
        token = token_factory()
        cards.append(Card(pid=pid, sequence_id=sequence_id, spare=spare, token=token))
        participants.append(
            Participant(pid=pid, sequence_id=sequence_id, spare=spare, token_sha256=hash_token(token))
        )
    if len({p.token_sha256 for p in participants}) != len(participants):
        raise StudyError("トークンが重なりました。作り直してください。")
    study = Study(
        study_id=study_id,
        department_id=department_id,
        consent_version=consent_version,
        created_at=now.isoformat(timespec="seconds"),
        task_sets=list(task_sets),
        questionnaires_per_block=questionnaires_per_block,
        arms={name: dict(conditions) for name, conditions in arms.items()},
        participants=participants,
    )
    return study, cards


def start_violations(study: Study, *, similar_to_edges: int, similar_models: list[str]) -> list[str]:
    """セッションを始めてよいか（制約 C8・C9）。有効な腕の変種と、DB の SIMILAR_TO の数え上げで決める。"""
    if study.active_arm is None:
        return ["study の腕が未決定"]
    flags_list = [VARIANTS[condition.variant_id] for condition in study.arms[study.active_arm].values()]
    violations: list[str] = []
    if similar_to_edges != 0 and any(flags.ai_edges == "official" for flags in flags_list):
        violations.append(
            f"C8: 実験の DB に SIMILAR_TO が {similar_to_edges} 本ある（ai_edges=official の study は 0 本で始める）"
        )
    for flags in flags_list:
        violations += embedding_violations(flags, similar_models)
    return violations
