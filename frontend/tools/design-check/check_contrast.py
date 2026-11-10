"""色のペアの WCAG 2.2 コントラスト比を計算し、AA を満たすかを判定する。

基準（WCAG 2.2 達成基準 1.4.3 / 1.4.11）:
  body  … 本文（通常の文字）           4.5:1 以上
  large … 大きい文字（24px 以上、または 18.66px 以上かつ太字 700 以上）  3:1 以上
  ui    … UI 部品の境界・アイコン・フォーカス表示など文字以外   3:1 以上
比は丸めずに判定する（4.499 は不合格）。表示は小数2桁で切り捨て（2.996 は 2.99 と出す）。

入力（どれか1つ以上）:
  1. JSON:  {"tokens": {"ink": "#1c2422", ...}, "pairs": [{"fg": "ink", "bg": "#f2f5f3", "use": "body", "label": "本文"}]}
            pairs だけのリストでもよい。fg / bg はトークン名か色そのもの。
  2. DESIGN.md:
     - YAML frontmatter の colors をトークンに、components の backgroundColor と textColor の組をペアにする
       （component の typography が大きい文字なら large）。frontmatter を読むには PyYAML が要る:
       uv run --with pyyaml python check_contrast.py DESIGN.md
     - 本文の表で「前景（fg）」「背景（bg）」「用途（use）」の列を持つものもペアとして読む。
       用途: 本文/body → body、大きい文字/large → large、UI/部品/アイコン/枠線/フォーカス/ui → ui
     - frontmatter が無い場合、表の行に色が1つだけ書いてあれば「先頭のセル＝トークン名」として読む。
  3. コマンドライン: --pair 前景 背景 [--use body|large|ui]

使い方:
  uv run --with pyyaml python check_contrast.py DESIGN.md
  uv run python check_contrast.py pairs.json --json
  uv run python check_contrast.py --pair "#5b6764" "#f2f5f3" --use body
終了コード: 0 = すべて合格 / 1 = 不合格あり / 2 = 入力の誤り（読めない色、未定義のトークン、ペアが無い など）
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import colorlib as cl  # noqa: E402

AA_MIN = {"body": 4.5, "large": 3.0, "ui": 3.0}
AAA_MIN = {"body": 7.0, "large": 4.5, "ui": None}
LARGE_PX = 24.0
LARGE_BOLD_PX = 18.66
BOLD_WEIGHT = 700
USE_WORDS = {
    "body": ("本文", "body", "text", "通常", "小さい文字", "normal"),
    "large": ("大きい文字", "大", "large", "見出し"),
    "ui": ("ui", "部品", "アイコン", "枠線", "境界", "フォーカス", "icon", "border", "focus", "非テキスト"),
}
FG_HEADERS = ("前景", "文字色", "fg", "foreground", "text", "テキスト")
BG_HEADERS = ("背景", "bg", "background", "地")
USE_HEADERS = ("用途", "use", "種類", "kind")


class InputError(Exception):
    pass


@dataclass
class Pair:
    label: str
    fg: str
    bg: str
    use: str
    source: str


@dataclass
class Result:
    label: str
    use: str
    fg: str
    bg: str
    fg_hex: str
    bg_hex: str
    ratio: float
    aa_min: float
    aa: bool
    aaa: bool | None
    note: str
    source: str


# ---------------------------------------------------------------- 入力の読み取り

def parse_use(text: str) -> str:
    t = text.strip().lower()
    for use, words in USE_WORDS.items():
        if any(w.lower() in t for w in words):
            return use
    raise InputError(f"用途「{text}」が分からない（本文/body・大きい文字/large・UI/ui のどれか）")


def flatten_colors(obj, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}{k}"
            if isinstance(v, dict):
                out.update(flatten_colors(v, key + "."))
            else:
                out[key] = str(v)
                out[key.replace(".", "-")] = str(v)
    return out


def resolve(value: str, tokens: dict[str, str], depth: int = 0) -> cl.RGBA:
    v = str(value).strip().strip('"').strip("'")
    ref = re.fullmatch(r"\{\s*colors\.([\w.-]+)\s*\}", v) or re.fullmatch(r"colors\.([\w.-]+)", v)
    name = ref.group(1) if ref else v
    if name in tokens and depth < 10:
        return resolve(tokens[name], tokens, depth + 1)
    rgba = cl.parse_color(v)
    if rgba is None:
        raise InputError(f"色「{value}」を読めない（未定義のトークンか、対応していない表記）")
    return rgba


def font_px(value) -> float | None:
    if value is None:
        return None
    m = re.fullmatch(r"\s*([\d.]+)\s*(px|rem|em)?\s*", str(value))
    if not m:
        return None
    n = float(m.group(1))
    return n * 16.0 if m.group(2) in ("rem", "em") else n


def is_large(typo: dict | None) -> bool:
    if not isinstance(typo, dict):
        return False
    px = font_px(typo.get("fontSize"))
    w = str(typo.get("fontWeight", "400")).strip().lower()
    weight = int(w) if w.isdigit() else (BOLD_WEIGHT if w == "bold" else 400)
    if px is None:
        return False
    return px >= LARGE_PX or (px >= LARGE_BOLD_PX and weight >= BOLD_WEIGHT)


def split_frontmatter(text: str) -> tuple[str | None, str]:
    m = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", text, re.S)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def md_tables(body: str):
    """Markdown の表を (見出しのセル, [行のセル...]) で返す。"""
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            header = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                j += 1
            yield header, rows
            i = j
        else:
            i += 1


def find_col(header: list[str], names: tuple[str, ...]) -> int | None:
    for idx, h in enumerate(header):
        hl = h.lower()
        if any(n.lower() in hl for n in names):
            return idx
    return None


def strip_md(cell: str) -> str:
    return re.sub(r"[`*]", "", cell).strip()


def load_design_md(path: Path) -> tuple[dict[str, str], list[Pair]]:
    text = path.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    tokens: dict[str, str] = {}
    pairs: list[Pair] = []
    if fm is not None:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as e:
            raise InputError("frontmatter を読むには PyYAML が要る: uv run --with pyyaml python check_contrast.py …") from e
        try:
            data = yaml.safe_load(fm) or {}
        except yaml.YAMLError as e:
            raise InputError(f"{path} の frontmatter を YAML として読めない: {e}") from e
        tokens.update(flatten_colors(data.get("colors") or {}))
        typography = data.get("typography") or {}
        for name, comp in (data.get("components") or {}).items():
            if not isinstance(comp, dict) or "backgroundColor" not in comp or "textColor" not in comp:
                continue
            typo = comp.get("typography")
            if isinstance(typo, str):
                ref = re.fullmatch(r"\{\s*typography\.([\w.-]+)\s*\}", typo.strip())
                typo = typography.get(ref.group(1)) if ref else None
            use = "large" if is_large(typo) else "body"
            pairs.append(Pair(f"components.{name}", str(comp["textColor"]), str(comp["backgroundColor"]), use, f"{path.name} frontmatter"))
    for header, rows in md_tables(body):
        fg_i, bg_i = find_col(header, FG_HEADERS), find_col(header, BG_HEADERS)
        use_i = find_col(header, USE_HEADERS)
        if fg_i is not None and bg_i is not None:
            for r in rows:
                if max(fg_i, bg_i) >= len(r):
                    continue
                use = parse_use(r[use_i]) if use_i is not None and use_i < len(r) and r[use_i] else "body"
                label = f"表: {strip_md(r[fg_i])} / {strip_md(r[bg_i])}"
                pairs.append(Pair(label, strip_md(r[fg_i]), strip_md(r[bg_i]), use, f"{path.name} 本文の表"))
            continue
        for r in rows:
            found = [c for cell in r for c in cl.find_colors(cell)]
            if len(found) == 1 and r and strip_md(r[0]) and strip_md(r[0]) not in tokens:
                tokens[strip_md(r[0])] = found[0].raw
    return tokens, pairs


def load_json(path: Path) -> tuple[dict[str, str], list[Pair]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise InputError(f"{path} を JSON として読めない: {e}") from e
    tokens = {}
    items = data
    if isinstance(data, dict):
        tokens = flatten_colors(data.get("tokens") or data.get("colors") or {})
        items = data.get("pairs", [])
    pairs = []
    for i, p in enumerate(items):
        if not isinstance(p, dict) or "fg" not in p or "bg" not in p:
            raise InputError(f"{path} の pairs[{i}] に fg と bg が無い")
        use = parse_use(p.get("use", "body"))
        pairs.append(Pair(p.get("label", f"pairs[{i}]"), str(p["fg"]), str(p["bg"]), use, path.name))
    return tokens, pairs


# ---------------------------------------------------------------- 判定

def evaluate(pair: Pair, tokens: dict[str, str], base: cl.RGBA) -> Result:
    fg, bg = resolve(pair.fg, tokens), resolve(pair.bg, tokens)
    notes = []
    if bg.a < 1.0:
        bg = cl.composite(bg, base)
        notes.append(f"背景が半透明なので {base.hex()} の上に重ねて計算")
    if fg.a < 1.0:
        fg = cl.composite(fg, bg)
        notes.append("前景が半透明なので背景に重ねて計算")
    ratio = cl.contrast_ratio(fg, bg)
    aa_min = AA_MIN[pair.use]
    aaa_min = AAA_MIN[pair.use]
    return Result(pair.label, pair.use, pair.fg, pair.bg, fg.hex(), bg.hex(), ratio, aa_min, ratio >= aa_min,
                  None if aaa_min is None else ratio >= aaa_min, "；".join(notes), pair.source)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="WCAG 2.2 のコントラスト比で AA を判定する")
    ap.add_argument("inputs", nargs="*", help="DESIGN.md か JSON")
    ap.add_argument("--pair", nargs=2, action="append", metavar=("FG", "BG"), help="前景と背景（何度でも）")
    ap.add_argument("--use", default="body", help="--pair の用途: body / large / ui（既定 body）")
    ap.add_argument("--base", default="#ffffff", help="背景が半透明のときに下に敷く色（既定 #ffffff）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    tokens: dict[str, str] = {}
    pairs: list[Pair] = []
    try:
        for name in args.inputs:
            path = Path(name)
            if not path.exists():
                raise InputError(f"ファイルが無い: {name}")
            t, p = load_json(path) if path.suffix.lower() == ".json" else load_design_md(path)
            tokens.update(t)
            pairs.extend(p)
        for fg, bg in args.pair or []:
            pairs.append(Pair(f"{fg} / {bg}", fg, bg, parse_use(args.use), "コマンドライン"))
        if not pairs:
            raise InputError("判定するペアが1つも無い（DESIGN.md の components か、前景・背景の列を持つ表か、--pair が要る）")
        base = cl.parse_color(args.base)
        if base is None:
            raise InputError(f"--base の色を読めない: {args.base}")
        results = [evaluate(p, tokens, base) for p in pairs]
    except InputError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2

    fails = [r for r in results if not r.aa]
    if args.json:
        print(json.dumps({"results": [asdict(r) for r in results], "fail": len(fails), "pass": len(results) - len(fails)},
                         ensure_ascii=False, indent=2))
    else:
        use_ja = {"body": "本文", "large": "大きい文字", "ui": "UI 部品"}
        for r in results:
            mark = "合格" if r.aa else "不合格"
            aaa = "" if r.aaa is None else ("（AAA も合格）" if r.aaa else "")
            print(f"[{mark}] {r.label}  {use_ja[r.use]}  {r.fg}({r.fg_hex}) / {r.bg}({r.bg_hex})  "
                  f"比 {math.floor(r.ratio * 100) / 100:.2f}:1  基準 {r.aa_min}:1{aaa}" + (f"  ※{r.note}" if r.note else ""))
        print(f"\n合格 {len(results) - len(fails)} / 不合格 {len(fails)}（全 {len(results)} 組）")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
