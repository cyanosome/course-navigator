"""診断の採点の道具（eval.diag_metrics）のテスト。DB・LLM 無し。データは tests/diagnose_fixtures.py の架空のもの。"""

import json

import pytest

from diagnose_fixtures import catalog, config_dict, course, make_config
from eval import diag_metrics as dm


def _md(*blocks: str) -> str:
    return "# 応募作\n\n説明の文。\n\n" + "\n\n".join(blocks) + "\n\n## 弱点\n- なし\n"


def _courses():
    return [
        course("10", group_id="G_A", name="架空の反応", slots=("月1",)),
        course("11", group_id="G_D", slots=("火1",)),
        course("12", slots=("水1",)),
        course("13", term="秋", group_id="G_C", slots=("月1",)),
        course("14", term="秋", slots=("火1",)),
    ]


# --- 取り出し ----------------------------------------------------------------------------


def test_extract_takes_the_json_block_as_is():
    body = json.dumps(config_dict(), ensure_ascii=False, indent=2)
    text, issues = dm.extract_config_text(_md("```python\nprint(1)\n```", f"```json\n{body}\n```"))
    assert issues == []
    assert text == body


def test_extract_falls_back_to_untagged_blocks_and_tilde_fences():
    text, issues = dm.extract_config_text(_md("```\n形の説明\n```", '~~~\n{"a": 1}\n~~~'))
    assert (text, issues) == ('{"a": 1}', [])


def test_extract_without_block_is_one_json_issue():
    text, issues = dm.extract_config_text(_md("```text\n{}\n```"))
    assert text is None
    assert [issue.kind for issue in issues] == ["json"]


def test_extract_with_two_json_blocks_uses_the_first_and_counts_one_issue():
    text, issues = dm.extract_config_text(_md('```json\n{"a": 1}\n```', '```JSON\n{"b": 2}\n```'))
    assert text == '{"a": 1}'
    assert [issue.kind for issue in issues] == ["shape"]


def test_extract_unclosed_block_runs_to_the_end():
    text, _ = dm.extract_config_text('前置き\n```json\n{"a": 1}\n')
    assert text == '{"a": 1}'


# --- 答えの組み合わせ ----------------------------------------------------------------------


def test_answer_choices_per_kind():
    config = make_config()
    multi, single, scale = config.questions
    assert dm.answer_choices(multi) == [("adv",), ("solo",), ("word",), ("adv", "solo"), ("adv", "word"), ("solo", "word")]
    assert dm.answer_choices(single) == [("ok",), ("avoid",)]
    assert dm.answer_choices(scale) == [(f"s{point}",) for point in range(1, 6)]


def test_sample_answers_takes_all_when_few():
    answers, total, sampled = dm.sample_answers(make_config())
    assert (len(answers), total, sampled) == (60, 60, False)
    assert answers[0] == {"interest": ("adv",), "morning": ("ok",), "scale": ("s1",)}
    assert answers[1] == {"interest": ("adv",), "morning": ("ok",), "scale": ("s2",)}  # 最後の質問がいちばん速く変わる
    assert len({json.dumps(a, sort_keys=True) for a in answers}) == 60


def test_sample_answers_is_seeded_when_many():
    first, total, sampled = dm.sample_answers(make_config(), max_combos=7, seed=dm.SEED)
    again, _, _ = dm.sample_answers(make_config(), max_combos=7, seed=dm.SEED)
    other, _, _ = dm.sample_answers(make_config(), max_combos=7, seed=1)
    assert (len(first), total, sampled) == (7, 60, True)
    assert first == again
    assert first != other
    every, _, _ = dm.sample_answers(make_config())
    assert all(answer in every for answer in first)


# --- 指標 --------------------------------------------------------------------------------


def test_mean_jaccard_distance():
    a, b, c = frozenset({"1", "2"}), frozenset({"2", "3"}), frozenset({"1", "2"})
    # (a,b) = 1 - 1/3、(a,c) = 0、(b,c) = 1 - 1/3
    assert dm.mean_jaccard_distance([a, b, c]) == pytest.approx((2 / 3 + 0 + 2 / 3) / 3)
    assert dm.mean_jaccard_distance([a]) == 0.0
    assert dm.mean_jaccard_distance([frozenset(), frozenset()]) == 0.0


def test_hhi():
    assert dm.hhi([frozenset({"1", "2"}), frozenset({"1"})]) == pytest.approx((2 / 3) ** 2 + (1 / 3) ** 2)
    assert dm.hhi([frozenset({"1"})] * 5) == 1.0
    assert dm.hhi([frozenset()]) is None


