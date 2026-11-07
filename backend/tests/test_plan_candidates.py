"""AI の微修正の「選べる科目」と「今のプラン」の文（agent.plan_candidates）の純関数のテスト。DB・LLM 無し。

科目・系統図・設定は tests/diagnose_fixtures.py の架空のもの（設定の埋める学期は1年春・1年秋）。
"""

from diagnose_fixtures import answers, catalog, course, make_config
from agent import plan_candidates
from agent.route_options import PlanTerm
from course_core.diagnose.answers import validate_answers
from course_core.diagnose.engine import DiagnoseEngine


def _context(courses, terms, *, raw_answers=None, summary="架空のまとめ"):
    config = make_config()
    selected, errors = validate_answers(config, raw_answers or answers())
    assert errors == []
    data = catalog(courses)
    return plan_candidates.build_refine_context(
        engine=DiagnoseEngine(config, data),
        catalog=data,
        answers=selected,
        answers_summary=summary,
        terms=[PlanTerm.model_validate(term) for term in terms],
    )


def _candidate_ids(context):
    return [[item.course.syllabus_id for item in term.courses] for term in context.candidates]


_COURSES = [
    course("10", name="系統図の科目", group_id="G_A", slots=("月1",)),  # プランにある・系統図に載る
    course("11", name="教養の科目", slots=("火2",), credits=1.0),  # プランにある・系統図に載らない
    course("12", name="系統図の科目", slots=("水1",)),  # プランの科目と同じ名前の別クラス（候補に出さない）
    course("13", name="足せる科目", group_id="G_B", slots=("木2",)),  # 候補（G_C につながるので点が高い）
    course("14", name="足せる科目その２", slots=("金3",)),  # 候補
    course("15", name="秋の科目", term="秋", slots=()),  # 1年秋の候補（曜限なし）
    course("16", name="3年の科目", year_min=3),  # 1年は取れないので候補でない
]
_TERMS = [
    {"year": 1, "term": "春", "syllabus_ids": ["10", "11", "999"]},
    {"year": 1, "term": "秋", "syllabus_ids": []},
]


def test_candidates_skip_names_in_the_plan_and_follow_the_engine_order():
    context = _context(_COURSES, _TERMS)

    assert _candidate_ids(context) == [["13", "14"], ["15"]]
    assert context.candidate_ids == {"13", "14", "15"}
    assert context.plan_ids == ["10", "11", "999"]
    # 点はエンジンの点（13 は G_C につながる +2 と year_fit +1）
    assert [item.score for item in context.candidates[0].courses] == [3.0, 1.0]


def test_candidates_are_capped_per_term():
    courses = [course(f"{index:02d}", name=f"候補{index}", slots=(f"月{index % 5 + 1}",)) for index in range(40)]
    config = make_config()
    selected, _ = validate_answers(config, answers())
    data = catalog(courses)
    picked = plan_candidates.term_candidates(
        DiagnoseEngine(config, data), selected, [PlanTerm(year=1, term="春")], frozenset({"候補0"}), limit=5
    )
    assert [item.course.syllabus_id for item in picked[0].courses] == ["01", "02", "03", "04", "05"]
    assert plan_candidates.CANDIDATES_PER_TERM == 30


def test_locked_ids_are_plan_courses_on_the_curriculum_chart():
    context = _context(_COURSES, _TERMS)
    assert context.locked_ids == {"10"}  # 11 はまとまりに属さない、999 は DB に無い


def test_terms_outside_the_engine_get_no_candidates():
    context = _context(_COURSES, [{"year": 2, "term": "春", "syllabus_ids": []}, {"year": 1, "term": "通年", "syllabus_ids": []}])
    assert _candidate_ids(context) == [[], []]
    assert context.candidate_ids == frozenset()


def test_block_marks_locked_courses_and_lists_candidates_with_scores():
    lines = _context(_COURSES, _TERMS).block.splitlines()

    assert lines == [
        plan_candidates.PLAN_HEADING,
        "診断のまとめ: 架空のまとめ",
        "### 1年 春（合計 3単位）",  # DB に無い 999 は数えない
        "- 10 系統図の科目（月1、2単位、まとまり: 架空基礎系）" + plan_candidates.LOCK_MARK,
        "- 11 教養の科目（火2、1単位）",
        "- 999（DB に無い syllabus_id）",
        "### 1年 秋（合計 0単位）",
        "- （科目なし）",
        "",
        plan_candidates.CANDIDATES_HEADING,
        "### 1年 春",
        "- 13 足せる科目（木2、2単位、まとまり: 架空応用系、点 3）",
        "- 14 足せる科目その２（金3、2単位、点 1）",
        "### 1年 秋",
        "- 15 秋の科目（曜限なし、2単位、点 1）",
    ]


def test_block_without_summary_and_with_full_year_course():
    courses = [course("20", name="通年の科目", term="通年", slots=("月2",))]
    block = _context(courses, [{"year": 1, "term": "春", "syllabus_ids": ["20"]}], summary="  ").block
    assert "診断のまとめ" not in block
    assert "- 20 通年の科目（月2、通年、2単位）" in block.splitlines()
