"""セルフチェック: PX-1 と PX-2 の数値を、集計スクリプトとは別の書き方で生データから計算し直して突き合わせる。

PX-1: calls.jsonl の各呼び出しの answers（1回目・再試行）から最終の答えを組み立て直す（ランナーが書いた final_answers は使わない）。
PX-2: グループ DAG の辺のリストから numpy の行列で到達可能性を求め、b(G)・d(G)・h(G)・最長路・比較可能な割合を出す。
"""
import sys
import json
import math
from pathlib import Path

import numpy as np

PX = Path(__file__).resolve().parent.parent
P1 = PX / "px1"
TOL = 1e-12


def close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= TOL


def recheck_px1(problems: list) -> dict:
    items = {i["item_id"]: i for i in json.loads((P1 / "items_O.json").read_text(encoding="utf-8"))}
    items.update({i["item_id"]: i for i in json.loads((P1 / "items_D.json").read_text(encoding="utf-8"))})
    res = json.loads((P1 / "results.json").read_text(encoding="utf-8"))
    calls = [json.loads(l) for l in (P1 / "raw" / "calls.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    # (model, prompt_id) -> attempt -> answers by item
    att: dict = {}
    meta: dict = {}
    for c in calls:
        if c.get("type") != "call":
            continue
        key = (c["model"], c["prompt_id"])
        att.setdefault(key, {})[c["attempt"]] = {c["qmap"][q]: v for q, v in c["answers"].items()}
        meta[key] = (c["task"], c["condition"], c["run"])
    final: dict = {}
    for key, a in att.items():
        model = key[0]
        task, cond, run = meta[key]
        merged = dict(a[1])
        if 2 in a:
            for iid, v in a[2].items():
                if merged.get(iid) is None:
                    merged[iid] = v
        final.setdefault((model, task, cond, run), {}).update(merged)
    checked = 0
    for k, o in res["O"].items():
        model, cond, run = k.split("|")
        f = final.get((model, "O", cond, int(run)), {})
        oi = [i for i in items.values() if i["item_id"].startswith("O")]
        valid = [i for i in oi if f.get(i["item_id"]) is not None]
        corr = [i for i in valid if f[i["item_id"]] == i["truth"]]
        acc = len(corr) / len(valid) if valid else None
        if not close(acc, o["accuracy"]) or len(valid) != o["n_valid"]:
            problems.append(("O acc", k, acc, o["accuracy"]))
        # 鏡像: 選ばれた「先の科目」が2項目で違えば矛盾
        mir = {}
        for i in valid:
            if i["kind"] == "mirror":
                pick = i["shown_A"] if f[i["item_id"]] == "A" else i["shown_B"]
                mir.setdefault(i["mirror_id"], []).append(pick)
        pairs = [v for v in mir.values() if len(v) == 2]
        rate = (sum(1 for v in pairs if v[0] != v[1]) / len(pairs)) if pairs else None
        if not close(rate, o["mirror_contradiction_rate"]):
            problems.append(("mirror", k, rate, o["mirror_contradiction_rate"]))
        # 三つ組: 「先の科目として選ばれた回数」が 1,1,1 なら循環
        tri = {}
        for i in valid:
            if i["kind"] == "triple":
                pick = i["shown_A"] if f[i["item_id"]] == "A" else i["shown_B"]
                tri.setdefault(i["triple_id"], []).append(pick)
        full = [v for v in tri.values() if len(v) == 3]
        cyc = (sum(1 for v in full if len(set(v)) == 3) / len(full)) if full else None
        if not close(cyc, o["triple_cycle_rate"]):
            problems.append(("cycle", k, cyc, o["triple_cycle_rate"]))
        checked += 3
    for k, d in res["D"].items():
        model, cond, run = k.split("|")
        f = final.get((model, "D", cond, int(run)), {})
        di = [i for i in items.values() if i["item_id"].startswith("D")]
        cm = {(t, p): 0 for t in ("はい", "いいえ") for p in ("はい", "いいえ")}
        for i in di:
            v = f.get(i["item_id"])
            if v is not None:
                cm[(i["truth"], v)] += 1
        tp, fn, fp, tn = cm[("はい", "はい")], cm[("はい", "いいえ")], cm[("いいえ", "はい")], cm[("いいえ", "いいえ")]
        den = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
        mcc = None if tp + fp + tn + fn == 0 else ((tp * tn - fp * fn) / den if den else 0.0)
        if (tp, fp, tn, fn) != (d["tp"], d["fp"], d["tn"], d["fn"]) or not close(mcc, d["mcc"]):
            problems.append(("D", k, (tp, fp, tn, fn, mcc), (d["tp"], d["fp"], d["tn"], d["fn"], d["mcc"])))
        checked += 2
    # 平均と仮説
    for m in {k.split("|")[0] for k in res["O"]}:
        for cond in ("C0", "C1", "C2"):
            accs = [res["O"][f"{m}|{cond}|{r}"]["accuracy"] for r in (1, 2)]
            accs = [a for a in accs if a is not None]
            mean = sum(accs) / len(accs) if accs else None
            if not close(mean, res["means"][f"{m}|{cond}"]["O_accuracy"]):
                problems.append(("mean", m, cond))
            checked += 1
    # B-year
    b = json.loads((P1 / "baseline_byear.json").read_text(encoding="utf-8"))
    bacc = sum(1 for iid, v in b.items() if v["answer"] == items[iid]["truth"]) / len(b)
    if not close(bacc, res["byear"]["accuracy"]):
        problems.append(("byear", bacc, res["byear"]["accuracy"]))
    return {"checked_values": checked + 1, "n_calls": len(calls)}


def recheck_px2(problems: list) -> dict:
    gd = json.loads((PX / "dataset" / "group_dag.json").read_text(encoding="utf-8"))
    courses = json.loads((PX / "dataset" / "courses.json").read_text(encoding="utf-8"))
    m2 = json.loads((PX / "px2_metrics.json").read_text(encoding="utf-8"))

    def metrics(nodes: list, edges: list) -> dict:
        idx = {v: i for i, v in enumerate(nodes)}
        n = len(nodes)
        a = np.zeros((n, n), dtype=np.int64)
        for s, t in edges:
            a[idx[s], idx[t]] = 1
        reach = a.copy()
        for _ in range(n):
            nxt = ((reach + reach @ a) > 0).astype(np.int64)
            if (nxt == reach).all():
                break
            reach = nxt
        assert not reach.diagonal().any(), "cycle"
        # 頂点数で数えた最長路（反復の緩和）
        down = np.ones(n, dtype=np.int64)  # v で終わる
        up = np.ones(n, dtype=np.int64)    # v から始まる
        for _ in range(n):
            nd = np.maximum(down, np.max(np.where(a.T == 1, down[None, :], 0), axis=1) + 1 * (a.sum(axis=0) > 0))
            nu = np.maximum(up, np.max(np.where(a == 1, up[None, :], 0), axis=1) + 1 * (a.sum(axis=1) > 0))
            if (nd == down).all() and (nu == up).all():
                break
            down, up = nd, nu
        delay = down + up - 1
        comparable = int(((reach + reach.T) > 0).sum() // 2)
        return {"n_nodes": n, "n_edges": int(a.sum()), "blocking_total_bG": int(reach.sum()),
                "delay_total_dG": int(delay.sum()), "structural_complexity_hG": int(reach.sum() + delay.sum()),
                "longest_path_vertices": int(delay.max()), "comparable_pairs": comparable,
                "comparable_ratio": comparable / (n * (n - 1) / 2)}

    gnodes = [x["group_id"] for x in gd["nodes"]]
    gedges = [(e["source"], e["target"]) for e in gd["edges"]]
    dp = {x["group_id"] for x in gd["nodes"] if x["is_dp"]}
    targets = {
        "group_dag_with_dp": (gnodes, gedges),
        "group_dag_no_dp": ([v for v in gnodes if v not in dp], [e for e in gedges if e[1] not in dp and e[0] not in dp]),
    }
    for key, keep in (("course_dag_70", lambda c: True), ("course_dag_67_with_syllabus", lambda c: c["has_syllabus"])):
        cs = [c for c in courses if keep(c)]
        ce = [(x["course_id"], y["course_id"]) for x in cs for y in cs if (x["group_id"], y["group_id"]) in set(gedges)]
        targets[key] = ([c["course_id"] for c in cs], ce)
    checked = 0
    for key, (nodes, edges) in targets.items():
        got = metrics(nodes, edges)
        for k, v in got.items():
            ref = m2[key][k]
            ok = abs(v - ref) <= TOL if isinstance(v, float) else v == ref
            if not ok:
                problems.append(("PX2", key, k, v, ref))
            checked += 1
    return {"checked_values": checked}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    problems: list = []
    out = {"px2": recheck_px2(problems)}
    if (P1 / "results.json").exists():
        out["px1"] = recheck_px1(problems)
    out["problems"] = problems
    out["all_match"] = not problems
    (PX / "recheck_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
