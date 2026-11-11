"""Study 1 の下調べ（eval.study1.feasibility）のテスト。実際のエンジンに合成の科目と設定を渡す。DB・LLM 無し。"""

from dataclasses import replace

import pytest

from course_core.diagnose.answers import validate_answers
from course_core.diagnose.engine import DiagnoseEngine, is_candidate
from course_core.diagnose.model import DiagCourse, PlanTerm
from diagnose_fixtures import catalog as engine_catalog
from diagnose_fixtures import config_dict, course, make_config
from eval.study1 import feasibility as fs
from eval.study1.score import Condition, TaskSet, Term, load_tasks, parse_plan, score_plan
from study1_fixtures import P1_INITIAL, course_catalog, course_infos


@pytest.fixture(scope="module")
def tasks():
    return load_tasks()


def _diag_courses() -> dict[str, DiagCourse]:
    """study1_fixtures の科目を診断のエンジンの形にしたもの（名前・学期・曜限・単位は同じ）。"""
    return {
        info.syllabus_id: course(
            info.syllabus_id,
            name=info.name,
            credits=info.credits,
            year_min=info.year_min,
            year_max=info.year_max,
            term=info.term,
            slots=info.slots,
            slot_note=info.slot_note,
            group_id=None,
        )
        for info in course_infos()
    }


def _initial(term: Term) -> list[DiagCourse]:
    courses = _diag_courses()
    return [courses[sid] for t in parse_plan(P1_INITIAL) if t.term == term for sid in t.syllabus_ids]


def _candidates(term: Term) -> list[DiagCourse]:
    engine_term = PlanTerm(year=term.year, term=term.term)
    return [c for c in sorted(_diag_courses().values(), key=lambda c: c.syllabus_id) if is_candidate(c, engine_term)]


def test_min_changes_autumn_moves_adds_and_removes_for_the_add(tasks):
    term = Term(1, "秋")
    solution = fs.min_changes(_initial(term), term, tasks.task_sets["P1"], _candidates(term), course_catalog())
    assert solution is not None
    assert solution.cost == 3
    assert solution.kinds() == {"移す": 1, "足す": 1, "外す": 1}
    assert solution.remove_for_add == 1  # 電磁気学１（木2）を足すために木2 の教養を外す
    steps = {(c.kind, c.syllabus_id) for c in solution.changes}
    assert steps == {("移す", "a05b"), ("足す", "a07"), ("外す", "e03")}


def test_min_changes_spring_and_reference_solution(tasks):
    p1 = tasks.task_sets["P1"]
    spring, autumn = Term(1, "春"), Term(1, "秋")
    solutions = [fs.min_changes(_initial(t), t, p1, _candidates(t), course_catalog()) for t in (spring, autumn)]
    assert solutions[0] is not None and solutions[0].cost == 2 and solutions[0].remove_for_add == 0
    solved = parse_plan(P1_INITIAL)
    for solution in solutions:
        assert solution is not None
        solved = fs.apply_solution(solved, solution)
    assert score_plan(solved, p1, course_catalog()).y == 1


def test_min_changes_is_none_when_a_kept_course_cannot_be_placed(tasks):
    term = Term(1, "秋")
    candidates = [c for c in _candidates(term) if c.name != "物理学実験"]
    initial = [c for c in _initial(term) if c.name != "物理学実験"]
    assert fs.min_changes(initial, term, tasks.task_sets["P1"], candidates, course_catalog()) is None


def _config_with_none() -> dict:
    raw = config_dict()
    raw["questions"][0]["options"].append({"id": "none", "label": "特にない", "effects": []})
    return raw


def test_answer_sets_keep_none_alone_and_sampling_is_fixed():
    config = make_config(_config_with_none())
    sets = dict(fs.answer_sets(config))
    assert sets["interest"][0] == ["none"] and all("none" not in s for s in sets["interest"][1:])
    assert len(sets["interest"]) == 1 + 3 + 3  # none だけ、1つ、2つ（3つの選択肢から）
    assert sets["morning"] == [["ok"], ["avoid"]] and sets["scale"] == [1, 2, 3, 4, 5]
    first, second = fs.sample_answers(config, 50, 7), fs.sample_answers(config, 50, 7)
    assert first == second and fs.sample_answers(config, 50, 8) != first
    assert all(not validate_answers(config, answers)[1] for answers in first)


def test_k5_drops_counts_names_missing_from_the_initial_plan():
    courses = [course("10", name="残る", slots=("火2",)), course("11", name="秋だけ", term="秋", slots=("火3",))]
    config = make_config()
    engine = DiagnoseEngine(config, engine_catalog(courses))
    spring = Term(1, "春")
    keep = Condition(
        id="K5", kind="keep_names", text="", terms=(spring,), names_by_term=((spring, ("残る", "秋だけ")),)
    )
    task_set = TaskSet("T", "", True, ("T-a", "T-b"), {}, (keep,), {})
    samples = fs.sample_answers(config, 20, 1)
    drops = fs.k5_drops(engine, config, task_set, samples)
    assert drops == {"1年春": {"combos": 20, "by_name": {"秋だけ": 20}}}


def test_reference_plan_runs_the_engine():
    courses = [course("10", slots=("火2",)), course("12", term="秋", slots=("水2",))]
    config = make_config()
    engine = DiagnoseEngine(config, engine_catalog(courses))
    plan = fs.reference_plan(engine, config, {"interest": ("adv",), "morning": ("ok",), "scale": 3})
    assert [(t.term.label, t.syllabus_ids) for t in plan] == [("1年春", ("10",)), ("1年秋", ("12",))]
    with pytest.raises(fs.TasksError):
        fs.reference_plan(engine, config, {"interest": ("x",)})


def _report(set_id: str, unmet: int, kinds: list[dict[str, int]], remove_for_add: list[int]) -> fs.CardReport:
    solutions = []
    for index, (counts, extra) in enumerate(zip(kinds, remove_for_add, strict=True)):
        changes = tuple(
            fs.Change(kind, "x", f"{kind}{index}{n}", None, ()) for kind, count in counts.items() for n in range(count)
        )
        solutions.append(fs.TermSolution(Term(1, "春" if index == 0 else "秋"), len(changes), changes, extra))
    return fs.CardReport(set_id, (), {}, unmet, "met", solutions, {"y": 1})


def test_balance_criteria_and_registered_diffs(tasks):
    p1, p2 = tasks.task_sets["P1"], tasks.task_sets["P2"]
    first = _report("P1", 3, [{"移す": 1, "外す": 2}, {"移す": 1, "足す": 1, "外す": 3}], [0, 1])
    second = _report("P2", 3, [{"移す": 1, "外す": 2}, {"移す": 1, "足す": 1, "外す": 3}], [0, 1])
    assert all(row["ok"] for row in fs.balance_criteria(p1, p2, first, second))
    assert fs.registered_diffs(p1, first) == []
    harder = _report("P2", 2, [{"移す": 1, "外す": 4}, {"移す": 1, "足す": 1, "外す": 3}], [0, 0])
    rows = {row["id"]: row["ok"] for row in fs.balance_criteria(p1, p2, first, harder)}
    assert rows == {"基準1": True, "基準2": False, "基準3": False, "基準4": False}
    assert any(d.startswith("unmet_initial") for d in fs.registered_diffs(p2, harder))
    odd = replace(p2, conditions=p2.conditions[:-1])
    assert not fs.balance_criteria(p1, odd, first, second)[0]["ok"]
