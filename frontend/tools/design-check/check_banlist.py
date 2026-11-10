"""禁止リスト（banlist.json）に当たる書体・色・見た目のパターンを、CSS / HTML / TSX / Markdown から拾う。

使い方:
  uv run python check_banlist.py <ファイルかフォルダ> [...]          違反の一覧と件数を出す
  uv run python check_banlist.py --json <パス> [...]                 機械向けの JSON で出す
  uv run python check_banlist.py --fail-on caution <パス>            要注意でも終了コード 1 にする
  uv run python check_banlist.py --self-check                        banlist.json と banlist.md の一致を確かめる

終了コード: 0 = 禁止なし / 1 = 禁止あり（--fail-on caution なら要注意も） / 2 = 使い方やデータの誤り
行に `banlist:allow` と書くと、その行の検出は「許可」に回る（件数には数えないが、一覧には必ず出す）。
外部パッケージは使わない。
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent))
import colorlib as cl  # noqa: E402

HERE = Path(__file__).resolve().parent
DEFAULT_BANLIST = HERE / "banlist.json"
DEFAULT_MD = HERE / "banlist.md"
SKIP_DIRS = {"node_modules", ".git", ".next", "dist", "build", ".venv", "_evidence", "_fonts_download"}
ALLOW_MARKER = "banlist:allow"
SEVERITIES = ("ban", "caution")

GENERIC_FAMILIES = {
    "serif", "sans-serif", "sans serif", "monospace", "cursive", "fantasy", "system-ui", "system ui",
    "ui-serif", "ui serif", "ui-sans-serif", "ui sans serif", "ui-monospace", "ui monospace",
    "ui-rounded", "ui rounded", "math", "emoji", "fangsong", "inherit", "initial", "unset", "revert",
}
SERIF_GENERICS = {"serif", "ui serif"}
SANS_GENERICS = {"sans serif", "ui sans serif", "system ui"}
MONO_GENERICS = {"monospace", "ui monospace"}
SYSTEM_FAMILIES = {
    "system ui", "apple system", "blinkmacsystemfont", "segoe ui", "segoe ui variable", "roboto",
    "helvetica neue", "helvetica", "arial", "hiragino sans", "hiragino kaku gothic pron",
    "hiragino kaku gothic pro", "ヒラギノ角ゴ pron", "ヒラギノ角ゴ pro", "ヒラギノ角ゴシック",
    "yu gothic", "yu gothic ui", "yugothic", "游ゴシック", "游ゴシック体", "meiryo", "メイリオ",
    "noto sans cjk jp", "ms pgothic", "ms gothic", "ｍｓ ｐゴシック", "osaka", "apple color emoji",
    "segoe ui emoji", "segoe ui symbol", "noto color emoji", "hiragino mincho pron", "yu mincho",
    "yumincho", "游明朝", "游明朝体", "ms mincho", "georgia", "times new roman", "times",
}

TW_PALETTE_OTHER = "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|pink|rose|fuchsia"
TW_COLOR_PREFIX = r"(?:bg|text|border|border-[trblxyse]|ring|ring-offset|outline|fill|stroke|shadow|decoration|accent|caret|divide|placeholder)"
TW_SHADES = r"(?:50|[1-9]00|950)"

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF"
    "\U0001FA70-\U0001FAFF\U0001F1E6-\U0001F1FF]"
    "|[←-⇿⌀-⏿☀-➿⬀-⯿]️"
    "|[✅✨❌❎❓❔❕❗⚡⭐⭕⏰⏳⌚⌛"
    "☔☕⚽⚾⛄⛅⛔⛪⛲⛳⛵⛺⛽➕➖➗"
    "➰➿⬛⬜♿⚓⚪⚫⛎✊✋♈-♓]"
)


# ---------------------------------------------------------------- データ構造

@dataclass
class Hit:
    file: str
    line: int
    col: int
    kind: str  # font / color / pattern
    id: str
    name: str
    severity: str
    detail: str
    allowed: bool = False


@dataclass
class Stack:
    offset: int
    families: list[str]
    source: str


class Doc:
    """1ファイル分の本文と、位置 → 行・列の変換。"""

    def __init__(self, path: Path, text: str, kind: str) -> None:
        self.path = path
        self.text = text
        self.kind = kind
        self.line_starts = [0] + [m.end() for m in re.finditer(r"\n", text)]
        self.lines = text.split("\n")
        # 画面に出る文字を見る検出（P06 P12 P13 P14 P26）用。コメントの中身を空白にする（位置と改行は保つ）
        self.masked = text if kind == "md" else mask_comments(text)
        self.masked_lines = self.masked.split("\n")

    def pos(self, offset: int) -> tuple[int, int]:
        idx = bisect.bisect_right(self.line_starts, offset) - 1
        return idx + 1, offset - self.line_starts[idx] + 1

    def line_text(self, line: int) -> str:
        return self.lines[line - 1] if 0 < line <= len(self.lines) else ""


# ---------------------------------------------------------------- 共通の小道具

def norm_family(name: str) -> str:
    n = name.strip().strip("'\"`").strip()
    n = re.sub(r"\s*!important$", "", n)
    return re.sub(r"[_+\-\s]+", " ", n).strip().lower()


def split_families(value: str) -> list[str]:
    """'"Noto Sans JP", sans-serif' → ['Noto Sans JP', 'sans-serif']（引用符の中のカンマは区切らない）。"""
    out, buf, quote = [], [], ""
    for ch in value:
        if quote:
            if ch == quote:
                quote = ""
            else:
                buf.append(ch)
            continue
        if ch in "'\"`":
            quote = ch
        elif ch == ",":
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf).strip())
    return [re.sub(r"\s*!important$", "", f).strip() for f in out if f.strip()]


def balanced(text: str, open_idx: int, open_ch: str = "(", close_ch: str = ")") -> int:
    """text[open_idx] が開き括弧のとき、対応する閉じ括弧の位置を返す（見つからなければ文末）。"""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return len(text) - 1


def css_blocks(text: str):
    """最も内側の `selector { body }` を (selector, body, body_offset) で返す（線形時間）。"""
    for m in re.finditer(r"\{([^{}]*)\}", text):
        sel_start = max(text.rfind("}", 0, m.start()), text.rfind("{", 0, m.start()), text.rfind(";", 0, m.start())) + 1
        selector = re.sub(r"/\*.*?\*/", " ", text[sel_start:m.start()], flags=re.S)
        yield selector, m.group(1), m.start(1)


def mask_comments(text: str) -> str:
    """/* */・<!-- -->・行末までの // コメントの中身を空白にする（URL の :// は残す）。"""
    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    text = re.sub(r"/\*.*?\*/|<!--.*?-->", blank, text, flags=re.S)
    return re.sub(r"(?<![:\w\"'(])//[^\n]*", blank, text)


