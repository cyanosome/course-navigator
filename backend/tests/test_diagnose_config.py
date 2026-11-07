"""診断の設定の読み込みと検査（M1 の数え方）のテスト。DB・LLM 無し。"""

import json
from collections import Counter

import pytest

from diagnose_fixtures import DEPT, GROUP_IDS, config_dict
from course_core.diagnose.config import (
    ConfigError,
    ConfigNotFoundError,
    load_config,
    load_config_text,
    parse_config,
    read_config_text,
    validate_config,
)


def _issues(raw, known_groups=GROUP_IDS):
    return validate_config(raw, department_id=DEPT, known_groups=known_groups)


def _kinds(raw, known_groups=GROUP_IDS):
    return Counter(issue.kind for issue in _issues(raw, known_groups))


def _option_effects(raw, question=0, option=0):
    return raw["questions"][question]["options"][option]["effects"]


def test_valid_config_has_no_issues():
    assert _issues(config_dict()) == []


def test_shipped_config_passes_shape_check():
    """リポに置いた設定（いま有効なもの）は形の検査を通る。まとまり ID は DB のテスト（test_diagnose_db）で見る。"""
    loaded = load_config(DEPT)
    assert loaded.config.version == loaded.raw["version"]
    assert loaded.config.department_id == DEPT
    assert 1 <= len(loaded.config.questions) <= 8


def test_unknown_department_has_no_config():
    with pytest.raises(ConfigNotFoundError):
        load_config("nope")


@pytest.mark.parametrize(
    "text",
    ["{", '{"version": "a", "version": "b"}', '{"x": NaN}', '{"x": 1,}', "// コメント\n{}"],
)
def test_unreadable_json_is_one_json_issue(text):
    raw, issues = read_config_text(text)
    assert raw is None
    assert [issue.kind for issue in issues] == ["json"]


def test_load_config_text_raises_with_all_issues():
    raw = config_dict(tie_break="nope")
    del raw["base_effects"]
    with pytest.raises(ConfigError) as caught:
        load_config_text(json.dumps(raw), department_id=DEPT, source="test")
    assert {issue.path for issue in caught.value.issues} == {"$.base_effects", "tie_break"}


def test_unknown_primitive_counts_once_per_effect():
    raw = config_dict()
    _option_effects(raw).append({"primitive": "similar_to", "args": {}, "weight": 1})
    raw["base_effects"].append({"primitive": "random", "args": {"x": 1}, "weight": 1})
    assert _kinds(raw) == Counter({"primitive": 2})


def test_unknown_group_ids_count_each_and_only_when_groups_are_known():
    raw = config_dict()
    _option_effects(raw)[0]["args"]["target"] = "G_X"
    _option_effects(raw, option=1)[0]["args"]["groups"] = ["G_A", "G_Y", "G_Z"]
    assert _kinds(raw) == Counter({"group": 3})
    assert _issues(raw, known_groups=None) == []


