"""PX-1 の標本・B-year 基準・全プロンプトを、LLM を呼ぶ前に決定的に作る。

出力（すべて SP/px/px1/ の下）:
  items_O.json, items_D.json   … 課題の項目（正解・提示順・三つ組/鏡像の所属）
  baseline_byear.json          … B-year の答え
  calls_plan.json              … 呼び出しの計画（task×condition×run×batch。2モデル共通のプロンプト）
  prompts/<prompt_id>.txt      … プロンプトの全文
  prompts_manifest.json        … プロンプトごとの SHA-256

乱数の種: SEED = 20261105。用途ごとに random.Random(f"{SEED}:{用途}") を作る。
"""
import sys
import json
import hashlib
import random
from itertools import combinations
from pathlib import Path

import networkx as nx

PX = Path(__file__).resolve().parent.parent
DATASET = PX / "dataset"
OUT = PX / "px1"
SEED = 20261105
N_TRIPLES = 20
N_MIRROR_BASE = 30
N_D_POS = 60
N_D_NEG = 60
BATCH_SIZE = 20
RUNS = (1, 2)
CONDITIONS = ("C0", "C1", "C2")
TASKS = ("O", "D")
SEM_ORDER = {"春": 1, "夏集": 2, "秋": 3}
DEPT = "関西大学 環境都市工学部 エネルギー環境・化学工学科"

TOOL_LINE = "この依頼では、コマンドの実行・ファイルの読み書き・検索などの道具を一切使わず、この文面だけを見て、指定の JSON だけを返してください。"

INTRO = {
    "O": (
        "対象は{dept}です。\n"
        "以下の各問いには、この学科の2つの科目 A と B が示されています。"
        "この学科の履修系統で、先に学ぶ（もう一方の土台になる）のはどちらかを、A か B で答えてください。"
        "どの問いにも、必ずどちらか一方を選んでください。"
    ),
    "D": (
        "対象は{dept}です。\n"
        "以下の各問いには、この学科の2つの科目 A と B が示されています。"
        "この学科の履修系統で、一方がもう一方の土台になる関係があるか（向きはどちらでもよい）を、はい か いいえ で答えてください。"
        "どの問いにも、必ずどちらか一方を選んでください。"
    ),
}
COND_NOTE = {
    "C0": "",
    "C1": "各科目には、シラバスの授業概要と到達目標（それぞれ先頭300字まで）を添えています。\n",
    "C2": "各科目には、シラバスの授業概要と到達目標（それぞれ先頭300字まで）と、配当年次・学期を添えています。\n",
}
OUTRO = {
    "O": (
        "返答は次の形の JSON だけにしてください（説明文やコードブロックの記号は付けない）。"
        "answers には上の全部の問いを1つずつ入れ、answer は \"A\" か \"B\" にしてください。\n"
        "{{\"answers\": [{{\"id\": \"q01\", \"answer\": \"A\"}}, {{\"id\": \"q02\", \"answer\": \"B\"}}]}}"
    ),
    "D": (
        "返答は次の形の JSON だけにしてください（説明文やコードブロックの記号は付けない）。"
        "answers には上の全部の問いを1つずつ入れ、answer は \"はい\" か \"いいえ\" にしてください。\n"
        "{{\"answers\": [{{\"id\": \"q01\", \"answer\": \"はい\"}}, {{\"id\": \"q02\", \"answer\": \"いいえ\"}}]}}"
    ),
}


def rng(purpose: str) -> random.Random:
    return random.Random(f"{SEED}:{purpose}")


def render_course(label: str, c: dict, cond: str) -> str:
    lines = [f"{label}: {c['name']}"]
    if cond in ("C1", "C2"):
        lines.append(f"  授業概要: {c['description_300']}")
        lines.append(f"  到達目標: {c['objectives_300']}")
    if cond == "C2":
        lines.append(f"  配当年次・学期: {c['year']}年次・{c['semester_display']}")
    return "\n".join(lines)


