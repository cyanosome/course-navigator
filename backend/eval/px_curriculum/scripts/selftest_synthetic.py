"""集計コードの自己検査: 正解どおり・全部 A・鏡像で位置に従う、などの合成の答えで既知の値が出るかを見る。"""
import sys
import json
import subprocess
from pathlib import Path

PX = Path(__file__).resolve().parent.parent
P1 = PX / "px1"
sys.path.insert(0, str(PX / "scripts"))
from px1_run import parse_answers  # noqa: E402

MODELS = ("Gemini 3.8 Flash (High)", "Claude Sonnet 5.5 (Medium)")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    # parse_answers
    assert parse_answers("O", '{"answers":[{"id":"q01","answer":"A"},{"id":"q02","answer":"b"}]}', ["q01", "q02"]) == (True, {"q01": "A", "q02": "B"}, "ok")
    assert parse_answers("O", '```json\n{"answers":[{"id":"q01","answer":"Ａ"}]}\n```', ["q01", "q02"])[2] == "invalid_items:1"
    assert parse_answers("O", '```json\n{"answers":[{"id":"q01","answer":"Ａ"}]}\n```', ["q01"])[1] == {"q01": "A"}
    assert parse_answers("D", '{"answers":[{"id":"q01","answer":"はい"},{"id":"q01","answer":"いいえ"}]}', ["q01"])[0] is False
    assert parse_answers("D", 'text', ["q01"])[2] == "no_json_object"
    assert parse_answers("D", '', ["q01"])[2] == "empty"
    plan = json.loads((P1 / "calls_plan.json").read_text(encoding="utf-8"))
    io = {i["item_id"]: i for i in json.loads((P1 / "items_O.json").read_text(encoding="utf-8"))}
    idd = {i["item_id"]: i for i in json.loads((P1 / "items_D.json").read_text(encoding="utf-8"))}
    lines = []
    for p in plan:
        for m in MODELS:
            ans = {}
            for q, iid in p["qmap"].items():
                it = io[iid] if p["task"] == "O" else idd[iid]
                if m.startswith("Gemini"):
                    ans[q] = it["truth"]                      # 完全に正解
                else:
                    ans[q] = "A" if p["task"] == "O" else "はい"  # 常に A / 常に はい
            lines.append(json.dumps({"type": "call", "model": m, "prompt_id": p["prompt_id"], "task": p["task"],
                                     "condition": p["condition"], "run": p["run"], "batch": p["batch"], "attempt": 1,
                                     "call_valid": True, "parse_note": "ok", "final": True, "qmap": p["qmap"],
                                     "final_answers": ans, "elapsed_s": 1.0, "tool_events": 0, "init_model": None},
                                    ensure_ascii=False))
    path = PX / "selftest" / "calls_synthetic.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run([sys.executable, "-I", str(PX / "scripts" / "px1_analyze.py"), str(path), "_selftest"], check=True,
                   capture_output=True)
    r = json.loads((P1 / "results_selftest.json").read_text(encoding="utf-8"))
    g, s = MODELS
    for cond in ("C0", "C1", "C2"):
        for run in (1, 2):
            o = r["O"][f"{g}|{cond}|{run}"]
            assert o["accuracy"] == 1.0 and o["mirror_contradiction_rate"] == 0 and o["triple_cycle_rate"] == 0, o
            d = r["D"][f"{g}|{cond}|{run}"]
            assert abs(d["mcc"] - 1.0) < 1e-12 and d["balanced_accuracy"] == 1.0, d
            o = r["O"][f"{s}|{cond}|{run}"]
            # 常に A: 正答 = truth が A の項目 = 提示を入れ替えていない60項目
            assert o["n_correct"] == 60 and o["mirror_contradiction_rate"] == 1.0 and o["mirror_contra_both_first"] == 30, o
            d = r["D"][f"{s}|{cond}|{run}"]
            assert d["tp"] == 60 and d["fp"] == 60 and d["mcc"] == 0.0 and d["precision_yes"] == 0.5 and d["recall_yes"] == 1.0, d
    assert r["kappa"][f"{g}|D|C0"]["kappa"] == 1.0
    h = r["hypotheses"]
    assert h["H1"]["supported"] is False and h["H4"]["supported"] is True
    print("selftest OK")
    print(json.dumps(h, ensure_ascii=False))
    (P1 / "results_selftest.json").unlink()
    (P1 / "item_answers_selftest.csv").unlink()


if __name__ == "__main__":
    main()
