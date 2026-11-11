"""P1・P2（と練習 C）の下調べを実際のエンジンで数える（事前登録 3.3・3.4・6.3）。

1. 参照の答え（tasks.json の reference_answers。3.2）で初期プランを出し、score.py で条件を当てる（満たさない条件の数）
2. 採点する1年の学期ごとに、すべての条件を満たすのに要る最小の変更（移す・足す・外すをそれぞれ1と数える）を探し、
   参照の解（変更を当てたプラン）が全部の条件を満たすことを score.py で確かめる
3. 3.4 の基準1〜4（条件の型と数が同じ、満たさない条件の数が同じ、最小の変更の数の差が1以下、移す数と足すために
   外す数が同じ）を P1 と P2 で確かめ、tasks.json の registered（下調べの値）と比べる
4. 3.3 の K5 の科目が初期プランから落ちる答えの組の数（答えの組 1,000、種 20261107。抜き方は D-a の模擬と同じで、
   multi の「特にない」（none）は単独、ほかは 1〜max_select 個の組み合わせ。質問の順に random.choice）

最小の変更の探し方（下調べの道具 bi/feasibility.py を移したもの）: 学期ごとに、系統図の科目（K5）は今のクラスのまま・
同じ名前の別クラスへ移す（落ちていれば足す）、K4 の科目は足す（入っていれば今のクラスか別クラス）、ほかの科目は
そのまま・外す・別クラスへ移す、のすべての組み合わせを深さ優先で調べ、今までの最小以上になる枝を切る。別クラスは
その学期にエンジンが入れてよい科目（engine.is_candidate）のうち同じ名前のもの。K6・K2 があれば、曜限が重なる・
空ける曜限にかかる選び方は先へ進めない。最小の組が複数あるときは、この順で最初に見つかったものを出す。
外す科目のうち、足した科目か移した先の科目と曜限が重なるものを「足すために外す」（remove_for_add）に数える。
K1（3年）は初期プランで満たすかだけを見る（満たさなければ、そう出して最小の変更は1年の学期の分だけ）。

DB が要るので、GMS では動いている backend のコンテナの中（/backend_app）で打つ:

    docker compose exec backend uv run --no-sync python -m eval.study1.feasibility --json-out /tmp/study1-feasibility.json

DB を読まずに eval.diag_metrics が保存したデータ（diag-catalog-v1）で流すときは --snapshot snap.json。設定は既定で
リポの configs/<学科>.json（凍結の設定）。--config で別の JSON を渡せる。結果は表を標準出力へ、--json-out に JSON
（参照の答えのプランは科目の ID と名前だけで、人のデータは含まない）。3.4 の基準を1つでも満たさないか、
registered と違えば終了コード 1。
"""

import argparse
import itertools
import random
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from eval.study1.catalog_snapshot import CatalogError, CourseCatalog, course_catalog_from_engine, load_engine_catalog
from eval.study1.files import OutputError, write_private_json
from eval.study1.score import (
    Condition,
    Plan,
    PlanTerm,
    TaskSet,
    Tasks,
    TasksError,
    Term,
    add_course,
    hits_slot,
    load_tasks,
    move_course,
    parse_plan,
    remove_course,
    score_plan,
)

if TYPE_CHECKING:
    from course_core.diagnose.config import DiagnoseConfig
    from course_core.diagnose.engine import DiagnoseEngine
    from course_core.diagnose.model import Catalog, DiagCourse

__all__ = [
    "DROP_SAMPLES",
    "DROP_SEED",
    "Change",
    "TermSolution",
    "answer_sets",
    "balance_criteria",
    "card_report",
    "k5_drops",
    "min_changes",
    "reference_plan",
    "sample_answers",
]

DROP_SEED: Final = 20261107
DROP_SAMPLES: Final = 1000
_NONE_OPTION: Final = "none"
_MOVE: Final = "移す"
_ADD: Final = "足す"
_REMOVE: Final = "外す"
_MAX_CHANGE_GAP: Final = 1  # 3.4 の基準3


