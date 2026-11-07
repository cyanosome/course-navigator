"""DB の行から診断の科目と系統図を作る部分（source）と、その SQL のテスト。実 DB を使わない。データはすべて架空。"""

import asyncio
import re

import pytest

from catalog_rows import course_row
from course_core.catalog.registry import GroupMeta, GroupMetaEntry, load_departments
from course_core.diagnose import source
from course_core.repositories import neo4j_curriculum_repo, postgres_diagnose_repo
from course_core.repositories.neo4j_curriculum_repo import GroupRecord

_DEPT = load_departments()["kansai-enechem-2026"]
_GROUPS = [
    GroupRecord("G_1Y_X", "【架空基礎系グループ】", 1, None, ("900001", "900002")),
    GroupRecord("G_2Y_X", "【架空反応系グループ】", 2, "春", ("900002", "900099")),  # 900002 は先のまとまり、900099 は courses に無い
]
_EDGES = [{"source": "G_1Y_X", "target": "G_2Y_X", "edge_type": "prerequisite", "is_major": True}]


def _row(syllabus_id, **overrides):
    return {**course_row(syllabus_id=syllabus_id, **overrides), "kind": None}


def test_is_own_department_means_only_the_own_faculty():
    assert source.is_own_department(["環"], "環境都市工学部")
    assert not source.is_own_department(["環", "化"], "環境都市工学部")
    assert not source.is_own_department([], "環境都市工学部")
    assert not source.is_own_department(["法", "文"], "環境都市工学部")


@pytest.mark.parametrize(
    ("label", "meta_name", "expected"),
    [
        ("【物理化学系グループ】", None, "物理化学系"),
        ("【共通教養科目グループ】（全学共通プラットフォーム）", None, "共通教養科目"),
        ("【特別研究Ⅰ】（4年春）", None, "特別研究Ⅰ"),
        ("フレッシュマンゼミナール", None, "フレッシュマンゼミナール"),
        ("【物理化学系グループ】", "物化", "物化"),
    ],
)
def test_group_name_fixes_broken_labels(label, meta_name, expected):
    assert source.group_name(label, meta_name) == expected


def test_build_catalog_maps_rows_like_the_course_list():
    rows = [
        _row("900001", subject_name="架空の反応工学１", description="ＡＢＣを学ぶ", objectives="設計できる"),
        _row("900002", semester="夏集", term_schedule="他", faculties=["環"]),
        _row("900003", year_range="３・４年次", term_schedule="月2/水2", objectives=None),
    ]
    meta = GroupMeta(groups={"G_2Y_X": GroupMetaEntry(name="架空の呼び名")})
    data = source.build_catalog(department=_DEPT, rows=rows, groups=_GROUPS, edges=_EDGES, meta=meta)

    first, second, third = data.courses
    assert (first.group_id, second.group_id, third.group_id) == ("G_1Y_X", "G_1Y_X", None)
    assert first.texts == {"name": "架空の反応工学1", "summary": "abcを学ぶ", "goals": "設計できる"}
    assert (first.term, first.slots, first.credits, first.year_min, first.year_max) == ("春", ("火2",), 2.0, 1, 4)
    assert (first.own_department, second.own_department) == (False, True)  # 架空の行の既定は ["環", "化"]
    assert (second.term, second.slots, second.slot_note) == (None, (), "他")
    assert (third.year_min, third.year_max, third.slots, third.texts["goals"]) == (3, 4, ("月2", "水2"), "")
    assert {group_id: group.name for group_id, group in data.groups.items()} == {
        "G_1Y_X": "架空基礎系",
        "G_2Y_X": "架空の呼び名",
    }
    assert data.reach["G_1Y_X"] == {"G_1Y_X", "G_2Y_X"}
    assert data.department_id == _DEPT.id and data.data_version == _DEPT.data_version


def test_load_catalog_reads_all_edge_types(monkeypatch):
    calls = []

    async def fetch_groups(session, faculty, department):
        calls.append(("groups", faculty, department))
        return _GROUPS

    async def fetch_group_edges(session, faculty, department, edge_types):
        calls.append(("edges", tuple(edge_types)))
        return _EDGES

    async def fetch_courses_for_diagnose(conn, academic_year):
        calls.append(("courses", academic_year))
        return [_row("900001")]

    monkeypatch.setattr(neo4j_curriculum_repo, "fetch_groups", fetch_groups)
    monkeypatch.setattr(neo4j_curriculum_repo, "fetch_group_edges", fetch_group_edges)
    monkeypatch.setattr(postgres_diagnose_repo, "fetch_courses_for_diagnose", fetch_courses_for_diagnose)
    data = asyncio.run(source.load_catalog(object(), object(), _DEPT))
    assert [c.syllabus_id for c in data.courses] == ["900001"]
    assert calls == [
        ("groups", "環境都市工学部", "エネルギー環境・化学工学科"),
        ("edges", ("prerequisite", "capstone", "english_track")),
        ("courses", 2026),
    ]


class _RecordingConnection:
    def __init__(self) -> None:
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return []


def test_fetch_courses_for_diagnose_sql_reads_objectives_with_one_parameter():
    conn = _RecordingConnection()
    assert asyncio.run(postgres_diagnose_repo.fetch_courses_for_diagnose(conn, 2026)) == []
    (sql, args), = conn.calls
    assert args == (2026,)
    assert set(re.findall(r"\$(\d+)", sql)) == {"1"}
    assert "c.objectives" in sql and "AS kind" in sql and "c.description" in sql
