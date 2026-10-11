"""eval.metrics（採点・集計・仮説判定の純関数）のテスト。DB も LLM も不要。"""

import pytest

from eval.metrics import (
    CONDITIONS,
    GoldenCase,
    QuestionScore,
    RunRecord,
    compare_rates,
    evaluate_hypotheses,
    extract_answer_codes,
    score_question,
    summarize_condition,
)

NEXT_STEP = GoldenCase(
    id="q01",
    question="データサイエンス入門の次に取れる科目は?",
    mode="next_step",
    anchor_code="GMS-301",
    expected_codes=["GMS-303", "GMS-401"],
    forbidden_codes=["GMS-101", "GMS-201"],
)
NO_MODE = GoldenCase(id="q11", question="何かおすすめの授業ある?", mode="unclear")
AMBIGUOUS = GoldenCase(
    id="q14", question="データサイエンスの次は?", mode="unclear", alternatives=["GMS-301", "GMS-401"]
)


# --- score_question -------------------------------------------------------------


def test_extract_answer_codes_normalizes_full_width_and_dedupes():
    answer = "機械学習 [GMS-303] と ＧＭＳ－４０１、再掲 GMS-303。gms-999 は小文字なので拾わない"

    assert extract_answer_codes(answer) == ["GMS-303", "GMS-401"]


def test_search_score_excludes_anchor_and_normalizes_codes():
    """起点科目は precision の分母に入れない。括弧付き・全角のコードも正規化して数える。"""
    score = score_question(NEXT_STEP, ["[GMS-301]", "ＧＭＳ－３０３", "GMS-201"], "回答")

    assert score.scored_codes == ["GMS-303", "GMS-201"]
    assert score.recall == pytest.approx(0.5)
    assert score.precision == pytest.approx(0.5)
    assert score.forbidden_hits == ["GMS-201"]
    assert score.unclear_pass is None


def test_search_score_with_only_anchor_has_undefined_precision():
    score = score_question(NEXT_STEP, ["GMS-301"], "回答")

    assert score.scored_codes == []
    assert score.recall == 0.0
    assert score.precision is None


def test_search_score_perfect():
    score = score_question(NEXT_STEP, ["GMS-401", "GMS-303", "GMS-303"], "回答")

    assert score.recall == 1.0
    assert score.precision == 1.0
    assert score.forbidden_hits == []


def test_uncited_answer_codes_skip_anchor_and_cited():
    answer = "データサイエンス入門 [GMS-301] の次は 機械学習 [GMS-303] と GMS-401 です"

    score = score_question(NEXT_STEP, ["GMS-303"], answer)

    assert score.answer_codes == ["GMS-301", "GMS-303", "GMS-401"]
    assert score.uncited_answer_codes == ["GMS-401"]


@pytest.mark.parametrize(
    ("case", "cited", "expected"),
    [
        (NO_MODE, [], True),
        (NO_MODE, ["GMS-101"], False),
        (AMBIGUOUS, ["GMS-301", "GMS-401"], True),  # 聞き返しの選択肢だけなら合格
        (AMBIGUOUS, ["GMS-301", "GMS-303"], False),  # 選択肢に無い後続科目を出したら不合格
    ],
)
def test_unclear_pass_rule(case: GoldenCase, cited: list[str], expected: bool):
    score = score_question(case, cited, "回答")

    assert score.unclear_pass is expected
    assert score.recall is None
    assert score.precision is None


# --- 集計 ----------------------------------------------------------------------


def _record(
    condition: str,
    case: GoldenCase,
    cited: list[str] | None,
    *,
    llm: int = 0,
    latency_ms: int = 1000,
    unverified: list[str] | None = None,
) -> RunRecord:
    """cited が None なら失敗した実行として作る。"""
    success = cited is not None
    return RunRecord(
        run_id="test",
        condition=condition,
        question_id=case.id,
        mode=case.mode,
        success=success,
        error=None if success else "RuntimeError: 失敗",
        cited_codes=cited or [],
        score=score_question(case, cited, "回答") if success else None,
        unverified_codes=unverified or [],
        llm_requests=llm,
        llm_requests_all_attempts=llm,
        latency_ms=latency_ms,
        started_at="2026-10-11T00:00:00+00:00",
    )


def test_summarize_counts_failures_as_zero_recall_and_unclear_fail():
    cases = {case.id: case for case in (NEXT_STEP, NO_MODE)}
    records = [
        _record("mcp_free", NEXT_STEP, None, llm=3),
        _record("mcp_free", NO_MODE, None, llm=2),
    ]

    summary = summarize_condition("mcp_free", records, cases)

    assert summary.successes == 0
    assert summary.recall_mean == 0.0
    assert summary.precision_mean is None
    assert summary.unclear_pass == 0
    assert summary.llm_requests_total == 5  # 失敗した実行の消費も予算には数える
    assert summary.llm_requests_mean is None  # コストの平均は成功した実行だけ


