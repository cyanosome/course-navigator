"""AI の微修正の「選べる科目」と「今のプラン」の文（agent.plan_candidates）の純関数のテスト。DB・LLM 無し。

科目・系統図・設定は tests/diagnose_fixtures.py の架空のもの（設定の埋める学期は1年春・1年秋）。
"""

from diagnose_fixtures import answers, catalog, course, make_config
from agent import plan_candidates
from agent.route_options import PlanTerm
from course_core.diagnose.answers import validate_answers
from course_core.diagnose.engine import DiagnoseEngine


def _context(courses, terms, *, raw_answers=None, summary="架空のまとめ", request_text=""):
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
        request_text=request_text,
    )


def _candidate_ids(context):
    return [[(item.course.syllabus_id, item.source) for item in term.courses] for term in context.candidates]


_COURSES = [
    course("10", name="系統図の科目", group_id="G_A", slots=("月1",)),  # プランにある・系統図に載る
    course("11", name="教養の科目", slots=("火2",), credits=1.0),  # プランにある・系統図に載らない
    course("12", name="系統図の科目", slots=("水1",)),  # プランの 10 と同じ名前の別クラス（移す先）
    course("13", name="足せる科目", group_id="G_B", slots=("木2",)),  # 候補（G_C につながるので点が高い）
    course("14", name="足せる科目その２", slots=("金3",)),  # 候補
    course("15", name="秋の科目", term="秋", slots=()),  # 1年秋の候補（曜限なし）
    course("16", name="3年の科目", year_min=3),  # 1年は取れないので候補でない
    course("17", name="系統図の科目", term="秋", slots=("水1",)),  # 10 と同じ名前だが秋なので、春の移す先ではない
]
_TERMS = [
    {"year": 1, "term": "春", "syllabus_ids": ["10", "11", "999"]},
    {"year": 1, "term": "秋", "syllabus_ids": []},
]


def test_candidates_follow_the_engine_order_and_add_other_classes_of_plan_courses():
    context = _context(_COURSES, _TERMS)

    assert _candidate_ids(context) == [[("13", "top"), ("14", "top"), ("12", "same_name")], [("15", "top")]]
    assert context.candidate_ids == {"12", "13", "14", "15"}
    assert context.plan_ids == ["10", "11", "999"]
    # 点はエンジンの点（13 は G_C につながる +2 と year_fit +1）
    assert [item.score for item in context.candidates[0].courses] == [3.0, 1.0, 1.0]
    # 移す組: プランの 10 → 同じ学期の同じ名前の別クラス 12（秋の 17 は入らない）
    assert context.move_pairs == {"10": {"12"}}
    assert context.source_counts == {"top": 3, "same_name": 1, "named": 0}


def test_top_candidates_are_capped_per_term_and_skip_plan_names():
    courses = [course(f"{index:02d}", name=f"候補{index}", slots=(f"月{index % 5 + 1}",)) for index in range(40)]
    config = make_config()
    selected, _ = validate_answers(config, answers())
    data = catalog(courses)
    terms = [PlanTerm(year=1, term="春", syllabus_ids=["00"])]
    picked = plan_candidates.term_candidates(
        DiagnoseEngine(config, data), selected, terms, {item.syllabus_id: item for item in courses}, limit=5
    )
    assert [item.course.syllabus_id for item in picked[0].courses] == ["01", "02", "03", "04", "05"]
    assert plan_candidates.CANDIDATES_PER_TERM == 30