def tw_strings(doc: Doc) -> list[tuple[int, str]]:
    """Tailwind のクラスが書かれうる文字列を集める（class / className 属性、@apply、cn()/clsx()、md のコード片）。"""
    out: list[tuple[int, str]] = []
    pat = re.compile(r"\bclass(?:Name)?\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|\{\s*`([^`]*)`\s*\}|\{\s*\"([^\"]*)\"\s*\}|\{\s*'([^']*)'\s*\})")
    for m in pat.finditer(doc.text):
        for g in range(1, 6):
            if m.group(g) is not None:
                out.append((m.start(g), m.group(g)))
    for m in re.finditer(r"@apply\s+([^;}\n]+)", doc.text):
        out.append((m.start(1), m.group(1)))
    for m in re.finditer(r"\b(?:cn|clsx|cva|twMerge|classNames|tw)\s*\(", doc.text):
        end = balanced(doc.text, m.end() - 1)
        for s in re.finditer(r"\"([^\"]*)\"|'([^']*)'|`([^`]*)`", doc.text[m.end():end]):
            g = next(i for i in (1, 2, 3) if s.group(i) is not None)
            out.append((m.end() + s.start(g), s.group(g)))
    if doc.kind == "md":
        for m in re.finditer(r"`([^`\n]+)`", doc.text):
            out.append((m.start(1), m.group(1)))
    return out


def tw_find(doc: Doc, pattern: str) -> list[tuple[int, str]]:
    """Tailwind の文字列の中で pattern に当たるトークンを (位置, トークン) で返す。"""
    rx = re.compile(pattern)
    hits = []
    for off, s in tw_strings(doc):
        for m in rx.finditer(s):
            hits.append((off + m.start(), m.group(0)))
    return hits


# ---------------------------------------------------------------- 書体

