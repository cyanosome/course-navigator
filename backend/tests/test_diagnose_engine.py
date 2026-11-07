"""診断のエンジン（primitive・答えの検査・プランの組み立て・理由の文）の純関数のテスト。DB・LLM 無し。"""

import dataclasses

import pytest

from diagnose_fixtures import answers, catalog, config_dict, course, make_config
from course_core.diagnose.answers import answers_digest, validate_answers
from course_core.diagnose.engine import DiagnoseEngine, build_plan, is_candidate, render_template
from course_core.diagnose.model import PlanTerm, reachability
from course_core.diagnose.primitives import PRIMITIVES

SPRING1 = PlanTerm(1, "春")
AUTUMN1 = PlanTerm(1, "秋")


def _primitive(name, **args):
    return PRIMITIVES[name].parse(args)


def _plan(courses, raw_answers=None, raw_config=None, edges=None):
    config = make_config(raw_config)
    selected, errors = validate_answers(config, raw_answers or answers())
    assert errors == []
    data = catalog(courses) if edges is None else catalog(courses, edges=edges)
    return build_plan(config, data, selected)


def _ids(plan):
    return [[course.syllabus_id for course in term.courses] for term in plan.terms]


# --- primitive ---------------------------------------------------------------------------


def test_reachability_includes_self_and_stops_on_cycles():
    reach = reachability(["A", "B", "C", "D"], [("A", "B"), ("B", "C"), ("C", "A")])
    assert reach["A"] == {"A", "B", "C"}
    assert reach["D"] == {"D"}


def test_group_primitives():
    data = catalog([])
    in_b = course("1", group_id="G_B")
    outside = course("2")
    assert _primitive("in_group", groups=["G_A", "G_B"]).value(in_b, SPRING1, data) == 1
    assert _primitive("in_group", groups=["G_A"]).value(in_b, SPRING1, data) == 0
    assert _primitive("reaches_group", target="G_C").value(in_b, SPRING1, data) == 1
    assert _primitive("reaches_group", target="G_B").value(in_b, SPRING1, data) == 1  # 同じまとまりも 1
    assert _primitive("reaches_group", target="G_A").value(in_b, SPRING1, data) == 0  # 線は逆向きにたどらない
    assert _primitive("reaches_group", target="G_C").value(outside, SPRING1, data) == 0
    assert _primitive("reaches_group", target="G_C").details(in_b, SPRING1, data) == {"target": "架空発展系"}
    assert _primitive("on_curriculum").value(in_b, SPRING1, data) == 1
    assert _primitive("on_curriculum").value(outside, SPRING1, data) == 0


def test_year_and_term_fit():
    data = catalog([])
    second_year = course("1", year_min=2, year_max=3, term="秋")
    full_year = course("2", term="通年")
    unknown = course("3", year_min=None, year_max=None, term=None)
    year_fit, term_fit = _primitive("year_fit"), _primitive("term_fit")
    assert year_fit.value(second_year, PlanTerm(2, "秋"), data) == 1
    assert year_fit.value(second_year, SPRING1, data) == 0
    assert year_fit.value(unknown, SPRING1, data) == 0
    assert term_fit.value(second_year, AUTUMN1, data) == 1
    assert term_fit.value(second_year, SPRING1, data) == 0
    assert term_fit.value(full_year, SPRING1, data) == term_fit.value(full_year, AUTUMN1, data) == 1
    assert term_fit.value(unknown, SPRING1, data) == 0


def test_slot_avoid():
    data = catalog([])
    two_slots = course("1", slots=("月2", "水1"))
    no_slot = course("2", slots=(), slot_note="他")
    assert _primitive("slot_avoid", periods=[1]).value(two_slots, SPRING1, data) == 1
    assert _primitive("slot_avoid", days=["月"]).value(two_slots, SPRING1, data) == 1
    assert _primitive("slot_avoid", days=["月"], periods=[1]).value(two_slots, SPRING1, data) == 0
    assert _primitive("slot_avoid", days=["月", "火", "水", "木", "金", "土"]).value(no_slot, SPRING1, data) == 0


def test_keyword_normalizes_and_reads_only_the_given_fields():
    data = catalog([])
    target = course("1", name="反応工学ＩＩ", summary="化学プロセスを学ぶ", goals="設計できる")
    by_name = _primitive("keyword", words=["反応工学ii", "触媒"], fields=["name"])
    assert by_name.value(target, SPRING1, data) == 1  # 全角とローマ字の大小を揃えて比べる
    assert by_name.details(target, SPRING1, data) == {"words": "反応工学ii"}
    both = _primitive("keyword", words=["反応", "プロセス", "触媒"], fields=["name", "summary"])
    assert both.details(target, SPRING1, data) == {"words": "反応・プロセス"}
    assert _primitive("keyword", words=["プロセス"], fields=["name"]).value(target, SPRING1, data) == 0
    assert _primitive("keyword", words=["プロセス"], fields=["summary"]).value(target, SPRING1, data) == 1
    assert _primitive("keyword", words=["設計"], fields=["goals"]).value(target, SPRING1, data) == 1


