"""変種の表（course_core/research/variants.py）と制約の検査のテスト。

_APPENDIX_A は設計 ab-variants.md の付録 A の JSON の写しに、11/7 の決定で足した因子 F20 diagnose と V30・V31
（表の版 2。事前登録 Study 1 の 2.1）を重ねたもの。コードの表と食い違えばここで落ちる。
_FRONTEND_DIGESTS は frontend（f3c866a）の devResearch.ts の devVariantOut の旗に variant.ts の flagsDigest をかけた値。
"""

import json
from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from course_core.research import settings, variants
from course_core.research.variants import (
    VARIANTS,
    VariantConstraintError,
    VariantFlags,
    build_flags,
    embedding_violations,
    human_study_violations,
    study_ai_edges_violations,
    task_set_violations,
    validate_flags,
)

_APPENDIX_A = json.loads(
    """
{
  "flags_version": "2",
  "base": {
    "search": "kw", "graph": "on", "recommend": "reach", "assistant": "on",
    "ai_route": "mcp_grounded", "verify": "on", "citations": "cards", "first_suggestion": "rule",
    "style": "standard", "timetable": "on", "detail": "full", "question_frame": "composed",
    "toolset": "reused", "rule_edges": "official_all", "ai_edges": "official", "model": "default",
    "retrieval": "agent_tools", "similar_panel": "off", "requirements": "shown", "diagnose": "off"
  },
  "ai_off": {"assistant": "off", "ai_route": null, "verify": null, "citations": null, "style": null,
             "question_frame": null, "toolset": null, "model": null, "ai_edges": null, "retrieval": null},
  "variants": {
    "V00": {},
    "V01": {"$ai_off": true},
    "V02": {"$ai_off": true, "graph": "off", "recommend": "off", "first_suggestion": "none"},
    "V03": {"graph": "off", "recommend": "off", "first_suggestion": "none"},
    "V04": {"$ai_off": true, "recommend": "off", "first_suggestion": "none"},
    "V05": {"$ai_off": true, "recommend": "catalog"},
    "V06": {"$ai_off": true, "recommend": "reach_seeded"},
    "V07": {"ai_route": "mcp_free"},
    "V08": {"ai_route": "static_llm"},
    "V09": {"ai_route": "static"},
    "V10": {"citations": "text"},
    "V11": {"style": "brief"},
    "V12": {"style": "detailed"},
    "V13": {"first_suggestion": "llm"},
    "V14": {"question_frame": "raw"},
    "V15": {"question_frame": "composed_guardrail"},
    "V16": {"toolset": "per_request"},
    "V17": {"$ai_off": true, "timetable": "off"},
    "V18": {"$ai_off": true, "detail": "core"},
    "V19": {"$ai_off": true, "rule_edges": "official_prereq"},
    "V20": {"$ai_off": true, "rule_edges": "with_inferred"},
    "V21": {"model": "alt"},
    "V22": {"$ai_off": true, "graph": "off", "recommend": "off", "first_suggestion": "none", "search": "kw_filter"},
    "V23": {"verify": "off"},
    "V24": {"$ai_off": true, "search": "off"},
    "V25": {"ai_edges": "with_similar"},
    "V26": {"retrieval": "vector_seed"},
    "V27": {"$ai_off": true, "similar_panel": "on"},
    "V28": {"ai_edges": "with_inferred"},
    "V29": {"$ai_off": true, "requirements": "hidden"},
    "V30": {"$ai_off": true, "diagnose": "quiz"},
    "V31": {"diagnose": "quiz"}
  }
}
"""
)

_ALL_IDS = [f"V{n:02d}" for n in range(32)]
# 凍結までの水準（8 章）だけでできていて、C4・C7 にもかからない変種。
_HUMAN_USABLE = {"V00", "V01", "V02", "V03", "V04", "V29", "V30", "V31"}
# frontend の flagsDigest の値（f3c866a の devVariantOut の旗。node で計算した）
_FRONTEND_DIGESTS = {
    "V00": "fnv1a32:9dceb921",
    "V01": "fnv1a32:ee6dfb25",
    "V30": "fnv1a32:37a1f183",
    "V31": "fnv1a32:ef5b9837",
}


def _with(variant_id: str, **changes: str | None) -> VariantFlags:
    """既存の変種の旗を一部だけ変えたもの（検査をすり抜けた旗を作るため model_copy で）。"""
    return VARIANTS[variant_id].model_copy(update=changes)


# --- 表が付録 A と一致する ----------------------------------------------------------


