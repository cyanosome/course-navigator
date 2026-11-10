"""色の読み取りと計算（check_banlist.py と check_contrast.py が共有する）。

- CSS の色表記を sRGB(0..1) に読み替える: #rgb #rgba #rrggbb #rrggbbaa / rgb() rgba() / hsl() hsla() / oklch() / oklab()
- sRGB → CIELAB(D65) → CIEDE2000 色差
- WCAG 2.2 の相対輝度とコントラスト比

外部パッケージは使わない。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# ---------------------------------------------------------------- 読み取り

HEX_RE = re.compile(r"(?<![\w&/=?])#(?P<hex>[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w-])")
FUNC_RE = re.compile(r"\b(?P<fn>rgba?|hsla?|oklch|oklab)\(\s*(?P<args>[^()]*)\)", re.I)

# グラデーションの中だけで読む名前付き色（全体で読むと単語と誤爆するため）
NAMED_COLORS = {
    "black": "#000000", "white": "#ffffff", "purple": "#800080", "indigo": "#4b0082",
    "violet": "#ee82ee", "blueviolet": "#8a2be2", "mediumpurple": "#9370db",
    "rebeccapurple": "#663399", "darkviolet": "#9400d3", "magenta": "#ff00ff",
    "fuchsia": "#ff00ff", "orchid": "#da70d6", "pink": "#ffc0cb", "hotpink": "#ff69b4",
    "deeppink": "#ff1493", "orange": "#ffa500", "darkorange": "#ff8c00", "coral": "#ff7f50",
    "tomato": "#ff6347", "cyan": "#00ffff", "aqua": "#00ffff", "blue": "#0000ff",
}


@dataclass(frozen=True)
class RGBA:
    r: float  # 0..1
    g: float
    b: float
    a: float = 1.0

    def hex(self) -> str:
        return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in (self.r, self.g, self.b))


@dataclass(frozen=True)
class FoundColor:
    start: int
    end: int
    raw: str
    rgba: RGBA


def _num(token: str, scale: float) -> float:
    """'50%' は scale に対する割合、それ以外は数値そのもの。"""
    token = token.strip()
    if token.endswith("%"):
        return float(token[:-1]) / 100.0 * scale
    return float(token)


def _alpha(token: str | None) -> float:
    if token is None:
        return 1.0
    token = token.strip()
    if token.endswith("%"):
        return float(token[:-1]) / 100.0
    return float(token)


def _hue(token: str) -> float:
    token = token.strip().lower()
    for unit, factor in (("deg", 1.0), ("grad", 0.9), ("rad", 180.0 / math.pi), ("turn", 360.0)):
        if token.endswith(unit):
            return float(token[: -len(unit)]) * factor
    return float(token)


def _split_args(args: str) -> tuple[list[str], str | None]:
    """'1 2 3 / .5' と '1, 2, 3, .5' の両方を (本体, アルファ) に分ける。"""
    alpha = None
    if "/" in args:
        body, alpha = args.split("/", 1)
        parts = body.replace(",", " ").split()
    else:
        parts = args.replace(",", " ").split()
        if len(parts) == 4:
            alpha = parts.pop()
    return parts, alpha


def parse_hex(hex_digits: str) -> RGBA:
    h = hex_digits
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    a = int(h[6:8], 16) / 255.0 if len(h) == 8 else 1.0
    return RGBA(r, g, b, a)


def _hsl_to_rgb(h: float, s: float, light: float) -> tuple[float, float, float]:
    h = (h % 360.0) / 360.0

    def channel(n: float) -> float:
        k = (n + h * 12.0) % 12.0
        a = s * min(light, 1.0 - light)
        return light - a * max(-1.0, min(k - 3.0, 9.0 - k, 1.0))

    return channel(0), channel(8), channel(4)


def oklab_to_srgb(L: float, a: float, b: float) -> tuple[float, float, float]:
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    lin = (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )
    return tuple(max(0.0, min(1.0, _gamma_encode(c))) for c in lin)  # type: ignore[return-value]


def parse_function(fn: str, args: str) -> RGBA | None:
    fn = fn.lower()
    parts, alpha_token = _split_args(args)
    if len(parts) != 3 or any(p.startswith("var") for p in parts):
        return None
    try:
        alpha = _alpha(alpha_token)
        if fn in ("rgb", "rgba"):
            r, g, b = (_num(p, 255.0) / 255.0 for p in parts)
            return RGBA(r, g, b, alpha)
        if fn in ("hsl", "hsla"):
            h = _hue(parts[0])
            s = _num(parts[1] if parts[1].endswith("%") else parts[1] + "%", 1.0)
            light = _num(parts[2] if parts[2].endswith("%") else parts[2] + "%", 1.0)
            return RGBA(*_hsl_to_rgb(h, s, light), alpha)
        if fn == "oklch":
            L = _num(parts[0], 1.0)
            C = _num(parts[1], 0.4)
            h = math.radians(_hue(parts[2]))
            return RGBA(*oklab_to_srgb(L, C * math.cos(h), C * math.sin(h)), alpha)
        if fn == "oklab":
            L = _num(parts[0], 1.0)
            return RGBA(*oklab_to_srgb(L, _num(parts[1], 0.4), _num(parts[2], 0.4)), alpha)
    except ValueError:
        return None
    return None


def parse_color(text: str) -> RGBA | None:
    """色1つ分の文字列を読む。読めなければ None。"""
    text = text.strip()
    if text.lower() in NAMED_COLORS:
        return parse_hex(NAMED_COLORS[text.lower()][1:])
    m = HEX_RE.fullmatch(text)
    if m:
        return parse_hex(m.group("hex"))
    m = FUNC_RE.fullmatch(text)
    if m:
        return parse_function(m.group("fn"), m.group("args"))
    return None


def find_colors(text: str, named: bool = False) -> list[FoundColor]:
    """文字列の中の色表記をすべて拾う（位置つき）。named=True なら名前付き色も拾う。"""
    found: list[FoundColor] = []
    for m in HEX_RE.finditer(text):
        found.append(FoundColor(m.start(), m.end(), m.group(0), parse_hex(m.group("hex"))))
    for m in FUNC_RE.finditer(text):
        rgba = parse_function(m.group("fn"), m.group("args"))
        if rgba is not None:
            found.append(FoundColor(m.start(), m.end(), m.group(0), rgba))
    if named:
        for name, hx in NAMED_COLORS.items():
            for m in re.finditer(rf"(?<![\w-]){name}(?![\w-])", text, re.I):
                found.append(FoundColor(m.start(), m.end(), m.group(0), parse_hex(hx[1:])))
    found.sort(key=lambda c: c.start)
    return found


# ---------------------------------------------------------------- 色空間

def _gamma_decode(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gamma_encode(c: float) -> float:
    if c <= 0.0031308:
        return 12.92 * c
    return 1.055 * (max(c, 0.0) ** (1.0 / 2.4)) - 0.055


def srgb_to_lab(rgba: RGBA) -> tuple[float, float, float]:
    r, g, b = (_gamma_decode(c) for c in (rgba.r, rgba.g, rgba.b))
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883
    delta = 6.0 / 29.0

    def f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > delta ** 3 else t / (3 * delta * delta) + 4.0 / 29.0

    fx, fy, fz = f(x), f(y), f(z)
    return 116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)


def srgb_to_oklch(rgba: RGBA) -> tuple[float, float, float]:
    """sRGB → OKLCH（L 0..1, C, h 度）。色相の帯で色を分けるのに使う（CIELAB より青〜紫の色相が均等）。"""
    r, g, b = (_gamma_decode(c) for c in (rgba.r, rgba.g, rgba.b))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1.0 / 3.0), v) for v in (l, m, s))
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360.0


def lab_to_lch(lab: tuple[float, float, float]) -> tuple[float, float, float]:
    L, a, b = lab
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360.0


def ciede2000(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    """CIEDE2000（kL=kC=kH=1）。Sharma ら (2005) の式どおり。"""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    g = 0.5 * (1.0 - math.sqrt(c_bar ** 7 / (c_bar ** 7 + 25.0 ** 7)))
    a1p, a2p = (1.0 + g) * a1, (1.0 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360.0 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360.0 if c2p else 0.0

    dLp = L2 - L1
    dCp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180.0:
        dhp = h2p - h1p
    elif h2p - h1p > 180.0:
        dhp = h2p - h1p - 360.0
    else:
        dhp = h2p - h1p + 360.0
    dHp = 2.0 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp) / 2.0)

    Lp_bar = (L1 + L2) / 2.0
    Cp_bar = (c1p + c2p) / 2.0
    if c1p * c2p == 0:
        hp_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        hp_bar = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        hp_bar = (h1p + h2p + 360.0) / 2.0
    else:
        hp_bar = (h1p + h2p - 360.0) / 2.0

    t = (
        1.0
        - 0.17 * math.cos(math.radians(hp_bar - 30.0))
        + 0.24 * math.cos(math.radians(2.0 * hp_bar))
        + 0.32 * math.cos(math.radians(3.0 * hp_bar + 6.0))
        - 0.20 * math.cos(math.radians(4.0 * hp_bar - 63.0))
    )
    d_theta = 30.0 * math.exp(-(((hp_bar - 275.0) / 25.0) ** 2))
    r_c = 2.0 * math.sqrt(Cp_bar ** 7 / (Cp_bar ** 7 + 25.0 ** 7))
    s_l = 1.0 + (0.015 * (Lp_bar - 50.0) ** 2) / math.sqrt(20.0 + (Lp_bar - 50.0) ** 2)
    s_c = 1.0 + 0.045 * Cp_bar
    s_h = 1.0 + 0.015 * Cp_bar * t
    r_t = -math.sin(math.radians(2.0 * d_theta)) * r_c
    return math.sqrt(
        (dLp / s_l) ** 2 + (dCp / s_c) ** 2 + (dHp / s_h) ** 2 + r_t * (dCp / s_c) * (dHp / s_h)
    )


def delta_e(c1: RGBA, c2: RGBA) -> float:
    return ciede2000(srgb_to_lab(c1), srgb_to_lab(c2))


# ---------------------------------------------------------------- WCAG

def relative_luminance(rgba: RGBA) -> float:
    """WCAG 2.2 の relative luminance（しきい値 0.04045）。"""
    r, g, b = (_gamma_decode(c) for c in (rgba.r, rgba.g, rgba.b))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def composite(fg: RGBA, bg: RGBA) -> RGBA:
    """半透明の fg を不透明の bg の上に重ねた見た目の色（sRGB 値で線形補間し 8bit に丸める。ブラウザの既定と同じ）。"""
    a = fg.a

    def mix(f: float, b: float) -> float:
        return round((f * a + b * (1 - a)) * 255) / 255  # ブラウザと同じく 8bit に丸める

    return RGBA(mix(fg.r, bg.r), mix(fg.g, bg.g), mix(fg.b, bg.b), 1.0)


def contrast_ratio(fg: RGBA, bg: RGBA) -> float:
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _self_test() -> None:
    # Sharma ら (2005) の検証データから2組
    assert abs(ciede2000((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485)) - 2.0425) < 1e-4
    assert abs(ciede2000((50.0, 2.5, 0.0), (73.0, 25.0, -18.0)) - 27.1492) < 1e-4
    assert abs(contrast_ratio(parse_color("#000"), parse_color("#fff")) - 21.0) < 1e-9
    assert parse_color("rgb(255 0 0 / 50%)") == RGBA(1.0, 0.0, 0.0, 0.5)
    white = parse_color("oklch(1 0 0)")
    assert white is not None and white.hex() == "#ffffff"
    assert parse_color("oklch(58.5% 0.233 277.117)").hex() == "#615fff"  # Tailwind v4 indigo-500 の sRGB 近似（範囲外は切り詰め）


if __name__ == "__main__":
    _self_test()
    print("colorlib self-test OK")
