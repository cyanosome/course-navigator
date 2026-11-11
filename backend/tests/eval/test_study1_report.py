"""Study 1 の判定と表（eval.study1.report・stats）のテスト。指標は合成。"""

import json
import math
from datetime import datetime, timedelta

import pytest

from eval.study1 import metrics as mt
from eval.study1 import report as rp
from eval.study1 import stats as st
from eval.study1.score import load_tasks
from study1_fixtures import JST, complete_participant, write_catalog, write_events

# 5.4 の表（二択に答えた人数 n → 同じ画面を選んだ人数がこれ以上）
PREREG_THRESHOLDS = {6: 6, 7: 7, 8: 8, 9: 8, 10: 9, 11: 10, 12: 10}


# --- 統計 ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("df", "expected"), [(1, 12.7062047), (5, 2.5705818), (7, 2.3646243), (11, 2.2009852), (30, 2.0422725)]
)
def test_t_quantile(df, expected):
    assert st.t_quantile(0.975, df) == pytest.approx(expected, abs=1e-6)
    assert st.t_quantile(0.025, df) == pytest.approx(-expected, abs=1e-6)


def test_binomial_threshold_matches_the_preregistered_table():
    assert {n: st.binomial_threshold(n) for n in PREREG_THRESHOLDS} == PREREG_THRESHOLDS
    assert st.binomial_threshold(5) is None


def test_mean_t_interval():
    interval = st.mean_t_interval([1.0, 2.0, 3.0, 4.0])
    half = st.t_quantile(0.975, 3) * math.sqrt(5 / 3) / 2
    assert interval is not None and interval.mean == 2.5
    assert (interval.low, interval.high) == pytest.approx((2.5 - half, 2.5 + half))
    assert st.mean_t_interval([]) is None and st.mean_t_interval([1.0]).low is None


def test_bca_is_fixed_by_the_seed_and_degenerates_safely():
    values = [0.0, 1 / 6, 1 / 3, 1 / 6, 0.5, -1 / 6, 1 / 3, 0.0]
    first, second = st.bca_interval(values), st.bca_interval(values)
    assert first == second and first.low is not None and first.low < first.mean < first.high
    other = st.bca_interval(values, seed=1)
    assert other.low != first.low or other.high != first.high
    flat = st.bca_interval([1 / 6] * 6)
    assert flat.low is None and "区間を作れない" in flat.note


def test_wilcoxon_exact():
    all_positive = st.wilcoxon_signed_rank([1, 2, 3, 4, 5, 6])
    assert all_positive.w_plus == 21 and all_positive.p_two_sided == pytest.approx(2 / 64)
    ties = st.wilcoxon_signed_rank([1, -1, 2, 0, 2, 3])  # 0 は除き、同順位は平均
    assert ties.n_nonzero == 5 and ties.w_plus == pytest.approx(1.5 + 3.5 + 3.5 + 5)
    assert st.wilcoxon_signed_rank([0, 0]) is None


@pytest.mark.parametrize(
    ("sign", "low", "high", "mean", "pairs", "expected"),
    [
        (+1, 0.05, 0.4, 0.2, 8, "予備的な支持"),
        (+1, -0.1, 0.4, 0.2, 8, "向きのみ"),
        (+1, -0.4, 0.1, -0.2, 8, "支持しない"),
        (-1, -0.4, -0.05, -0.2, 8, "予備的な支持"),
        (-1, -0.4, 0.1, -0.2, 8, "向きのみ"),
        (+1, 0.05, 0.4, 0.2, 5, "記述だけ（両ブロックがそろった人が 5 人で6人未満）"),
        (None, 0.05, 0.4, 0.2, 8, "区間だけ（向きを予想しない）"),
    ],
)
def test_tier(sign, low, high, mean, pairs, expected):
    assert rp.tier(sign, st.Interval(pairs, mean, low, high), pairs) == expected


# --- 表 -----------------------------------------------------------------------------------------------


def _metrics(tmp_path, people: int, *, unsolved_ai: bool = False):
    builders = []
    sequences = ("Q1", "Q2", "Q3", "Q4")
    for index in range(people):
        sequence = sequences[index % 4]
        # V31 のブロックのセットだけ解けない人を作る（Δ を負にする）
        ai_set = {"Q1": "P2", "Q2": "P1", "Q3": "P1", "Q4": "P2"}[sequence]
        solve = [s for s in ("P1", "P2") if not (unsolved_ai and s == ai_set)]
        start = datetime(2026, 11, 12, 10, 0, tzinfo=JST) + timedelta(hours=index)
        builders.append(complete_participant(f"P{index + 1:02d}", sequence, start=start, solve=solve, prefer="1"))
    events = write_events(tmp_path / "events.jsonl", builders)
    return mt.build_metrics(events, write_catalog(tmp_path / "catalog.json"), load_tasks())


def test_report_with_few_people_only_describes(tmp_path):
    data = _metrics(tmp_path, 4)
    text = rp.build_report(data, metrics_sha256="x")
    assert "| F1 | 両ブロックの課題 b を出した人 ≥ 8 | 4 人 | 満たさない |" in text
    assert "| F5 |" in text and "測らない" in text
    assert "記述だけ（両ブロックがそろった人が 4 人で6人未満）" in text
    assert "AI の欄を使ったのは V31 のブロックの 0/4" in text
    assert "P01" not in text  # pid は出さない


def test_report_with_enough_people_judges(tmp_path):
    data = _metrics(tmp_path, 8, unsolved_ai=True)
    pairs = rp.analysis_pairs(data["participants"])
    assert len(pairs) == 8
    text = rp.build_report(data, metrics_sha256="x")
    delta_row = next(line for line in text.splitlines() if line.startswith("| Δ 達成度 a（主）"))
    assert "| 8 | -0.500 |" in delta_row and "支持しない" in delta_row and "0・0・8" in delta_row
    assert "| F1 | 両ブロックの課題 b を出した人 ≥ 8 | 8 人 | 満たす |" in text
    # 二択は全員が画面1 → 条件に直すと系列で分かれる（Q1・Q3 は V30、Q2・Q4 は V31）
    assert "| 8 | 4 | 4 | 8 | 閾値を満たさない" in text


def test_exclusions_and_pids_on_request(tmp_path):
    data = _metrics(tmp_path, 4)
    data["participants"][0]["faculty"] = "other"
    data["participants"][1]["blocks"][0]["system_failure"] = True
    data["participants"][2]["blocks"][1]["premise_failures"] = ["旗の指紋が違う"]
    assert len(rp.analysis_pairs(data["participants"])) == 1
    assert (
        len(
            rp.analysis_pairs(
                data["participants"], rp.Options(include_system_failures=True, include_other_faculty=True)
            )
        )
        == 3
    )
    text = rp.build_report(data, metrics_sha256="x", show_pids=True, withdrawn=["P09"])
    assert "| E6 |" in text and "P01" in text and "P03 ブロック2（旗の指紋が違う）" in text
    assert "| E2 | 撤回した（CLI の withdraw で行を消す） | 1 | P09 |" in text


def test_main_reads_metrics_and_writes_markdown(tmp_path, capsys):
    data = _metrics(tmp_path, 4)
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert rp.main(["--metrics", str(metrics_path)]) == 0
    assert "## 5.1 実施可能性" in capsys.readouterr().out
    out = tmp_path / "report.md"
    assert rp.main(["--metrics", str(metrics_path), "--out", str(out)]) == 0 and out.is_file()
    assert rp.main(["--metrics", str(metrics_path), "--out", str(out)]) == 1  # 上書きしない
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert rp.main(["--metrics", str(bad)]) == 1