def test_credits_and_own_department():
    data = catalog([])
    assert _primitive("credits").value(course("1", credits=3.0), SPRING1, data) == 3
    assert _primitive("credits").value(course("2", credits=None), SPRING1, data) == 0
    assert _primitive("own_department").value(course("3", own_department=False), SPRING1, data) == 0
    assert _primitive("own_department").value(course("4"), SPRING1, data) == 1


# --- 答え --------------------------------------------------------------------------------


def test_validate_answers_normalizes_option_order_and_scale5():
    config = make_config()
    selected, errors = validate_answers(config, answers(interest=["word", "adv"], scale=5))
    assert errors == []
    assert selected == {"interest": ("adv", "word"), "morning": ("ok",), "scale": ("s5",)}


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        (answers(extra=["x"]), "知らない質問"),
        ({"interest": ["adv"], "morning": ["ok"]}, "答えていない質問"),
        (answers(interest=["adv", "solo", "word"]), "1〜2 個"),
        (answers(interest=[]), "1〜2 個"),
        (answers(interest=["adv", "adv"]), "2回"),
        (answers(interest=["nope"]), "知らない選択肢"),
        (answers(morning=["ok", "avoid"]), "1つだけ"),
        (answers(morning=3), "配列"),
        (answers(scale=0), "1〜5"),
        (answers(scale=6), "1〜5"),
        (answers(scale=True), "1〜5"),
        (answers(scale=["s1"]), "1〜5"),
    ],
)
def test_validate_answers_errors(raw, fragment):
    selected, errors = validate_answers(make_config(), raw)
    assert any(fragment in error for error in errors), errors


def test_answers_digest_ignores_order():
    first = answers_digest({"interest": ("adv", "word"), "morning": ("ok",)})
    second = answers_digest({"morning": ("ok",), "interest": ("word", "adv")})
    assert first == second
    assert first.startswith("sha256:") and len(first) == len("sha256:") + 64
    assert first != answers_digest({"interest": ("adv",), "morning": ("ok",)})


# --- 候補 --------------------------------------------------------------------------------


def test_is_candidate():
    assert is_candidate(course("1"), SPRING1)
    assert not is_candidate(course("2", term="秋"), SPRING1)
    assert is_candidate(course("3", term="通年"), SPRING1) and is_candidate(course("3", term="通年"), AUTUMN1)
    assert not is_candidate(course("4", term=None), SPRING1)  # 学期の読めない科目（集中など）
    assert not is_candidate(course("5", year_min=2, year_max=4), SPRING1)
    assert not is_candidate(course("6", year_min=None, year_max=None), SPRING1)
    assert not is_candidate(course("7", credits=None), SPRING1)
    assert is_candidate(course("8", slots=(), slot_note="他"), SPRING1)  # 曜限の読めない科目は入れてよい


# --- プランの組み立て ---------------------------------------------------------------------


def test_plan_takes_higher_scores_first_and_never_two_in_one_slot():
    courses = [
        course("10", group_id="G_C", slots=("月1",)),  # 2 + 1
        course("11", group_id="G_A", slots=("月1",)),  # 2 + 1。同点で syllabus_id の後なので月1 は 10 が取る
        course("12", slots=("火1",)),  # 1
    ]
    plan = _plan(courses)
    assert _ids(plan) == [["10", "12"], []]
    assert [course.score for course in plan.terms[0].courses] == [3.0, 1.0]
    assert plan.terms[0].credits_total == 4.0


def test_plan_respects_credit_cap_and_skips_to_smaller_courses():
    courses = [
        course("10", group_id="G_C", credits=4.0, slots=("月1",)),
        course("11", group_id="G_C", credits=4.0, slots=("火1",)),  # 4 + 4 = 8 > 6 なので飛ばす
        course("12", credits=2.0, slots=("水1",)),
        course("13", credits=1.0, slots=("木1",)),  # 6 で上限に達したら止める
    ]
    plan = _plan(courses)
    assert _ids(plan)[0] == ["10", "12"]
    assert plan.terms[0].credits_total == 6.0