@dataclass(frozen=True)
class Change:
    kind: str  # 移す・足す・外す
    name: str
    syllabus_id: str  # 移す・足すは入れる先のクラス、外すは外す科目
    from_id: str | None  # 移すときの元のクラス
    slots: tuple[str, ...]

    def text(self) -> str:
        where = "/".join(self.slots) or "他"
        return f"{self.kind} {self.name} {where}（{self.syllabus_id}）"


@dataclass(frozen=True)
class TermSolution:
    term: Term
    cost: int
    changes: tuple[Change, ...]
    remove_for_add: int

    def kinds(self) -> dict[str, int]:
        counts = Counter(change.kind for change in self.changes)
        return {kind: counts.get(kind, 0) for kind in (_MOVE, _ADD, _REMOVE)}


# --- 最小の変更 ---------------------------------------------------------------------------------


def _term_conditions(task_set: TaskSet, term: Term) -> list[Condition]:
    """その学期だけに絞った条件（group_count は 3年の条件なので除く）。"""
    out: list[Condition] = []
    for condition in task_set.conditions:
        if condition.kind == "group_count" or term not in condition.terms:
            continue
        if condition.kind == "keep_names":
            names = tuple((t, n) for t, n in condition.names_by_term if t == term)
            out.append(replace(condition, terms=(term,), names_by_term=names))
        else:
            out.append(replace(condition, terms=(term,)))
    return out


def _slot_blocked(slots: Sequence[str], conditions: Sequence[Condition]) -> bool:
    """空ける曜限（free_slot）にかかるか（score.py と同じ規則）。"""
    return any(
        hits_slot(slot, condition.days, condition.periods)
        for condition in conditions
        if condition.kind == "free_slot"
        for slot in slots
    )


def min_changes(
    initial: Sequence[DiagCourse],
    term: Term,
    task_set: TaskSet,
    candidates: Sequence[DiagCourse],
    course_catalog: CourseCatalog,
) -> TermSolution | None:
    """学期 term の初期の科目に、すべての条件を満たすための最小の変更。満たせなければ None。"""
    conditions = _term_conditions(task_set, term)
    no_overlap = any(condition.kind == "no_overlap" for condition in conditions)
    keep_names = [name for c in conditions if c.kind == "keep_names" for _, names in c.names_by_term for name in names]
    has_names = [c.name for c in conditions if c.kind == "has_name" and c.name is not None]
    by_name: dict[str, list[DiagCourse]] = {}
    for course in candidates:
        by_name.setdefault(course.name, []).append(course)
    current = {course.name: course for course in initial}

    Option = tuple["DiagCourse | None", int, Change | None]
    items: list[list[Option]] = []
    for name in [*keep_names, *(n for n in has_names if n not in keep_names)]:
        here = current.get(name)
        options: list[Option] = []
        for alt in by_name.get(name, []):
            if here is not None and alt.syllabus_id == here.syllabus_id:
                options.insert(0, (alt, 0, None))
            elif here is not None:
                options.append((alt, 1, Change(_MOVE, name, alt.syllabus_id, here.syllabus_id, alt.slots)))
            else:
                options.append((alt, 1, Change(_ADD, name, alt.syllabus_id, None, alt.slots)))
        items.append(options)
    fixed = set(keep_names) | set(has_names)
    for course in initial:
        if course.name in fixed:
            continue
        options = [(course, 0, None), (None, 1, Change(_REMOVE, course.name, course.syllabus_id, None, course.slots))]
        options += [
            (alt, 1, Change(_MOVE, course.name, alt.syllabus_id, course.syllabus_id, alt.slots))
            for alt in by_name.get(course.name, [])
            if alt.syllabus_id != course.syllabus_id
        ]
        items.append(options)

    task_view = replace(task_set, conditions=tuple(conditions))
    best: list[Any] = [None, ()]

    def satisfied(chosen: Sequence[DiagCourse]) -> bool:
        plan: Plan = (PlanTerm(term, tuple(course.syllabus_id for course in chosen)),)
        return score_plan(plan, task_view, course_catalog).y == 1

    def dfs(index: int, chosen: list[DiagCourse], used: frozenset[str], cost: int, log: tuple[Change, ...]) -> None:
        if best[0] is not None and cost >= best[0]:
            return  # これ以上は今までの最小より小さくならない
        if index == len(items):
            if satisfied(chosen):
                best[0], best[1] = cost, log
            return
        for alt, step, change in items[index]:
            if alt is not None:
                if no_overlap and used.intersection(alt.slots):
                    continue  # 重なる選び方は後で満たせない
                if _slot_blocked(alt.slots, conditions):
                    continue  # 空ける曜限にかかる選び方は後で満たせない
            dfs(
                index + 1,
                chosen + ([alt] if alt is not None else []),
                used | frozenset(alt.slots) if alt is not None else used,
                cost + step,
                log + ((change,) if change is not None else ()),
            )

    dfs(0, [], frozenset(), 0, ())
    if best[0] is None:
        return None
    changes: tuple[Change, ...] = best[1]
    placed_slots = {slot for change in changes if change.kind in (_MOVE, _ADD) for slot in change.slots}
    remove_for_add = sum(change.kind == _REMOVE and bool(placed_slots.intersection(change.slots)) for change in changes)
    return TermSolution(term=term, cost=best[0], changes=changes, remove_for_add=remove_for_add)