def extract_stacks(doc: Doc) -> list[Stack]:
    text = doc.text
    stacks: list[Stack] = []

    def add(offset: int, value: str, source: str) -> None:
        fams = split_families(value)
        if fams:
            stacks.append(Stack(offset, fams, source))

    for m in re.finditer(r"(?<![\w-])font-family\s*:\s*([^;{}\n]+)", text):
        add(m.start(1), m.group(1), "font-family")
    for m in re.finditer(r"(?<![\w-])font\s*:\s*([^;{}\n]+)", text):
        fam = re.search(r"\d[\w.%]*(?:\s*/\s*[\w.%]+)?\s+(.+)$", m.group(1))
        if fam:
            add(m.start(1) + fam.start(1), fam.group(1), "font 一括指定")
    for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;{}\n]+)", text):
        name, value = m.group(1).lower(), m.group(2).strip()
        if re.search(r"size|weight|leading|tracking|line|letter|feature|variation|optical|stretch|style|smooth", name):
            continue
        has_generic = re.search(r"(?<![\w-])(sans-serif|serif|monospace|system-ui|ui-sans-serif|ui-serif|ui-monospace)(?![\w-])", value)
        if has_generic or ("font" in name and value and not value[0].isdigit() and not value.startswith(("var(", "calc(", "clamp("))):
            add(m.start(2), value, "CSS 変数")
    rx_ff = re.compile(r"[\"']?fontFamily[\"']?\s*:\s*(?:\"([^\"]*)\"|'([^']*)'|`([^`]*)`|\[([^\]]*)\]|([^,{}\[\n]+))")
    for m in rx_ff.finditer(text):
        g = next(i for i in range(1, 6) if m.group(i) is not None)
        add(m.start(g), m.group(g), "fontFamily")
    for m in re.finditer(r"fontFamily\s*:\s*\{", text):
        end = balanced(text, m.end() - 1, "{", "}")
        for arr in re.finditer(r"\[([^\]]*)\]", text[m.end():end]):
            add(m.end() + arr.start(1), arr.group(1), "Tailwind fontFamily")
    for m in re.finditer(r"(?<![\w-])font-\[([^\]]+)\]", text):
        value = m.group(1).replace("_", " ")
        if not re.fullmatch(r"[\d.]+", value):
            add(m.start(1), value, "Tailwind font-[…]")
    if doc.kind == "md":
        for m in re.finditer(r"(?<![\w-])(sans-serif|ui-sans-serif|ui-serif|serif|ui-monospace|monospace|system-ui)(?![\w-])", text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            seg_start = max(text.rfind(d, line_start, m.start()) for d in ("|", "`", ":", "：", "(", "（", "="))
            seg_start = seg_start + 1 if seg_start >= line_start else line_start
            seg = text[seg_start:m.end()]
            fams = split_families(seg)
            if len(fams) >= 2 and norm_family(fams[-1]) in GENERIC_FAMILIES:
                stacks.append(Stack(seg_start, fams, "md の書体指定"))
    seen, unique = set(), []
    for st in stacks:
        key = (doc.pos(st.offset)[0], tuple(norm_family(f) for f in st.families))
        if key not in seen:
            seen.add(key)
            unique.append(st)
    return unique


def extract_loads(doc: Doc) -> list[tuple[int, str, str]]:
    """Web フォントとして読み込んでいる書体: (位置, 名前, 読み込み方)。"""
    text = doc.text
    loads: list[tuple[int, str, str]] = []
    for m in re.finditer(r"fonts\.googleapis\.com/css2?\?[^\"'\s)>]+", text):
        for fm in re.finditer(r"family=([^&:\"'\s)>]+)", m.group(0)):
            loads.append((m.start() + fm.start(1), unquote_plus(fm.group(1)), "Google Fonts の URL"))
    for m in re.finditer(r"import\s*\{([^}]+)\}\s*from\s*[\"']next/font/google[\"']", text):
        for name in m.group(1).split(","):
            name = name.strip().split(" as ")[0].strip()
            if name:
                loads.append((m.start(1), name.replace("_", " "), "next/font/google"))
    for m in re.finditer(r"[\"']@fontsource(?:-variable)?/([\w-]+)", text):
        loads.append((m.start(1), m.group(1).replace("-", " "), "@fontsource"))
    for m in re.finditer(r"api\.fontshare\.com/v2/css\?[^\"'\s)>]+", text):
        for fm in re.finditer(r"f\[\]=([\w-]+)", m.group(0)):
            loads.append((m.start() + fm.start(1), fm.group(1).replace("-", " "), "Fontshare"))
    for m in re.finditer(r"@font-face\s*\{([^}]*)\}", text):
        fm = re.search(r"font-family\s*:\s*([^;}]+)", m.group(1))
        if fm:
            loads.append((m.start(1) + fm.start(1), fm.group(1).strip().strip("'\""), "@font-face"))
    return loads


def match_font(fonts: list[dict], name: str) -> dict | None:
    n = norm_family(name)
    for f in fonts:
        if f["_rx"].search(n):
            return f
    return None


def check_fonts(doc: Doc, fonts: list[dict], stacks: list[Stack]) -> list[tuple[int, dict, str]]:
    found: list[tuple[int, dict, str]] = []
    for st in stacks:
        primary = next((i for i, f in enumerate(st.families)
                        if norm_family(f) not in GENERIC_FAMILIES and not f.strip().startswith("var(")), None)
        for i, fam in enumerate(st.families):
            f = match_font(fonts, fam)
            if f is None:
                continue
            if f["match"] == "primary" and i != primary:
                continue
            where = "先頭" if i == primary else f"{i + 1}番目"
            found.append((st.offset, f, f"{st.source}（{where}）: {', '.join(st.families)[:120]}"))
    for off, name, how in extract_loads(doc):
        f = match_font(fonts, name)
        if f is not None:
            found.append((off, f, f"Web フォントとして読み込み（{how}）: {name}"))
    if doc.kind == "md":
        for f in fonts:
            if f["match"] == "primary":
                continue  # 代替に書くのは可の書体は、md の書体指定（先頭かどうか）でだけ判定する
            for m in f["_mention_rx"].finditer(doc.text):
                found.append((m.start(), f, f"md に記載: {m.group(0)}"))
    return found


# ---------------------------------------------------------------- 色

def check_colors(doc: Doc, groups: list[dict], min_alpha: float) -> list[tuple[int, dict, str]]:
    found = []
    for c in cl.find_colors(doc.text):
        if doc.text[max(0, c.start - 4):c.start].lower() == "url(" or c.rgba.a < min_alpha:
            continue
        lab = cl.srgb_to_lab(c.rgba)
        L, C, H = cl.srgb_to_oklch(c.rgba)
        best = None
        for g in groups:
            gate = g.get("gate")
            if gate:
                lo, hi = gate["oklch_hue"]
                if not (lo <= H <= hi and C >= gate["oklch_chroma_min"] and L >= gate["oklch_l_min"]):
                    continue
            d, idx = min((cl.ciede2000(lab, s["_lab"]), i) for i, s in enumerate(g["swatches"]))
            sw = g["swatches"][idx]
            if d > g["threshold"]:
                continue
            rank = (SEVERITIES.index(g["severity"]), d)
            if best is None or rank < best[0]:
                best = (rank, g, d, sw)
        if best:
            _, g, d, sw = best
            found.append((c.start, g, f"{c.raw} は {sw['hex']}（{sw['label']}）から ΔE00={d:.2f}（しきい値 {g['threshold']}）"))
    return found


# ---------------------------------------------------------------- パターン

def gradients(text: str):
    for m in re.finditer(r"(?:repeating-)?(?:linear|radial|conic)-gradient\(", text):
        end = balanced(text, m.end() - 1)
        yield m.start(), text[m.end():end]


def classify_stop(rgba: cl.RGBA) -> str | None:
    if rgba.a < 0.2:
        return None
    _, C, H = cl.srgb_to_oklch(rgba)
    if C < 0.10:
        return None
    if 268 <= H <= 330:
        return "purple"
    if 35 <= H <= 80:
        return "orange"
    if H > 330 or H < 20:
        return "pink"
    return None


def det_glass(doc: Doc):
    for m in re.finditer(r"(?<![\w-])(?:-webkit-)?backdrop-filter\s*:(?!\s*none\b)\s*[^;{}\n]+", doc.text):
        yield m.start(), m.group(0).strip()
    for m in re.finditer(r"\b(?:Webkit)?[bB]ackdropFilter\s*:\s*[\"'`](?!none)", doc.text):
        yield m.start(), m.group(0)
    for off, tok in tw_find(doc, r"(?<![\w-])(?:[\w-]+:)*backdrop-(?:blur|saturate|brightness|contrast|filter)(?:-[\w\[\].%-]+)?(?![\w-])"):
        yield off, tok


def det_gradient_text(doc: Doc):
    for _sel, body, off in css_blocks(doc.text):
        clip = re.search(r"(?:-webkit-)?background-clip\s*:\s*text", body)
        if clip and "gradient(" in body:
            yield off + clip.start(), "background-clip: text とグラデーションが同じ指定にある"
    for m in re.finditer(r"\b(?:Webkit)?[bB]ackgroundClip\s*:\s*[\"']text[\"']", doc.text):
        if "gradient(" in doc.text[max(0, m.start() - 400): m.end() + 400]:
            yield m.start(), "backgroundClip: 'text' の近くにグラデーション"
    for off, s in tw_strings(doc):
        toks = s.split()
        if any(re.fullmatch(r"(?:[\w-]+:)*bg-clip-text", t) for t in toks) and any(
            re.match(r"(?:[\w-]+:)*(?:bg-gradient-to-|bg-linear-|bg-radial|bg-conic|from-)", t) for t in toks
        ):
            yield off, "bg-clip-text とグラデーションのクラスが同じ要素にある"


def det_purple_gradient(doc: Doc):
    for off, body in gradients(doc.text):
        stops = [c for c in cl.find_colors(body, named=True) if classify_stop(c.rgba) == "purple"]
        if stops:
            yield off, f"紫系の色を含むグラデーション: {stops[0].raw}"
    for off, tok in tw_find(doc, r"(?<![\w-])(?:[\w-]+:)*(?:from|via|to)-(?:indigo|violet|purple|fuchsia)-" + TW_SHADES + r"(?:/\d+)?(?![\w-])"):
        yield off, f"Tailwind のグラデーション: {tok}"


def det_orange_pink_gradient(doc: Doc):
    for off, body in gradients(doc.text):
        kinds = {classify_stop(c.rgba) for c in cl.find_colors(body, named=True)}
        if {"orange", "pink"} <= kinds:
            yield off, "オレンジとピンクの両方を含むグラデーション"
    for off, s in tw_strings(doc):
        has_o = re.search(r"(?<![\w-])(?:[\w-]+:)*(?:from|via|to)-(?:orange|amber)-\d+", s)
        has_p = re.search(r"(?<![\w-])(?:[\w-]+:)*(?:from|via|to)-(?:pink|rose|fuchsia)-\d+", s)
        if has_o and has_p:
            yield off, f"Tailwind のグラデーション: {has_o.group(0)} と {has_p.group(0)}"


def det_tw_purple(doc: Doc):
    rx = r"(?<![\w-])(?:[\w-]+:)*" + TW_COLOR_PREFIX + r"-(?:indigo|violet|purple)-" + TW_SHADES + r"(?:/\d+)?(?![\w-])"
    for off, tok in tw_find(doc, rx):
        yield off, tok
    for m in re.finditer(r"var\(--color-(?:indigo|violet|purple)-\d+\)", doc.text):
        yield m.start(), m.group(0)


def det_emoji(doc: Doc):
    for m in EMOJI_RE.finditer(doc.masked):
        yield m.start(), f"{m.group(0)}（U+{ord(m.group(0)[0]):04X}）"


def det_sparkles(doc: Doc):
    rx = (r"(?<![\w-])(?:Sparkles?(?:Icon)?|AutoAwesome(?:Icon|Outlined|Rounded|Sharp)?|auto_awesome|IconSparkles|"
          r"PiSparkle\w*|HiSparkles|HiOutlineSparkles|LuSparkles?|TbSparkles|FaWandMagicSparkles|wand-magic-sparkles|"
          r"ph-sparkle|i-lucide-sparkles?|sparkles?-icon)(?![\w-])")
    for m in re.finditer(rx, doc.text):
        yield m.start(), m.group(0)


def det_lucide(doc: Doc):
    rx = (r"(?:from\s*|require\(\s*|import\s*)[\"'](?:lucide-react|lucide-vue(?:-next)?|lucide-svelte|lucide-solid|"
          r"lucide-angular|lucide-preact|lucide-static|lucide|@lucide/[\w-]+)(?:/[^\"']*)?[\"']"
          r"|unpkg\.com/lucide|cdn\.jsdelivr\.net/npm/lucide|data-lucide\s*=|lucide\.createIcons|i-lucide-[\w-]+")
    if doc.kind == "md":
        rx = r"(?i)(?<![\w-])lucide(?:-react|-vue|-svelte)?(?![\w-])"
    for m in re.finditer(rx, doc.text):
        yield m.start(), m.group(0)


def det_shadcn_default(doc: Doc):
    for rx, label in (
        (r"--radius\s*:\s*0?\.625rem", "shadcn/ui 既定の --radius"),
        (r"oklch\(\s*0?\.205\s+0\s+0\s*\)", "shadcn/ui 既定の --primary"),
        (r"oklch\(\s*0?\.145\s+0\s+0\s*\)", "shadcn/ui 既定の --foreground"),
    ):
        for m in re.finditer(rx, doc.text):
            yield m.start(), f"{label}: {m.group(0)}"


def _shadow_layers(value: str) -> list[str]:
    layers, depth, buf = [], 0, []
    for ch in value:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            layers.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    layers.append("".join(buf))
    return layers


def _is_soft_black_shadow(value: str) -> bool:
    for layer in _shadow_layers(value):
        colors = cl.find_colors(layer, named=True)
        if not colors:
            continue
        col = colors[0]
        L, C, _ = cl.srgb_to_oklch(col.rgba)
        if not (L <= 0.35 and C <= 0.03 and 0.03 <= col.rgba.a <= 0.2):
            continue
        rest = layer[: col.start] + layer[col.end:]
        lengths = []
        for n, unit in re.findall(r"(-?\d*\.?\d+)(px|rem|em)?", rest):
            px = float(n) * (16.0 if unit in ("rem", "em") else 1.0)
            lengths.append(px)
        if len(lengths) >= 3 and lengths[2] >= 4:
            return True
    return False


def det_soft_shadow(doc: Doc):
    for m in re.finditer(r"(?<![\w-])box-shadow\s*:\s*([^;{}\n]+)", doc.text):
        if _is_soft_black_shadow(m.group(1)):
            yield m.start(), m.group(0).strip()[:100]
    for m in re.finditer(r"\bboxShadow\s*:\s*[\"'`]([^\"'`]+)", doc.text):
        if _is_soft_black_shadow(m.group(1)):
            yield m.start(), m.group(0)[:100]
    for off, tok in tw_find(doc, r"(?<![\w-])(?:[\w-]+:)*shadow(?:-(?:xs|sm|md|lg|xl|2xl))?(?![\w\[/-])"):
        yield off, f"Tailwind の既定の影: {tok}"
    for off, tok in tw_find(doc, r"(?<![\w-])(?:[\w-]+:)*shadow-\[([^\]]+)\]"):
        if _is_soft_black_shadow(tok.split("[", 1)[1].rstrip("]").replace("_", " ")):
            yield off, tok


def _tracking_is_wide(value: str, unit: str) -> bool:
    v = float(value)
    return v >= (0.8 if unit in ("px", "") else 0.05)


def det_eyebrow(doc: Doc):
    for _sel, body, off in css_blocks(doc.text):
        up = re.search(r"text-transform\s*:\s*uppercase", body)
        ls = re.search(r"letter-spacing\s*:\s*(-?[\d.]+)(em|rem|px)", body)
        if up and ls and _tracking_is_wide(ls.group(1), ls.group(2)):
            yield off + up.start(), f"uppercase ＋ letter-spacing: {ls.group(1)}{ls.group(2)}"
    for m in re.finditer(r"\btextTransform\s*:\s*[\"']uppercase[\"']", doc.text):
        near = doc.text[max(0, m.start() - 300): m.end() + 300]
        ls = re.search(r"letterSpacing\s*:\s*[\"']?(-?[\d.]+)(em|rem|px)?", near)
        if ls and _tracking_is_wide(ls.group(1), ls.group(2) or ""):
            yield m.start(), "textTransform: uppercase ＋ letterSpacing"
    for off, s in tw_strings(doc):
        toks = s.split()
        if not any(re.fullmatch(r"(?:[\w-]+:)*uppercase", t) for t in toks):
            continue
        for t in toks:
            tm = re.fullmatch(r"(?:[\w-]+:)*tracking-(wide|wider|widest|\[([\d.]+)(em|rem|px)\])", t)
            if tm and (tm.group(2) is None or _tracking_is_wide(tm.group(2), tm.group(3))):
                yield off, f"uppercase ＋ {t}"
                break


def _ui_lines(doc: Doc, rx: str, min_count: int = 1):
    """コメントを除いた行ごとに rx を探す（画面に出る文字の検出用）。"""
    for i, line in enumerate(doc.masked_lines, start=1):
        ms = list(re.finditer(rx, line))
        if len(ms) >= min_count:
            yield doc.line_starts[i - 1] + ms[0].start(), doc.line_text(i).strip()[:100]


def det_middot(doc: Doc):
    yield from _ui_lines(doc, r"\s(?:·|&middot;)\s", min_count=2)


def det_arrow(doc: Doc):
    """文字列やリンク・ボタンの『末尾』に付く → だけを拾う（文中の『A → B』は対象外）。"""
    yield from _ui_lines(doc, r"(?:→|&rarr;|\\u2192)\s*(?=</(?:a|button|span|Link|Button)\b|[\"'`]|\{?\s*$)")
    for m in re.finditer(r"content\s*:\s*[\"'](?:[^\"']*\s)?(?:→|\\2192|\\u2192)\s*[\"']", doc.text):
        yield m.start(), m.group(0)


def det_emdash(doc: Doc):
    yield from _ui_lines(doc, r"(?<=\S)\s+(?:—|&mdash;|\\u2014)\s+(?=\S)")


def det_italic_heading(doc: Doc):
    for m in re.finditer(r"<h([1-3])\b[^>]*>(?:(?!</h\1>).){0,600}?<(?:em|i)\b", doc.text, re.S):
        yield m.start(), f"<h{m.group(1)}> の中に斜体"
    for m in re.finditer(r"<h[1-3]\b[^>]*class(?:Name)?\s*=\s*[\"'{][^>]*?(?<![\w-])italic(?![\w-])", doc.text):
        yield m.start(), "見出しに italic クラス"
    for sel, body, off in css_blocks(doc.text):
        if re.search(r"(?:^|[\s,>+~])(?:h[1-3]\b|[.#][\w-]*(?:hero|title|headline|heading|display)[\w-]*)", sel, re.I) and re.search(r"font-style\s*:\s*italic", body):
            yield off, f"{sel.strip()[:60]} に font-style: italic"


def det_side_stripe(doc: Doc):
    for m in re.finditer(r"(?<![\w-])border-(?:left|inline-start|right|inline-end)\s*:\s*(?:[3-9]|1[0-2])(?:\.\d+)?px\s+solid", doc.text):
        yield m.start(), m.group(0)
    for m in re.finditer(r"(?<![\w-])border-(?:left|inline-start)-width\s*:\s*(?:[3-9]|1[0-2])px", doc.text):
        yield m.start(), m.group(0)
    for off, tok in tw_find(doc, r"(?<![\w-])(?:[\w-]+:)*border-(?:l|s|r|e)-(?:4|8|\[(?:[3-9]|1[0-2])px\])(?![\w-])"):
        yield off, tok


def det_transition_all(doc: Doc):
    for m in re.finditer(r"(?<![\w-])transition(?:-property)?\s*:\s*all\b", doc.text):
        yield m.start(), m.group(0)
    for m in re.finditer(r"\btransition\s*:\s*[\"'`]all\b", doc.text):
        yield m.start(), m.group(0)
    for off, tok in tw_find(doc, r"(?<![\w-])(?:[\w-]+:)*transition-all(?![\w-])"):
        yield off, tok


def det_hover_scale(doc: Doc):
    for off, tok in tw_find(doc, r"(?<![\w-])(?:[\w-]+:)*hover:(?:[\w-]+:)*scale-(?:x-|y-)?(?:10[1-9]|110|\[1\.\d+\])(?![\w-])"):
        yield off, tok
    for sel, body, off in css_blocks(doc.text):
        if ":hover" in sel and re.search(r"scale\(\s*1\.(?:0[1-9]|1)|scale\s*:\s*1\.(?:0[1-9]|1)", body):
            yield off, f"{sel.strip()[:60]} で拡大"
    for m in re.finditer(r"whileHover\s*=\s*\{\{\s*scale\s*:\s*1\.(?:0[1-9]|1)", doc.text):
        yield m.start(), m.group(0)


def det_overshoot(doc: Doc):
    rx = r"cubic-bezier\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)"
    for m in re.finditer(rx, doc.text):
        y1, y2 = float(m.group(2)), float(m.group(4))
        if not (0 <= y1 <= 1 and 0 <= y2 <= 1):
            yield m.start(), m.group(0)
    for m in re.finditer(r"\bease\s*:\s*\[\s*[\d.]+\s*,\s*([-\d.]+)\s*,\s*[\d.]+\s*,\s*([-\d.]+)\s*\]", doc.text):
        y1, y2 = float(m.group(1)), float(m.group(2))
        if not (0 <= y1 <= 1 and 0 <= y2 <= 1):
            yield m.start(), m.group(0)


SERIF_NAME = re.compile(r"mincho|明朝|garamond|bodoni|times|tiempos|copernicus|playfair|fraunces|lora|merriweather|newsreader|serif")
SANS_NAME = re.compile(r"gothic|ゴシック|sans|grotesk|grotesque|hiragino kaku|meiryo|メイリオ")


def stack_style(st: Stack) -> str | None:
    fams = [norm_family(f) for f in st.families]
    for f in reversed(fams):
        if f in MONO_GENERICS:
            return "mono"
        if f in SERIF_GENERICS:
            return "serif"
        if f in SANS_GENERICS:
            return "sans"
    first = next((f for f in fams if f not in GENERIC_FAMILIES and not f.startswith("var(")), "")
    if "mono" in first or "code" in first:
        return "mono"
    if "sans" in first or SANS_NAME.search(first):
        return "sans"
    if SERIF_NAME.search(first):
        return "serif"
    return None


def det_serif_sans_pair(doc: Doc, stacks: list[Stack]):
    serif = [s for s in stacks if stack_style(s) == "serif"]
    sans = [s for s in stacks if stack_style(s) == "sans"]
    if serif and sans:
        yield serif[0].offset, f"セリフ系「{serif[0].families[0]}」とサンセリフ系「{sans[0].families[0]}」が同じファイルにある"


def det_tw_default_palette(doc: Doc):
    rx = r"(?<![\w-])(?:[\w-]+:)*(?:" + TW_COLOR_PREFIX[3:-1] + r"|from|via|to)-(?:" + TW_PALETTE_OTHER + r")-" + TW_SHADES + r"(?:/\d+)?(?![\w-])"
    by_line: dict[int, list[tuple[int, str]]] = {}
    for off, tok in tw_find(doc, rx):
        by_line.setdefault(doc.pos(off)[0], []).append((off, tok))
    for m in re.finditer(r"var\(--color-(?:" + TW_PALETTE_OTHER + r")-\d+\)", doc.text):
        by_line.setdefault(doc.pos(m.start())[0], []).append((m.start(), m.group(0)))
    for _line, items in sorted(by_line.items()):
        yield items[0][0], "、".join(t for _, t in items[:6]) + ("…" if len(items) > 6 else "")


def det_any_gradient(doc: Doc):
    for off, body in gradients(doc.text):
        yield off, f"gradient({body.strip()[:60]}…)"
    for off, tok in tw_find(doc, r"(?<![\w-])(?:[\w-]+:)*(?:bg-gradient-to-\w+|bg-linear-[\w\[\]/-]+|bg-radial[\w\[\]/-]*|bg-conic[\w\[\]/-]*)(?![\w-])"):
        yield off, tok


def det_grain(doc: Doc):
    for m in re.finditer(r"feTurbulence|(?<![\w-])(?:grain|film-grain|noise-(?:overlay|texture|bg))(?![\w-])|noise\.(?:svg|png|webp)", doc.text):
        yield m.start(), m.group(0)


def det_fade_up(doc: Doc):
    for m in re.finditer(r"@keyframes\s+([\w-]+)\s*\{", doc.text):
        end = balanced(doc.text, m.end() - 1, "{", "}")
        body = doc.text[m.end():end]
        if re.search(r"opacity\s*:\s*0(?:\.0+)?\s*[;}]", body) and re.search(r"translate(?:Y|3d)?\(", body):
            yield m.start(), f"@keyframes {m.group(1)}（不透明度0から移動）"
    for m in re.finditer(r"initial\s*=\s*\{\{[^}]*opacity\s*:\s*0\b[^}]*\by\s*:\s*-?\d", doc.text):
        yield m.start(), "Framer Motion の initial={{ opacity: 0, y: … }}"
    for off, tok in tw_find(doc, r"(?<![\w-])(?:[\w-]+:)*animate-(?:fade-up|fade-in-up|slide-up|fade-in-bottom)(?![\w-])"):
        yield off, tok


def det_full_viewport(doc: Doc):
    for m in re.finditer(r"(?<![\w-])(?:min-)?height\s*:\s*100(?:vh|dvh|svh|lvh)\b", doc.text):
        yield m.start(), m.group(0)
    for m in re.finditer(r"\bminHeight\s*:\s*[\"']100(?:vh|dvh|svh)", doc.text):
        yield m.start(), m.group(0)
    for off, tok in tw_find(doc, r"(?<![\w-])(?:[\w-]+:)*(?:min-h|h)-(?:screen|dvh|svh|lvh|\[100(?:vh|dvh|svh)\])(?![\w-])"):
        yield off, tok


def det_numbered(doc: Doc):
    yield from _ui_lines(doc, r"(?<![\w/.:\-])0[1-9]\s*(?:/|·|—|–|\|)\s+[^\s\d]")


def det_system_only_stack(doc: Doc, stacks: list[Stack]):
    for st in stacks:
        fams = [norm_family(f) for f in st.families]
        named = [f for f in fams if f not in GENERIC_FAMILIES]
        if not named or any(f.startswith("var(") for f in fams):
            continue
        if stack_style(st) == "mono":
            continue
        if all(f in SYSTEM_FAMILIES for f in named):
            yield st.offset, f"システムフォントだけ: {', '.join(st.families)[:100]}"


DETECTORS = {
    "glass": det_glass, "gradient_text": det_gradient_text, "purple_gradient": det_purple_gradient,
    "orange_pink_gradient": det_orange_pink_gradient, "tw_purple": det_tw_purple, "emoji": det_emoji,
    "sparkles": det_sparkles, "lucide": det_lucide, "shadcn_default": det_shadcn_default,
    "soft_shadow": det_soft_shadow, "eyebrow": det_eyebrow, "middot": det_middot, "arrow": det_arrow,
    "emdash": det_emdash, "italic_heading": det_italic_heading, "side_stripe": det_side_stripe,
    "transition_all": det_transition_all, "hover_scale": det_hover_scale, "overshoot": det_overshoot,
    "serif_sans_pair": det_serif_sans_pair, "tw_default_palette": det_tw_default_palette,
    "any_gradient": det_any_gradient, "grain": det_grain, "fade_up": det_fade_up,
    "full_viewport": det_full_viewport, "numbered": det_numbered, "system_only_stack": det_system_only_stack,
}
NEEDS_STACKS = {"serif_sans_pair", "system_only_stack"}
# 同じ行に禁止のグラデーション系があれば、要注意の P22 は出さない
SUPERSEDED_BY = {"any_gradient": {"gradient_text", "purple_gradient", "orange_pink_gradient"}}


# ---------------------------------------------------------------- 読み込みと実行

class BanlistError(Exception):
    pass


def mention_regex(names: list[str]) -> re.Pattern:
    parts = []
    for n in names:
        esc = re.escape(n)
        esc = re.sub(r"(\\ |_|\\\+|\\-)", r"[\\s_+-]?", esc)
        parts.append(esc)
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(parts) + r")(?![A-Za-z0-9])")


