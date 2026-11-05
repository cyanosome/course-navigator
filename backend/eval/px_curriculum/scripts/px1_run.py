"""PX-1 の実行: agy（Antigravity CLI）で 2モデル × 72プロンプト を呼ぶ。

- 専用プロファイル --gemini_dir=SP/px/agy_profile、stream-json の標準入力に1件、cwd は空の SP/px/agy_ws
- 環境変数から ANTHROPIC_API_KEY / GEMINI_API_KEY / GOOGLE_API_KEY を外して起動
- 並列は最大3本。agy の呼び出しは smoke を含めて合計 250 回まで（BUDGET）
- 呼び出しが無効（JSON が読めない・項目の欠け/不正・agy の失敗）なら同じプロンプトで1回だけ再試行。
  項目ごとに、1回目で有効ならその答え、1回目で無効なら再試行の答え（有効なら）、どちらも無効なら無効
- 1回の agy 呼び出しを px1/raw/calls.jsonl に1行で残す。途中で止まっても、終わった job は飛ばして再開できる

使い方:
  python -I scripts/px1_run.py smoke     … 形式確認（各モデル1回、ダミーの問い）
  python -I scripts/px1_run.py main      … 本番
"""
import os
import sys
import json
import time
import hashlib
import shutil
import subprocess
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PX = Path(__file__).resolve().parent.parent
P1 = PX / "px1"
RAW = P1 / "raw"
PROFILE = PX / "agy_profile"
WS = PX / "agy_ws"
AGY = shutil.which("agy") or "agy"
MODELS = ("Gemini 3.8 Flash (High)", "Claude Sonnet 5.5 (Medium)")
BUDGET = 250
MAX_PARALLEL = 3
CALL_TIMEOUT_S = 660
PRINT_TIMEOUT = "600s"
CALLS_LOG = RAW / "calls.jsonl"
DROP_ENV = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
ALLOWED = {"O": {"A", "B"}, "D": {"はい", "いいえ"}}

_lock = threading.Lock()
_budget_used = 0


def count_logged_calls() -> int:
    if not CALLS_LOG.exists():
        return 0
    return sum(1 for line in CALLS_LOG.read_text(encoding="utf-8").splitlines() if line.strip())


def reserve_budget() -> bool:
    global _budget_used
    with _lock:
        if _budget_used >= BUDGET:
            return False
        _budget_used += 1
        return True


def append_log(rec: dict) -> None:
    with _lock:
        with open(CALLS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)


def call_agy(model: str, prompt: str, call_id: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    cmd = [AGY, f"--gemini_dir={PROFILE}", "--model", model, "--input-format", "stream-json",
           "--output-format", "stream-json", "--print-timeout", PRINT_TIMEOUT]
    line = json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=True) + "\n"
    out_dir = RAW / "stdout"
    err_dir = RAW / "stderr"
    out_dir.mkdir(parents=True, exist_ok=True)
    err_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(WS), env=env)
    timed_out = {"v": False}

    def watchdog():
        if p.poll() is None:
            timed_out["v"] = True
            kill_tree(p.pid)

    timer = threading.Timer(CALL_TIMEOUT_S, watchdog)
    timer.start()
    err_chunks = []
    err_thread = threading.Thread(target=lambda: err_chunks.append(p.stderr.read()), daemon=True)
    err_thread.start()
    result_ev = None
    init_model = None
    n_events = 0
    tool_events = 0
    try:
        p.stdin.write(line.encode("utf-8"))
        p.stdin.flush()
        with open(out_dir / f"{call_id}.jsonl", "wb") as raw:
            for ln in p.stdout:
                raw.write(ln)
                raw.flush()
                try:
                    ev = json.loads(ln.decode("utf-8"))
                except Exception:
                    continue
                n_events += 1
                kind = ev.get("event") or ev.get("type")
                if isinstance(kind, str) and "tool" in kind.lower():
                    tool_events += 1
                if kind == "init" and init_model is None:
                    init_model = ev.get("model")
                    if init_model is None and isinstance(ev.get("init"), dict):
                        init_model = ev["init"].get("model")
                if kind == "result":
                    result_ev = ev
                    break
    finally:
        timer.cancel()
        try:
            p.stdin.close()
        except Exception:
            pass
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            kill_tree(p.pid)
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                pass
    err_thread.join(timeout=5)
    stderr = b"".join(c for c in err_chunks if c).decode("utf-8", errors="replace")
    (err_dir / f"{call_id}.txt").write_text(stderr, encoding="utf-8")
    elapsed = time.time() - t0
    response = None
    meta = None
    if result_ev is not None:
        r = result_ev.get("result")
        if isinstance(r, dict):
            response = r.get("response")
            meta = {k: v for k, v in r.items() if k != "response"}
        else:
            response = result_ev.get("response") or (r if isinstance(r, str) else None)
            meta = {k: v for k, v in result_ev.items() if k not in ("response", "result")}
    return {"elapsed_s": round(elapsed, 2), "returncode": p.returncode, "timed_out": timed_out["v"],
            "response": response, "result_meta": meta, "init_model": init_model, "n_events": n_events,
            "tool_events": tool_events, "stderr_tail": stderr[-800:]}


def strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def parse_answers(task: str, response: str | None, qids: list[str]) -> tuple[bool, dict, str]:
    """(call_valid, {qid: answer or None}, parse_note)"""
    out = {q: None for q in qids}
    if not response or not response.strip():
        return False, out, "empty"
    t = strip_fences(response)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < i:
        return False, out, "no_json_object"
    try:
        obj = json.loads(t[i:j + 1])
    except Exception as e:
        return False, out, f"json_error:{type(e).__name__}"
    ans = obj.get("answers") if isinstance(obj, dict) else None
    if not isinstance(ans, list):
        return False, out, "no_answers_list"
    seen: dict[str, set] = {}
    for a in ans:
        if not isinstance(a, dict):
            continue
        qid = str(a.get("id", "")).strip()
        val = unicodedata.normalize("NFKC", str(a.get("answer", ""))).strip()
        if task == "O":
            val = val.upper()
        if qid in out:
            seen.setdefault(qid, set()).add(val)
    for q in qids:
        vals = seen.get(q, set())
        if len(vals) == 1:
            v = next(iter(vals))
            if v in ALLOWED[task]:
                out[q] = v
    n_bad = sum(1 for v in out.values() if v is None)
    note = "ok" if n_bad == 0 else f"invalid_items:{n_bad}"
    return n_bad == 0, out, note


def run_job(model: str, plan: dict, prompts_dir: Path, done_final: set) -> None:
    key = (model, plan["prompt_id"])
    if key in done_final:
        return
    prompt = (prompts_dir / f"{plan['prompt_id']}.txt").read_text(encoding="utf-8")
    sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert sha == plan["prompt_sha256"], plan["prompt_id"]
    qids = list(plan["qmap"].keys())
    final = {q: None for q in qids}
    for attempt in (1, 2):
        if not reserve_budget():
            append_log({"type": "skipped_budget", "model": model, "prompt_id": plan["prompt_id"], "attempt": attempt,
                        "final": attempt == 1, "final_answers": final, "t": time.time()})
            return
        call_id = f"{plan['prompt_id']}__{'G' if model.startswith('Gemini') else 'S'}__a{attempt}"
        t_start = time.time()
        res = call_agy(model, prompt, call_id)
        ok, answers, note = parse_answers(plan["task"], res["response"], qids)
        for q in qids:
            if final[q] is None and answers[q] is not None:
                final[q] = answers[q]
        is_final = ok or attempt == 2
        rec = {"type": "call", "call_id": call_id, "model": model, "prompt_id": plan["prompt_id"],
               "task": plan["task"], "condition": plan["condition"], "run": plan["run"], "batch": plan["batch"],
               "attempt": attempt, "prompt_sha256": sha, "t_start": t_start, "call_valid": ok, "parse_note": note,
               "answers": answers, "qmap": plan["qmap"], "final": is_final,
               "final_answers": final if is_final else None, **res}
        append_log(rec)
        print(f"[{time.strftime('%H:%M:%S')}] {call_id} valid={ok} note={note} {res['elapsed_s']}s budget={_budget_used}", flush=True)
        if ok:
            return


def smoke() -> None:
    prompt = (
        "この依頼では、コマンドの実行・ファイルの読み書き・検索などの道具を一切使わず、この文面だけを見て、指定の JSON だけを返してください。\n\n"
        "対象は架空の大学の架空の学科です（形式の確認用）。\n"
        "以下の各問いには、この学科の2つの科目 A と B が示されています。この学科の履修系統で、先に学ぶ（もう一方の土台になる）のはどちらかを、A か B で答えてください。"
        "どの問いにも、必ずどちらか一方を選んでください。\n問い:\nq01\nA: 四則演算\nB: 微分積分\n\nq02\nA: 古典文学研究\nB: ひらがなの読み書き\n\n"
        "返答は次の形の JSON だけにしてください（説明文やコードブロックの記号は付けない）。answers には上の全部の問いを1つずつ入れ、answer は \"A\" か \"B\" にしてください。\n"
        "{\"answers\": [{\"id\": \"q01\", \"answer\": \"A\"}, {\"id\": \"q02\", \"answer\": \"B\"}]}"
    )
    sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    for model in MODELS:
        if not reserve_budget():
            print("budget exhausted")
            return
        call_id = f"SMOKE__{'G' if model.startswith('Gemini') else 'S'}__{int(time.time())}"
        t_start = time.time()
        res = call_agy(model, prompt, call_id)
        ok, answers, note = parse_answers("O", res["response"], ["q01", "q02"])
        append_log({"type": "smoke", "call_id": call_id, "model": model, "prompt_sha256": sha, "t_start": t_start,
                    "call_valid": ok, "parse_note": note, "answers": answers, **res})
        print(call_id, ok, note, res["elapsed_s"], res["init_model"], repr((res["response"] or "")[:200]), res["stderr_tail"][-300:])


def main() -> None:
    global _budget_used
    sys.stdout.reconfigure(encoding="utf-8")
    RAW.mkdir(parents=True, exist_ok=True)
    WS.mkdir(exist_ok=True)
    PROFILE.mkdir(exist_ok=True)
    for k in DROP_ENV:
        os.environ.pop(k, None)
    _budget_used = count_logged_calls()
    mode = sys.argv[1] if len(sys.argv) > 1 else "main"
    if mode == "smoke":
        smoke()
        return
    plan = json.loads((P1 / "calls_plan.json").read_text(encoding="utf-8"))
    done_final = set()
    if CALLS_LOG.exists():
        for line in CALLS_LOG.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("type") == "call" and r.get("final"):
                done_final.add((r["model"], r["prompt_id"]))
    jobs = []
    for run in (1, 2):
        run_plan = [p for p in plan if p["run"] == run]
        for p in run_plan:
            for m in MODELS:
                jobs.append((m, p))
    print(f"jobs {len(jobs)}, already done {len(done_final)}, budget used {_budget_used}/{BUDGET}", flush=True)
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
        futs = [ex.submit(run_job, m, p, P1 / "prompts", done_final) for m, p in jobs]
        for f in futs:
            f.result()
    print(f"finished. budget used {_budget_used}/{BUDGET}", flush=True)


if __name__ == "__main__":
    main()