def apply_solution(plan: Plan, solution: TermSolution) -> Plan:
    for change in solution.changes:
        if change.kind == _REMOVE:
            plan = remove_course(plan, change.syllabus_id)
        elif change.kind == _MOVE and change.from_id is not None:
            plan = move_course(plan, change.from_id, change.syllabus_id)
        else:
            plan = add_course(plan, change.syllabus_id, solution.term)
    return plan


# --- 参照の答え ---------------------------------------------------------------------------------


def reference_plan(engine: DiagnoseEngine, config: DiagnoseConfig, answers: Mapping[str, Any]) -> Plan:
    """参照の答え（選択肢の id の並び。scale5 は 1〜5 の数）でエンジンが出すプラン。"""
    from course_core.diagnose.answers import validate_answers

    raw = {key: list(value) if isinstance(value, (list, tuple)) else value for key, value in answers.items()}
    checked, errors = validate_answers(config, raw)
    if errors:
        raise TasksError(f"参照の答えが設定 {config.version} で読めません: {'; '.join(errors)}")
    out = engine.plan(checked)
    return parse_plan(
        [{"year": t.year, "term": t.term, "syllabus_ids": [c.syllabus_id for c in t.courses]} for t in out.terms]
    )


@dataclass
class CardReport:
    task_set: str
    initial: Plan
    score: dict[str, Any]
    unmet_initial: int
    k1_initial: str | None
    solutions: list[TermSolution | None]
    solved_score: dict[str, Any] | None
    names: Mapping[str, str] = field(default_factory=dict)

    @property
    def total_changes(self) -> int | None:
        if any(solution is None for solution in self.solutions):
            return None
        return sum(solution.cost for solution in self.solutions if solution is not None)

    def totals(self) -> dict[str, int]:
        out = {_MOVE: 0, _ADD: 0, _REMOVE: 0, "remove_for_add": 0}
        for solution in self.solutions:
            if solution is None:
                continue
            for kind, count in solution.kinds().items():
                out[kind] += count
            out["remove_for_add"] += solution.remove_for_add
        return out

    def as_dict(self) -> dict[str, Any]:
        totals = self.totals()
        return {
            "task_set": self.task_set,
            "initial_plan": [
                {"term": t.term.label, "courses": [[sid, self.names.get(sid, "")] for sid in t.syllabus_ids]}
                for t in self.initial
            ],
            "initial_score": self.score,
            "unmet_initial": self.unmet_initial,
            "k1_initial": self.k1_initial,
            "min_changes": self.total_changes,
            "move": totals[_MOVE],
            "add": totals[_ADD],
            "remove": totals[_REMOVE],
            "remove_for_add": totals["remove_for_add"],
            "terms": [
                None
                if solution is None
                else {
                    "term": solution.term.label,
                    "cost": solution.cost,
                    "kinds": solution.kinds(),
                    "remove_for_add": solution.remove_for_add,
                    "steps": [c.text() for c in solution.changes],
                }
                for solution in self.solutions
            ],
            "reference_solution_score": self.solved_score,
        }


