"""test3-2（POST /test/agent/mcp）を実 Gemini・実 DB で確かめた e2e スクリプト（2026-10-11 実行）。

記録は docs/experiments/2026-10-11_test3-2-e2e.md、そのときの出力は
results/2026-10-11_e2e_test3-2.txt。結果を再現できるよう、実行したときの中身から
この docstring 以外は変えていない。

backend コンテナの中で、標準入力からスクリプトを渡して実行する（リポのルートで）:

    docker compose exec -T backend python - <q|all|old> <timeout_s> < backend/eval/e2e_test3_2.py

- 第1引数: 1 / 2 / 3 なら QUESTIONS のその1問だけを POST /test/agent/mcp に送る。
  old なら旧エンドポイント POST /test/agent に Q1 だけを送る。all（既定）なら Q1〜Q3 と old を順に送る。
- 第2引数: 1リクエストの HTTP タイムアウト秒（既定 240。10/11 の実行は 600）。
- 送り先は http://localhost:8000（コンテナ内の uvicorn に直接。Traefik は通らない）。
- 各問で status・壁時計時間・route・ツール呼び出し・cited_codes・sources・unverified_codes・
  回答の先頭300文字と、応答全体を1行にした "JSON ..." 行を標準出力に書く。

10/11 の実行では "JSON" 行を grep -v で除き、各行を cut -c で切って保存した
（正確なコマンドは記録の「6. 手順」）。実 LLM を呼ぶので API の料金と回数制限に注意する。
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
QUESTIONS = [
    "データサイエンスの次に取るべき科目は?",
    "機械学習を取るには何が必要?",
    "データベースの担当教員と開講時期を教えて",
]
TIMEOUT = int(sys.argv[2]) if len(sys.argv) > 2 else 240


def post(path, question):
    body = json.dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status = resp.status
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        status = exc.code
        data = {"error_body": exc.read().decode("utf-8", "replace")[:500]}
    wall = int((time.perf_counter() - started) * 1000)
    return status, wall, data


def short(value, limit=160):
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


which = sys.argv[1] if len(sys.argv) > 1 else "all"
results = []
for index, question in enumerate(QUESTIONS, 1):
    if which not in ("all", str(index)):
        continue
    status, wall, data = post("/test/agent/mcp", question)
    print(f"=== Q{index}: {question}")
    print("status", status, "wall_ms", wall)
    if status != 200:
        print(data)
        continue
    print("route", data["route"], "model", data["model"], "latency_ms", data["latency_ms"])
    print("node_sequence", data["node_sequence"])
    for call in data["tool_calls"]:
        print("  tool", call["name"], short(call["args"]))
    print("cited_codes", data["cited_codes"])
    print("sources", [f"{s['code']}:{s['title']}" for s in data["sources"]])
    print("unverified_codes", data["unverified_codes"])
    print("notes", data["notes"])
    print("answer", data["answer"][:300].replace("\n", " / "))
    print("JSON", json.dumps({"q": question, "status": status, "wall_ms": wall, **data}, ensure_ascii=False), flush=True)

if which in ("all", "old"):
    status, wall, data = post("/test/agent", QUESTIONS[0])
    print("=== OLD /test/agent Q1")
    print("status", status, "wall_ms", wall)
    if status == 200:
        print("keys", sorted(data))
        print("cited_codes", data["cited_codes"], "node_sequence", data["node_sequence"])
        print("answer", data["answer"][:200].replace("\n", " / "))
    else:
        print(data)