def test_courses_named_in_the_request_are_added_outside_the_cap():
    courses = [
        course("20", name="上位の科目", group_id="G_B"),
        course("21", name="物理を学ぶ（電磁気学１）", slots=("木2",)),
        course("22", name="物理を学ぶ（電磁気学１）", slots=("水2",)),
        course("23", name="物理を学ぶ（力学１）", slots=("火3",)),  # 括弧の外（物理を学ぶ）だけでは当たらない
        course("24", name="基礎からの数学２", term="秋", slots=("月5",)),
    ]
    config = make_config()
    selected, _ = validate_answers(config, answers())
    data = catalog(courses)
    terms = [PlanTerm(year=1, term="春", syllabus_ids=[]), PlanTerm(year=1, term="秋", syllabus_ids=[])]
    by_id = {item.syllabus_id: item for item in courses}

    picked = plan_candidates.term_candidates(
        DiagnoseEngine(config, data), selected, terms, by_id, "1年秋に「電磁気学1」と基礎からの数学２を入れたい", limit=1
    )

    assert [(item.course.syllabus_id, item.source) for item in picked[0].courses] == [
        ("20", "top"),
        ("21", "named"),
        ("22", "named"),
    ]
    assert [(item.course.syllabus_id, item.source) for item in picked[1].courses] == [("24", "top")]
    # 頼みの文が無ければ named は入らない
    none = plan_candidates.term_candidates(DiagnoseEngine(config, data), selected, terms, by_id, "", limit=1)
    assert [item.source for term in none for item in term.courses] == ["top", "top"]


def test_name_parts():
    assert plan_candidates.name_parts("物理を学ぶ（電磁気学１）") == {"物理を学ぶ(電磁気学1)", "電磁気学1"}
    assert plan_candidates.name_parts("健康・スポーツ科学実習ａ（ソフトボール）") == {
        "健康・スポーツ科学実習a(ソフトボール)",
        "ソフトボール",
    }
    assert plan_candidates.name_parts("英語（Ａ）") == {"英語(a)"}  # 短い括弧の中身は使わない
    assert plan_candidates.name_parts("数学") == frozenset()  # 短すぎる名前は当てない


def test_locked_ids_are_plan_courses_on_the_curriculum_chart():
    context = _context(_COURSES, _TERMS)
    assert context.locked_ids == {"10"}  # 11 はまとまりに属さない、999 は DB に無い


def test_terms_outside_the_engine_get_no_candidates():
    context = _context(_COURSES, [{"year": 2, "term": "春", "syllabus_ids": []}, {"year": 1, "term": "通年", "syllabus_ids": []}])
    assert _candidate_ids(context) == [[], []]
    assert context.candidate_ids == frozenset()
    assert context.source_counts == {"top": 0, "same_name": 0, "named": 0}


def test_source_counts_count_each_course_once_across_terms():
    courses = [course("30", name="通年の科目", term="通年"), course("31", name="プランの科目")]
    context = _context(
        courses,
        [
            {"year": 1, "term": "春", "syllabus_ids": ["31"]},
            {"year": 1, "term": "秋", "syllabus_ids": []},
        ],
    )
    assert _candidate_ids(context) == [[("30", "top")], [("30", "top")]]  # 春にも秋にも出る
    assert context.source_counts == {"top": 1, "same_name": 0, "named": 0}
    assert len(context.candidate_ids) == 1


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
        "- 12 系統図の科目（水1、2単位、点 1）［今のプランの 10 の別クラス。10 を外す案と組にして移すときだけ足せる］",
        "### 1年 秋",
        "- 15 秋の科目（曜限なし、2単位、点 1）",
    ]


def test_block_marks_named_courses():
    block = _context(_COURSES, _TERMS, request_text="「足せる科目その２」を入れたい").block
    # 上位にも入る科目は top のまま（印を付けない）
    assert "- 14 足せる科目その２（金3、2単位、点 1）" in block.splitlines()
    courses = [*_COURSES, *(course(f"4{index}", name=f"上位{index}", group_id="G_B") for index in range(30))]
    named = _context(courses, _TERMS, request_text="「足せる科目その２」を入れたい").block.splitlines()
    assert "- 14 足せる科目その２（金3、2単位、点 1）［頼みに名前が出た科目］" in named


def test_block_without_summary_and_with_full_year_course():
    courses = [course("20", name="通年の科目", term="通年", slots=("月2",))]
    block = _context(courses, [{"year": 1, "term": "春", "syllabus_ids": ["20"]}], summary="  ").block
    assert "診断のまとめ" not in block
    assert "- 20 通年の科目（月2、通年、2単位）" in block.splitlines()
