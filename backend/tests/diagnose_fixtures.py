"""診断のテストで使う架空の科目・系統図・設定（tests/catalog_rows.py と同じく tests の下の部品）。

系統図: G_A（1年）→ G_B（2年）→ G_C（3年）、G_D はどこにもつながらない。データはすべて架空。
"""

import copy
from typing import Any

from course_core.diagnose.config import DiagnoseConfig, parse_config, validate_config
from course_core.diagnose.model import Catalog, DiagCourse, GroupInfo, normalize_text

DEPT = "kansai-enechem-2026"
GROUPS = (
    GroupInfo("G_A", "架空基礎系", 1),
    GroupInfo("G_B", "架空応用系", 2),
    GroupInfo("G_C", "架空発展系", 3),
    GroupInfo("G_D", "架空独立系", 1),
)
EDGES = (("G_A", "G_B"), ("G_B", "G_C"))
GROUP_IDS = frozenset(group.group_id for group in GROUPS)


def course(syllabus_id: str, **overrides: Any) -> DiagCourse:
    name = overrides.pop("name", f"架空の科目{syllabus_id}")
    summary = overrides.pop("summary", "")
    goals = overrides.pop("goals", "")
    values: dict[str, Any] = {
        "syllabus_id": syllabus_id,
        "name": name,
        "credits": 2.0,
        "year_min": 1,
        "year_max": 4,
        "term": "春",
        "slots": ("月1",),
        "slot_note": None,
        "group_id": None,
        "own_department": True,
        "texts": {"name": normalize_text(name), "summary": normalize_text(summary), "goals": normalize_text(goals)},
    }
    values.update(overrides)
    return DiagCourse(**values)


def catalog(courses: list[DiagCourse], *, edges: tuple[tuple[str, str], ...] = EDGES) -> Catalog:
    return Catalog.build(department_id=DEPT, data_version="test", courses=courses, groups=GROUPS, edges=edges)


_BASE_CONFIG: dict[str, Any] = {
    "version": "test-1",
    "department_id": DEPT,
    "scope": {"terms": [{"year": 1, "term": "春"}, {"year": 1, "term": "秋"}], "credit_cap_per_term": 6},
    "questions": [
        {
            "id": "interest",
            "text": "気になる分野は？",
            "kind": "multi",
            "max_select": 2,
            "options": [
                {"id": "adv", "label": "発展", "effects": [{"primitive": "reaches_group", "args": {"target": "G_C"}, "weight": 2}]},
                {"id": "solo", "label": "独立", "effects": [{"primitive": "in_group", "args": {"groups": ["G_D"]}, "weight": 2}]},
                {
                    "id": "word",
                    "label": "語",
                    "effects": [{"primitive": "keyword", "args": {"words": ["反応"], "fields": ["name", "summary"]}, "weight": 1}],
                },
            ],
        },
        {
            "id": "morning",
            "text": "1限は？",
            "kind": "single",
            "options": [
                {"id": "ok", "label": "平気", "effects": []},
                {"id": "avoid", "label": "避けたい", "effects": [{"primitive": "slot_avoid", "args": {"periods": [1]}, "weight": -3}]},
            ],
        },
        {
            "id": "scale",
            "text": "専門を多めに？",
            "kind": "scale5",
            "options": [
                {"id": f"s{point}", "label": f"{point}", "effects": [{"primitive": "on_curriculum", "args": {}, "weight": point - 3}]}
                for point in range(1, 6)
            ],
        },
    ],
    "base_effects": [{"primitive": "year_fit", "args": {}, "weight": 1}],
    "tie_break": "syllabus_id",
    "reason_templates": {
        "reaches_group": "{target}につながる",
        "in_group": "{group}の科目",
        "keyword": "「{words}」を扱う",
        "year_fit": "{year}年{term}に取れる",
        "on_curriculum": "系統図に載る",
    },
}


def config_dict(**overrides: Any) -> dict[str, Any]:
    """検査を通る架空の設定（JSON の形）。上書きは最上位の項目だけ。"""
    raw = copy.deepcopy(_BASE_CONFIG)
    raw.update(copy.deepcopy(overrides))
    return raw


def make_config(raw: dict[str, Any] | None = None) -> DiagnoseConfig:
    raw = config_dict() if raw is None else raw
    issues = validate_config(raw, department_id=DEPT, known_groups=GROUP_IDS)
    assert issues == [], issues
    return parse_config(raw)


def answers(**overrides: Any) -> dict[str, Any]:
    """どの質問にも答えた架空の答え（API の形）。"""
    values: dict[str, Any] = {"interest": ["adv"], "morning": ["ok"], "scale": 3}
    values.update(overrides)
    return values
