"""Study 1 の採点（eval.study1.score・catalog_snapshot・tasks.json）のテスト。DB・LLM 無し。科目は合成。"""

import json
from dataclasses import replace

import pytest

from eval.study1 import score as sc
from eval.study1.catalog_snapshot import CatalogError, CourseInfo, catalog_from_dict, load_course_catalog
from study1_fixtures import (
    P1_INITIAL,
    P1_SOLVED,
    P2_INITIAL,
    P2_SOLVED,
    catalog_json,
    course_catalog,
    plan,
    write_catalog,
)

# 事前登録 3.1 の「守ること」の科目（1年春8・1年秋6）
KEEP_SPRING = ["化学工学量論及び演習", "入門エネルギー環境学", "物理を学ぶ（力学１）", "基礎からの情報処理", "線形代数１",
               "情報処理演習", "化学を学ぶ（基礎化学）", "フレッシュマンゼミナール"]  # fmt: skip
KEEP_AUTUMN = ["プロセス量論及び演習", "無機化学", "線形代数２", "入門化学結合論", "化学実験", "物理学実験"]


@pytest.fixture(scope="module")
def tasks() -> sc.Tasks:
    return sc.load_tasks()


@pytest.fixture(scope="module")
def catalog():
    return course_catalog()


def _statuses(score: sc.Score) -> dict[str, str]:
    return {r.id: r.status for r in score.results}


# --- tasks.json --------------------------------------------------------------------------------


def test_tasks_json_matches_the_preregistration(tasks):
    p1, p2, practice = tasks.task_sets["P1"], tasks.task_sets["P2"], tasks.task_sets["practice"]
    assert tasks.config_version == "2026-11-07-2"
    assert [c.id for c in p1.conditions] == ["K1", "K2", "K3", "K4", "K5", "K6"]
    assert [c.kind for c in p1.conditions] == [c.kind for c in p2.conditions]
    for task_set in (p1, p2):
        keep = next(c for c in task_set.conditions if c.kind == "keep_names")
        assert dict(keep.names_by_term) == {sc.Term(1, "春"): tuple(KEEP_SPRING), sc.Term(1, "秋"): tuple(KEEP_AUTUMN)}
        k1 = task_set.conditions[0]
        assert k1.terms == (sc.Term(3, "春"), sc.Term(3, "秋"))
        assert all(
            c.terms == (sc.Term(1, "春"), sc.Term(1, "秋"))
            for c in task_set.conditions[1:]
            if c.kind not in ("has_name",)
        )
        assert task_set.registered["min_changes"] == 8
    assert p1.conditions[0].groups == ("G_3Y_MatEnergy",) and p1.conditions[0].min == 4
    assert p2.conditions[0].groups == ("G_3Y_OrgCatal",) and p2.conditions[0].min == 3
    assert p1.conditions[1].days == ("月",) and p1.conditions[1].periods == ()
    assert p2.conditions[1].days == ("火",) and p2.conditions[1].periods == (3, 4, 5)
    assert p1.conditions[3].name == "物理を学ぶ（電磁気学１）" and p2.conditions[3].name == "基礎からの数学２"
    assert p1.conditions[3].terms == (sc.Term(1, "秋"),)
    assert p1.reference_answers["freeday"] == ("mon",) and p2.reference_answers["future"] == ("organic",)
    assert not practice.scored and [c.kind for c in practice.conditions] == ["free_slot", "credits"]
    assert (
        tasks.task_set_of("P2-b") is p2 and tasks.task_set_of("practice") is practice and tasks.task_set_of("X") is None
    )


def test_load_tasks_lists_every_problem(tmp_path):
    raw = json.loads(sc.TASKS_PATH.read_text(encoding="utf-8"))
    raw["task_sets"]["P1"]["conditions"][0]["min"] = 0
    raw["task_sets"]["P2"]["conditions"][1]["days"] = ["月曜"]
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(sc.TasksError) as excinfo:
        sc.load_tasks(path)
    assert "min が1以上の整数でない" in str(excinfo.value) and "days が曜日の配列でない" in str(excinfo.value)


# --- 採点 -------------------------------------------------------------------------------------------


def test_initial_and_solved_plans(tasks, catalog):
    for set_id, initial, solved in (("P1", P1_INITIAL, P1_SOLVED), ("P2", P2_INITIAL, P2_SOLVED)):
        score0 = sc.score_plan(sc.parse_plan(initial), tasks.task_sets[set_id], catalog)
        assert _statuses(score0) == {"K1": "met", "K2": "unmet", "K3": "unmet", "K4": "unmet", "K5": "met", "K6": "met"}
        assert (score0.y, score0.a) == (0, 0.5)
        score1 = sc.score_plan(sc.parse_plan(solved), tasks.task_sets[set_id], catalog)
        assert (score1.y, score1.a, score1.unknown) == (1, 1.0, 0), score1.as_dict()