def load_banlist(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise BanlistError(f"{path} を読めない: {e}") from e
    for f in data["fonts"]:
        f["_rx"] = re.compile(f["regex"])
        f["_mention_rx"] = mention_regex(f["mention"])
    for g in data["colors"]:
        for s in g["swatches"]:
            rgba = cl.parse_color(s["hex"])
            if rgba is None:
                raise BanlistError(f"{g['id']} の色 {s['hex']} を読めない")
            s["_lab"] = cl.srgb_to_lab(rgba)
    kinds = {}
    for kind, exts in data["file_kinds"].items():
        for ext in exts:
            kinds["." + ext] = kind
    data["_ext_kind"] = kinds
    return data


def iter_files(paths: list[str], ext_kind: dict[str, str]):
    for p in paths:
        path = Path(p)
        if not path.exists():
            raise BanlistError(f"パスが無い: {p}")
        if path.is_file():
            if path.suffix.lower() not in ext_kind:
                raise BanlistError(f"対象外の拡張子: {p}（対象: {', '.join(sorted(ext_kind))}）")
            yield path
            continue
        for f in sorted(path.rglob("*")):
            if f.is_file() and f.suffix.lower() in ext_kind and not any(part in SKIP_DIRS for part in f.parts):
                yield f


def scan_file(path: Path, data: dict) -> list[Hit]:
    kind = data["_ext_kind"][path.suffix.lower()]
    text = path.read_text(encoding="utf-8", errors="replace")
    doc = Doc(path, text, kind)
    stacks = extract_stacks(doc)
    raw: list[tuple[int, str, str, str, str, str]] = []  # (offset, kind, id, name, severity, detail)

    for off, f, detail in check_fonts(doc, data["fonts"], stacks):
        raw.append((off, "font", f["id"], f["name"], f["severity"], detail))
    for off, g, detail in check_colors(doc, data["colors"], data["color_rules"]["min_alpha"]):
        raw.append((off, "color", g["id"], g["name"], g["severity"], detail))
    for p in data["patterns"]:
        if kind not in p["kinds"]:
            continue
        fn = DETECTORS[p["detector"]]
        results = fn(doc, stacks) if p["detector"] in NEEDS_STACKS else fn(doc)
        for off, detail in results:
            raw.append((off, "pattern", p["id"], p["name"], p["severity"], detail))

    hits: list[Hit] = []
    seen: set[tuple[int, str, str]] = set()
    by_detector = {p["id"]: p["detector"] for p in data["patterns"]}
    ban_lines: dict[int, set[str]] = {}
    for off, k, hid, _n, _s, _d in raw:
        if k == "pattern":
            ban_lines.setdefault(doc.pos(off)[0], set()).add(by_detector[hid])
    for off, k, hid, name, sev, detail in sorted(raw, key=lambda r: r[0]):
        line, col = doc.pos(off)
        sup = SUPERSEDED_BY.get(by_detector.get(hid, ""), set())
        if sup & ban_lines.get(line, set()):
            continue
        key = (line, hid, detail if k == "color" else "")
        if key in seen:
            continue
        seen.add(key)
        hits.append(Hit(str(path), line, col, k, hid, name, sev, detail, ALLOW_MARKER in doc.line_text(line)))
    return hits


def summarize(hits: list[Hit]) -> dict:
    active = [h for h in hits if not h.allowed]
    summary = {"ban": 0, "caution": 0, "allowed": len(hits) - len(active), "by_kind": {}, "by_id": {}}
    for h in active:
        summary[h.severity] += 1
        summary["by_kind"].setdefault(h.severity, {}).setdefault(h.kind, 0)
        summary["by_kind"][h.severity][h.kind] += 1
        summary["by_id"][h.id] = summary["by_id"].get(h.id, 0) + 1
    return summary


def print_report(hits: list[Hit], summary: dict, labels: dict) -> None:
    kind_ja = {"font": "書体", "color": "色", "pattern": "パターン"}
    for h in hits:
        tag = "許可" if h.allowed else labels[h.severity].split("（")[0]
        print(f"{h.file}:{h.line}:{h.col}  [{tag}] {h.id} {kind_ja[h.kind]}: {h.name}")
        print(f"    {h.detail}")
    print()
    for sev in SEVERITIES:
        parts = "・".join(f"{kind_ja[k]} {n}" for k, n in sorted(summary["by_kind"].get(sev, {}).items()))
        print(f"{labels[sev].split('（')[0]}: {summary[sev]} 件" + (f"（{parts}）" if parts else ""))
    print(f"許可マーカー（{ALLOW_MARKER}）で除外: {summary['allowed']} 件")
    if summary["by_id"]:
        print("ID 別: " + "、".join(f"{k} {v}" for k, v in sorted(summary["by_id"].items())))


# ---------------------------------------------------------------- 自己点検（JSON と md の一致）

def self_check(data: dict, md_path: Path) -> list[str]:
    problems: list[str] = []
    ev = set(data["evidence"])
    sections = {"F": data["fonts"], "C": data["colors"], "P": data["patterns"], "M": data["manual_checks"], "N": data["no_evidence"]}
    all_ids = [x["id"] for items in sections.values() for x in items] + list(ev)
    dup = {i for i in all_ids if all_ids.count(i) > 1}
    if dup:
        problems.append(f"ID の重複: {sorted(dup)}")
    for items in (data["fonts"], data["colors"], data["patterns"], data["manual_checks"]):
        for x in items:
            missing = [e for e in x.get("evidence", []) if e not in ev]
            if missing:
                problems.append(f"{x['id']} が存在しない根拠を参照: {missing}")
            if not x.get("evidence"):
                problems.append(f"{x['id']} に根拠が無い")
            if "severity" in x and x["severity"] not in SEVERITIES:
                problems.append(f"{x['id']} の区分が不正: {x['severity']}")
    for p in data["patterns"]:
        if p["detector"] not in DETECTORS:
            problems.append(f"{p['id']} の検出器が無い: {p['detector']}")
        bad = [k for k in p["kinds"] if k not in data["file_kinds"]]
        if bad:
            problems.append(f"{p['id']} の対象種別が不正: {bad}")
    if not md_path.exists():
        return problems + [f"{md_path} が無い"]
    md = md_path.read_text(encoding="utf-8")
    rows = {}
    for line in md.splitlines():
        m = re.match(r"^\|\s*\**([FCPMNE]\d{2})\**\s*\|", line)
        if m:
            rows.setdefault(m.group(1), []).append(line)
    json_ids = set(all_ids)
    for i in sorted(json_ids - set(rows)):
        problems.append(f"banlist.md の表に {i} の行が無い")
    for i in sorted(set(rows) - json_ids):
        problems.append(f"banlist.md にあって banlist.json に無い ID: {i}")
    labels = {"ban": "禁止", "caution": "要注意"}
    for items in (data["fonts"], data["colors"], data["patterns"]):
        for x in items:
            for row in rows.get(x["id"], []):
                cells = [c.strip().strip("*").strip() for c in row.strip().strip("|").split("|")]
                want = labels[x["severity"]]
                if len(cells) < 2 or cells[1] != want:
                    problems.append(f"{x['id']} の区分が md と違う（JSON は {want}、md は {cells[1] if len(cells) > 1 else '?'}）")
    for g in data["colors"]:
        row = " ".join(rows.get(g["id"], []))
        if str(g["threshold"]) not in row:
            problems.append(f"{g['id']} のしきい値 {g['threshold']} が md の行に無い")
        for s in g["swatches"]:
            if s["hex"].lower() not in md.lower():
                problems.append(f"{g['id']} の色 {s['hex']} が md に無い")
    return problems


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="禁止リストに当たる書体・色・パターンを拾う")
    ap.add_argument("paths", nargs="*", help="調べるファイルかフォルダ")
    ap.add_argument("--banlist", type=Path, default=DEFAULT_BANLIST)
    ap.add_argument("--md", type=Path, default=DEFAULT_MD, help="--self-check で突き合わせる banlist.md")
    ap.add_argument("--json", action="store_true", help="JSON で出力する")
    ap.add_argument("--fail-on", choices=["ban", "caution", "never"], default="ban")
    ap.add_argument("--self-check", action="store_true", help="banlist.json と banlist.md の一致を確かめる")
    args = ap.parse_args(argv)

    try:
        data = load_banlist(args.banlist)
    except (BanlistError, KeyError, re.error) as e:
        print(f"エラー: 禁止リストを読めない: {e}", file=sys.stderr)
        return 2

    if args.self_check:
        problems = self_check(data, args.md)
        for p in problems:
            print("NG: " + p)
        n = {k: len(data[k]) for k in ("fonts", "colors", "patterns", "manual_checks", "no_evidence", "evidence")}
        print(f"自己点検: 書体 {n['fonts']}・色 {n['colors']}・パターン {n['patterns']}・目視 {n['manual_checks']}・"
              f"根拠なし {n['no_evidence']}・根拠 {n['evidence']} 件 → " + ("OK" if not problems else f"不一致 {len(problems)} 件"))
        return 0 if not problems else 1

    if not args.paths:
        ap.error("調べるパスを1つ以上指定する（または --self-check）")
    try:
        files = list(iter_files(args.paths, data["_ext_kind"]))
    except BanlistError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    if not files:
        print("エラー: 対象のファイルが1つも無い", file=sys.stderr)
        return 2

    hits: list[Hit] = []
    for f in files:
        hits.extend(scan_file(f, data))
    summary = summarize(hits)
    if args.json:
        print(json.dumps({"files": [str(f) for f in files], "summary": summary, "hits": [asdict(h) for h in hits]},
                         ensure_ascii=False, indent=2))
    else:
        print(f"対象 {len(files)} ファイル\n")
        print_report(hits, summary, data["severity_labels"])
    if args.fail_on == "never":
        return 0
    failing = summary["ban"] + (summary["caution"] if args.fail_on == "caution" else 0)
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