def test_table_matches_appendix_a():
    assert variants.FLAGS_VERSION == _APPENDIX_A["flags_version"]
    assert dict(variants.BASE_FLAGS) == _APPENDIX_A["base"]
    assert dict(variants.AI_OFF) == _APPENDIX_A["ai_off"]
    assert {key: dict(value) for key, value in variants.VARIANT_DIFFS.items()} == _APPENDIX_A["variants"]


def test_thirty_two_variants_with_names():
    assert sorted(VARIANTS) == _ALL_IDS
    assert sorted(variants.VARIANT_NAMES) == _ALL_IDS
    assert len(set(variants.VARIANT_NAMES.values())) == 32
    assert (variants.VARIANT_NAMES["V30"], variants.VARIANT_NAMES["V31"]) == ("noai_diag", "ai_diag")


def test_flags_have_twenty_fields():
    assert len(VariantFlags.model_fields) == 20
    assert set(VariantFlags.model_fields) == set(_APPENDIX_A["base"])
    assert set(variants.IMPLEMENTED_LEVELS) == set(VariantFlags.model_fields)


@pytest.mark.parametrize("variant_id", _ALL_IDS)
def test_expanded_flags_follow_the_merge_rule(variant_id: str):
    """旗 = base に、$ai_off なら ai_off を重ね、さらに差を重ねたもの（付録 A の規則）。"""
    diff = _APPENDIX_A["variants"][variant_id]
    expected = dict(_APPENDIX_A["base"])
    if diff.get("$ai_off"):
        expected.update(_APPENDIX_A["ai_off"])
    expected.update({key: value for key, value in diff.items() if key != "$ai_off"})
    assert VARIANTS[variant_id].model_dump() == expected


def test_named_variants_from_section_3():
    """3 章の表の言葉どおりの差（代表）。"""
    assert VARIANTS["V01"] == _with("V00", assistant="off", **{name: None for name in variants.AI_FLAG_NAMES})
    assert VARIANTS["V02"] == _with("V01", graph="off", recommend="off", first_suggestion="none")
    assert VARIANTS["V03"] == _with("V00", graph="off", recommend="off", first_suggestion="none")
    assert VARIANTS["V22"] == _with("V02", search="kw_filter")
    assert VARIANTS["V30"] == _with("V01", diagnose="quiz")
    assert VARIANTS["V31"] == _with("V00", diagnose="quiz")
    assert all(flags.diagnose == "off" for variant_id, flags in VARIANTS.items() if variant_id not in {"V30", "V31"})


def test_diag_variants_differ_only_in_the_ai_flags():
    """診断のみ（V30）と診断＋対話（V31）の差は assistant と AI の旗9つだけ（事前登録 Study 1 の 2.1）。"""
    v30, v31 = VARIANTS["V30"].model_dump(), VARIANTS["V31"].model_dump()
    assert {name for name in v30 if v30[name] != v31[name]} == {"assistant", *variants.AI_FLAG_NAMES}


def _fnv1a32(flags: Mapping[str, str | None]) -> str:
    """frontend/src/navi/variant.ts の flagsDigest と同じ計算（キー順・空白なしの JSON の UTF-8 に FNV-1a 32 ビット）。"""
    value = 0x811C9DC5
    for byte in json.dumps(dict(flags), sort_keys=True, separators=(",", ":")).encode("utf-8"):
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"fnv1a32:{value:08x}"


@pytest.mark.parametrize(("variant_id", "digest"), sorted(_FRONTEND_DIGESTS.items()))
def test_flags_digest_matches_frontend(variant_id: str, digest: str):
    """表の版 2 の旗の全量（diagnose を含む）の指紋が、frontend の開発用の表で計算した値と一致する。"""
    assert _fnv1a32(VARIANTS[variant_id].model_dump()) == digest


# --- 制約 C1〜C11 -----------------------------------------------------------------


@pytest.mark.parametrize("variant_id", _ALL_IDS)
def test_all_variants_satisfy_structural_constraints(variant_id: str):
    validate_flags(VARIANTS[variant_id], variant_id)