def test_free_slot_whole_day_and_periods(tasks, catalog):
    p1, p2 = tasks.task_sets["P1"], tasks.task_sets["P2"]
    monday = sc.parse_plan(plan(y1s=["s04"]))  # 月1
    assert _statuses(sc.score_plan(monday, p1, catalog))["K2"] == "unmet"
    assert _statuses(sc.score_plan(monday, p2, catalog))["K2"] == "met"
    tuesday3 = sc.parse_plan(plan(y1s=["s03"], y1a=["a02"]))  # 火3・火2
    result = next(r for r in sc.score_plan(tuesday3, p2, catalog).results if r.id == "K2")
    assert result.status == "unmet" and result.codes == ("s03",) and "1年春の火3" in result.reason
    other = sc.parse_plan(plan(y1s=["e05"]))  # 曜限「他」はかからない
    assert _statuses(sc.score_plan(other, p1, catalog))["K2"] == "met"
    later = sc.parse_plan(plan(y3s=["g1"]))  # 採点しない学期の月曜はかからない
    assert _statuses(sc.score_plan(later, p1, catalog))["K2"] == "met"


def test_credits_range_and_unknown_courses(tasks, catalog):
    p1 = tasks.task_sets["P1"]
    spring17 = ["s01", "s02", "s03b", "s04b", "s05", "s06", "s07", "s08", "e02"]
    autumn17 = ["a01", "a02", "a03", "a04", "a05b", "a06", "a07", "e04", "e06"]
    assert _statuses(sc.score_plan(sc.parse_plan(plan(y1s=spring17, y1a=autumn17)), p1, catalog))["K3"] == "met"
    low = sc.parse_plan(plan(y1s=spring17[:-2], y1a=autumn17))  # 1年春 14 単位
    assert _statuses(sc.score_plan(low, p1, catalog))["K3"] == "unmet"
    # 下限に届かず、単位の分からない科目（スナップショットに無い）があれば判定できない
    unknown = sc.parse_plan(plan(y1s=[*spring17[:-2], "zz"], y1a=autumn17))
    score = sc.score_plan(unknown, p1, catalog)
    assert _statuses(score)["K3"] == "unknown" and score.unknown_courses == ("zz",)
    # 上限を超えていれば、分からない科目があっても満たさない
    high = sc.parse_plan(plan(y1s=[*spring17, "e01", "zz"], y1a=autumn17))
    assert _statuses(sc.score_plan(high, p1, catalog))["K3"] == "unmet"


def test_full_year_course_counts_in_both_halves(tasks, catalog):
    practice = tasks.task_sets["practice"]
    base = ["s01", "s02", "s03b", "s04b", "s05", "s06", "s07", "s08", "e01", "e02"]  # 19 単位
    assert _statuses(sc.score_plan(sc.parse_plan(plan(y1s=base)), practice, catalog))["C2"] == "met"  # 20 単位まで
    in_autumn = sc.parse_plan(plan(y1s=base, y1a=["y1"]))  # 通年 2 単位を1年秋に置いても1年春に数える（21 単位）
    result = next(r for r in sc.score_plan(in_autumn, practice, catalog).results if r.id == "C2")
    assert result.status == "unmet" and "1年春 21単位" in result.reason


def test_names_ignore_class_and_k4_needs_the_term(tasks, catalog):
    p1 = tasks.task_sets["P1"]
    autumn = ["a01", "a02", "a03", "a04", "a05b", "a06", "a07"]
    assert _statuses(sc.score_plan(sc.parse_plan(plan(y1a=autumn)), p1, catalog))["K4"] == "met"
    spring_only = sc.parse_plan(plan(y1s=["a07"], y1a=autumn[:-1]))  # 1年春に置いても K4 は満たさない
    assert _statuses(sc.score_plan(spring_only, p1, catalog))["K4"] == "unmet"
    keep = sc.parse_plan(plan(y1s=["s01", "s02", "s03", "s04b", "s05", "s06", "s07", "s08"], y1a=autumn))
    assert _statuses(sc.score_plan(keep, p1, catalog))["K5"] == "met"
    missing = sc.parse_plan(plan(y1s=["s01", "s02", "s03", "s05", "s06", "s07", "s08"], y1a=autumn))
    result = next(r for r in sc.score_plan(missing, p1, catalog).results if r.id == "K5")
    assert result.status == "unmet" and "基礎からの情報処理" in result.reason


def test_overlap_and_group_count(tasks, catalog):
    p1, p2 = tasks.task_sets["P1"], tasks.task_sets["P2"]
    clash = sc.parse_plan(plan(y1a=["a07", "e03"]))  # 両方 木2
    result = next(r for r in sc.score_plan(clash, p1, catalog).results if r.id == "K6")
    assert result.status == "unmet" and set(result.codes) == {"a07", "e03"}
    assert _statuses(sc.score_plan(sc.parse_plan(plan(y3s=["g1", "g2"], y3a=["g3"])), p1, catalog))["K1"] == "unmet"
    # 採点する学期（3年）の外のまとまりの科目は数えない
    outside = sc.parse_plan(plan(y2s=["g1"], y3s=["g2"], y3a=["g3", "g4"]))
    assert _statuses(sc.score_plan(outside, p1, catalog))["K1"] == "unmet"
    assert _statuses(sc.score_plan(sc.parse_plan(plan(y3s=["o1"], y3a=["o2", "o3"])), p2, catalog))["K1"] == "met"


