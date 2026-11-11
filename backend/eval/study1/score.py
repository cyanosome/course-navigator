"""Study 1 の採点（事前登録 3.3 の K1〜K6 と、4.1 の成否 y・達成度 a・初期プランの a0）。

課題 b の最終プラン（task_submit の payload の plan）と初期プラン（plan_shown の plan）に、tasks.json の条件を当てる。
プランの形は画面の planPayload（frontend/src/navi/diagnose.ts）: [{"year": 1, "term": "春", "syllabus_ids": ["…"]}, …]。
科目の属性（名前・学期・曜限・単位・まとまり）は、プランの学期に courses（[{syllabus_id, name, credits, slots, group_id}]）が
あればそれを、無ければ科目のスナップショット（catalog_snapshot.py）を使う。

規則（画面のチェック frontend/src/navi/status.ts・ledger.ts と同じにしたもの）:
- 科目はプランの学期に置く。通年の科目は、プランの学年の春と秋の両方に数える（画面の termsOf と同じく単位も両方に入る。
  画面は科目の配当の学年を使う。下調べの 1,500 プランに通年の科目は1件も無い）
- credits（K3）: 学期ごとに単位を足す。単位の分からない科目があれば、下限に届かないときと上限を超えないときは「判定できない」
- free_slot（K2）: 学期ごとに、指定の曜日（periods があればその時限だけ）の曜限を持つ科目があれば満たさない。曜限が
  「月1」の形でないもの（「他」など。スナップショットでは slots が空）はかからない。曜限の分からない科目があれば判定できない
- no_overlap（K6）: 学期ごとに、同じ曜限の科目が2つ以上あれば満たさない
- group_count（K1）: 採点する学期の科目のうち、まとまりが groups のどれかに入る科目の数（同じ名前の別クラスも1つずつ数える。
  画面と同じ）が min 以上。系統図に無いクラス（syllabus_id でまとまりが引けない科目）は、同じ名前の系統図の科目の
  まとまりとみなす（画面の判定と同じ。catalog_snapshot.CourseCatalog.group_of）。画面のチェックはプランの全部の学期を
  数え、事前登録 3.3 は採点する学期だけを数える。ここは事前登録に従う
- has_name（K4）・keep_names（K5）: 採点だけの規則。指定の学期に同じ名前の科目があれば入っているとみなす（クラスは区別しない）
- 学期ごとの条件は、どれか1つの学期で満たさなければ満たさない、満たさない学期が無く判定できない学期があれば判定できない
成否 y は6つ（練習は2つ）すべてを満たせば 1。達成度 a は満たした数 ÷ 条件の数。判定できない条件は満たした数に入れない
（その件数を unknown に出す。スナップショットに無い科目がプランにあるときに起きる）。

手で作った例と画面の判定を突き合わせる（事前登録 3.3 の「手で作った例 20 件」）:

    python -m eval.study1.score --catalog catalog.json --examples examples.jsonl

examples.jsonl の1行: {"id": "ex01", "task_set": "P1", "plan": [...], "screen": {"K2": "met", "K3": "unmet", ...}}
（screen は画面に出た判定。書いた条件だけを比べる）。1つでも違えば終了コード 1。1つのプランを採点するだけなら
--plan plan.json --task-set P1（plan.json はプランの配列か {"plan": [...]}）。
"""

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, get_args

from eval.study1.catalog_snapshot import CatalogError, CourseCatalog, CourseInfo, load_course_catalog

__all__ = [
    "CONDITION_KINDS",
    "Condition",
    "ConditionResult",
    "Plan",
    "PlanError",
    "PlanTerm",
    "Score",
    "TaskSet",
    "Tasks",
    "TasksError",
    "Term",
    "add_course",
    "default_place",
    "hits_slot",
    "load_tasks",
    "move_course",
    "parse_plan",
    "plan_payload",
    "remove_course",
    "score_plan",
]