def test_plan_without_cap_takes_every_positive_course():
    raw = config_dict()
    raw["scope"]["credit_cap_per_term"] = None
    courses = [course(str(index), slots=(f"月{index}",)) for index in range(1, 6)]
    plan = _plan(courses, raw_config=raw)
    assert _ids(plan)[0] == ["1", "2", "3", "4", "5"]


def test_plan_skips_courses_with_non_positive_scores():
    courses = [course("10", slots=("月1",)), course("11", slots=("火2",))]
    plan = _plan(courses, raw_answers=answers(morning=["avoid"]))  # 月1 は 1 - 3 = -2
    assert _ids(plan)[0] == ["11"]


def test_same_name_is_placed_once_across_terms():
    courses = [
        course("10", name="同名", slots=("月1",)),
        course("11", name="同名", slots=("火1",)),  # 同じ名前の別クラス
        course("12", name="同名", term="秋", slots=("月1",)),
        course("13", term="通年", slots=("水1",)),
    ]
    plan = _plan(courses)
    assert _ids(plan) == [["10", "13"], []]


def test_only_the_top_class_of_a_name_is_considered_in_a_term():
    """同じ名前の別クラスは点の高い1つだけを残す。それが曜限で入らなくても、下のクラスで埋めない。"""
    courses = [
        course("10", group_id="G_C", slots=("月1",)),  # 3 点で月1 を取る
        course("11", name="同名", slots=("月1",)),  # 同名の中で最も上だが月1 が埋まっている
        course("12", name="同名", slots=("火1",)),  # 同名の下のクラスは見ない
        course("13", name="同名", term="秋", slots=("火1",)),  # 前の学期に入っていないので秋は入る
    ]
    plan = _plan(courses)
    assert _ids(plan) == [["10"], ["13"]]


def test_full_year_course_placed_in_spring_also_blocks_its_autumn_slot():
    courses = [
        course("10", term="通年", slots=("金4",)),
        course("11", term="秋", slots=("金4",)),
        course("12", term="秋", slots=("金5",)),
    ]
    plan = _plan(courses)
    assert _ids(plan) == [["10"], ["12"]]


def test_courses_without_slots_block_nothing():
    courses = [course("10", slots=(), slot_note="他"), course("11", slots=("月1",))]
    plan = _plan(courses)
    assert _ids(plan)[0] == ["10", "11"]
    assert plan.terms[0].courses[0].slots == [] and plan.terms[0].courses[0].slot_note == "他"


@pytest.mark.parametrize(
    ("tie_break", "expected"),
    [
        ("syllabus_id", ["10", "11", "12"]),
        ("year_then_syllabus_id", ["12", "10", "11"]),
        ("credits", ["11", "10", "12"]),
    ],
)
def test_tie_break(tie_break, expected):
    raw = config_dict(tie_break=tie_break, scope={"terms": [{"year": 2, "term": "春"}], "credit_cap_per_term": None})
    courses = [
        course("10", year_min=2, slots=("月1",)),
        course("11", year_min=2, credits=3.0, slots=("月2",)),
        course("12", year_min=1, slots=("月3",)),  # year_then_syllabus_id は配当年次の下限の小さい順
    ]
    plan = _plan(courses, raw_config=raw)
    assert _ids(plan)[0] == expected


def test_reasons_come_from_the_largest_positive_contributions():
    courses = [course("10", group_id="G_A", name="反応の基礎", slots=("月1",))]
    plan = _plan(courses, raw_answers=answers(interest=["adv", "word"], morning=["avoid"], scale=5))
    placed = plan.terms[0].courses[0]
    # reaches_group 2・on_curriculum 2・keyword 1・year_fit 1・slot_avoid -3。正の上位2つ（同点は一覧の順）
    assert placed.score == 3.0
    assert [(reason.primitive, reason.text) for reason in placed.reasons] == [
        ("reaches_group", "架空発展系につながる"),
        ("on_curriculum", "系統図に載る"),
    ]


def test_reasons_skip_primitives_without_templates_and_fill_placeholders():
    raw = config_dict()
    del raw["reason_templates"]["reaches_group"]
    plan = _plan([course("10", group_id="G_C")], raw_answers=answers(interest=["adv"]), raw_config=raw)
    assert plan.terms[0].courses[0].reasons == []
    plan = _plan([course("10", group_id="G_D")], raw_answers=answers(interest=["solo"]), raw_config=raw)
    assert [reason.text for reason in plan.terms[0].courses[0].reasons] == ["架空独立系の科目"]


