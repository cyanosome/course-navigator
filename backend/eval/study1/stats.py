"""report.py が使う統計の計算（標準ライブラリだけ。事前登録 4.1・4.2・5.3・5.4）。

- t の 95% 区間: 平均 ± t(0.975, n−1) × 標準偏差 ÷ √n。t の分位点は、正則化不完全ベータ関数（連分数）で t 分布の
  累積を出し、二分法で解く
- BCa ブートストラップの区間（4.1。既定 10,000 回、種 20261109）: random.Random(種) の choices で n 個を復元抽出して
  平均を取ることを B 回。偏りの補正 z0 = Φ⁻¹(#{θ* < θ̂} / B)（scipy.stats.bootstrap と同じく「より小さい」だけを数える）、
  加速 a はジャックナイフ（Σ(θ̄−θ_i)³ / (6 (Σ(θ̄−θ_i)²)^1.5)、分母が 0 なら 0）。分位点は直線の補間（numpy の既定と同じ）。
  θ* がすべて θ̂ 以上かすべて θ̂ より小さい（値がすべて同じなど）ときは区間を作れない（None と理由）
- Wilcoxon の符号順位検定（5.3 の補助。結論に使わない）: 差が 0 の人を除き、|差| の順位（同順位は平均）で W+ を出し、
  符号のすべての組み合わせの数え上げ（正確な分布）で両側の p
- 二項の閾値（5.4）: n 人のうち同じ画面を選んだ人数が k 以上なら、両側 5% の二項検定（p = 0.5）で有意になる最小の k
"""

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import NormalDist
from typing import Final

__all__ = [
    "BCA_RESAMPLES",
    "BCA_SEED",
    "Interval",
    "bca_interval",
    "binomial_threshold",
    "mean_t_interval",
    "t_quantile",
    "wilcoxon_signed_rank",
]

BCA_RESAMPLES: Final = 10_000
BCA_SEED: Final = 20261109
LEVEL: Final = 0.95
ALPHA_TWO_SIDED: Final = 0.05
_BETA_EPS: Final = 1e-14
_BETA_TINY: Final = 1e-300
_BETA_MAX_ITER: Final = 500
_BISECT_ITER: Final = 200
_T_UPPER_START: Final = 1.0
_TIE_TOLERANCE: Final = 1e-9


@dataclass(frozen=True)
class Interval:
    n: int
    mean: float
    low: float | None
    high: float | None
    note: str = ""


def _betacf(a: float, b: float, x: float) -> float:
    """不完全ベータ関数の連分数（Lentz の方法）。"""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > _BETA_TINY else _BETA_TINY)
    h = d
    for m in range(1, _BETA_MAX_ITER + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _BETA_TINY else _BETA_TINY)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > _BETA_TINY else _BETA_TINY
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _BETA_TINY else _BETA_TINY)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > _BETA_TINY else _BETA_TINY
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _BETA_EPS:
            return h
    raise ArithmeticError("不完全ベータ関数の連分数が収束しません。")


