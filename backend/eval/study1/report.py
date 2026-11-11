"""Study 1 の判定と表（事前登録 5章）。metrics.py の JSON から Markdown の表を作る。

- 5.1 実施可能性 F1〜F4（F5 は測らない。変更記録のとおり）
- 5.5 除外 E1〜E6 と、主の分析に入る人（両ブロックがそろい、どちらのブロックも外れていない人）
- 5.6 AI の失敗（V31 のブロックの依頼。練習は別に出す）
- 4.1 成否・達成度（条件ごとの割合、対の 2×2、K1〜K6 ごとの満たした割合）
- 5.3 3段の書き方: 参加者ごとの差（V31 − V30）の平均 m、t の 95% 区間、Δ（達成度）だけ BCa の 95% 区間
  （10,000 回、種 20261109）、差が正・0・負の人数。両ブロックがそろった人が6人未満なら判定せず記述だけ。
  主は Δ（H1、s=+1）、副は log R'（H2、s=−1）・Δ_B（H3、s=−1）・Δ_SUS（H4、s=+1）。log R と Q11・Q12 は区間だけ。
  補助の Wilcoxon の符号順位検定は n ≥ 6 のときだけ出し、結論に使わない
- 4.2〜4.5 の記述（時間の幾何平均、確かめる行動、変更の数、V31 の AI の利用、SUS・Q11・Q12）
- 5.4 二択の閾値（両側 5% の二項検定の最小の人数。n 6〜12 は事前登録の表と同じ値）
- 5.7 感度分析（すべて記述）

p 値で結論を書かない。表に pid は出さない（--show-pids で研究者の手元用に除外の pid を出す）。自由記述は metrics の JSON に
入っていない。使い方:

    python -m eval.study1.report --metrics study1-metrics.json --out study1-report.md
"""

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from eval.study1.files import OutputError, sha256_file, write_private_text
from eval.study1.stats import (
    BCA_RESAMPLES,
    BCA_SEED,
    Interval,
    bca_interval,
    binomial_threshold,
    mean_t_interval,
    wilcoxon_signed_rank,
)

__all__ = ["Options", "analysis_pairs", "build_report", "feasibility_rows", "tier"]

NO_AI: Final = "V30"
AI: Final = "V31"
CONDITIONS: Final = (NO_AI, AI)
MIN_PAIRS_FOR_JUDGEMENT: Final = 6  # 5.3
MIN_N_FOR_WILCOXON: Final = 6
F1_MIN_PEOPLE: Final = 8
F2_MIN_SHARE: Final = 0.90
F3_MAX_SHARE: Final = 0.10
F4_MAX_MINUTES: Final = 45.0
AI_USE_NOTICE_SHARE: Final = 0.5  # 4.4: 使った割合が 0.5 未満なら結果の最初に書く
LIKERT_POINTS: Final = (1, 2, 3, 4, 5)
OTHER_FACULTY: Final = "other"
REMOTE: Final = "remote"
MS_PER_MINUTE: Final = 60_000.0
_DASH: Final = "—"


@dataclass(frozen=True)
class Options:
    """除外の切り替え（5.5 の主の分析は既定。5.7 の感度分析で切り替える）。"""

    include_system_failures: bool = False
    include_other_faculty: bool = False
    exclude_remote: bool = False
    exclude_answer_deviation: bool = False


MAIN_ANALYSIS: Final = Options()


def _fmt(value: float | None, digits: int = 3) -> str:
    return _DASH if value is None else f"{value:.{digits}f}"


def _share(part: int, whole: int) -> str:
    return f"{part}/{whole}（{part / whole:.1%}）" if whole else f"{part}/0"


def _blocks_by_variant(person: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(b.get("variant_id")): b for b in person.get("blocks", []) if b.get("variant_id") in CONDITIONS}


def _block_excluded(block: Mapping[str, Any], options: Options) -> list[str]:
    reasons = []
    if block.get("premise_failures"):
        reasons.append("E4")
    if block.get("system_failure") and not options.include_system_failures:
        reasons.append("E5")
    if options.exclude_answer_deviation and block.get("answers_deviate"):
        reasons.append("答えのずれ")
    return reasons