def card_report(
    task_set: TaskSet,
    engine: DiagnoseEngine,
    config: DiagnoseConfig,
    catalog: Catalog,
    course_catalog: CourseCatalog,
) -> CardReport:
    from course_core.diagnose.engine import is_candidate
    from course_core.diagnose.model import PlanTerm as EngineTerm

    initial = reference_plan(engine, config, task_set.reference_answers)
    score = score_plan(initial, task_set, course_catalog)
    k1 = next((r for r in score.results if r.kind == "group_count"), None)
    by_id = {course.syllabus_id: course for course in catalog.courses}
    solutions: list[TermSolution | None] = []
    solved = initial
    for term in task_set.graded_terms:
        if not any(term in c.terms for c in task_set.conditions if c.kind != "group_count"):
            continue  # 3年の学期は K1 だけ（初期プランで満たすかだけを見る）
        engine_term = EngineTerm(year=term.year, term=term.term)
        courses = [by_id[sid] for t in initial if t.term == term for sid in t.syllabus_ids]
        candidates = [course for course in catalog.courses if is_candidate(course, engine_term)]
        solution = min_changes(courses, term, task_set, candidates, course_catalog)
        solutions.append(solution)
        if solution is not None:
            solved = apply_solution(solved, solution)
    solved_score = (
        score_plan(solved, task_set, course_catalog).as_dict() if all(s is not None for s in solutions) else None
    )
    names = {course.syllabus_id: course.name for course in catalog.courses}
    return CardReport(
        task_set=task_set.id,
        initial=initial,
        score=score.as_dict(),
        unmet_initial=score.total - score.met,
        k1_initial=None if k1 is None else k1.status,
        solutions=solutions,
        solved_score=solved_score,
        names=names,
    )


# --- 3.4 の基準 ---------------------------------------------------------------------------------


def balance_criteria(
    first: TaskSet, second: TaskSet, first_report: CardReport, second_report: CardReport
) -> list[dict[str, Any]]:
    """3.4 の基準1〜4。各行に {id, text, values, ok}。"""
    kinds_first = sorted(c.kind for c in first.conditions)
    kinds_second = sorted(c.kind for c in second.conditions)
    total_first, total_second = first_report.total_changes, second_report.total_changes
    t1, t2 = first_report.totals(), second_report.totals()
    gap_ok = total_first is not None and total_second is not None and abs(total_first - total_second) <= _MAX_CHANGE_GAP
    return [
        {
            "id": "基準1",
            "text": "条件の型と数が同じ",
            "values": [kinds_first, kinds_second],
            "ok": kinds_first == kinds_second,
        },
        {
            "id": "基準2",
            "text": "参照の答えの初期プランで満たさない条件の数が同じ",
            "values": [first_report.unmet_initial, second_report.unmet_initial],
            "ok": first_report.unmet_initial == second_report.unmet_initial,
        },
        {"id": "基準3", "text": "最小の変更の数の差が1以下", "values": [total_first, total_second], "ok": gap_ok},
        {
            "id": "基準4",
            "text": "別クラスへ移す数と、足すために外す数が同じ",
            "values": [[t1[_MOVE], t1["remove_for_add"]], [t2[_MOVE], t2["remove_for_add"]]],
            "ok": t1[_MOVE] == t2[_MOVE] and t1["remove_for_add"] == t2["remove_for_add"],
        },
    ]


def registered_diffs(task_set: TaskSet, report: CardReport) -> list[str]:
    """tasks.json の registered（下調べの値）と違う項目。"""
    totals = report.totals()
    now: dict[str, Any] = {
        "unmet_initial": report.unmet_initial,
        "min_changes": report.total_changes,
        "move": totals[_MOVE],
        "add": totals[_ADD],
        "remove": totals[_REMOVE],
        "remove_for_add": totals["remove_for_add"],
    }
    return [
        f"{key}: 下調べ {task_set.registered.get(key)} → 今 {value}"
        for key, value in now.items()
        if task_set.registered.get(key) != value
    ]


# --- K5 の科目が落ちる組 --------------------------------------------------------------------------