def _betainc(a: float, b: float, x: float) -> float:
    """正則化不完全ベータ関数 I_x(a, b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _t_cdf(t: float, df: float) -> float:
    tail = 0.5 * _betainc(df / 2.0, 0.5, df / (df + t * t))
    return 1.0 - tail if t >= 0 else tail


def t_quantile(p: float, df: int) -> float:
    """t 分布（自由度 df）の p 分位点。"""
    if not 0.0 < p < 1.0 or df < 1:
        raise ValueError(f"p={p}・df={df} は範囲の外です。")
    if p < 0.5:
        return -t_quantile(1.0 - p, df)
    low, high = 0.0, _T_UPPER_START
    while _t_cdf(high, df) < p:
        high *= 2.0
    for _ in range(_BISECT_ITER):
        mid = (low + high) / 2.0
        if _t_cdf(mid, df) < p:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def mean_t_interval(values: Sequence[float], level: float = LEVEL) -> Interval | None:
    """平均と t の区間。値が1つ以下なら None。"""
    n = len(values)
    if n == 0:
        return None
    mean = statistics.fmean(values)
    if n < 2:
        return Interval(n, mean, None, None, "1人だけ")
    half = t_quantile(1.0 - (1.0 - level) / 2.0, n - 1) * statistics.stdev(values) / math.sqrt(n)
    return Interval(n, mean, mean - half, mean + half)


def _percentile(ordered: Sequence[float], q: float) -> float:
    position = q * (len(ordered) - 1)
    below = math.floor(position)
    above = min(below + 1, len(ordered) - 1)
    return ordered[below] + (ordered[above] - ordered[below]) * (position - below)


def bca_interval(
    values: Sequence[float], *, resamples: int = BCA_RESAMPLES, seed: int = BCA_SEED, level: float = LEVEL
) -> Interval | None:
    """平均の BCa ブートストラップの区間。値が無ければ None、作れなければ low・high が None で理由つき。"""
    n = len(values)
    if n == 0:
        return None
    theta = statistics.fmean(values)
    if n < 2:
        return Interval(n, theta, None, None, "1人だけ")
    rng = random.Random(seed)
    boots = sorted(statistics.fmean(rng.choices(values, k=n)) for _ in range(resamples))
    less = sum(b < theta for b in boots)
    if less in (0, resamples):
        return Interval(n, theta, None, None, "区間を作れない（再標本の平均がすべて片側。値がほぼ同じ）")
    normal = NormalDist()
    z0 = normal.inv_cdf(less / resamples)
    jack = [statistics.fmean([*values[:i], *values[i + 1 :]]) for i in range(n)]
    jbar = statistics.fmean(jack)
    denominator = 6.0 * sum((jbar - j) ** 2 for j in jack) ** 1.5
    accel = sum((jbar - j) ** 3 for j in jack) / denominator if denominator > 0 else 0.0
    alpha = (1.0 - level) / 2.0

    def adjusted(q: float) -> float:
        z = normal.inv_cdf(q)
        return normal.cdf(z0 + (z0 + z) / (1.0 - accel * (z0 + z)))

    return Interval(n, theta, _percentile(boots, adjusted(alpha)), _percentile(boots, adjusted(1.0 - alpha)))


@dataclass(frozen=True)
class Wilcoxon:
    n_nonzero: int
    w_plus: float
    p_two_sided: float


def wilcoxon_signed_rank(differences: Sequence[float]) -> Wilcoxon | None:
    """差が 0 でない人が1人もいなければ None。"""
    nonzero = [d for d in differences if abs(d) > _TIE_TOLERANCE]
    n = len(nonzero)
    if n == 0:
        return None
    ordered = sorted(range(n), key=lambda i: abs(nonzero[i]))
    ranks = [0.0] * n
    start = 0
    while start < n:
        end = start
        while end + 1 < n and abs(abs(nonzero[ordered[end + 1]]) - abs(nonzero[ordered[start]])) <= _TIE_TOLERANCE:
            end += 1
        average = (start + end) / 2.0 + 1.0
        for k in range(start, end + 1):
            ranks[ordered[k]] = average
        start = end + 1
    w_plus = sum(rank for rank, d in zip(ranks, nonzero, strict=True) if d > 0)
    doubled = [round(rank * 2) for rank in ranks]  # 平均の順位は 0.5 刻みなので2倍で整数にする
    counts: dict[int, int] = {0: 1}
    for value in doubled:
        nxt: dict[int, int] = {}
        for total, count in counts.items():
            nxt[total] = nxt.get(total, 0) + count
            nxt[total + value] = nxt.get(total + value, 0) + count
        counts = nxt
    center = sum(doubled) / 2.0
    observed = abs(round(w_plus * 2) - center)
    extreme = sum(count for total, count in counts.items() if abs(total - center) >= observed - _TIE_TOLERANCE)
    return Wilcoxon(n, w_plus, min(1.0, extreme / 2**n))


def binomial_threshold(n: int, alpha: float = ALPHA_TWO_SIDED) -> int | None:
    """n 人のうち同じ側を選んだ人数がこれ以上なら両側 alpha で有意（p = 0.5）。どの人数でも有意にならなければ None。"""
    for k in range((n + 1) // 2, n + 1):
        tail = sum(math.comb(n, j) for j in range(k, n + 1)) / 2**n
        if min(1.0, 2.0 * tail) <= alpha and k > n - k:
            return k
    return None
