"""探索的（事前登録外）: 検出課題 D に「配当年次が違えば はい」の規則（D-year）を当てたときの指標と、鏡像の矛盾の実例。"""
import sys
import csv
import json
import math
from pathlib import Path

PX = Path(__file__).resolve().parent.parent
P1 = PX / "px1"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    c = {x["course_id"]: x for x in json.loads((PX / "dataset" / "courses.json").read_text(encoding="utf-8"))}
    d = json.loads((P1 / "items_D.json").read_text(encoding="utf-8"))
    tp = fp = tn = fn = 0
    for it in d:
        pred = "はい" if c[it["shown_A"]]["year"] != c[it["shown_B"]]["year"] else "いいえ"
        if it["truth"] == "はい":
            tp += pred == "はい"; fn += pred == "いいえ"
        else:
            fp += pred == "はい"; tn += pred == "いいえ"
    den = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    out = {"D_year_rule": {"rule": "はい iff 配当年次が異なる", "tp": tp, "fp": fp, "tn": tn, "fn": fn,
                           "balanced_accuracy": (tp / (tp + fn) + tn / (tn + fp)) / 2, "mcc": (tp * tn - fp * fn) / den,
                           "precision_yes": tp / (tp + fp), "recall_yes": tp / (tp + fn)}}
    rows = list(csv.DictReader(open(P1 / "item_answers.csv", encoding="utf-8-sig")))
    io = {i["item_id"]: i for i in json.loads((P1 / "items_O.json").read_text(encoding="utf-8"))}
    ex = []
    for m in ("Claude Sonnet 5.5 (Medium)",):
        for run in ("1", "2"):
            ans = {r["item_id"]: r for r in rows if r["task"] == "O" and r["model"] == m and r["condition"] == "C0" and r["run"] == run}
            mir = {}
            for iid, it in io.items():
                if it["kind"] == "mirror":
                    mir.setdefault(it["mirror_id"], []).append(iid)
            for mid, (a, b) in sorted(mir.items()):
                ra, rb = ans[a], ans[b]
                pa = ra["shown_A"] if ra["answer"] == "A" else ra["shown_B"]
                pb = rb["shown_A"] if rb["answer"] == "A" else rb["shown_B"]
                if pa != pb:
                    ex.append({"run": run, "mirror_id": mid, "presentation1": f"A={ra['shown_A']} / B={ra['shown_B']} -> {ra['answer']}",
                               "presentation2": f"A={rb['shown_A']} / B={rb['shown_B']} -> {rb['answer']}",
                               "truth_earlier": c[io[a]["earlier"]]["name"]})
    out["sonnet_C0_mirror_contradictions"] = ex
    (P1 / "exploratory.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