def test_more_than_eight_questions_is_one_issue():
    raw = config_dict()
    base = raw["questions"][1]
    raw["questions"] = [dict(base, id=f"q{index}") for index in range(9)]
    assert _kinds(raw) == Counter({"too_many_questions": 1})
    raw["questions"] = raw["questions"][:8]
    assert _issues(raw) == []


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (lambda raw: raw.pop("tie_break"), "$.tie_break"),
        (lambda raw: raw.update(extra=1), "$.extra"),
        (lambda raw: raw.update(version=""), "version"),
        (lambda raw: raw.update(department_id="other"), "department_id"),
        (lambda raw: raw["scope"].update(credit_cap_per_term=0), "scope.credit_cap_per_term"),
        (lambda raw: raw["scope"]["terms"].append({"year": 1, "term": "春"}), "scope.terms[2]"),
        (lambda raw: raw["scope"]["terms"].append({"year": 5, "term": "春"}), "scope.terms[2].year"),
        (lambda raw: raw["scope"]["terms"].append({"year": 2, "term": "通年"}), "scope.terms[2].term"),
        (lambda raw: raw["questions"][0].pop("max_select"), "questions[0].max_select"),
        (lambda raw: raw["questions"][0].update(max_select=4), "questions[0].max_select"),
        (lambda raw: raw["questions"][1].update(max_select=1), "questions[1].max_select"),
        (lambda raw: raw["questions"][1].update(kind="rank"), "questions[1].kind"),
        (lambda raw: raw["questions"][1].update(id="朝"), "questions[1].id"),
        (lambda raw: raw["questions"][1].update(id="interest"), "questions[1].id"),
        (lambda raw: raw["questions"][1]["options"][1].update(id="ok"), "questions[1].options[1].id"),
        (lambda raw: raw["questions"][1]["options"][0].update(label=" "), "questions[1].options[0].label"),
        (lambda raw: raw["questions"][2]["options"].pop(), "questions[2].options"),
        (lambda raw: _option_effects(raw)[0].update(weight=3.5), "questions[0].options[0].effects[0].weight"),
        (lambda raw: _option_effects(raw)[0].update(weight=True), "questions[0].options[0].effects[0].weight"),
        (lambda raw: _option_effects(raw)[0].pop("args"), "questions[0].options[0].effects[0].args"),
        (lambda raw: _option_effects(raw, question=1, option=1)[0]["args"].update(periods=[0]), "questions[1].options[1].effects[0].args.periods[0]"),
        (lambda raw: _option_effects(raw, question=1, option=1)[0].update(args={}), "questions[1].options[1].effects[0].args"),
        (lambda raw: _option_effects(raw, option=2)[0]["args"].update(fields=["teacher"]), "questions[0].options[2].effects[0].args.fields[0]"),
        (lambda raw: raw["base_effects"][0].update(args={"year": 1}), "base_effects[0].args.year"),
        (lambda raw: raw.update(tie_break="in_group"), "tie_break"),
        (lambda raw: raw["reason_templates"].update(keyword="{words"), "reason_templates.keyword"),
        (lambda raw: raw["reason_templates"].update(keyword="words}"), "reason_templates.keyword"),
        (lambda raw: raw["reason_templates"].update(keyword=""), "reason_templates.keyword"),
    ],
)
def test_shape_violation_is_one_shape_issue(mutate, path):
    raw = config_dict()
    mutate(raw)
    issues = _issues(raw)
    assert [(issue.kind, issue.path) for issue in issues] == [("shape", path)], issues


def test_unknown_tie_break_and_template_keys_are_primitive_issues():
    raw = config_dict(tie_break="random")
    raw["reason_templates"]["similar_to"] = "近い"
    assert sorted((issue.kind, issue.path) for issue in _issues(raw)) == [
        ("primitive", "reason_templates.similar_to"),
        ("primitive", "tie_break"),
    ]


def test_unknown_placeholders_are_not_issues():
    """知らない差し込みは文を作るときに空にする（変更記録 2026-11-07 (3)）。"""
    raw = config_dict()
    raw["reason_templates"].update(keyword="{teacher}の{word}", in_group="{target}{0}{group.x}")
    assert _issues(raw) == []


def test_not_an_object_is_one_issue():
    assert [issue.kind for issue in _issues([1, 2])] == ["shape"]


def test_parse_config_sorts_terms_and_scale5_options():
    raw = config_dict()
    raw["scope"]["terms"] = [{"year": 2, "term": "秋"}, {"year": 1, "term": "秋"}, {"year": 2, "term": "春"}]
    config = parse_config(raw)
    assert [(term.year, term.term) for term in config.terms] == [(1, "秋"), (2, "春"), (2, "秋")]
    assert config.credit_cap_per_term == 6.0
    assert config.question("scale").option_ids() == ("s1", "s2", "s3", "s4", "s5")
    assert config.question("nope") is None
