"""3つのツールの検出・非検出をまとめて確かめる。

使い方（design フォルダで）:
  uv run --with fonttools --with brotli --with pyyaml python tests/run_tests.py [フォントのフォルダ]
フォントのフォルダを渡さなければ check_font.py の確認は飛ばす（飛ばしたことは表示する）。
終了コード: 0 = 全部合格 / 1 = どれか不合格
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DESIGN = HERE.parent
PY = sys.executable
results: list[tuple[bool, str]] = []


def run(*args: str) -> tuple[int, str]:
    p = subprocess.run([PY, *args], cwd=DESIGN, capture_output=True, text=True, encoding="utf-8")
    return p.returncode, p.stdout + p.stderr


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(("OK  " if ok else "NG  ") + label)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    data = json.loads((DESIGN / "banlist.json").read_text(encoding="utf-8"))

    # 1. 禁止リストの自己点検（JSON と md の一致）
    code, out = run("check_banlist.py", "--self-check")
    check(code == 0, f"banlist.json と banlist.md が一致する（{out.strip().splitlines()[-1]}）")
    md = (DESIGN / "banlist.md").read_text(encoding="utf-8")
    broken = md.replace("| F41 | 要注意 |", "| F41 | 禁止 |").replace("| C03 | 禁止 |", "| C03x | 禁止 |")
    tmp = HERE / "_tmp_broken_banlist.md"
    tmp.write_text(broken, encoding="utf-8")
    try:
        code, out = run("check_banlist.py", "--self-check", "--md", str(tmp))
    finally:
        tmp.unlink()
    check(code == 1 and "F41 の区分が md と違う" in out and "C03 の行が無い" in out,
          "md の区分を変えた・行を消した場合に自己点検が不一致を出す")

    # 2. 違反サンプル: すべての色・パターンの ID と、狙った書体の ID が出る
    code, out = run("check_banlist.py", "--json", "--fail-on", "ban", "tests/bad")
    rep = json.loads(out)
    found = set(rep["summary"]["by_id"])
    want = {c["id"] for c in data["colors"]} | {p["id"] for p in data["patterns"]}
    want |= {"F01", "F02", "F15", "F16", "F17", "F18", "F20", "F32", "F38", "F39", "F40"}
    check(code == 1, f"違反サンプルで終了コード 1（禁止 {rep['summary']['ban']} 件・要注意 {rep['summary']['caution']} 件）")
    check(want <= found, f"違反サンプルで狙った {len(want)} 種の ID がすべて出る（足りない: {sorted(want - found) or 'なし'}）")
    extra = found - want
    check(not extra, f"違反サンプルで狙っていない ID が出ない（余分: {sorted(extra) or 'なし'}）")

    # 3. 違反の無いサンプル: 禁止も要注意も 0、許可マーカーの行は「許可」に回る
    code, out = run("check_banlist.py", "--json", "--fail-on", "caution", "tests/good")
    rep = json.loads(out)
    s = rep["summary"]
    check(code == 0 and s["ban"] == 0 and s["caution"] == 0, f"違反の無いサンプルで 0 件・終了コード 0（禁止 {s['ban']}・要注意 {s['caution']}）")
    check(s["allowed"] == 1, f"許可マーカーの行が1件だけ許可に回る（許可 {s['allowed']} 件）")

    # 4. 代替（2番目以降）なら可の書体は、代替に置いても出ない
    roboto_fallback = [h for h in rep["hits"] if h["id"] in ("F02", "F38")]
    check(not roboto_fallback, "Roboto / Noto Sans JP を代替に置いただけでは出ない")

    # 5. コントラスト
    code, out = run("check_contrast.py", "--json", "tests/contrast/pairs.json")
    res = {r["label"].split("（")[0]: r for r in json.loads(out)["results"]}
    check(code == 1, "コントラストの JSON で不合格があり終了コード 1")
    check(abs(res["黒と白"]["ratio"] - 21.0) < 1e-9, f"黒と白が 21:1（{res['黒と白']['ratio']:.4f}）")
    check(res["#767676 本文"]["aa"] and not res["#777777 本文"]["aa"], "#767676 は本文合格、#777777 は本文不合格")
    check(res["#777777 大きい文字"]["aa"], "#777777 は大きい文字なら合格（3:1）")
    check(res["#949494 枠線"]["aa"] and not res["#959595 枠線"]["aa"], "#949494 は UI 合格、#959595 は UI 不合格（2.99 は丸めない）")
    check(res["半透明の黒 50%"]["fg_hex"] == "#808080", "半透明の前景を背景に重ねて計算する")
    code, out = run("check_contrast.py", "tests/good/DESIGN.md")
    check(code == 0, "DESIGN.md（違反なし）の components と表がすべて合格")
    code, out = run("check_contrast.py", "tests/bad/DESIGN.md")
    check(code == 1 and "不合格 2" in out, "DESIGN.md（違反あり）の2組が不合格")
    code, out = run("check_contrast.py", "--pair", "nosuch", "#fff")
    check(code == 2, "未定義のトークンは黙って通さず終了コード 2")

    # 6. フォント
    font_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if font_dir is None:
        print("--  check_font.py の確認は飛ばした（フォントのフォルダを渡していない）")
    else:
        ttf = font_dir / "BIZUDPGothic-Regular.ttf"
        latin = font_dir / "AtkinsonHyperlegible-latin.woff2"
        subset = font_dir / "NotoSansJP-subset-text.woff2"
        code, out = run("check_font.py", "--json", str(ttf), str(latin), str(subset))
        reps = {Path(r["file"]).name: r for r in json.loads(out)}
        check(code == 0, "フォント3つを読めて終了コード 0")
        biz = reps[ttf.name]
        check(all(c["rate"] == 1.0 for c in biz["coverage"].values()), "BIZ UDPGothic は JIS X 0208 の全区分が 100%")
        check(biz["license"]["kind"].startswith("SIL Open Font License"), "BIZ UDPGothic のライセンスが OFL と出る")
        lat = reps[latin.name]
        check(lat["coverage"]["kanji_level1"]["covered"] == 0 and lat["format"] == "WOFF2", "欧文の woff2 は漢字 0・形式 WOFF2")
        check(lat["metrics"]["measured"]["x_over_cap"] is not None, f"欧文の x/cap が出る（{lat['metrics']['measured']['x_over_cap']}）")
        sub = reps[subset.name]["coverage"]
        check(sub["hiragana"]["covered"] == 3 and sub["katakana"]["covered"] == 1 and sub["kanji_level1"]["covered"] == 1,
              "『あいう亜ア』だけのサブセットで ひらがな3・カタカナ1・第1水準1")
        code, out = run("check_font.py", str(font_dir / "OFL-bizudpgothic.txt"))
        check(code == 2, "フォントでないファイルは終了コード 2")

    bad = [label for ok, label in results if not ok]
    print(f"\n合格 {len(results) - len(bad)} / 不合格 {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