TASKS_PATH: Final = Path(__file__).with_name("tasks.json")
TASKS_FORMAT: Final = "study1-tasks-v1"
ConditionKind = Literal["group_count", "free_slot", "credits", "has_name", "keep_names", "no_overlap"]
CONDITION_KINDS: Final = frozenset(get_args(ConditionKind))
Status = Literal["met", "unmet", "unknown"]
STATUSES: Final = frozenset(get_args(Status))
SPRING: Final = "春"
AUTUMN: Final = "秋"
FULL_YEAR: Final = "通年"
_HALVES: Final = (SPRING, AUTUMN)
_DAYS: Final = frozenset("月火水木金土日")
_PERIOD_MIN: Final = 1
_PERIOD_MAX: Final = 7
_YEAR_MIN: Final = 1
_YEAR_MAX: Final = 6
SLOT_PATTERN: Final = re.compile(r"^([月火水木金土日])(\d+)$")  # status.ts の SLOT_PATTERN と同じ


class TasksError(ValueError):
    """tasks.json が読めない・形が違う。"""


class PlanError(ValueError):
    """プランの形が違う。"""


@dataclass(frozen=True, order=True)
class Term:
    year: int
    term: str  # 春・秋

    @property
    def label(self) -> str:
        return f"{self.year}年{self.term}"

    @property
    def key(self) -> str:
        return f"{self.year}-{self.term}"