def test_summarize_mixes_search_and_unclear():
    cases = {case.id: case for case in (NEXT_STEP, NO_MODE)}
    records = [
        _record("static_llm", NEXT_STEP, ["GMS-301", "GMS-303", "GMS-999"], llm=1, latency_ms=3000,
                unverified=["GMS-999"]),
        _record("static_llm", NO_MODE, [], llm=0, latency_ms=100),
    ]

    summary = summarize_condition("static_llm", records, cases)

    assert summary.successes == 2
    assert summary.recall_mean == pytest.approx(0.5)
    assert summary.precision_mean == pytest.approx(0.5)
    assert summary.unverified_total == 1
    assert summary.unverified_questions == 1
    assert summary.unclear_pass == 1
    assert summary.search_llm_requests_mean == 1.0
    assert summary.search_latency_median_s == 3.0
    assert summary.search_latency_mean_s == 3.0
    assert summary.search_tool_calls_mean == 0.0
    assert summary.mcp_preflight_median_s is None  # M1 以外は事前接続しない
    assert summary.latency_median_s == pytest.approx(1.55)


# --- compare_rates -------------------------------------------------------------


def test_compare_rates_labels():
    better = {f"q{i}": 1.0 for i in range(4)}
    worse = {f"q{i}": 0.5 for i in range(4)}

    assert compare_rates(better, worse).label == "差あり"
    assert compare_rates(worse, better).label == "差あり"
    assert compare_rates(better, better).label == "差なし"
    # 平均差は大きいが1問だけの差（符号カウント1）は「差は小さい」
    one_off = {**better, "q0": 0.0}
    assert compare_rates(one_off, better).label == "差は小さい"
    assert compare_rates({"q0": None}, {"q0": 1.0}).label == "比較不能"


def test_compare_rates_ignores_questions_undefined_on_either_side():
    result = compare_rates({"q1": 1.0, "q2": None}, {"q1": 0.0, "q2": 0.0, "q3": 1.0})

    assert result.questions == 1
    assert result.delta_mean == pytest.approx(1.0)
    assert result.sign_margin == 1


# --- 仮説判定 -------------------------------------------------------------------


def _cases() -> dict[str, GoldenCase]:
    return {case.id: case for case in (NEXT_STEP, NO_MODE, AMBIGUOUS)}


def _full_records(*, mcp_unclear_cited: list[str]) -> list[RunRecord]:
    """検索1問 + unclear 2問の小さな集合で、全条件の記録をそろえる。

    mcp_unclear_cited は M1・M2 が q14（ambiguous）で引用するコード。
    """
    perfect = ["GMS-303", "GMS-401"]
    records = []
    for condition in CONDITIONS:
        llm = {"static": 0, "static_llm": 1}.get(condition, 6)
        latency = {"static": 50, "static_llm": 2000}.get(condition, 40000)
        cited = perfect if condition != "mcp_free" else [*perfect, "GMS-201", "GMS-999"]
        records.append(_record(condition, NEXT_STEP, cited, llm=llm, latency_ms=latency,
                               unverified=["GMS-999"] if condition == "mcp_free" else None))
        records.append(_record(condition, NO_MODE, [], llm=llm))
        unclear_cited = mcp_unclear_cited if condition in ("mcp_free", "mcp_grounded") else []
        records.append(_record(condition, AMBIGUOUS, unclear_cited, llm=llm))
    return records


def test_evaluate_hypotheses_on_synthetic_records():
    verdicts = {
        verdict.hypothesis.split(" ", 1)[0]: verdict
        for verdict in evaluate_hypotheses(_full_records(mcp_unclear_cited=["GMS-303"]), _cases())
    }

    assert verdicts["H5"].label == "支持"
    # (a) M2 は unverified 0 件。(b) precision 差は 0.5 だが1問しかないので符号カウント1で満たさない
    assert verdicts["H1"].label == "一部支持"
    assert verdicts["H2"].label == "支持"  # 20倍・6倍
    assert verdicts["H3"].label == "不支持"  # 検索1問で一致1問 < 9
    assert verdicts["H4"].label == "支持"  # S0・S1 は全問合格、M1・M2 は q14 で不合格


def test_h4_not_supported_when_mcp_passes_every_unclear_question():
    verdicts = evaluate_hypotheses(_full_records(mcp_unclear_cited=["GMS-301"]), _cases())

    h4 = next(verdict for verdict in verdicts if verdict.hypothesis.startswith("H4"))
    assert h4.label == "不支持"


def test_evaluate_hypotheses_undecidable_when_runs_missing():
    records = [
        record for record in _full_records(mcp_unclear_cited=[]) if record.condition != "mcp_free"
    ]

    labels = {
        verdict.hypothesis.split(" ", 1)[0]: verdict.label
        for verdict in evaluate_hypotheses(records, _cases())
    }

    assert labels["H5"] == "支持"
    assert labels["H1"] == "判定不能"
    assert labels["H2"] == "判定不能"
    assert labels["H4"] == "判定不能"


def test_question_score_defaults_are_independent():
    """Field(default_factory=...) の既定値が実行間で共有されないこと。"""
    first, second = QuestionScore(), QuestionScore()
    first.forbidden_hits.append("GMS-101")

    assert second.forbidden_hits == []