def test_score_config_on_fake_data():
    data = catalog(_courses())
    result = dm.score_config(json.dumps(config_dict()), data, markdown=False)
    assert result["M1"] == {"count": 0, "by_kind": {}, "issues": []}
    assert result["combos"] == {"total": 60, "used": 60, "sampled": False, "seed": dm.SEED, "max": dm.MAX_COMBOS}
    assert 0.0 < result["M2"] < 1.0
    assert 0.0 < result["M3"] <= 1.0
    per_term = result["M4"]["per_term"]
    assert [(row["year"], row["term"]) for row in per_term] == [(1, "春"), (1, "秋")]
    assert all(0.0 <= row["rate"] <= 1.0 for row in per_term)
    assert result["M4"]["mean"] == pytest.approx(sum(row["rate"] for row in per_term) / 2)
    assert result["plans"]["distinct"] >= 2
    assert result["config_version"] == "test-1"


def test_score_config_is_reproducible_and_markdown_gives_the_same_numbers():
    data = catalog(_courses())
    body = json.dumps(config_dict(), ensure_ascii=False, indent=2)
    from_json = dm.score_config(body, data, markdown=False)
    from_md = dm.score_config(_md(f"```json\n{body}\n```"), data, markdown=True)
    assert from_json == from_md


def test_m4_without_cap_counts_three_courses():
    raw = config_dict()
    raw["scope"]["credit_cap_per_term"] = None
    data = catalog([course(str(index), slots=(f"火{index + 1}",)) for index in range(1, 4)])  # 1限を避けても3科目残る
    result = dm.score_config(json.dumps(raw), data, markdown=False)
    spring, autumn = result["M4"]["per_term"]
    assert spring["rate"] == 1.0  # 3科目とも点が正（year_fit +1）
    assert autumn["rate"] == 0.0


def test_score_config_with_errors_skips_the_engine():
    raw = config_dict(tie_break="random")
    raw["base_effects"].append({"primitive": "in_group", "args": {"groups": ["G_GONE"]}, "weight": 1})
    result = dm.score_config(json.dumps(raw), catalog(_courses()), markdown=False)
    assert result["M1"]["count"] == 2
    assert result["M1"]["by_kind"] == {"group": 1, "primitive": 1}
    assert result["M2"] is None and result["M3"] is None and result["M4"] is None
    unreadable = dm.score_config("{", catalog(_courses()), markdown=False)
    assert unreadable["M1"]["count"] == 1 and unreadable["config_version"] is None


def test_plans_sink_keeps_answers_and_plans():
    sink: list = []
    dm.score_config(json.dumps(config_dict()), catalog(_courses()), markdown=False, plans_sink=sink)
    assert len(sink) == 60
    assert sink[0]["answers"] == {"interest": ["adv"], "morning": ["ok"], "scale": ["s1"]}
    assert sink[0]["answers_digest"].startswith("sha256:")
    assert [term["term"] for term in sink[0]["terms"]] == ["春", "秋"]


# --- データの保存と入口 ---------------------------------------------------------------------


def test_snapshot_round_trip():
    data = catalog(_courses())
    again = dm.catalog_from_snapshot(json.loads(json.dumps(dm.catalog_to_snapshot(data), ensure_ascii=False)))
    assert again == data
    with pytest.raises(ValueError):
        dm.catalog_from_snapshot({"format": "other"})


def test_main_with_snapshot_writes_table_json_and_plans(tmp_path, capsys):
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(json.dumps(dm.catalog_to_snapshot(catalog(_courses())), ensure_ascii=False), encoding="utf-8")
    good = tmp_path / "good.json"
    good.write_text(json.dumps(config_dict(), ensure_ascii=False), encoding="utf-8")
    entry = tmp_path / "plan.md"
    entry.write_text(_md("```json\n{ 壊れた JSON\n```"), encoding="utf-8")
    out, plans = tmp_path / "out.json", tmp_path / "plans.jsonl"

    code = dm.main([str(good), str(entry), "--snapshot", str(snapshot), "--json-out", str(out), "--plans-out", str(plans), "--git-sha", "abc"])

    assert code == 0
    printed = capsys.readouterr().out
    assert "| good.json | test-1 | 0 |" in printed
    assert "| plan.md | — | 1 |" in printed
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["git_sha"] == "abc"
    assert report["data"]["source"] == "snapshot" and report["data"]["course_count"] == 5
    assert [result["M1"]["count"] for result in report["results"]] == [0, 1]
    assert len(plans.read_text(encoding="utf-8").splitlines()) == 60
