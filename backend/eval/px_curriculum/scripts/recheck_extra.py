"""セルフチェックの追加: D の適合率・再現率・平均、Wilson 区間（2次方程式を numpy で解く）、McNemar（scipy の二項検定）、
κ（混同行列から）、仮説 H1〜H5 の判定を、item_answers.csv（集計とは別の出力）と calls.jsonl から計算し直して results.json と突き合わせる。
"""
import sys
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import binomtest

PX = Path(__file__).resolve().parent.parent
P1 = PX / "px1"
TOL = 1e-9
Z = 1.959963984540054


def wilson_quad(k, n):
    p = k / n
    # (p - x)^2 = Z^2 x(1-x)/n  ->  (1 + Z^2/n) x^2 - (2p + Z^2/n) x + p^2 = 0
    roots = np.roots([1 + Z * Z / n, -(2 * p + Z * Z / n), p * p])
    return sorted(float(np.real(r)) for r in roots)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    res = json.loads((P1 / "results.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader(open(P1 / "item_answers.csv", encoding="utf-8-sig")))
    # item_answers.csv を calls.jsonl の生の answers と照合（1回目→再試行の順に埋める）
    calls = [json.loads(l) for l in (P1 / "raw" / "calls.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    raw = {}
    for c in sorted((c for c in calls if c.get("type") == "call"), key=lambda c: c["attempt"]):
        for q, iid in c["qmap"].items():
            k = (c["model"], c["condition"], str(c["run"]), iid)
            if raw.get(k) is None:
                raw[k] = c["answers"][q]
    problems = []
    for r in rows:
        v = raw.get((r["model"], r["condition"], r["run"], r["item_id"]))
        if (v or "") != r["answer"]:
            problems.append(("csv_vs_raw", r["item_id"], r["model"], r["condition"], r["run"], v, r["answer"]))
    g = defaultdict(list)
    for r in rows:
        g[(r["task"], r["model"], r["condition"], int(r["run"]))].append(r)
    n_checked = len(rows)
    for (task, m, cond, run), rs in g.items():
        key = f"{m}|{cond}|{run}"
        valid = [r for r in rs if r["answer"] != ""]
        if task == "O":
            k = sum(int(r["correct"]) for r in valid)
            if valid:
                lo, hi = wilson_quad(k, len(valid))
                w = res["O"][key]["wilson95"]
                if abs(lo - w[0]) > TOL or abs(hi - w[1]) > TOL:
                    problems.append(("wilson", key, (lo, hi), w))
            n_checked += 1
        else:
            tp = sum(1 for r in valid if r["truth"] == "はい" and r["answer"] == "はい")
            fp = sum(1 for r in valid if r["truth"] == "いいえ" and r["answer"] == "はい")
            fn = sum(1 for r in valid if r["truth"] == "はい" and r["answer"] == "いいえ")
            prec = tp / (tp + fp) if tp + fp else None
            rec = tp / (tp + fn) if tp + fn else None
            d = res["D"][key]
            for a, b, nm in ((prec, d["precision_yes"], "prec"), (rec, d["recall_yes"], "rec")):
                if (a is None) != (b is None) or (a is not None and abs(a - b) > TOL):
                    problems.append((nm, key, a, b))
            n_checked += 2
    # McNemar
    for k, v in res["mcnemar"].items():
        n = v["only_first_correct"] + v["only_second_correct"]
        p = 1.0 if n == 0 else binomtest(v["only_first_correct"], n, 0.5).pvalue
        if abs(p - v["p_exact_two_sided"]) > TOL:
            problems.append(("mcnemar", k, p, v["p_exact_two_sided"]))
        n_checked += 1
    # 鏡像・三つ組を除いた McNemar の b,c も CSV から
    by = json.loads((P1 / "baseline_byear.json").read_text(encoding="utf-8"))
    for k, v in res["mcnemar"].items():
        m, run, pair = k.split("|")
        c1, c2 = pair.split("_vs_")
        run = int(run[3:])

        def corr(cond):
            if cond == "B-year":
                return {i: int(b["correct"]) for i, b in by.items()}
            return {r["item_id"]: int(r["correct"]) for r in g[("O", m, cond, run)] if r["answer"] != ""}
        a, b = corr(c1), corr(c2)
        common = set(a) & set(b)
        bb = sum(1 for i in common if a[i] and not b[i])
        cc = sum(1 for i in common if b[i] and not a[i])
        if (bb, cc, len(common)) != (v["only_first_correct"], v["only_second_correct"], v["n"]):
            problems.append(("mcnemar_bc", k, (bb, cc, len(common)), v))
        n_checked += 1
    # κ（O は正誤、D は答え）
    for k, v in res["kappa"].items():
        m, task, cond = k.split("|")
        r1 = {r["item_id"]: r for r in g[(task, m, cond, 1)] if r["answer"] != ""}
        r2 = {r["item_id"]: r for r in g[(task, m, cond, 2)] if r["answer"] != ""}
        both = sorted(set(r1) & set(r2))
        lab = (lambda r: r["correct"]) if task == "O" else (lambda r: r["answer"])
        x = [lab(r1[i]) for i in both]
        y = [lab(r2[i]) for i in both]
        if not both:
            kap = None
        else:
            labels = sorted(set(x) | set(y))
            mat = np.zeros((len(labels), len(labels)))
            for a_, b_ in zip(x, y):
                mat[labels.index(a_), labels.index(b_)] += 1
            n = mat.sum()
            po = np.trace(mat) / n
            pe = float((mat.sum(1) * mat.sum(0)).sum() / n / n)
            kap = None if pe == 1 else (po - pe) / (1 - pe)
        if (kap is None) != (v["kappa"] is None) or (kap is not None and abs(kap - v["kappa"]) > TOL):
            problems.append(("kappa", k, kap, v["kappa"]))
        n_checked += 1
    # 平均と仮説
    O, D = res["O"], res["D"]
    models = sorted({k.split("|")[0] for k in O})

    def avg(tab, m, cond, f):
        vals = [tab[f"{m}|{cond}|{r}"][f] for r in (1, 2) if tab[f"{m}|{cond}|{r}"][f] is not None]
        return sum(vals) / len(vals) if vals else None
    by_acc = res["byear"]["accuracy"]
    h = {
        "H1": all(avg(O, m, "C1", "accuracy") < 0.90 for m in models),
        "H2": all(avg(O, m, "C0", "accuracy") <= by_acc for m in models),
        "H3": all(avg(D, m, "C1", "mcc") < 0.5 and avg(D, m, "C1", "precision_yes") < avg(D, m, "C1", "recall_yes") for m in models),
        "H4": any((avg(O, m, "C0", "mirror_contradiction_rate") or 0) >= 0.05 or (avg(O, m, "C0", "triple_cycle_rate") or 0) >= 0.05 for m in models),
        "H5": all(avg(O, m, "C2", "accuracy") - avg(O, m, "C1", "accuracy") >= 0.05 for m in models),
    }
    for k, v in h.items():
        if v != res["hypotheses"][k]["supported"]:
            problems.append(("hyp", k, v, res["hypotheses"][k]["supported"]))
        n_checked += 1
    for m in models:
        for cond in ("C0", "C1", "C2"):
            for f, tab, mk in (("mcc", D, "D_mcc"), ("precision_yes", D, "D_precision_yes"), ("recall_yes", D, "D_recall_yes"),
                               ("balanced_accuracy", D, "D_balanced_accuracy"), ("mirror_contradiction_rate", O, "O_mirror_contradiction_rate")):
                a = avg(tab, m, cond, f)
                b = res["means"][f"{m}|{cond}"][mk]
                if (a is None) != (b is None) or (a is not None and abs(a - b) > TOL):
                    problems.append(("mean", m, cond, f, a, b))
                n_checked += 1
    out = {"checked_values": n_checked, "problems": problems, "all_match": not problems, "hypotheses_recomputed": h}
    (PX / "recheck_extra_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
