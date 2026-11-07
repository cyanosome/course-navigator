"""データの API の写像と検索の純関数（course_core/catalog）のテスト。データはすべて架空。"""

from decimal import Decimal

import pytest

from course_core.catalog import mapping, registry
from course_core.catalog.search import (
    CourseFilter,
    QueryTooLongError,
    filter_and_sort,
    ilike_pattern,
    split_query,
)
from catalog_rows import course_row, graduation_row
from course_core.schemas.catalog import CourseSummary, Instructor


# --- 1つずつの規則（api-contract.md 2.7 の表） ------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("１〜４年次", (1, 4, "1〜4年次")),
        ("２年次", (2, 2, "2年次")),
        ("３・４年次", (3, 4, "3・4年次")),
        ("3~4年次", (3, 4, "3~4年次")),
        ("３－４年次", (3, 4, "3-4年次")),
        ("年次指定なし", (None, None, "年次指定なし")),
        ("", (None, None, None)),
        (None, (None, None, None)),
    ],
)
def test_parse_year_range(raw, expected):
    assert mapping.parse_year_range(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("春", "春"), ("秋", "秋"), ("通年", "通年"), (" 春 ", "春"), ("春学期", None), ("集中", None), (None, None)],
)
def test_parse_term(raw, expected):
    assert mapping.parse_term(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("火2", (["火2"], None)),
        ("月1・月2", (["月1", "月2"], None)),
        ("月１", (["月1"], None)),
        ("水3,水3", (["水3"], None)),
        ("集中", ([], "集中")),
        ("", ([], None)),
        (None, ([], None)),
    ],
)
def test_parse_slots(raw, expected):
    assert mapping.parse_slots(raw) == expected


def test_to_float_credits():
    assert mapping.to_float_credits(Decimal("2.0")) == 2.0
    assert mapping.to_float_credits(Decimal("0.5")) == 0.5
    assert mapping.to_float_credits(None) is None


def test_primary_teacher():
    first = Instructor(name="A", is_primary=False)
    primary = Instructor(name="B", is_primary=True)
    assert mapping.primary_teacher([first, primary]) == "B"
    assert mapping.primary_teacher([first]) == "A"
    assert mapping.primary_teacher([]) is None


def test_lead_text_cuts_like_truncate_text():
    assert mapping.lead_text(None) == ""
    assert mapping.lead_text("短い") == "短い"
    assert mapping.lead_text("あ" * 120) == "あ" * 120
    assert mapping.lead_text("あ" * 121) == "あ" * 120 + "…"


@pytest.mark.parametrize(
    ("label", "meta_name", "expected"),
    [
        ("【物理化学系グループ】", None, "物理化学系"),
        ("【物理化学系グループ】", "物理化学", "物理化学"),
        ("【初年次教育】", None, "初年次教育"),
        ("グループ", None, "グループ"),
    ],
)
def test_group_display_name(label, meta_name, expected):
    assert mapping.group_display_name(label, meta_name) == expected


def test_parse_kind_rejects_unknown_values():
    assert mapping.parse_kind(None, "900001") is None
    assert mapping.parse_kind("elective_required", "900001") == "elective_required"
    with pytest.raises(ValueError, match="900001"):
        mapping.parse_kind("optional", "900001")


# --- 行 → 応答の型 ------------------------------------------------------------------------


def test_course_summary_from_row():
    summary = mapping.course_summary_from_row(course_row(kind="required"), group_id="G_X")
    assert summary.model_dump() == {
        "syllabus_id": "900001",
        "course_code": "X00001",
        "name": "架空の反応工学１",
        "subtitle": None,
        "group_id": "G_X",
        "year_min": 1,
        "year_max": 4,
        "year_range": "1〜4年次",
        "term": "春",
        "term_raw": "春",
        "slots": ["火2"],
        "slot_note": None,
        "credits": 2.0,
        "faculties": ["環", "化"],
        "teacher": "架空 花子",
        "lead": "あ" * 120 + "…",
        "kind": "required",
        "detail_url": "https://example.invalid/900001",
    }


def test_course_summary_keeps_unreadable_values_as_raw():
    summary = mapping.course_summary_from_row(
        course_row(semester="集中", term_schedule="その他", year_range=None, instructors="[]", faculties=None, credits=None),
        group_id=None,
    )
    assert (summary.term, summary.term_raw) == (None, "集中")
    assert (summary.slots, summary.slot_note) == ([], "その他")
    assert (summary.year_min, summary.year_max, summary.year_range) == (None, None, None)
    assert summary.teacher is None
    assert summary.faculties == []
    assert summary.credits is None


def test_course_summary_accepts_decoded_jsonb():
    """プールに JSON の型の変換を入れた場合（リストで届く）も同じ結果。"""
    row = course_row(instructors=[{"name": "架空 次郎", "is_primary": True}])
    assert mapping.course_summary_from_row(row, group_id=None).teacher == "架空 次郎"


@pytest.mark.parametrize(
    "instructors",
    ['{"name": "x"}', "[1, 2]", '[{"code": "1"}]', "not json"],
)
def test_broken_jsonb_raises_with_syllabus_id(instructors):
    with pytest.raises(ValueError, match="900001"):
        mapping.course_summary_from_row(course_row(instructors=instructors), group_id=None)


def test_course_detail_from_row_without_bulletin():
    detail = mapping.course_detail_from_row(course_row(), group_id=None)
    assert detail.academic_year == 2026
    assert [item.model_dump() for item in detail.schedule] == [{"number": 1, "topic": "導入"}]
    assert [item.name for item in detail.instructors] == ["架空 一郎", "架空 花子"]
    assert detail.textbooks == ["架空の教科書"]
    assert detail.references == []
    assert detail.bulletin is None
    assert detail.kind is None
    assert detail.source == "postgres:courses"