def render_prompt(task: str, cond: str, entries: list[tuple[str, dict, dict]]) -> str:
    parts = [TOOL_LINE, "", INTRO[task].format(dept=DEPT), COND_NOTE[cond], "問い:"]
    for qid, a, b in entries:
        parts.append(qid)
        parts.append(render_course("A", a, cond))
        parts.append(render_course("B", b, cond))
        parts.append("")
    parts.append(OUTRO[task].format())
    return "\n".join(p for p in parts if p is not None)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    (OUT / "prompts").mkdir(exist_ok=True)
    courses = json.loads((DATASET / "courses.json").read_text(encoding="utf-8"))
    gd = json.loads((DATASET / "group_dag.json").read_text(encoding="utf-8"))
    pool = {c["course_id"]: c for c in courses if c["has_syllabus"]}
    group_of = {cid: c["group_id"] for cid, c in pool.items()}

    gg = nx.DiGraph()
    gg.add_edges_from((e["source"], e["target"]) for e in gd["edges"])
    greach = {g: nx.descendants(gg, g) for g in gg}
    ids = sorted(pool)

    def reach(x: str, y: str) -> bool:
        return group_of[y] in greach.get(group_of[x], set())

    def direct(x: str, y: str) -> bool:
        return gg.has_edge(group_of[x], group_of[y])

    o_pool = [(x, y) for x in ids for y in ids if x != y and reach(x, y)]
    chains = [(a, b, c) for a in ids for b in ids for c in ids
              if len({a, b, c}) == 3 and direct(a, b) and direct(b, c)]
    diff_group_pairs = [(x, y) for x, y in combinations(ids, 2) if group_of[x] != group_of[y]]
    comparable = [(x, y) for x, y in diff_group_pairs if reach(x, y) or reach(y, x)]
    incomparable = [(x, y) for x, y in diff_group_pairs if not (reach(x, y) or reach(y, x))]

    # --- 向き課題 O ---
    r = rng("triples")
    used = set()
    triples = []
    cand = chains[:]
    r.shuffle(cand)
    for a, b, c in cand:
        prs = [frozenset((a, b)), frozenset((b, c)), frozenset((a, c))]
        if any(p in used for p in prs):
            continue
        triples.append((a, b, c))
        used.update(prs)
        if len(triples) == N_TRIPLES:
            break
    r = rng("mirror_base")
    cand = [p for p in o_pool if frozenset(p) not in used]
    r.shuffle(cand)
    mirror_base = []
    for x, y in cand:
        if frozenset((x, y)) in used:
            continue
        mirror_base.append((x, y))
        used.add(frozenset((x, y)))
        if len(mirror_base) == N_MIRROR_BASE:
            break

    items_o = []
    r_swap = rng("swap_triples")
    swap_flags = [True] * (N_TRIPLES * 3 // 2) + [False] * (N_TRIPLES * 3 - N_TRIPLES * 3 // 2)
    r_swap.shuffle(swap_flags)
    k = 0
    for ti, (a, b, c) in enumerate(triples):
        for role, (x, y) in zip(("AB", "BC", "AC"), ((a, b), (b, c), (a, c))):
            first, second = (y, x) if swap_flags[k] else (x, y)
            items_o.append({"item_id": f"O{len(items_o)+1:03d}", "earlier": x, "later": y,
                            "shown_A": first, "shown_B": second, "swapped": swap_flags[k],
                            "kind": "triple", "triple_id": f"T{ti+1:02d}", "triple_role": role})
            k += 1
    for mi, (x, y) in enumerate(mirror_base):
        for side, (first, second) in (("base", (x, y)), ("mirror", (y, x))):
            items_o.append({"item_id": f"O{len(items_o)+1:03d}", "earlier": x, "later": y,
                            "shown_A": first, "shown_B": second, "swapped": first != x,
                            "kind": "mirror", "mirror_id": f"M{mi+1:02d}", "mirror_side": side})
    for it in items_o:
        it["truth"] = "A" if it["shown_A"] == it["earlier"] else "B"

    # --- 検出課題 D（O の90組と重ならない組から）---
    r = rng("d_pos")
    cand = [p for p in comparable if frozenset(p) not in used]
    r.shuffle(cand)
    d_pos = cand[:N_D_POS]
    r = rng("d_neg")
    cand = incomparable[:]
    r.shuffle(cand)
    d_neg = cand[:N_D_NEG]
    r_ord = rng("d_order")
    items_d = []
    for lab, prs in (("はい", d_pos), ("いいえ", d_neg)):
        for x, y in prs:
            first, second = (y, x) if r_ord.random() < 0.5 else (x, y)
            items_d.append({"item_id": f"D{len(items_d)+1:03d}", "shown_A": first, "shown_B": second,
                            "truth": lab, "path_dir": ("A->B" if reach(first, second) else "B->A" if reach(second, first) else None)})

    # --- B-year 基準 ---
    r_coin = rng("byear_coin")
    byear = {}
    for it in items_o:
        a, b = pool[it["shown_A"]], pool[it["shown_B"]]
        ka = (a["year"], SEM_ORDER.get(a["semester_key"], 0))
        kb = (b["year"], SEM_ORDER.get(b["semester_key"], 0))
        coin = r_coin.random() < 0.5  # 全項目で1回ずつ引く（同順位でないときも消費して系列を固定）
        if ka < kb:
            ans, tie = "A", False
        elif kb < ka:
            ans, tie = "B", False
        else:
            ans, tie = ("A" if coin else "B"), True
        byear[it["item_id"]] = {"answer": ans, "tie": tie, "key_A": ka, "key_B": kb, "correct": ans == it["truth"]}

    # --- 呼び出しの計画とプロンプト ---
    plan = []
    manifest = {}
    items_by_task = {"O": items_o, "D": items_d}
    for task in TASKS:
        for cond in CONDITIONS:
            for run in RUNS:
                rr = rng(f"batch:{task}:{cond}:{run}")
                its = items_by_task[task]
                tries = 0
                while True:
                    tries += 1
                    order = its[:]
                    rr.shuffle(order)
                    batches = [order[i:i + BATCH_SIZE] for i in range(0, len(order), BATCH_SIZE)]
                    if task != "O":
                        break
                    ok = True
                    for bt in batches:
                        mids = [it.get("mirror_id") for it in bt if it["kind"] == "mirror"]
                        if len(mids) != len(set(mids)):
                            ok = False
                            break
                    if ok:
                        break
                for bi, bt in enumerate(batches, 1):
                    pid = f"{task}_{cond}_r{run}_b{bi}"
                    entries = []
                    qmap = {}
                    for qi, it in enumerate(bt, 1):
                        qid = f"q{qi:02d}"
                        qmap[qid] = it["item_id"]
                        entries.append((qid, pool[it["shown_A"]], pool[it["shown_B"]]))
                    text = render_prompt(task, cond, entries)
                    (OUT / "prompts" / f"{pid}.txt").write_text(text, encoding="utf-8")
                    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    manifest[pid] = {"sha256": sha, "chars": len(text)}
                    plan.append({"prompt_id": pid, "task": task, "condition": cond, "run": run, "batch": bi,
                                 "qmap": qmap, "shuffle_tries": tries, "prompt_sha256": sha})

    (OUT / "items_O.json").write_text(json.dumps(items_o, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "items_D.json").write_text(json.dumps(items_d, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "baseline_byear.json").write_text(json.dumps(byear, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "calls_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "prompts_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    group_pairs_o = {}
    for it in items_o:
        key = f"{group_of[it['earlier']]}->{group_of[it['later']]}"
        group_pairs_o[key] = group_pairs_o.get(key, 0) + 1
    stats = {
        "seed": SEED,
        "pool_courses": len(pool),
        "o_pool_ordered_reachable_pairs": len(o_pool),
        "direct_chains_available": len(chains),
        "triples": len(triples),
        "mirror_base": len(mirror_base),
        "items_O": len(items_o),
        "items_O_swapped": sum(it["swapped"] for it in items_o),
        "unique_unordered_pairs_O": len(used),
        "diff_group_pairs": len(diff_group_pairs),
        "comparable_pairs": len(comparable),
        "incomparable_diff_group_pairs": len(incomparable),
        "items_D": len(items_d),
        "items_D_pos": sum(it["truth"] == "はい" for it in items_d),
        "byear_accuracy": sum(v["correct"] for v in byear.values()) / len(byear),
        "byear_ties": sum(v["tie"] for v in byear.values()),
        "byear_correct_nontie": sum(v["correct"] for v in byear.values() if not v["tie"]),
        "byear_nontie": sum(not v["tie"] for v in byear.values()),
        "n_prompts": len(manifest),
        "max_prompt_chars": max(m["chars"] for m in manifest.values()),
        "o_group_pairs": dict(sorted(group_pairs_o.items(), key=lambda kv: -kv[1])),
        "manifest_sha256": hashlib.sha256((OUT / "prompts_manifest.json").read_bytes()).hexdigest(),
    }
    (OUT / "sampling_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "o_group_pairs"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
