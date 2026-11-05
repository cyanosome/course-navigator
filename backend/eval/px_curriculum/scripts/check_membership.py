"""PDF 上の科目名（●付き）の座標と、リポに手で書かれたグループ枠 bbox を照合する。

リポの PAGE_6_GROUPS_DEF は所属科目を手で列挙している。PDF の文字位置から見た所属と一致するかを確かめる。
"""
import sys
import json
import re
from pathlib import Path

PX = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PX / "code" / "ingestion"))

import pdfplumber  # noqa: E402
from src.transformers.kansai.curriculum_tree_parser import PAGE_6_GROUPS_DEF, normalize_title  # noqa: E402

PDF = PX / "data_raw" / "2026" / "curriculum" / "tree_env.pdf"
OUT = PX / "work"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with pdfplumber.open(PDF) as pdf:
        page = pdf.pages[5]
        words = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5)
    # ● で始まる語、または直前が ● の語を科目名として拾う
    items = []
    for i, w in enumerate(words):
        t = w["text"]
        if t.startswith("●") and len(t) > 1:
            items.append((t[1:], w))
        elif t == "●" and i + 1 < len(words):
            nxt = words[i + 1]
            items.append((nxt["text"], nxt))
    print("bullet words:", len(items))
    defined = {}
    for g in PAGE_6_GROUPS_DEF:
        for c in g["courses"]:
            defined[normalize_title(c)] = g["id"]
    rows = []
    for name, w in items:
        cx = (w["x0"] + w["x1"]) / 2
        cy = (w["top"] + w["bottom"]) / 2
        inside = []
        for g in PAGE_6_GROUPS_DEF:
            x0, y0, x1, y1 = g["bbox"]
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                inside.append(g["id"])
        n = normalize_title(name)
        rows.append({"name": name, "norm": n, "cx": round(cx, 1), "cy": round(cy, 1),
                     "geom_groups": inside, "defined_group": defined.get(n)})
    for r in rows:
        flag = "OK" if r["defined_group"] in r["geom_groups"] else "DIFF"
        print(flag, r["name"], r["cx"], r["cy"], r["geom_groups"], r["defined_group"])
    (OUT / "membership_check.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