def _person_excluded(person: Mapping[str, Any], options: Options) -> list[str]:
    reasons = []
    if not person.get("both_b_submitted") or not person.get("completed"):
        reasons.append("E1")
    if person.get("e3"):
        reasons.append("E3")
    if person.get("faculty") == OTHER_FACULTY and not options.include_other_faculty:
        reasons.append("E6")
    if options.exclude_remote and person.get("mode") == REMOTE:
        reasons.append("遠隔")
    return reasons


def analysis_pairs(
    participants: Sequence[Mapping[str, Any]], options: Options = MAIN_ANALYSIS
) -> list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]:
    """主の分析に入る (人, V30 のブロック, V31 のブロック)。"""
    out = []
    for person in participants:
        if _person_excluded(person, options):
            continue
        blocks = _blocks_by_variant(person)
        if set(blocks) != set(CONDITIONS):
            continue
        if any(_block_excluded(blocks[c], options) for c in CONDITIONS):
            continue
        out.append((person, blocks[NO_AI], blocks[AI]))
    return out


def _log_ratio(key: str) -> Callable[[Mapping[str, Any], Mapping[str, Any]], float | None]:
    def compute(no_ai: Mapping[str, Any], ai: Mapping[str, Any]) -> float | None:
        a, b = no_ai.get(key), ai.get(key)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or a <= 0 or b <= 0:
            return None
        return math.log(b / a)

    return compute


def _difference(key: str) -> Callable[[Mapping[str, Any], Mapping[str, Any]], float | None]:
    def compute(no_ai: Mapping[str, Any], ai: Mapping[str, Any]) -> float | None:
        a, b = no_ai.get(key), ai.get(key)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return None
        return float(b) - float(a)

    return compute


@dataclass(frozen=True)
class Measure:
    label: str
    hypothesis: str
    sign: int | None  # 予想の向き s（None は向きを予想しない。区間だけ）
    compute: Callable[[Mapping[str, Any], Mapping[str, Any]], float | None]
    bca: bool = False


MEASURES: Final = (
    Measure("Δ 達成度 a（主）", "H1", +1, _difference("a"), bca=True),
    Measure("log R' 待ちを引いた時間", "H2", -1, _log_ratio("t_b_prime_ms")),
    Measure("Δ_B 確かめる行動（B1＋B2）", "H3", -1, _difference("B")),
    Measure("Δ_SUS", "H4", +1, _difference("SUS")),
    Measure("log R 待ちを含む時間", "—", None, _log_ratio("t_b_ms")),
    Measure("Δ Q11", "—", None, _difference("Q11")),
    Measure("Δ Q12", "—", None, _difference("Q12")),
)


def tier(sign: int | None, interval: Interval | None, n_pairs: int) -> str:
    """5.3 の書き方。"""
    if sign is None:
        return "区間だけ（向きを予想しない）"
    if n_pairs < MIN_PAIRS_FOR_JUDGEMENT:
        return f"記述だけ（両ブロックがそろった人が {n_pairs} 人で6人未満）"
    if interval is None:
        return "値が無い"
    if sign * interval.mean <= 0:
        return "支持しない"
    if interval.low is None or interval.high is None:
        return "向きのみ（区間を作れない）"
    excludes_zero = interval.low > 0 if sign > 0 else interval.high < 0
    return "予備的な支持" if excludes_zero else "向きのみ"


def _values(pairs: Sequence[tuple[Any, Mapping[str, Any], Mapping[str, Any]]], measure: Measure) -> list[float]:
    values = [measure.compute(no_ai, ai) for _, no_ai, ai in pairs]
    return [v for v in values if v is not None]