def test_reasons_never_use_year_fit_or_term_fit():
    """year_fit・term_fit は候補の条件と同じ意味なので、base からでも選択肢からでも理由にしない。"""
    raw = config_dict(
        base_effects=[
            {"primitive": "year_fit", "args": {}, "weight": 20},
            {"primitive": "term_fit", "args": {}, "weight": 20},
        ],
        reason_templates={"year_fit": "{year}年に取れる", "term_fit": "{term}に開く", "on_curriculum": "系統図に載る"},
    )
    raw["questions"][2]["options"][4]["effects"].append({"primitive": "year_fit", "args": {}, "weight": 3})
    plan = _plan([course("10", group_id="G_A")], raw_answers=answers(interest=["solo"], scale=5), raw_config=raw)
    placed = plan.terms[0].courses[0]
    assert placed.score == 45.0  # 20 + 20 + 3（選択肢の year_fit）+ 2（on_curriculum）
    assert [(reason.primitive, reason.text) for reason in placed.reasons] == [("on_curriculum", "系統図に載る")]


def test_reasons_use_chosen_options_and_only_curriculum_base_effects():
    """理由に出すのは選んだ選択肢の effect と、base の in_group・reaches_group・on_curriculum だけ。"""
    raw = config_dict(
        base_effects=[
            {"primitive": "year_fit", "args": {}, "weight": 1},
            {"primitive": "on_curriculum", "args": {}, "weight": 8},
            {"primitive": "in_group", "args": {"groups": ["G_B"]}, "weight": 1},
            {"primitive": "reaches_group", "args": {"target": "G_C"}, "weight": 1},
            {"primitive": "keyword", "args": {"words": ["基礎"], "fields": ["name"]}, "weight": 5},
            {"primitive": "own_department", "args": {}, "weight": 4},
        ],
        reason_templates={
            "on_curriculum": "系統図に載る",
            "in_group": "{group}の科目",
            "reaches_group": "{target}につながる",
            "keyword": "「{words}」と答えた",
            "own_department": "学科の科目",
        },
    )
    courses = [
        course("10", group_id="G_B", name="架空の基礎", slots=("月1",)),
        course("11", name="架空の基礎と反応", slots=("火1",)),
        course("12", name="架空の基礎演習", slots=("水1",)),
    ]
    plan = _plan(courses, raw_answers=answers(interest=["solo"]), raw_config=raw)
    by_id = {placed.syllabus_id: placed for placed in plan.terms[0].courses}
    # base の on_curriculum 8・in_group 1・reaches_group 1 は理由になる。base の keyword 5・own_department 4 はならない
    assert [reason.primitive for reason in by_id["10"].reasons] == ["on_curriculum", "in_group"]
    assert by_id["10"].score == 1 + 8 + 1 + 1 + 5 + 4
    # 「反応」は選んでいない選択肢（word）の語。base の keyword だけで入った科目には理由が無い
    assert by_id["11"].reasons == [] and by_id["12"].reasons == []
    plan = _plan(courses, raw_answers=answers(interest=["word"]), raw_config=raw)
    by_id = {placed.syllabus_id: placed for placed in plan.terms[0].courses}
    # 選んだ選択肢の keyword の語だけを差し込む（base の keyword の「基礎」は入らない）
    assert [reason.text for reason in by_id["11"].reasons] == ["「反応」と答えた"]
    assert by_id["12"].reasons == []


def test_plan_is_deterministic_and_ignores_answer_order():
    courses = [
        course(str(index), group_id=("G_A", "G_B", None)[index % 3], slots=(f"{'月火水'[index % 3]}{index % 5 + 1}",))
        for index in range(30)
    ]
    first = _plan(courses, raw_answers=answers(interest=["adv", "word"]))
    second = _plan(list(reversed(courses)), raw_answers=answers(interest=["word", "adv"]))
    assert first.model_dump() == second.model_dump()
    assert first.config_version == "test-1"


def test_render_template_fills_known_placeholders_and_empties_unknown_ones():
    values = {"group": "架空基礎系", "target": "架空発展系", "year": "1", "term": "春", "words": "反応", "credits": "2"}
    assert render_template("{group}から{target}へ（{year}年{term}・{credits}単位・{words}）", values) == (
        "架空基礎系から架空発展系へ（1年春・2単位・反応）"
    )
    assert render_template("{name}{0}{group.x}{words!r:>5}を扱う", values) == "反応を扱う"
    assert render_template(" {target} ", {}) == ""


def test_engine_reuses_values_across_answers():
    config = make_config()
    engine = DiagnoseEngine(config, catalog([course("10", group_id="G_A")]))
    selected, _ = validate_answers(config, answers())
    assert engine.plan(selected) == engine.plan(selected)


def test_engine_refuses_other_department():
    other = dataclasses.replace(catalog([]), department_id="other")
    with pytest.raises(ValueError):
        DiagnoseEngine(make_config(), other)
