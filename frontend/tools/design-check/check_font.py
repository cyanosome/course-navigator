"""フォントファイル（woff2 / woff / ttf / otf）を調べる。

出すもの:
  (a) 日本語の収録率: JIS X 0208 の第1水準漢字（16〜47区）・第2水準漢字（48〜84区）・ひらがな（4区）・
      カタカナ（5区）・全角記号（1〜2区）・全角英数（3区）
      文字の一覧は Python の codec（euc_jp と cp932）から機械的に作る。同じ区点に Unicode の割り当てが2通りある文字
      （1区の「～」が U+301C / U+FF5E など）は、どちらかが入っていれば収録とみなす。
  (b) ファイルサイズ（と形式、グリフ数、可変フォントの軸）
  (c) ライセンス情報（name テーブルの著作権・ライセンス説明・ライセンス URL・製造者など）と OS/2 の埋め込み許可（fsType）
  (d) x-height と cap-height（OS/2 の申告値と、x / H のグリフの実測値）とその比

使い方（fonttools をグローバルに入れずに一時的に使う）:
  uv run --with fonttools --with brotli python check_font.py <フォント> [...] [--json] [--missing 20]
終了コード: 0 = 読めた / 2 = 読めないファイルがあった
"""

from __future__ import annotations

import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path

LEVEL1_ROWS = range(16, 48)
LEVEL2_ROWS = range(48, 85)
EXPECTED = {"kanji_level1": 2965, "kanji_level2": 3390, "hiragana": 83, "katakana": 86, "symbols": 147, "alnum": 62}
GROUPS = (
    ("kanji_level1", "第1水準漢字（16〜47区）", LEVEL1_ROWS),
    ("kanji_level2", "第2水準漢字（48〜84区）", LEVEL2_ROWS),
    ("hiragana", "ひらがな（4区）", range(4, 5)),
    ("katakana", "カタカナ（5区）", range(5, 6)),
    ("symbols", "全角記号（1〜2区）", range(1, 3)),
    ("alnum", "全角英数（3区）", range(3, 4)),
)
NAME_IDS = {0: "著作権", 1: "ファミリー名", 2: "サブファミリー", 4: "フルネーム", 5: "バージョン", 7: "商標",
            8: "製造者", 9: "デザイナー", 11: "製造者 URL", 13: "ライセンス説明", 14: "ライセンス URL"}


def _jis_to_sjis(row: int, cell: int) -> bytes:
    j1, j2 = row + 0x20, cell + 0x20
    s1 = (j1 + 1) // 2 + 0x70
    if s1 >= 0xA0:
        s1 += 0x40
    if j1 % 2:
        s2 = j2 + 0x1F + (1 if j2 >= 0x60 else 0)
    else:
        s2 = j2 + 0x7E
    return bytes([s1, s2])


@lru_cache(maxsize=1)
def jis0208_table() -> dict[str, list[tuple[str, set[int]]]]:
    """区点ごとの文字（候補のコードポイントの集合）を、まとまりごとに返す。"""
    table: dict[str, list[tuple[str, set[int]]]] = {key: [] for key, _, _ in GROUPS}
    for key, _label, rows in GROUPS:
        for row in rows:
            for cell in range(1, 95):
                cands: set[int] = set()
                for raw, codec in ((bytes([0xA0 + row, 0xA0 + cell]), "euc_jp"), (_jis_to_sjis(row, cell), "cp932")):
                    try:
                        ch = raw.decode(codec)
                    except UnicodeDecodeError:
                        continue
                    if len(ch) == 1:
                        cands.add(ord(ch))
                if cands:
                    table[key].append((chr(min(cands)), cands))
    counts = {k: len(v) for k, v in table.items()}
    if counts != EXPECTED:
        raise RuntimeError(f"JIS X 0208 の文字数が想定と違う（codec の差の可能性）: {counts} != {EXPECTED}")
    return table


def coverage(cmap: dict[int, str], show_missing: int) -> dict:
    out = {}
    for key, label, _rows in GROUPS:
        chars = jis0208_table()[key]
        missing = [ch for ch, cands in chars if not (cands & cmap.keys())]
        total = len(chars)
        out[key] = {"label": label, "total": total, "covered": total - len(missing),
                    "rate": (total - len(missing)) / total, "missing_sample": "".join(missing[:show_missing])}
    return out


def read_names(font) -> dict[str, str]:
    names: dict[str, str] = {}
    table = font["name"]
    for nid, label in NAME_IDS.items():
        rec = table.getName(nid, 3, 1, 0x409) or table.getName(nid, 1, 0, 0) or table.getDebugName(nid)
        if rec is None:
            continue
        names[label] = str(rec).strip()
    return names


def license_kind(names: dict[str, str]) -> str:
    text = (names.get("ライセンス説明", "") + " " + names.get("ライセンス URL", "")).lower()
    if "open font license" in text or "openfontlicense" in text or "scripts.sil.org/ofl" in text:
        return "SIL Open Font License（OFL）"
    if "apache" in text:
        return "Apache License"
    if "ubuntu font licence" in text:
        return "Ubuntu Font Licence"
    if not text.strip():
        return "name テーブルにライセンスの記載なし（配布元で要確認）"
    return "上記の説明を読んで要確認"


def fs_type(font) -> str:
    if "OS/2" not in font:
        return "OS/2 テーブルなし"
    v = font["OS/2"].fsType
    parts = []
    usage = v & 0x000F
    parts.append({0: "インストール可（制限なし）", 2: "埋め込み不可（Restricted）", 4: "プレビューと印刷のみ",
                  8: "編集可能な埋め込み"}.get(usage, f"不明な値 {usage}"))
    if v & 0x0100:
        parts.append("サブセット化不可")
    if v & 0x0200:
        parts.append("ビットマップ埋め込みのみ")
    return f"{v}（{'、'.join(parts)}）"