# --- tasks.json ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Condition:
    id: str
    kind: ConditionKind
    text: str
    terms: tuple[Term, ...]
    groups: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None
    days: tuple[str, ...] = ()
    periods: tuple[int, ...] = ()
    name: str | None = None
    names_by_term: tuple[tuple[Term, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class TaskSet:
    id: str
    card: str
    scored: bool  # 効果の分析で採点するか（練習は False）
    task_ids: tuple[str, ...]
    reference_answers: Mapping[str, tuple[str, ...]]
    conditions: tuple[Condition, ...]
    registered: Mapping[str, Any]

    @property
    def graded_terms(self) -> tuple[Term, ...]:
        return tuple(sorted({term for condition in self.conditions for term in condition.terms}))


@dataclass(frozen=True)
class Tasks:
    department_id: str
    config_version: str
    task_sets: Mapping[str, TaskSet]
    sha256: str
    path: str

    def task_set_of(self, task_id: str | None) -> TaskSet | None:
        if task_id is None:
            return None
        return next((ts for ts in self.task_sets.values() if task_id in ts.task_ids), None)


def _term(raw: Any, where: str, problems: list[str]) -> Term | None:
    if not isinstance(raw, dict):
        problems.append(f"{where}: 学期の形が違う")
        return None
    year, half = raw.get("year"), raw.get("term")
    if isinstance(year, bool) or not isinstance(year, int) or not _YEAR_MIN <= year <= _YEAR_MAX or half not in _HALVES:
        problems.append(f"{where}: 学期 {raw!r} が読めない")
        return None
    return Term(year, half)


def _terms(raw: Any, where: str, problems: list[str]) -> tuple[Term, ...]:
    if not isinstance(raw, list) or not raw:
        problems.append(f"{where}: terms が空か配列でない")
        return ()
    terms = [_term(item, f"{where}[{index}]", problems) for index, item in enumerate(raw)]
    return tuple(term for term in terms if term is not None)


def _number_or_none(raw: Any) -> bool:
    return raw is None or (not isinstance(raw, bool) and isinstance(raw, (int, float)))


def _condition(raw: Any, where: str, problems: list[str]) -> Condition | None:
    if not isinstance(raw, dict):
        problems.append(f"{where}: 形が違う")
        return None
    cid, kind, text = raw.get("id"), raw.get("kind"), raw.get("text", "")
    if not isinstance(cid, str) or not cid or kind not in CONDITION_KINDS or not isinstance(text, str):
        problems.append(f"{where}: id・kind・text が読めない（kind {kind!r}）")
        return None
    before = len(problems)
    if kind == "keep_names":
        groups_raw = raw.get("names_by_term")
        names_by_term: list[tuple[Term, tuple[str, ...]]] = []
        if not isinstance(groups_raw, list) or not groups_raw:
            problems.append(f"{where}: names_by_term が空")
        else:
            for index, item in enumerate(groups_raw):
                term = _term(item, f"{where}.names_by_term[{index}]", problems)
                names = item.get("names") if isinstance(item, dict) else None
                if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
                    problems.append(f"{where}.names_by_term[{index}]: names が空か文字列でない")
                    continue
                if term is not None:
                    names_by_term.append((term, tuple(names)))
        condition = Condition(
            id=cid, kind=kind, text=text, terms=tuple(t for t, _ in names_by_term), names_by_term=tuple(names_by_term)
        )
        return condition if len(problems) == before else None
    terms = _terms(raw.get("terms"), f"{where}.terms", problems)
    values: dict[str, Any] = {}
    if kind == "group_count":
        groups, minimum = raw.get("groups"), raw.get("min")
        if not isinstance(groups, list) or not groups or not all(isinstance(g, str) and g for g in groups):
            problems.append(f"{where}: groups が空か文字列でない")
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
            problems.append(f"{where}: min が1以上の整数でない")
        values = {"groups": tuple(groups or ()), "min": minimum}
    elif kind == "credits":
        minimum, maximum = raw.get("min"), raw.get("max")
        if not _number_or_none(minimum) or not _number_or_none(maximum) or (minimum is None and maximum is None):
            problems.append(f"{where}: min・max は数か null で、少なくとも一方が要る")
        values = {"min": minimum, "max": maximum}
    elif kind == "free_slot":
        days, periods = raw.get("days"), raw.get("periods")
        if not isinstance(days, list) or not days or not all(d in _DAYS for d in days):
            problems.append(f"{where}: days が曜日の配列でない")
        if not isinstance(periods, list) or not all(
            not isinstance(p, bool) and isinstance(p, int) and _PERIOD_MIN <= p <= _PERIOD_MAX for p in periods
        ):
            problems.append(f"{where}: periods が時限の配列でない")
        values = {"days": tuple(days or ()), "periods": tuple(periods or ())}
    elif kind == "has_name":
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            problems.append(f"{where}: name が無い")
        values = {"name": name}
    if len(problems) != before:
        return None
    return Condition(id=cid, kind=kind, text=text, terms=terms, **values)


def _answers(raw: Any, where: str, problems: list[str]) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw, dict) or not all(
        isinstance(v, list) and all(isinstance(i, str) for i in v) for v in raw.values()
    ):
        problems.append(f"{where}: 参照の答えの形が違う")
        return {}
    return {question: tuple(ids) for question, ids in raw.items()}


def load_tasks(path: Path = TASKS_PATH) -> Tasks:
    """tasks.json を読んで検査する。誤りはすべて並べて TasksError。"""
    try:
        data_bytes = path.read_bytes()
        data = json.loads(data_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TasksError(f"{path} を読めません: {exc}") from exc
    problems: list[str] = []
    if not isinstance(data, dict) or data.get("format") != TASKS_FORMAT:
        raise TasksError(f"{path}: 形が {TASKS_FORMAT} ではありません。")
    department_id, config_version, raw_sets = (
        data.get("department_id"),
        data.get("config_version"),
        data.get("task_sets"),
    )
    if not isinstance(department_id, str) or not isinstance(config_version, str) or not isinstance(raw_sets, dict):
        raise TasksError(f"{path}: department_id・config_version・task_sets がありません。")
    task_sets: dict[str, TaskSet] = {}
    seen_task_ids: set[str] = set()
    for set_id, raw in raw_sets.items():
        where = f"task_sets.{set_id}"
        if not isinstance(raw, dict):
            problems.append(f"{where}: 形が違う")
            continue
        conditions_raw = raw.get("conditions")
        if not isinstance(conditions_raw, list) or not conditions_raw:
            problems.append(f"{where}: conditions が空")
            continue
        conditions = [_condition(c, f"{where}.conditions[{i}]", problems) for i, c in enumerate(conditions_raw)]
        ids = [c.id for c in conditions if c is not None]
        if len(set(ids)) != len(ids):
            problems.append(f"{where}: 条件の id が重なっている")
        task_ids = raw.get("task_ids")
        if not isinstance(task_ids, list) or not task_ids or not all(isinstance(t, str) and t for t in task_ids):
            problems.append(f"{where}: task_ids が無い")
            task_ids = []
        for task_id in task_ids:
            if task_id in seen_task_ids:
                problems.append(f"{where}: 課題 {task_id} が2つのセットにある")
            seen_task_ids.add(task_id)
        registered = raw.get("registered", {})
        if not isinstance(registered, dict):
            problems.append(f"{where}: registered の形が違う")
            registered = {}
        task_sets[set_id] = TaskSet(
            id=set_id,
            card=str(raw.get("card", "")),
            scored=bool(raw.get("scored", False)),
            task_ids=tuple(task_ids),
            reference_answers=_answers(raw.get("reference_answers"), f"{where}.reference_answers", problems),
            conditions=tuple(c for c in conditions if c is not None),
            registered=registered,
        )
    if problems:
        raise TasksError(f"{path}: " + " / ".join(problems))
    return Tasks(
        department_id=department_id,
        config_version=config_version,
        task_sets=task_sets,
        sha256=hashlib.sha256(data_bytes).hexdigest(),
        path=str(path),
    )


# --- プラン ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanTerm:
    term: Term
    syllabus_ids: tuple[str, ...]
    # プランの payload に科目の属性があれば（syllabus_id → 属性）。無ければ空でスナップショットを引く
    courses: Mapping[str, CourseInfo] = field(default_factory=dict)


Plan = tuple[PlanTerm, ...]


def _course_override(raw: Any, term: Term) -> CourseInfo | None:
    """プランの payload の科目の属性（syllabus_id・name・credits・slots が要る）。読めなければ None（スナップショットを引く）。"""
    if not isinstance(raw, dict) or not isinstance(raw.get("syllabus_id"), str) or not isinstance(raw.get("name"), str):
        return None
    slots = raw.get("slots")
    credits = raw.get("credits")
    if not isinstance(slots, list) or "credits" not in raw or not _number_or_none(credits):
        return None
    return CourseInfo(
        syllabus_id=raw["syllabus_id"],
        name=raw["name"],
        credits=float(credits) if _number_or_none(credits) and credits is not None else None,
        year_min=None,
        year_max=None,
        term=raw.get("term") if raw.get("term") in (SPRING, AUTUMN, FULL_YEAR) else term.term,
        slots=tuple(s for s in slots if isinstance(s, str)),
        slot_note=None,
        group_id=raw.get("group_id") if isinstance(raw.get("group_id"), str) else None,
    )


def parse_plan(value: Any) -> Plan:
    """学期ごとの syllabus_id の配列（frontend の planPayload の形）。学期が2回出たら PlanError。"""
    if not isinstance(value, list):
        raise PlanError("プランが配列ではありません。")
    terms: list[PlanTerm] = []
    seen: set[Term] = set()
    for index, raw in enumerate(value):
        problems: list[str] = []
        term = _term(raw, f"plan[{index}]", problems)
        ids = raw.get("syllabus_ids") if isinstance(raw, dict) else None
        if term is None or not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise PlanError(
                f"plan[{index}] の形が違います（{'; '.join(problems) or 'syllabus_ids が文字列の配列でない'}）。"
            )
        if term in seen:
            raise PlanError(f"plan に {term.label} が2回あります。")
        seen.add(term)
        overrides = {}
        if isinstance(raw.get("courses"), list):
            for item in raw["courses"]:
                info = _course_override(item, term)
                if info is not None:
                    overrides[info.syllabus_id] = info
        terms.append(PlanTerm(term=term, syllabus_ids=tuple(ids), courses=overrides))
    return tuple(sorted(terms, key=lambda t: t.term))


def plan_payload(plan: Plan) -> list[dict[str, Any]]:
    return [{"year": t.term.year, "term": t.term.term, "syllabus_ids": list(t.syllabus_ids)} for t in plan]


def plan_ids(plan: Plan) -> set[str]:
    return {sid for t in plan for sid in t.syllabus_ids}


def remove_course(plan: Plan, syllabus_id: str) -> Plan:
    """科目を外す（学期は残す。画面の removeCourseFromPlan と同じ）。"""
    return tuple(PlanTerm(t.term, tuple(s for s in t.syllabus_ids if s != syllabus_id), t.courses) for t in plan)


def add_course(plan: Plan, syllabus_id: str, term: Term) -> Plan:
    """科目を学期に足す。もう入っていれば変えない、学期が無ければ足す（画面の addCourseToPlan と同じ）。"""
    if syllabus_id in plan_ids(plan):
        return plan
    if any(t.term == term for t in plan):
        return tuple(PlanTerm(t.term, (*t.syllabus_ids, syllabus_id), t.courses) if t.term == term else t for t in plan)
    return tuple(sorted((*plan, PlanTerm(term, (syllabus_id,))), key=lambda t: t.term))


def move_course(plan: Plan, from_id: str, to_id: str) -> Plan:
    """同じ学期で from を to に替える（別クラスへ移す）。from が無ければ変えない。"""
    where = next((t.term for t in plan if from_id in t.syllabus_ids), None)
    if where is None:
        return plan
    return add_course(remove_course(plan, from_id), to_id, where)


def default_place(info: CourseInfo) -> Term | None:
    """画面が置き場所の指定なしに科目を足す学年と学期（diagnose.ts の coursePlace: 配当年次の下限、秋なら秋、ほかは春）。"""
    if info.year_min is None:
        return None
    return Term(info.year_min, AUTUMN if info.term == AUTUMN else SPRING)


# --- 採点 --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Placed:
    """プランの1科目。known が偽ならスナップショットにも payload にも無い（属性が分からない）。"""

    syllabus_id: str
    name: str | None
    credits: float | None
    slots: tuple[str, ...] | None
    group_id: str | None
    terms: tuple[Term, ...]
    known: bool


@dataclass(frozen=True)
class ConditionResult:
    id: str
    kind: ConditionKind
    status: Status
    reason: str
    codes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "reason": self.reason,
            "codes": list(self.codes),
        }


@dataclass(frozen=True)
class Score:
    task_set: str
    results: tuple[ConditionResult, ...]
    unknown_courses: tuple[str, ...]

    @property
    def met(self) -> int:
        return sum(r.status == "met" for r in self.results)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def y(self) -> int:
        return int(self.met == self.total)

    @property
    def a(self) -> float:
        return self.met / self.total

    @property
    def unknown(self) -> int:
        return sum(r.status == "unknown" for r in self.results)

    def status_of(self, condition_id: str) -> Status | None:
        return next((r.status for r in self.results if r.id == condition_id), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_set": self.task_set,
            "y": self.y,
            "a": self.a,
            "met": self.met,
            "total": self.total,
            "unknown": self.unknown,
            "results": [r.as_dict() for r in self.results],
            "unknown_courses": list(self.unknown_courses),
        }


def _place(plan: Plan, catalog: CourseCatalog) -> list[Placed]:
    placed: list[Placed] = []
    for plan_term in plan:
        for sid in plan_term.syllabus_ids:
            info = plan_term.courses.get(sid) or catalog.get(sid)
            if info is None:
                placed.append(Placed(sid, None, None, None, None, (plan_term.term,), known=False))
                continue
            terms = (
                (Term(plan_term.term.year, SPRING), Term(plan_term.term.year, AUTUMN))
                if info.term == FULL_YEAR
                else (plan_term.term,)
            )
            placed.append(Placed(sid, info.name, info.credits, info.slots, catalog.group_of(info), terms, known=True))
    return placed


def _here(placed: Sequence[Placed], term: Term) -> list[Placed]:
    return [p for p in placed if term in p.terms]


def _worst(statuses: Iterable[Status]) -> Status:
    values = list(statuses)
    if "unmet" in values:
        return "unmet"
    if "unknown" in values:
        return "unknown"
    return "met"


def _credit_range(credits: float, unknown: int, minimum: float | None, maximum: float | None) -> Status:
    """status.ts の creditRange と同じ（分からない単位は 0 以上のどれか、として扱う）。"""
    results: list[Status] = []
    if minimum is not None:
        results.append("met" if credits >= minimum else "unknown" if unknown > 0 else "unmet")
    if maximum is not None:
        results.append("unmet" if credits > maximum else "unknown" if unknown > 0 else "met")
    return _worst(results)


def hits_slot(slot: str, days: Sequence[str], periods: Sequence[int]) -> bool:
    match = SLOT_PATTERN.fullmatch(slot)
    if match is None:
        return False
    return match.group(1) in days and (not periods or int(match.group(2)) in periods)


def _number_text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _per_term(condition: Condition, placed: Sequence[Placed]) -> ConditionResult:
    statuses: list[Status] = []
    reasons: list[str] = []
    codes: list[str] = []
    for term in condition.terms:
        here = _here(placed, term)
        if condition.kind == "credits":
            credits = sum(p.credits for p in here if p.credits is not None)
            unknown = sum(p.credits is None for p in here)
            status = _credit_range(credits, unknown, condition.min, condition.max)
            reasons.append(
                f"{term.label} {_number_text(credits)}単位" + (f"（単位の分からない科目 {unknown}）" if unknown else "")
            )
            if status == "unmet" and condition.max is not None and credits > condition.max:
                codes += [p.syllabus_id for p in here]
        elif condition.kind == "free_slot":
            hits = [p for p in here if any(hits_slot(s, condition.days, condition.periods) for s in p.slots or ())]
            if hits:
                status = "unmet"
                slots = sorted(
                    {s for p in hits for s in p.slots or () if hits_slot(s, condition.days, condition.periods)}
                )
                reasons.append(f"{term.label}の{'・'.join(slots)}に入っている")
                codes += [p.syllabus_id for p in hits]
            elif any(p.slots is None for p in here):
                status = "unknown"
                reasons.append(f"{term.label}に曜限の分からない科目がある")
            else:
                status = "met"
        elif condition.kind == "no_overlap":
            by_slot: dict[str, list[str]] = {}
            for p in here:
                for slot in p.slots or ():
                    by_slot.setdefault(slot, []).append(p.syllabus_id)
            clashes = {slot: ids for slot, ids in by_slot.items() if len(ids) > 1}
            if clashes:
                status = "unmet"
                reasons.append("、".join(f"{term.label}の{slot}" for slot in sorted(clashes)))
                codes += [sid for ids in clashes.values() for sid in ids]
            elif any(p.slots is None for p in here):
                status = "unknown"
                reasons.append(f"{term.label}に曜限の分からない科目がある")
            else:
                status = "met"
        elif condition.kind == "has_name":
            found = [p.syllabus_id for p in here if p.name == condition.name]
            if found:
                status = "met"
                codes += found
            else:
                status = "unknown" if any(not p.known for p in here) else "unmet"
                reasons.append(f"{term.label}に「{condition.name}」が無い")
        else:  # keep_names
            names = dict(condition.names_by_term)[term]
            present = {p.name for p in here if p.name is not None}
            missing = [name for name in names if name not in present]
            if missing:
                status = "unknown" if any(not p.known for p in here) else "unmet"
                reasons.append(f"{term.label}に{'、'.join(missing)}が無い")
            else:
                status = "met"
        statuses.append(status)
    return ConditionResult(
        condition.id, condition.kind, _worst(statuses), "、".join(reasons), tuple(dict.fromkeys(codes))
    )


def _group_count(condition: Condition, placed: Sequence[Placed]) -> ConditionResult:
    graded = set(condition.terms)
    hits = [p.syllabus_id for p in placed if p.group_id in condition.groups and graded.intersection(p.terms)]
    minimum = condition.min or 0
    status: Status = "met" if len(hits) >= minimum else "unmet"
    return ConditionResult(
        condition.id, condition.kind, status, f"{len(hits)}つ（{_number_text(minimum)}つ以上）", tuple(hits)
    )


def evaluate(condition: Condition, placed: Sequence[Placed]) -> ConditionResult:
    if condition.kind == "group_count":
        return _group_count(condition, placed)
    return _per_term(condition, placed)


def score_plan(plan: Plan, task_set: TaskSet, catalog: CourseCatalog) -> Score:
    """プランに task_set の条件を当てる。"""
    placed = _place(plan, catalog)
    results = tuple(evaluate(condition, placed) for condition in task_set.conditions)
    unknown = tuple(dict.fromkeys(p.syllabus_id for p in placed if not p.known))
    return Score(task_set.id, results, unknown)


# --- 入口 --------------------------------------------------------------------------------------


def _read_plan_file(path: Path) -> Any:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["plan"] if isinstance(data, dict) and "plan" in data else data


def _line(score: Score) -> str:
    parts = [f"{r.id} {r.status}" + (f"（{r.reason}）" if r.reason else "") for r in score.results]
    return f"y={score.y} a={score.met}/{score.total} | " + " | ".join(parts)


def _check_examples(path: Path, tasks: Tasks, catalog: CourseCatalog) -> int:
    """手で作った例と画面の判定を比べる。違いがあれば 1。読めない行も数えて 1。"""
    mismatches = 0
    unreadable = 0
    checked = 0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            task_set = tasks.task_sets[row["task_set"]]
            score = score_plan(parse_plan(row["plan"]), task_set, catalog)
            screen = row.get("screen", {})
            if not isinstance(screen, dict) or not all(v in STATUSES for v in screen.values()):
                raise PlanError("screen の値は met・unmet・unknown のどれか")
        except (json.JSONDecodeError, KeyError, TypeError, PlanError) as exc:
            unreadable += 1
            print(f"{path}:{number} 読めません: {exc}")
            continue
        checked += 1
        diffs = [
            f"{cid}: 採点 {score.status_of(cid)} / 画面 {value}"
            for cid, value in screen.items()
            if score.status_of(cid) != value
        ]
        mismatches += bool(diffs)
        print(
            f"{row.get('id', number)} {task_set.id} {_line(score)}"
            + (f" | 違い: {'; '.join(diffs)}" if diffs else " | 一致")
        )
    print(f"例 {checked} 件、画面と違う例 {mismatches} 件、読めない行 {unreadable} 件")
    return 0 if mismatches == 0 and unreadable == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Study 1 の採点（事前登録 3.3・4.1）")
    parser.add_argument("--catalog", type=Path, required=True, help="catalog_snapshot.py の出力か diag-catalog-v1")
    parser.add_argument("--tasks", type=Path, default=TASKS_PATH)
    parser.add_argument("--plan", type=Path, help='1つのプラン（配列か {"plan": [...]}）')
    parser.add_argument("--task-set", help="--plan の課題セット（P1・P2・practice）")
    parser.add_argument("--examples", type=Path, help="手で作った例（JSONL）。画面の判定と比べる")
    args = parser.parse_args(argv)
    try:
        tasks = load_tasks(args.tasks)
        catalog = load_course_catalog(args.catalog)
        if args.examples is not None:
            return _check_examples(args.examples, tasks, catalog)
        if args.plan is None or args.task_set not in tasks.task_sets:
            parser.error("--examples か、--plan と --task-set（tasks.json にあるもの）を渡してください")
        score = score_plan(parse_plan(_read_plan_file(args.plan)), tasks.task_sets[args.task_set], catalog)
    except (TasksError, CatalogError, PlanError, OSError, json.JSONDecodeError) as exc:
        print(f"止めました: {exc}", file=sys.stderr)
        return 1
    print(_line(score))
    if score.unknown_courses:
        print(f"スナップショットに無い科目: {', '.join(score.unknown_courses)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