@pytest.mark.parametrize(
    ("variant_id", "changes", "code"),
    [
        ("V00", {"graph": "off"}, "C1"),  # graph=off・recommend=reach
        ("V03", {"recommend": "catalog"}, "C1"),
        ("V02", {"first_suggestion": "rule"}, "C2"),
        ("V01", {"first_suggestion": "llm"}, "C2"),
        ("V01", {"style": "standard"}, "C3"),  # assistant=off なのに AI の旗に値
        ("V00", {"verify": None}, "C3"),  # assistant=on なのに AI の旗が null
        ("V02", {"search": "off"}, "C5"),
    ],
)
def test_broken_combinations_are_rejected(variant_id: str, changes: dict, code: str):
    with pytest.raises(VariantConstraintError) as excinfo:
        validate_flags(_with(variant_id, **changes))
    assert any(message.startswith(code) for message in excinfo.value.violations)


def test_broken_table_fails_on_build():
    """表に壊れた差を入れると、検査を通さずには旗にならない。"""
    flags = build_flags({"graph": "off"})
    with pytest.raises(VariantConstraintError):
        validate_flags(flags, "VXX")


def test_unknown_flag_and_value_are_rejected():
    with pytest.raises(ValidationError):
        build_flags({"colour": "red"})
    with pytest.raises(ValidationError):
        build_flags({"search": "fulltext"})


def test_flags_are_immutable():
    with pytest.raises(ValidationError):
        VARIANTS["V00"].graph = "off"  # type: ignore[misc]


def test_human_study_usable_variants():
    usable = {variant_id for variant_id, flags in VARIANTS.items() if not human_study_violations(flags)}
    assert usable == _HUMAN_USABLE


@pytest.mark.parametrize(
    ("variant_id", "code"),
    [("V08", "C4"), ("V23", "C4"), ("V20", "C7"), ("V28", "C7"), ("V17", "C11"), ("V07", "C11")],
)
def test_human_study_violations_name_the_constraint(variant_id: str, code: str):
    assert any(message.startswith(code) for message in human_study_violations(VARIANTS[variant_id]))


def test_task_set_c6():
    assert task_set_violations(VARIANTS["V18"], has_grading_task=True)
    assert not task_set_violations(VARIANTS["V18"], has_grading_task=False)
    assert not task_set_violations(VARIANTS["V01"], has_grading_task=True)


def test_study_ai_edges_c8():
    # 分岐 A・B の腕（V00・V01・V02）は ai_edges が official か null でそろう。
    assert not study_ai_edges_violations([VARIANTS[v] for v in ("V00", "V01", "V02")], human_study=True)
    mixed = [VARIANTS["V00"], VARIANTS["V25"]]
    assert study_ai_edges_violations(mixed, human_study=False)
    assert study_ai_edges_violations([VARIANTS["V25"]], human_study=True)
    assert not study_ai_edges_violations([VARIANTS["V25"]], human_study=False)


def test_embedding_c9():
    assert not embedding_violations(VARIANTS["V00"], [])
    for variant_id in ("V25", "V26", "V27"):
        flags = VARIANTS[variant_id]
        assert embedding_violations(flags, [])
        assert embedding_violations(flags, [variants.MOCK_EMBEDDING_MODEL, "text-embedding-004"])
        assert not embedding_violations(flags, ["text-embedding-004"])


# --- 設定値 -----------------------------------------------------------------------


def test_default_variant_setting(monkeypatch):
    monkeypatch.delenv("NAVI_DEFAULT_VARIANT", raising=False)
    assert settings.default_variant_id() == "V01"
    monkeypatch.setenv("NAVI_DEFAULT_VARIANT", "V00")
    assert settings.default_variant_id() == "V00"
    monkeypatch.setenv("NAVI_DEFAULT_VARIANT", "V99")
    with pytest.raises(ValueError):
        settings.default_variant_id()


def test_research_dev_setting(monkeypatch):
    monkeypatch.delenv("RESEARCH_DEV", raising=False)
    assert settings.research_dev() is False
    monkeypatch.setenv("RESEARCH_DEV", "true")
    assert settings.research_dev() is True
    monkeypatch.setenv("RESEARCH_DEV", "0")
    assert settings.research_dev() is False


def test_research_data_dir_setting(monkeypatch, tmp_path):
    monkeypatch.setenv("RESEARCH_DATA_DIR", str(tmp_path))
    assert settings.research_data_dir() == tmp_path
    monkeypatch.delenv("RESEARCH_DATA_DIR")
    default = settings.research_data_dir()
    assert default.parts[-2:] == ("logs", "research")
    assert (default.parent.parent / "seed" / "courses.json").is_file()


def test_app_commit_setting(monkeypatch):
    monkeypatch.delenv("APP_COMMIT", raising=False)
    assert settings.app_commit() is None
    monkeypatch.setenv("APP_COMMIT", "abc1234")
    assert settings.app_commit() == "abc1234"