def answer_sets(config: DiagnoseConfig) -> list[tuple[str, list[Any]]]:
    """質問ごとの答え方の一覧（D-a の模擬 check.py の all_answer_sets と同じ。multi の none は単独）。scale5 は 1〜5。"""
    per_question: list[tuple[str, list[Any]]] = []
    for question in config.questions:
        ids = list(question.option_ids())
        if question.kind == "multi":
            real = [option_id for option_id in ids if option_id != _NONE_OPTION]
            sets: list[Any] = [[_NONE_OPTION]] if _NONE_OPTION in ids else []
            for size in range(1, (question.max_select or 1) + 1):
                sets += [list(combo) for combo in itertools.combinations(real, size)]
        elif question.kind == "scale5":
            sets = list(range(1, len(ids) + 1))
        else:
            sets = [[option_id] for option_id in ids]
        per_question.append((question.id, sets))
    return per_question


def sample_answers(config: DiagnoseConfig, samples: int = DROP_SAMPLES, seed: int = DROP_SEED) -> list[dict[str, Any]]:
    per_question = answer_sets(config)
    rng = random.Random(seed)
    return [{qid: rng.choice(sets) for qid, sets in per_question} for _ in range(samples)]


def k5_drops(
    engine: DiagnoseEngine, config: DiagnoseConfig, task_set: TaskSet, samples: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """答えの組ごとに、K5（keep_names）の科目が初期プランの同じ学期に無い組の数と、科目ごとの数。"""
    from course_core.diagnose.answers import validate_answers

    keep = [(term, names) for c in task_set.conditions if c.kind == "keep_names" for term, names in c.names_by_term]
    combos = {term.label: 0 for term, _ in keep}
    by_name: dict[str, Counter[str]] = {term.label: Counter() for term, _ in keep}
    for raw in samples:
        answers, errors = validate_answers(config, dict(raw))
        if errors:
            raise TasksError(f"抜いた答えが読めません: {'; '.join(errors)}")
        plan = engine.plan(answers)
        for term, names in keep:
            present = {c.name for t in plan.terms if t.year == term.year and t.term == term.term for c in t.courses}
            missing = [name for name in names if name not in present]
            combos[term.label] += bool(missing)
            by_name[term.label].update(missing)
    return {label: {"combos": combos[label], "by_name": dict(by_name[label])} for label in combos}


# --- 入口 --------------------------------------------------------------------------------------


def _load_config(department_id: str, path: Path | None) -> DiagnoseConfig:
    from course_core.diagnose.config import load_config, load_config_text

    if path is None:
        return load_config(department_id).config
    return load_config_text(path.read_text(encoding="utf-8"), department_id=department_id, source=str(path)).config


def _print_card(report: CardReport, task_set: TaskSet, emit: Callable[[str], None]) -> None:
    k1 = "" if report.k1_initial is None else f"、K1 {report.k1_initial}"
    emit(f"==== {task_set.id}（{task_set.card}）初期プランで満たさない条件 {report.unmet_initial}{k1}")
    for result in report.score["results"]:
        emit(f"  {result['id']} {result['status']}" + (f" {result['reason']}" if result["reason"] else ""))
    for term in report.initial:
        if term.term.year != 1:
            continue
        names = "、".join(report.names.get(sid, sid) for sid in term.syllabus_ids)
        emit(f"  {term.term.label}: {names}")
    for solution in report.solutions:
        if solution is None:
            emit("    満たせない学期がある")
            continue
        emit(
            f"    {solution.term.label} 最小の変更 {solution.cost} {solution.kinds()} 足すために外す {solution.remove_for_add}: "
            + " / ".join(change.text() for change in solution.changes)
        )
    totals = report.totals()
    emit(
        f"  合計 {report.total_changes}（移す {totals[_MOVE]}・足す {totals[_ADD]}・外す {totals[_REMOVE]}、"
        f"足すために外す {totals['remove_for_add']}）。参照の解: "
        + ("全部を満たす" if report.solved_score is not None and report.solved_score["y"] == 1 else "満たさない")
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Study 1 の下調べ（事前登録 3.3・3.4）を実際のエンジンで数える")
    parser.add_argument("--tasks", type=Path, default=None, help="既定はこの道具の隣の tasks.json")
    parser.add_argument(
        "--snapshot",
        type=Path,
        help="DB を読まず diag-catalog-v1 のファイルから（eval.diag_metrics の --save-snapshot）",
    )
    parser.add_argument("--config", type=Path, help="診断の設定の JSON（既定はリポの configs/<学科>.json）")
    parser.add_argument("--json-out", type=Path, help="結果の JSON（リポの外）")
    parser.add_argument("--samples", type=int, default=DROP_SAMPLES)
    parser.add_argument("--seed", type=int, default=DROP_SEED)
    parser.add_argument(
        "--git-sha", default=None, help="実行したコードの commit（コンテナに .git が無いのでホストから渡す）"
    )
    args = parser.parse_args(argv)
    try:
        tasks: Tasks = load_tasks(args.tasks) if args.tasks is not None else load_tasks()
        config = _load_config(tasks.department_id, args.config)
        catalog = load_engine_catalog(tasks.department_id, args.snapshot)
        from course_core.diagnose.engine import DiagnoseEngine

        engine = DiagnoseEngine(config, catalog)
        course_catalog = course_catalog_from_engine(catalog)
        lines: list[str] = []
        emit = lines.append
        emit(
            f"設定 {config.version}（tasks.json は {tasks.config_version}）、データ {catalog.data_version}・科目 {len(catalog.courses)}・"
            f"指紋 {course_catalog.fingerprint}、tasks.json の SHA-256 {tasks.sha256}"
        )
        if config.version != tasks.config_version:
            emit(f"注意: 設定の版 {config.version} が tasks.json の {tasks.config_version} と違います")
        missing_names = sorted(
            {
                n
                for ts in tasks.task_sets.values()
                for c in ts.conditions
                for n in ([c.name] if c.name else []) + [x for _, names in c.names_by_term for x in names]
            }
            - {course.name for course in catalog.courses}
        )
        if missing_names:
            emit(f"注意: tasks.json の科目名のうちデータに無いもの: {'、'.join(missing_names)}")
        reports = {
            set_id: card_report(ts, engine, config, catalog, course_catalog) for set_id, ts in tasks.task_sets.items()
        }
        problems: list[str] = []
        for set_id, report in reports.items():
            _print_card(report, tasks.task_sets[set_id], emit)
            diffs = registered_diffs(tasks.task_sets[set_id], report)
            emit("  下調べの値（registered）と " + ("同じ" if not diffs else "違う: " + "、".join(diffs)))
            problems += [f"{set_id} {d}" for d in diffs]
            if report.solved_score is None or report.solved_score["y"] != 1:
                problems.append(f"{set_id} の参照の解が全部の条件を満たさない")
        criteria = balance_criteria(tasks.task_sets["P1"], tasks.task_sets["P2"], reports["P1"], reports["P2"])
        emit("==== 3.4 の基準（P1・P2）")
        for row in criteria:
            emit(
                f"  {row['id']} {row['text']}: {row['values'][0]} / {row['values'][1]} → {'満たす' if row['ok'] else '満たさない'}"
            )
        problems += [f"3.4 {row['id']} を満たさない" for row in criteria if not row["ok"]]
        samples = sample_answers(config, args.samples, args.seed)
        drops = k5_drops(engine, config, tasks.task_sets["P1"], samples)
        emit(
            f"==== K5 の科目が初期プランから落ちる組（{args.samples} 組、種 {args.seed}）: "
            + "、".join(f"{label} {value['combos']} 組 {value['by_name']}" for label, value in drops.items())
        )
        print("\n".join(lines))
        if missing_names:
            problems.append("tasks.json の科目名がデータに無い")
        if args.json_out is not None:
            digest = write_private_json(
                args.json_out,
                {
                    "git_sha": args.git_sha,
                    "config_version": config.version,
                    "tasks_sha256": tasks.sha256,
                    "data_version": catalog.data_version,
                    "catalog_fingerprint": course_catalog.fingerprint,
                    "course_count": len(catalog.courses),
                    "cards": {set_id: report.as_dict() for set_id, report in reports.items()},
                    "criteria": criteria,
                    "k5_drops": {"samples": args.samples, "seed": args.seed, "terms": drops},
                    "problems": problems,
                },
                "feasibility の結果",
            )
            print(f"JSON: {args.json_out}（SHA-256 {digest}）")
    except (TasksError, CatalogError, OutputError, OSError, ValueError) as exc:
        print(f"止めました: {exc}", file=sys.stderr)
        return 1
    if problems:
        print("問題: " + " / ".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