def test_class_moved_off_the_graph_counts_in_its_group(tasks, catalog):
    """系統図に無い別クラス（g1b）へ移しても、同じ名前の系統図の科目（g1）のまとまりで K1 に数える（画面と同じ）。"""
    p1 = tasks.task_sets["P1"]
    assert catalog.get("g1b").group_id is None and catalog.group_of(catalog.get("g1b")) == "G_3Y_MatEnergy"
    moved = sc.parse_plan(plan(y3s=["g1b", "g2"], y3a=["g3", "g4"]))
    result = next(r for r in sc.score_plan(moved, p1, catalog).results if r.id == "K1")
    assert result.status == "met" and "g1b" in result.codes
    other = sc.parse_plan(plan(y3s=["e01", "g2"], y3a=["g3", "g4"]))  # 名前の違う科目は数えない
    assert _statuses(sc.score_plan(other, p1, catalog))["K1"] == "unmet"


def test_payload_course_attributes_override_the_snapshot(tasks, catalog):
    p1 = tasks.task_sets["P1"]
    value = plan(y1s=["s04"])
    value[0]["courses"] = [
        {"syllabus_id": "s04", "name": "基礎からの情報処理", "credits": 2, "slots": ["金1"], "group_id": None}
    ]
    assert _statuses(sc.score_plan(sc.parse_plan(value), p1, catalog))["K2"] == "met"


def test_parse_plan_rejects_bad_shapes():
    with pytest.raises(sc.PlanError):
        sc.parse_plan({"year": 1})
    with pytest.raises(sc.PlanError):
        sc.parse_plan([{"year": 1, "term": "夏", "syllabus_ids": []}])
    with pytest.raises(sc.PlanError):
        sc.parse_plan(plan(y1s=["a"]) + plan(y1s=["b"]))


def test_plan_edits_follow_the_screen():
    value = sc.parse_plan(plan(y1s=["s04"], y1a=["a05"]))
    moved = sc.move_course(value, "a05", "a05b")
    assert sc.plan_payload(moved)[1]["syllabus_ids"] == ["a05b"]
    added = sc.add_course(value, "g1", sc.Term(3, "春"))
    assert sc.plan_payload(added)[-1] == {"year": 3, "term": "春", "syllabus_ids": ["g1"]}
    assert sc.add_course(value, "s04", sc.Term(1, "秋")) == value  # もう入っていれば変えない
    assert sc.plan_payload(sc.remove_course(value, "s04"))[0]["syllabus_ids"] == []
    info = CourseInfo("x", "x", 2.0, 1, 4, "秋", (), None, None)
    assert sc.default_place(info) == sc.Term(1, "秋")
    assert sc.default_place(replace(info, term="通年")) == sc.Term(1, "春")


# --- スナップショット ---------------------------------------------------------------------------------


def test_catalog_formats_and_fingerprint(tmp_path):
    data = catalog_json()
    catalog = catalog_from_dict(data, source="t")
    assert catalog.get("s01").name == "化学工学量論及び演習"
    diag = {**data, "format": "diag-catalog-v1"}
    del diag["fingerprint"]
    diag["courses"] = [{**c, "own_department": True, "texts": {"name": c["name"]}} for c in data["courses"]]
    assert catalog_from_dict(diag, source="d").fingerprint == catalog.fingerprint
    broken = {**data, "courses": [*data["courses"][:-1], {**data["courses"][-1], "name": "書き換え"}]}
    with pytest.raises(CatalogError, match="指紋"):
        catalog_from_dict(broken, source="b")
    bad = {**data, "courses": [{"syllabus_id": "x"}]}
    with pytest.raises(CatalogError, match="読めない科目の行が 1 件"):
        catalog_from_dict(bad, source="b")
    assert load_course_catalog(write_catalog(tmp_path / "c.json")).fingerprint == catalog.fingerprint


def test_examples_cli_reports_mismatch(tmp_path, capsys):
    catalog_path = write_catalog(tmp_path / "c.json")
    rows = [
        {"id": "ok", "task_set": "P1", "plan": P1_INITIAL, "screen": {"K2": "unmet", "K3": "unmet", "K6": "met"}},
        {"id": "ng", "task_set": "P1", "plan": P1_SOLVED, "screen": {"K3": "unmet"}},
    ]
    examples = tmp_path / "ex.jsonl"
    examples.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    assert sc.main(["--catalog", str(catalog_path), "--examples", str(examples)]) == 1
    out = capsys.readouterr().out
    assert "ok P1" in out and "一致" in out and "K3: 採点 met / 画面 unmet" in out
    examples.write_text(json.dumps(rows[0], ensure_ascii=False) + "\n", encoding="utf-8")
    assert sc.main(["--catalog", str(catalog_path), "--examples", str(examples)]) == 0
