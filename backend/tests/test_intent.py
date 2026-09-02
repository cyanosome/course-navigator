"""意図パーサのテスト（設計書 実験3-2 §8.3 の A1 / A10）。DB も LLM も不要。

A1: golden 14問すべてで mode / anchor_code / anchor_status / unclear_kind が一致する。
A10: 応答してはいけない質問（q11〜q14）で科目を1件も提示しない。
"""

import json
from pathlib import Path

import pytest

from agent.intent_rules import parse_intent

_GOLDEN_RELATIVE = Path("tests") / "golden" / "questions.json"


def _load_golden() -> list[dict]:
    """golden セットは backend/tests/golden/questions.json の1箇所だけ（§5.3）。"""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _GOLDEN_RELATIVE
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"{_GOLDEN_RELATIVE} が見つかりません。")


GOLDEN = _load_golden()
UNCLEAR_IDS = ("q11", "q12", "q13", "q14")


def _ids(cases: list[dict]) -> list[str]:
    return [case["id"] for case in cases]


def test_golden_set_is_complete() -> None:
    """golden が14問そろっていること（減っていたら A1 の分母が黙って縮む）。"""
    assert len(GOLDEN) == 14
    assert _ids(GOLDEN) == [f"q{i:02d}" for i in range(1, 15)]


@pytest.mark.parametrize("case", GOLDEN, ids=_ids(GOLDEN))
def test_mode_and_anchor(case: dict) -> None:
    """A1: 14問すべてで mode / anchor / anchor_status / unclear_kind が golden と一致。"""
    intent = parse_intent(case["question"])

    assert intent.mode == case["mode"]
    assert intent.anchor_code == case["anchor_code"]
    assert intent.anchor_status == case["anchor_status"]
    assert intent.unclear_kind == case["unclear_kind"]
    assert intent.alternatives == case["alternatives"]
    assert intent.raw_question == case["question"]
    # matched_rule はトレース用。空だと外れた質問の原因追跡ができない。
    assert intent.matched_rule != ""


@pytest.mark.parametrize(
    ("question", "expected_code"),
    [
        ("GMS-301 の次に取れる科目は?", "GMS-301"),  # コード直書き
        ("gms301 の次に取れる科目は?", "GMS-301"),  # 小文字・ハイフンなし
        ("ＧＭＳ－３０１ の次に取れる科目は?", "GMS-301"),  # 全角英数（NFKC）
    ],
)
def test_code_normalization(question: str, expected_code: str) -> None:
    """段0: 表記ゆれを正準化してからカタログに当てる。"""
    intent = parse_intent(question)

    assert intent.anchor_code == expected_code
    assert intent.anchor_status == "exact"


@pytest.mark.parametrize(
    "question",
    [
        "データサイエンス入門の次に取れる科目は?",
        "でーたさいえんす入門の次に取れる科目は?",  # ひらがな・長音のゆれ
        "「データ サイエンス入門」の次に取れる科目は?",  # 空白・かぎ括弧の除去
    ],
)
def test_title_normalization(question: str) -> None:
    """normalize() がひらがな・長音のゆれを吸収して同じアンカーに解決する。"""
    intent = parse_intent(question)

    assert intent.anchor_code == "GMS-301"
    assert intent.anchor_status == "exact"


def test_unknown_code_is_not_found() -> None:
    """存在しないコードは別科目に当てず not_found に倒す（サイレントな取り違えの禁止）。"""
    intent = parse_intent("GMS-999 の前提科目は?")

    assert intent.mode == "unclear"
    assert intent.unclear_kind == "not_found"
    assert intent.anchor_code is None


@pytest.mark.parametrize(
    "case", [c for c in GOLDEN if c["id"] in UNCLEAR_IDS], ids=list(UNCLEAR_IDS)
)
def test_no_speculation(case: dict) -> None:
    """A10 の純関数部分: q11〜q14 は科目を1件も提示しない。

    候補提示の入口は anchor_code と alternatives の2つしかないので、
    anchor_code が None であること・alternatives が ambiguous のときだけ埋まることを見る。
    """
    intent = parse_intent(case["question"])

    assert intent.mode == "unclear"
    assert intent.anchor_code is None
    assert intent.anchor_title is None
    if intent.anchor_status == "ambiguous":
        # 聞き返しのための候補提示なので、コード昇順・最大3件に収まっていること。
        assert intent.alternatives == sorted(intent.alternatives)
        assert len(intent.alternatives) <= 3
    else:
        assert intent.alternatives == []


def test_parse_intent_is_deterministic() -> None:
    """同じ質問を2回投げて完全一致すること（A4 の前提になる決定論性）。"""
    for case in GOLDEN:
        assert parse_intent(case["question"]) == parse_intent(case["question"])