def _effect_rows(pairs: Sequence[tuple[Any, Mapping[str, Any], Mapping[str, Any]]]) -> list[str]:
    lines = [
        "| 指標 | 予想 | n | 平均 m | t の 95% 区間 | BCa の 95% 区間 | 正・0・負 | 書き方 | 補助: Wilcoxon（結論に使わない） |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for measure in MEASURES:
        values = _values(pairs, measure)
        interval = mean_t_interval(values)
        bca = bca_interval(values) if measure.bca else None
        signs = (sum(v > 0 for v in values), sum(v == 0 for v in values), sum(v < 0 for v in values))
        wilcoxon = wilcoxon_signed_rank(values) if len(values) >= MIN_N_FOR_WILCOXON else None
        direction = _DASH if measure.sign is None else f"{measure.hypothesis}（s={measure.sign:+d}）"
        t_text = _DASH if interval is None or interval.low is None else f"[{_fmt(interval.low)}, {_fmt(interval.high)}]"
        if not measure.bca:
            bca_text = _DASH
        elif bca is None or bca.low is None:
            bca_text = bca.note if bca is not None else _DASH
        else:
            bca_text = f"[{_fmt(bca.low)}, {_fmt(bca.high)}]"
        lines.append(
            f"| {measure.label} | {direction} | {len(values)} | {_fmt(interval.mean if interval else None)} | {t_text} | "
            f"{bca_text} | {signs[0]}・{signs[1]}・{signs[2]} | {tier(measure.sign, interval, len(pairs))} | "
            + (
                f"W+ {wilcoxon.w_plus:g}（0 でない差 {wilcoxon.n_nonzero} 人）、p {wilcoxon.p_two_sided:.3f}"
                if wilcoxon
                else "n < 6 で出さない"
            )
            + " |"
        )
    return lines


# --- 5.1 実施可能性 ----------------------------------------------------------------------------


def _v31_failures(participants: Iterable[Mapping[str, Any]]) -> tuple[int, int, Counter[str]]:
    requests = failures = 0
    outcomes: Counter[str] = Counter()
    for person in participants:
        for block in person.get("blocks", []):
            if block.get("variant_id") != AI or not block.get("ai_failures"):
                continue
            requests += block["ai_failures"]["requests"]
            failures += block["ai_failures"]["failures"]
            outcomes.update(block["ai_failures"]["by_outcome"])
    return requests, failures, outcomes


def feasibility_rows(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    participants = data["participants"]
    f1 = sum(1 for p in participants if p.get("completed") and p.get("both_b_submitted"))
    sessions = len(participants)
    clean = sum(1 for p in participants if p.get("seq_missing") == 0)
    requests, failures, _ = _v31_failures(participants)
    durations = [p["f4_minutes"] for p in participants if p.get("f4_minutes") is not None]
    median = statistics.median(durations) if durations else None
    return [
        {
            "id": "F1",
            "rule": f"両ブロックの課題 b を出した人 ≥ {F1_MIN_PEOPLE}",
            "value": f"{f1} 人",
            "ok": f1 >= F1_MIN_PEOPLE,
        },
        {
            "id": "F2",
            "rule": f"seq の欠けが0のセッション ≥ {F2_MIN_SHARE:.0%}",
            "value": _share(clean, sessions),
            "ok": sessions > 0 and clean / sessions >= F2_MIN_SHARE,
        },
        {
            "id": "F3",
            "rule": f"AI の失敗 ≤ AI への依頼の {F3_MAX_SHARE:.0%}（V31 のブロック）",
            "value": _share(failures, requests),
            "ok": None if requests == 0 else failures / requests <= F3_MAX_SHARE,
        },
        {
            "id": "F4",
            "rule": f"自走の所要時間の中央値 ≤ {F4_MAX_MINUTES:g} 分",
            "value": f"{_fmt(median, 1)} 分（{len(durations)} 人）",
            "ok": None if median is None else median <= F4_MAX_MINUTES,
        },
        {
            "id": "F5",
            "rule": "研究者の1人あたりの時間の中央値 ≤ 20 分",
            "value": "測らない（変更記録: リンクで送り、ひとりで進める形にしたため）",
            "ok": None,
        },
    ]


def _ok_text(ok: bool | None) -> str:
    return "満たす" if ok is True else "満たさない" if ok is False else "判定しない"


# --- 記述の表 ---------------------------------------------------------------------------------------


def _by_condition(
    pairs: Sequence[tuple[Any, Mapping[str, Any], Mapping[str, Any]]],
) -> dict[str, list[Mapping[str, Any]]]:
    return {NO_AI: [no_ai for _, no_ai, _ in pairs], AI: [ai for _, _, ai in pairs]}


def _numbers(blocks: Iterable[Mapping[str, Any]], key: str) -> list[float]:
    return [float(b[key]) for b in blocks if isinstance(b.get(key), (int, float)) and not isinstance(b.get(key), bool)]


def _mean_median(values: Sequence[float], digits: int = 2) -> str:
    if not values:
        return _DASH
    return f"{statistics.fmean(values):.{digits}f}（中央値 {statistics.median(values):.{digits}f}、n {len(values)}）"


def _success_tables(pairs: Sequence[tuple[Any, Mapping[str, Any], Mapping[str, Any]]]) -> list[str]:
    groups = _by_condition(pairs)
    lines = ["| 条件 | 成功 y=1 | 達成度 a | 初期 a0 | 伸び a − a0 |", "|---|---|---|---|---|"]
    for condition in CONDITIONS:
        blocks = groups[condition]
        success = sum(1 for b in blocks if b.get("y") == 1)
        lines.append(
            f"| {condition} | {_share(success, len(blocks))} | {_mean_median(_numbers(blocks, 'a'))} | "
            f"{_mean_median(_numbers(blocks, 'a0'))} | {_mean_median(_numbers(blocks, 'gain'))} |"
        )
    both = sum(1 for _, a, b in pairs if a.get("y") == 1 and b.get("y") == 1)
    only_ai = sum(1 for _, a, b in pairs if a.get("y") != 1 and b.get("y") == 1)
    only_no_ai = sum(1 for _, a, b in pairs if a.get("y") == 1 and b.get("y") != 1)
    neither = len(pairs) - both - only_ai - only_no_ai
    lines += [
        "",
        "| 対の 2×2 | 人数 |",
        "|---|---|",
        f"| 両方で成功 | {both} |",
        f"| V31 だけ成功 | {only_ai} |",
        f"| V30 だけ成功 | {only_no_ai} |",
        f"| 両方で失敗 | {neither} |",
    ]
    ids = sorted({cid for block in groups[NO_AI] + groups[AI] for cid in (block.get("conditions") or {})})
    lines += ["", "| 条件（カード） | V30 で満たした割合 | V31 で満たした割合 |", "|---|---|---|"]
    for cid in ids:
        cells = []
        for condition in CONDITIONS:
            scored = [b for b in groups[condition] if b.get("conditions")]
            met = sum(1 for b in scored if b["conditions"].get(cid) == "met")
            cells.append(_share(met, len(scored)))
        lines.append(f"| {cid} | {cells[0]} | {cells[1]} |")
    return lines


def _geometric(values: Sequence[float]) -> str:
    interval = mean_t_interval(values)
    if interval is None:
        return _DASH
    if interval.low is None or interval.high is None:
        return f"{math.exp(interval.mean):.3f}（区間なし、n {interval.n}）"
    low, high = math.exp(interval.low), math.exp(interval.high)
    return f"{math.exp(interval.mean):.3f}（log の t の 95% 区間から [{low:.3f}, {high:.3f}]、n {interval.n}）"


def _time_tables(pairs: Sequence[tuple[Any, Mapping[str, Any], Mapping[str, Any]]]) -> list[str]:
    groups = _by_condition(pairs)
    lines = ["| 条件 | t_b（分） | W（分） | t_b'（分） | 課題 a の時間（分） |", "|---|---|---|---|---|"]
    for condition in CONDITIONS:
        blocks = groups[condition]

        def minutes(key: str, blocks: Sequence[Mapping[str, Any]] = blocks) -> list[float]:
            return [v / MS_PER_MINUTE for v in _numbers(blocks, key)]

        lines.append(
            f"| {condition} | {_mean_median(minutes('t_b_ms'))} | {_mean_median(minutes('W_ms'))} | "
            f"{_mean_median(minutes('t_b_prime_ms'))} | {_mean_median(minutes('t_a_ms'))} |"
        )
    ratio = [v for v in (_log_ratio("t_b_ms")(a, b) for _, a, b in pairs) if v is not None]
    ratio_prime = [v for v in (_log_ratio("t_b_prime_ms")(a, b) for _, a, b in pairs) if v is not None]
    lines += ["", f"- GM(R)（待ちを含む）: {_geometric(ratio)}", f"- GM(R')（待ちを引く）: {_geometric(ratio_prime)}"]
    return lines


def _behavior_tables(pairs: Sequence[tuple[Any, Mapping[str, Any], Mapping[str, Any]]]) -> list[str]:
    groups = _by_condition(pairs)
    lines = [
        "| 条件 | B1 チェックを開いた | B2 原因の科目を見た | B3 チェックを足した | B4 原文を開いた | B = B1 + B2 |",
        "|---|---|---|---|---|---|",
    ]
    for condition in CONDITIONS:
        blocks = groups[condition]
        cells = " | ".join(_mean_median(_numbers(blocks, key)) for key in ("B1", "B2", "B3", "B4", "B"))
        lines.append(f"| {condition} | {cells} |")
    b5 = _numbers(groups[AI], "B5")
    lines.append(f"\nB5（V31。案を採ったあと次の依頼か出すまでに B1 か B2 があった割合）: {_mean_median(b5)}")
    return lines


def _change_tables(pairs: Sequence[tuple[Any, Mapping[str, Any], Mapping[str, Any]]]) -> list[str]:
    groups = _by_condition(pairs)
    lines = ["| 条件 | 変更の数 D | うち移す | 出どころ（合計） | 効率 = 最小の変更 ÷ D |", "|---|---|---|---|---|"]
    for condition in CONDITIONS:
        blocks = groups[condition]
        changes = [b["changes"] for b in blocks if b.get("changes")]
        sources: Counter[str] = Counter()
        for c in changes:
            sources.update(c.get("by_source", {}))
        counts = _mean_median([float(c["D"]) for c in changes])
        moves = _mean_median([float(c["moves"]) for c in changes])
        by_source = "、".join(f"{k} {v}" for k, v in sorted(sources.items())) or _DASH
        efficiency = _mean_median(_numbers(blocks, "efficiency"))
        lines.append(f"| {condition} | {counts} | {moves} | {by_source} | {efficiency} |")
    return lines


def _ai_use(blocks: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    used = sum(1 for b in blocks if (b.get("ai") or {}).get("used"))
    return used, len(blocks)


def _ai_tables(pairs: Sequence[tuple[Any, Mapping[str, Any], Mapping[str, Any]]]) -> list[str]:
    blocks = [ai for _, _, ai in pairs if ai.get("ai")]
    used, total = _ai_use(blocks)
    ai = [b["ai"] for b in blocks]
    shown = sum(a["lines_shown"] for a in ai)
    accepted = sum(a["lines_accepted"] for a in ai)
    decisions: Counter[str] = Counter()
    for a in ai:
        decisions.update(a.get("decisions", {}))
    breaking_shown = sum(a["breaking_lines_shown"] for a in ai)
    breaking_accepted = sum(a["breaking_lines_accepted"] for a in ai)
    unevaluable = sum(a["lines_unevaluable"] for a in ai)
    not_in_catalog = sum(a["ids_not_in_catalog"] for a in ai)
    seen = sum(a["ids_seen"] for a in ai)
    unverified = sum(a["unverified_codes"] for a in ai)
    return [
        "| 項目 | 値 |",
        "|---|---|",
        f"| AI に1回以上頼んだブロック | {_share(used, total)} |",
        f"| 依頼の数（微修正・さがすの AI に聞く） | {sum(a['refine_requests'] for a in ai)}・{sum(a['chat_requests'] for a in ai)} |",
        f"| 受け入れ率（採った行 ÷ 示した行） | {_share(accepted, shown)} |",
        f"| 案ごと（全部採った・一部・採らなかった・判断の記録なし） | {decisions.get('all', 0)}・{decisions.get('partial', 0)}・"
        f"{decisions.get('none', 0)}・{decisions.get('no_decision', 0)} |",
        f"| 誤りへの依存（探索。条件を壊す行のうち採られた割合） | {_share(breaking_accepted, breaking_shown)}"
        f"（判定できない行 {unevaluable}） |",
        f"| 案と回答に出た syllabus_id のうちスナップショットに無いもの | {not_in_catalog}"
        f"（出た ID {seen}、サーバーが未照合とした ID {unverified}） |",
    ]


def _questionnaire_tables(pairs: Sequence[tuple[Any, Mapping[str, Any], Mapping[str, Any]]]) -> list[str]:
    groups = _by_condition(pairs)
    lines = [
        "| 条件 | SUS | Q11 の分布（1〜5） | Q11 の中央値 | Q12 の分布（1〜5） | Q12 の中央値 |",
        "|---|---|---|---|---|---|",
    ]
    for condition in CONDITIONS:
        blocks = groups[condition]
        cells = []
        for key in ("Q11", "Q12"):
            values = _numbers(blocks, key)
            counts = Counter(int(v) for v in values)
            cells += [
                "・".join(str(counts.get(p, 0)) for p in LIKERT_POINTS) + f"（n {len(values)}）",
                _fmt(statistics.median(values) if values else None, 1),
            ]
        lines.append(f"| {condition} | {_mean_median(_numbers(blocks, 'SUS'), 1)} | {' | '.join(cells)} |")
    return lines


def _preference_rows(people: Sequence[Mapping[str, Any]]) -> list[str]:
    answered = [p for p in people if p.get("prefer_variant_id") in CONDITIONS]
    counts = Counter(p["prefer_variant_id"] for p in answered)
    n = len(answered)
    threshold = binomial_threshold(n) if n else None
    top = max(counts.values(), default=0)
    if n < MIN_PAIRS_FOR_JUDGEMENT or threshold is None:
        verdict = "人数だけ（5.4 の表は n 6 以上）"
    elif top >= threshold:
        verdict = f"閾値を満たす（同じ画面を選んだ人 {top} ≥ {threshold}）"
    else:
        verdict = f"閾値を満たさない（同じ画面を選んだ人 {top} < {threshold}）。人数だけを書く"
    return [
        "| 二択に答えた人数 n | V30 を選んだ | V31 を選んだ | 閾値（両側 5% の二項検定） | 書き方 |",
        "|---|---|---|---|---|",
        f"| {n} | {counts.get(NO_AI, 0)} | {counts.get(AI, 0)} | {threshold if threshold is not None else _DASH} | {verdict} |",
    ]


# --- 5.5・5.6・5.7 ------------------------------------------------------------------------------------


def _exclusions(data: Mapping[str, Any], show_pids: bool, withdrawn: Sequence[str] | None) -> list[str]:
    participants = data["participants"]
    groups: dict[str, list[str]] = {"E1": [], "E3": [], "E4": [], "E5": [], "E6": []}
    for person in participants:
        pid = str(person.get("pid"))
        for reason in _person_excluded(person, MAIN_ANALYSIS):
            groups.setdefault(reason, []).append(pid)
        for block in person.get("blocks", []):
            for reason in _block_excluded(block, MAIN_ANALYSIS):
                detail = "・".join(block.get("premise_failures") or []) if reason == "E4" else ""
                groups.setdefault(reason, []).append(
                    f"{pid} ブロック{block['block']}" + (f"（{detail}）" if detail else "")
                )
    rules = {
        "E1": "両ブロックの課題 b を出していない（人。効果の分析から外す）",
        "E2": "撤回した（CLI の withdraw で行を消す）",
        "E3": "seq の欠けがセッションのイベントの 10% を超える（人）",
        "E4": "5.2 の前提が外れた（ブロック）",
        "E5": "課題 b がシステムの失敗になった（ブロック。主の分析で外す）",
        "E6": "環境都市工学部の外の学生（人。主の分析から外し、別に記述）",
    }
    lines = ["| ID | 規則 | 数 |" + (" 中身 |" if show_pids else ""), "|---|---|---|" + ("---|" if show_pids else "")]
    for key in ("E1", "E2", "E3", "E4", "E5", "E6"):
        if key == "E2":
            count = "書き出しには現れない（study.json を渡していない）" if withdrawn is None else str(len(withdrawn))
            items = "、".join(withdrawn or [])
        else:
            count = str(len(groups.get(key, [])))
            items = "、".join(groups.get(key, []))
        lines.append(f"| {key} | {rules[key]} | {count} |" + (f" {items or _DASH} |" if show_pids else ""))
    return lines


def _failure_rows(data: Mapping[str, Any]) -> list[str]:
    requests, failures, outcomes = _v31_failures(data["participants"])
    systems = sum(
        1
        for p in data["participants"]
        for b in p.get("blocks", [])
        if b.get("variant_id") == AI and b.get("system_failure")
    )
    retries = sum(
        (b.get("ai_failures") or {}).get("retries", 0)
        for p in data["participants"]
        for b in p.get("blocks", [])
        if b.get("variant_id") == AI
    )
    practice = data.get("practice_ai", {})
    return [
        "| 項目 | 値 |",
        "|---|---|",
        f"| V31 のブロックの依頼 | {requests} |",
        f"| 失敗（5.6 の (1)〜(3)） | {failures} |",
        f"| 依頼の結果の内訳 | {'、'.join(f'{k} {v}' for k, v in sorted(outcomes.items())) or _DASH} |",
        f"| 再試行（もう一度送る） | {retries} |",
        f"| システムの失敗（課題 b で2回続けて失敗。E5） | {systems} ブロック |",
        f"| 練習の依頼・失敗（F3 には入れない） | {practice.get('requests', 0)}・{practice.get('failures', 0)} |",
    ]


def _sensitivity_rows(data: Mapping[str, Any]) -> list[str]:
    participants = data["participants"]
    delta = MEASURES[0]
    lines = ["| 版 | 対の数 | 平均 Δ | t の 95% 区間 |", "|---|---|---|---|"]

    def row(label: str, pairs: Sequence[tuple[Any, Mapping[str, Any], Mapping[str, Any]]]) -> None:
        values = _values(pairs, delta)
        interval = mean_t_interval(values)
        ci = _DASH if interval is None or interval.low is None else f"[{_fmt(interval.low)}, {_fmt(interval.high)}]"
        lines.append(f"| {label} | {len(values)} | {_fmt(interval.mean if interval else None)} | {ci} |")

    row("主の分析", analysis_pairs(participants))
    row("システムの失敗を含める", analysis_pairs(participants, Options(include_system_failures=True)))
    row(
        "診断の答えが参照の答えとずれたブロックを除く",
        analysis_pairs(participants, Options(exclude_answer_deviation=True)),
    )
    row("学部の外の人を含める", analysis_pairs(participants, Options(include_other_faculty=True)))
    row("遠隔の人を除く", analysis_pairs(participants, Options(exclude_remote=True)))
    grades = sorted({str(p.get("grade")) for p in participants})
    for grade in grades:
        row(f"学年 {grade}", [pair for pair in analysis_pairs(participants) if str(pair[0].get("grade")) == grade])
    first: dict[str, list[float]] = {NO_AI: [], AI: []}
    for person in participants:
        if _person_excluded(person, MAIN_ANALYSIS):
            continue
        block = next((b for b in person.get("blocks", []) if b.get("block") == 1), None)
        if block is None or _block_excluded(block, MAIN_ANALYSIS) or not isinstance(block.get("a"), (int, float)):
            continue
        if block.get("variant_id") in first:
            first[block["variant_id"]].append(float(block["a"]))
    means = {c: statistics.fmean(v) if v else None for c, v in first.items()}
    diff = means[AI] - means[NO_AI] if means[AI] is not None and means[NO_AI] is not None else None
    lines.append(
        f"| 第1ブロックだけ（被験者間）: V30 n {len(first[NO_AI])} 平均 a {_fmt(means[NO_AI])}、"
        f"V31 n {len(first[AI])} 平均 a {_fmt(means[AI])} | — | {_fmt(diff)} | — |"
    )
    return lines


# --- 全体 -------------------------------------------------------------------------------------------


def build_report(
    data: Mapping[str, Any], *, metrics_sha256: str, show_pids: bool = False, withdrawn: Sequence[str] | None = None
) -> str:
    participants = data["participants"]
    pairs = analysis_pairs(participants)
    inputs = data["inputs"]
    out: list[str] = ["# Study 1 の判定と表（事前登録 5章）", ""]
    ai_blocks = [ai for _, _, ai in pairs if ai.get("ai")]
    used, total = _ai_use(ai_blocks)
    if total and used / total < AI_USE_NOTICE_SHARE:
        out += [
            f"**AI の欄を使ったのは V31 のブロックの {_share(used, total)} で、0.5 未満です。差は「AI の欄があること」の効果で、"
            "「AI を使うこと」の効果ではありません（4.4）。**",
            "",
        ]
    out += [
        "## 入力",
        "",
        f"- 指標: SHA-256 {metrics_sha256}（{data.get('format')}、作成 {data.get('generated_at')}）",
        f"- 書き出し: SHA-256 {inputs['events']['sha256']}、行 {inputs['events']['lines']}、イベント {inputs['events']['events']}、"
        f"読めない行 {inputs['events']['unreadable']}、形の一部が違う行 {inputs['events']['problems']}",
        f"- 科目のスナップショット: 指紋 {inputs['catalog']['fingerprint']}（科目 {inputs['catalog']['courses']}）",
        f"- tasks.json: SHA-256 {inputs['tasks']['sha256']}（設定の版 {inputs['tasks']['config_version']}）",
        f"- セッション {data['sessions']}、主の分析に入る人（両ブロックがそろい外れていない） {len(pairs)}",
        f"- BCa: {BCA_RESAMPLES:,} 回、種 {BCA_SEED}。p 値で結論を書かない",
        "",
        "## 5.1 実施可能性（主の判定）",
        "",
        "| ID | 基準 | 値 | 判定 |",
        "|---|---|---|---|",
    ]
    rows = feasibility_rows(data)
    out += [f"| {r['id']} | {r['rule']} | {r['value']} | {_ok_text(r['ok'])} |" for r in rows]
    unmet = [r["id"] for r in rows if r["ok"] is False]
    out += ["", "満たさない項目: " + ("、".join(unmet) if unmet else "なし"), ""]
    out += ["## 5.5 除外", ""] + _exclusions(data, show_pids, withdrawn) + [""]
    out += ["## 5.6 AI の失敗", ""] + _failure_rows(data) + [""]
    out += ["## 4.1 成否と達成度", ""] + _success_tables(pairs) + [""]
    out += ["## 5.3 効果の書き方（参加者ごとの差 V31 − V30）", ""] + _effect_rows(pairs) + [""]
    out += ["## 4.2 時間", ""] + _time_tables(pairs) + [""]
    out += ["## 4.3 確かめる行動（課題 b の中の回数）", ""] + _behavior_tables(pairs) + [""]
    out += ["## 4.4 プランの足し外し", ""] + _change_tables(pairs) + [""]
    out += ["### V31 の AI の利用", ""] + _ai_tables(pairs) + [""]
    out += ["## 4.5 質問票", ""] + _questionnaire_tables(pairs) + [""]
    out += ["## 5.4 二択（主の分析に入る人）", ""] + _preference_rows([p for p, _, _ in pairs]) + [""]
    out += ["## 5.7 感度分析（すべて記述。Δ = 達成度の差）", ""] + _sensitivity_rows(data) + [""]
    return "\n".join(out)


def _withdrawn(study_json: Path | None) -> list[str] | None:
    if study_json is None:
        return None
    study = json.loads(study_json.read_text(encoding="utf-8"))
    return [str(w.get("pid")) for w in study.get("withdrawals", [])]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Study 1 の判定と表（事前登録 5章）を Markdown で出す")
    parser.add_argument("--metrics", type=Path, required=True, help="metrics.py の JSON")
    parser.add_argument("--out", type=Path, help="Markdown の書き先（リポの外）。無ければ標準出力")
    parser.add_argument("--study-json", type=Path, help="study.json（E2 の撤回の数を出す）")
    parser.add_argument("--show-pids", action="store_true", help="除外の表に pid を出す（研究者の手元用。公開しない）")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.metrics.read_text(encoding="utf-8"))
        if data.get("format") != "study1-metrics-v1":
            raise ValueError(f"{args.metrics} は metrics.py の JSON ではありません。")
        text = build_report(
            data,
            metrics_sha256=sha256_file(args.metrics),
            show_pids=args.show_pids,
            withdrawn=_withdrawn(args.study_json),
        )
        if args.out is None:
            print(text)
            return 0
        digest = write_private_text(args.out, text + "\n", "判定と表")
    except (OSError, ValueError, KeyError, OutputError) as exc:
        print(f"止めました: {exc}", file=sys.stderr)
        return 1
    print(f"Markdown: {args.out}（SHA-256 {digest}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