def test_course_detail_from_row_with_bulletin():
    row = course_row(
        kind="elective_required",
        cr_subject_name_bulletin="架空の反応工学Ⅰ",
        cr_credits=Decimal("2.0"),
        cr_assigned_year=2,
        cr_bulletin_code="CEE9",
        cr_field_category=None,
    )
    detail = mapping.course_detail_from_row(row, group_id="G_X")
    assert detail.kind == "elective_required"
    assert detail.bulletin is not None
    assert detail.bulletin.model_dump() == {
        "subject_name_bulletin": "架空の反応工学Ⅰ",
        "requirement_type": "elective_required",
        "credits": 2.0,
        "assigned_year": 2,
        "bulletin_code": "CEE9",
        "field_category": None,
    }


def test_graduation_requirements_from_row():
    requirements = mapping.graduation_requirements_from_row(graduation_row())
    assert requirements.total_credits == 124.0
    assert [(b.key, b.credits) for b in requirements.buckets] == [
        ("general_education", 10.0),
        ("general_designated", 6.0),
        ("foreign_language", 8.0),
        ("foreign_lang_first", 6.0),
        ("foreign_lang_second", 2.0),
        ("major", 90.0),
        ("major_required", 40.0),
        ("major_elective_required", 20.0),
    ]
    assert all(bucket.label for bucket in requirements.buckets)
    assert requirements.thesis.mandatory_courses_completed == ["架空の実験"]
    assert requirements.rules_notes == ["架空の注記"]
    assert requirements.term_cap is None


def test_graduation_requirements_rejects_broken_thesis():
    with pytest.raises(ValueError, match="2099_fictional"):
        mapping.graduation_requirements_from_row(graduation_row(thesis_requirements='{"x": 1}'))


# --- 検索の純関数 -----------------------------------------------------------------------------


def test_split_query():
    assert split_query(None) == []
    assert split_query("  ") == []
    assert split_query("反応　工学 反応") == ["反応", "工学"]  # 全角空白でも切り、重複は1つ
    with pytest.raises(QueryTooLongError):
        split_query("a b c d e f")
    with pytest.raises(QueryTooLongError):
        split_query("あ" * 101)


def test_ilike_pattern_escapes_wildcards():
    assert ilike_pattern("反応") == "%反応%"
    assert ilike_pattern("100%") == "%100\\%%"
    assert ilike_pattern("a_b") == "%a\\_b%"
    assert ilike_pattern("a\\b") == "%a\\\\b%"


def _summary(syllabus_id, name, **overrides) -> CourseSummary:
    data = mapping.course_summary_from_row(
        course_row(syllabus_id=syllabus_id, subject_name=name), group_id=None
    ).model_dump()
    data.update(overrides)
    return CourseSummary(**data)


def test_filter_and_sort_puts_name_matches_first_then_syllabus_id():
    courses = [
        _summary("900003", "架空の熱力学"),  # 概要だけに当たった科目
        _summary("900002", "架空の反応工学２"),
        _summary("900001", "架空の反応工学１"),
    ]
    ordered = filter_and_sort(courses, CourseFilter(), ["反応"])
    assert [c.syllabus_id for c in ordered] == ["900001", "900002", "900003"]
    assert [c.syllabus_id for c in filter_and_sort(courses, CourseFilter(), [])] == ["900001", "900002", "900003"]
    # 大文字小文字を区別しない
    latin = [_summary("900005", "Fictional A"), _summary("900004", "other")]
    assert [c.syllabus_id for c in filter_and_sort(latin, CourseFilter(), ["fictional"])] == ["900005", "900004"]


def test_filter_and_sort_filters():
    courses = [
        _summary("900001", "A", year_min=1, year_max=1, term="春", slots=["月1"], group_id="G1", kind="required"),
        _summary("900002", "B", year_min=2, year_max=4, term="秋", slots=["火2", "火3"], group_id="G2", kind=None),
        _summary("900003", "C", year_min=None, year_max=None, term=None, slots=[], group_id=None, kind="elective"),
    ]

    def ids(flt):
        return [c.syllabus_id for c in filter_and_sort(courses, flt, [])]

    assert ids(CourseFilter(year=3)) == ["900002"]
    assert ids(CourseFilter(year=1)) == ["900001"]
    assert ids(CourseFilter(term="秋")) == ["900002"]
    assert ids(CourseFilter(slots=frozenset({"火3", "月1"}))) == ["900001", "900002"]
    assert ids(CourseFilter(groups=frozenset({"G2"}))) == ["900002"]
    assert ids(CourseFilter(kinds=frozenset({"required", "elective"}))) == ["900001", "900003"]
    assert ids(CourseFilter(year=2, term="春")) == []


# --- 学科の登録 -------------------------------------------------------------------------------


def test_registry_has_one_department_with_meta():
    departments = registry.load_departments()
    assert list(departments) == ["kansai-enechem-2026"]
    department = departments["kansai-enechem-2026"]
    assert (department.pg.academic_year, department.pg.faculty_code, department.pg.department_code) == (
        2026,
        "320",
        "031",
    )
    meta = registry.load_group_meta("kansai-enechem-2026")
    assert isinstance(meta, registry.GroupMeta)


def test_registry_refuses_unknown_department_meta():
    with pytest.raises(KeyError):
        registry.load_group_meta("../departments")
