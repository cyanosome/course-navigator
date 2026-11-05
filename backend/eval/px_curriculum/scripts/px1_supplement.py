"""PX-1 の補足の集計（事前登録の仮説の判定には使わない記述的な内訳）。

- 道具の使用: stdout の step_update で step_type が user_input / agent_response 以外のもの
- トークンと所要時間（result イベント）
- 向き課題: 年次の差（同年次 / 1年差 / 2年以上差）ごとの正答率、三つ組・鏡像ごとの正答率、B-year との一致
- 検出課題: 正解（有/無）× 年次差ごとの「はい」の割合
- 2モデル・2回とも間違えた項目（C1）
出力: px1/supplement.json
"""
import sys
import json
from collections import Counter, defaultdict
from pathlib import Path

PX = Path(__file__).resolve().parent.parent
P1 = PX / "px1"
MODELS = ("Gemini 3.8 Flash (High)", "Claude Sonnet 5.5 (Medium)")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    courses = {c["course_id"]: c for c in json.loads((PX / "dataset" / "courses.json").read_text(encoding="utf-8"))}
    io = {i["item_id"]: i for i in json.loads((P1 / "items_O.json").read_text(encoding="utf-8"))}
    idd = {i["item_id"]: i for i in json.loads((P1 / "items_D.json").read_text(encoding="utf-8"))}
    byear = json.loads((P1 / "baseline_byear.json").read_text(encoding="utf-8"))
    calls = [json.loads(l) for l in (P1 / "raw" / "calls.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    sup: dict = {}

    steps = Counter()
    tool_calls_by = Counter()
    for c in calls:
        if c.get("type") not in ("call", "smoke"):
            continue
        f = P1 / "raw" / "stdout" / f"{c['call_id']}.jsonl"
        if not f.exists():
            continue
        seen = set()
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except Exception:
                continue
            su = e.get("step_update")
            if isinstance(su, dict) and su.get("step_type") and su.get("step_index") not in seen:
                seen.add(su.get("step_index"))
                steps[su["step_type"]] += 1
                if su["step_type"] not in ("user_input", "agent_response"):
                    tool_calls_by[c["model"]] += 1
    sup["step_types"] = dict(steps)
    sup["non_response_steps_by_model"] = dict(tool_calls_by)

    tok = defaultdict(lambda: Counter())
    el = defaultdict(list)
    for c in calls:
        if c.get("type") != "call":
            continue
        u = ((c.get("result_meta") or {}).get("usage")) or {}
        for k in ("input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens"):
            tok[c["model"]][k] += u.get(k, 0) or 0
        el[(c["model"], c["condition"])].append(c["elapsed_s"])
    sup["tokens_by_model"] = {m: dict(v) for m, v in tok.items()}
    sup["elapsed_median_by_model_condition"] = {f"{m}|{cond}": sorted(v)[len(v) // 2] for (m, cond), v in el.items()}

    res = json.loads((P1 / "results.json").read_text(encoding="utf-8"))
    final = {}
    for c in calls:
        if c.get("type") == "call" and c.get("final"):
            for q, iid in c["qmap"].items():
                final[(c["model"], c["condition"], c["run"], iid)] = c["final_answers"][q]

    def dy_bucket(a, b):
        d = abs(courses[a]["year"] - courses[b]["year"])
        return "0" if d == 0 else "1" if d == 1 else "2+"

    o_break = {}
    for m in MODELS:
        for cond in ("C0", "C1", "C2"):
            agg = defaultdict(lambda: [0, 0])
            for run in (1, 2):
                for iid, it in io.items():
                    v = final.get((m, cond, run, iid))
                    if v is None:
                        continue
                    for key in (f"dy={dy_bucket(it['earlier'], it['later'])}", f"kind={it['kind']}",
                                f"byear={'correct' if byear[iid]['correct'] else 'wrong'}",
                                f"agree_byear={'yes' if v == byear[iid]['answer'] else 'no'}"):
                        agg[key][1] += 1
                        agg[key][0] += v == it["truth"]
            o_break[f"{m}|{cond}"] = {k: {"correct": a, "n": n, "acc": a / n if n else None} for k, (a, n) in sorted(agg.items())}
    sup["O_breakdown_pooled_runs"] = o_break
    byear_by = defaultdict(lambda: [0, 0])
    for iid, it in io.items():
        k = f"dy={dy_bucket(it['earlier'], it['later'])}"
        byear_by[k][1] += 1
        byear_by[k][0] += byear[iid]["correct"]
    sup["byear_by_dy"] = {k: {"correct": a, "n": n} for k, (a, n) in byear_by.items()}

    d_break = {}
    for m in MODELS:
        for cond in ("C0", "C1", "C2"):
            agg = defaultdict(lambda: [0, 0])
            for run in (1, 2):
                for iid, it in idd.items():
                    v = final.get((m, cond, run, iid))
                    if v is None:
                        continue
                    key = f"truth={it['truth']}|dy={dy_bucket(it['shown_A'], it['shown_B'])}"
                    agg[key][1] += 1
                    agg[key][0] += v == "はい"
            d_break[f"{m}|{cond}"] = {k: {"yes": a, "n": n, "yes_rate": a / n if n else None} for k, (a, n) in sorted(agg.items())}
    sup["D_yes_rate_breakdown_pooled_runs"] = d_break

    hard = []
    for iid, it in io.items():
        vals = [final.get((m, "C1", r, iid)) for m in MODELS for r in (1, 2)]
        if all(v is not None and v != it["truth"] for v in vals):
            hard.append({"item_id": iid, "earlier": courses[it["earlier"]]["name"], "later": courses[it["later"]]["name"],
                         "earlier_group": courses[it["earlier"]]["group_id"], "later_group": courses[it["later"]]["group_id"],
                         "years": [courses[it["earlier"]]["year"], courses[it["later"]]["year"]],
                         "sem": [courses[it["earlier"]]["semester_display"], courses[it["later"]]["semester_display"]]})
    sup["O_wrong_by_all_4_C1"] = hard
    for cond in ("C0", "C2"):
        n = 0
        for iid, it in io.items():
            vals = [final.get((m, cond, r, iid)) for m in MODELS for r in (1, 2)]
            n += all(v is not None and v != it["truth"] for v in vals)
        sup[f"O_wrong_by_all_4_{cond}_count"] = n

    d_fp = []
    for iid, it in idd.items():
        if it["truth"] != "いいえ":
            continue
        vals = [final.get((m, "C1", r, iid)) for m in MODELS for r in (1, 2)]
        if all(v == "はい" for v in vals):
            d_fp.append({"item_id": iid, "A": courses[it["shown_A"]]["name"], "B": courses[it["shown_B"]]["name"],
                         "groups": [courses[it["shown_A"]]["group_id"], courses[it["shown_B"]]["group_id"]]})
    sup["D_false_yes_by_all_4_C1"] = d_fp
    d_fn = []
    for iid, it in idd.items():
        if it["truth"] != "はい":
            continue
        vals = [final.get((m, "C1", r, iid)) for m in MODELS for r in (1, 2)]
        if all(v == "いいえ" for v in vals):
            d_fn.append({"item_id": iid, "A": courses[it["shown_A"]]["name"], "B": courses[it["shown_B"]]["name"],
                         "groups": [courses[it["shown_A"]]["group_id"], courses[it["shown_B"]]["group_id"]]})
    sup["D_false_no_by_all_4_C1"] = d_fn
    (P1 / "supplement.json").write_text(json.dumps(sup, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(sup, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