def glyph_height(font, char: str) -> float | None:
    from fontTools.pens.boundsPen import BoundsPen

    cmap = font.getBestCmap() or {}
    gname = cmap.get(ord(char))
    if gname is None:
        return None
    gs = font.getGlyphSet()
    pen = BoundsPen(gs)
    gs[gname].draw(pen)
    if pen.bounds is None:
        return None
    return float(pen.bounds[3])  # ベースラインからの上端（yMax）


def metrics(font) -> dict:
    upm = font["head"].unitsPerEm
    os2 = font["OS/2"] if "OS/2" in font else None
    declared_x = getattr(os2, "sxHeight", 0) if os2 is not None and os2.version >= 2 else 0
    declared_cap = getattr(os2, "sCapHeight", 0) if os2 is not None and os2.version >= 2 else 0
    measured_x, measured_cap = glyph_height(font, "x"), glyph_height(font, "H")
    out = {"units_per_em": upm,
           "declared": {"x_height": declared_x or None, "cap_height": declared_cap or None},
           "measured": {"x_height": measured_x, "cap_height": measured_cap}}
    for kind in ("declared", "measured"):
        xh, cap = out[kind]["x_height"], out[kind]["cap_height"]
        out[kind]["x_over_cap"] = round(xh / cap, 4) if xh and cap else None
        out[kind]["x_over_em"] = round(xh / upm, 4) if xh else None
        out[kind]["cap_over_em"] = round(cap / upm, 4) if cap else None
    return out


def inspect(path: Path, show_missing: int) -> dict:
    from fontTools.ttLib import TTFont

    font = TTFont(str(path), lazy=False, fontNumber=0)
    cmap = font.getBestCmap() or {}
    axes = [f"{a.axisTag} {a.minValue:g}〜{a.maxValue:g}" for a in font["fvar"].axes] if "fvar" in font else []
    names = read_names(font)
    return {
        "file": str(path),
        "size_bytes": path.stat().st_size,
        "format": {"woff2": "WOFF2", "woff": "WOFF"}.get(font.flavor or "", "TrueType" if "glyf" in font else "OpenType (CFF)"),
        "glyphs": font["maxp"].numGlyphs,
        "cmap_chars": len(cmap),
        "variable_axes": axes,
        "coverage": coverage(cmap, show_missing),
        "license": {"kind": license_kind(names), "fsType": fs_type(font), "names": names},
        "metrics": metrics(font),
    }


def print_report(r: dict) -> None:
    kb = r["size_bytes"] / 1024
    print(f"== {r['file']}")
    print(f"(b) サイズ: {r['size_bytes']:,} バイト（{kb:,.1f} KB / {kb / 1024:,.2f} MB）  形式 {r['format']}  "
          f"グリフ {r['glyphs']:,}  文字の割り当て {r['cmap_chars']:,}" + (f"  可変軸 {', '.join(r['variable_axes'])}" if r["variable_axes"] else ""))
    print("(a) JIS X 0208 の収録率")
    for c in r["coverage"].values():
        miss = f"  欠け例: {c['missing_sample']}" if c["missing_sample"] else ""
        print(f"    {c['label']:<16} {c['covered']:>5} / {c['total']:<5} {c['rate'] * 100:6.2f}%{miss}")
    lic = r["license"]
    print(f"(c) ライセンス: {lic['kind']}  埋め込み許可 fsType={lic['fsType']}")
    for k, v in lic["names"].items():
        print(f"    {k}: {v[:160]}{'…' if len(v) > 160 else ''}")
    m = r["metrics"]
    print(f"(d) 字面の高さ（unitsPerEm {m['units_per_em']}）")
    for kind, label in (("declared", "OS/2 の申告値"), ("measured", "x と H のグリフ実測")):
        d = m[kind]
        if d["x_height"] is None or d["cap_height"] is None:
            print(f"    {label}: 取れない（x={d['x_height']} H={d['cap_height']}）")
            continue
        print(f"    {label}: x-height {d['x_height']:g} / cap-height {d['cap_height']:g} → x/cap = {d['x_over_cap']:.3f}"
              f"（x/em {d['x_over_em']:.3f}・cap/em {d['cap_over_em']:.3f}）")
    print()


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="フォントの日本語収録率・サイズ・ライセンス・x-height/cap-height を出す")
    ap.add_argument("fonts", nargs="+", help="woff2 / woff / ttf / otf")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--missing", type=int, default=20, help="欠けている文字を何文字まで例示するか（既定 20）")
    args = ap.parse_args(argv)
    try:
        import fontTools  # noqa: F401
    except ImportError:
        print("エラー: fonttools が無い。uv run --with fonttools --with brotli python check_font.py … で実行する", file=sys.stderr)
        return 2

    reports, failed = [], 0
    for name in args.fonts:
        path = Path(name)
        try:
            if not path.is_file():
                raise FileNotFoundError(f"ファイルが無い: {name}")
            reports.append(inspect(path, args.missing))
        except Exception as e:  # noqa: BLE001 — fontTools は壊れたファイルで様々な例外を出すので、ここで1件ずつ報告する
            failed += 1
            print(f"エラー: {name} を読めない: {type(e).__name__}: {e}", file=sys.stderr)
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        for r in reports:
            print_report(r)
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
