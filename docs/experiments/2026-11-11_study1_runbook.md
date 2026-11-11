# Study 1 の運用手順書（GMS サーバー）

| 項目 | 内容 |
|---|---|
| 読む人 | GMS サーバー（https://gms-app-2.komazawa-u.ac.jp）の運用担当と実験者 |
| 作成 | 2026-11-11 |
| 元の計画 | [事前登録 Study 1](2026-11-07_prereg_study1_diag-ab.md)（2.3〜2.5 の配り方・1人の流れ、5.5 の除外、8.3 の変更記録と逸脱の表）。食い違ったら事前登録が正です |
| 対象の study | 本番 `study1-diag-ab-202611`（作成・activate 済み）。試し `pilot-diag-ab-202611`（これから作る） |
| 一言 | CLI は動いている backend の中で `docker compose exec` で打ちます。凍結を記録し、試しの study で1人分を通してから、本番のカードを配ります |

## 1. 範囲と守ること

この手順書は、凍結の記録、試しの通し、本番の運用、出力の読み方、困ったときの直し方を書きます。分析（事前登録 4・5章）は書きません。

- **CLI は動いている backend の中で打ちます。** `docker compose run --rm` は、その時点の compose.yaml と .env から新しいコンテナを作るので、backend の起動後に設定を変えていると backend と違う設定で動きえます。`exec` なら、コード（`./backend` を `/backend_app` にマウント）、環境変数、研究データの置き場所が、動いている backend と必ず同じです。backend の Dockerfile は `WORKDIR /backend_app` で、`uv sync --frozen` が backend を editable で入れるので、`exec` で `python -m course_core.research.cli` が動きます。
- 研究データの置き場所は `research_data_dir()`（`backend/src/course_core/research/settings.py`）です。環境変数 `RESEARCH_DATA_DIR` があればそこ、無ければ backend の直下の `logs/research`（コンテナでは `/backend_app/logs/research`、ホストでは `backend/logs/research`。`backend/.gitignore` の `logs/` で git の対象外）です。
- **カードの CSV（トークンの平文）、書き出し、研究データを公開リポに入れません。** 置き場所は、研究者だけが読めるリポの外のフォルダ（以下 `$PRIV`）です。CLI は、書き先が既にあるか、親に `.git` があると止まります（`cli.py` の `_private_output`）。ただしコンテナの中からはホストの `.git` が見えないので、`/backend_app` の下（ホストの `backend/`）を指定しても止まりません。**コンテナの中では `/tmp` に書き**、`docker compose cp` でリポの外へ出し、コンテナの中のものを消します。
- **凍結の後は、コード・.env・DB（PostgreSQL・Neo4j）を変えません。** backend は `fastapi dev`、frontend は `npm run dev` で動き、マウントしたファイルを変えるとすぐ読み込み直します。サーバーの作業ツリーで pull・ブランチの切り替え・編集をすると、その時点で条件が変わります。変えたら、事前登録の変更記録（参加者の前）か逸脱の表（参加者の後）に書きます。
- 設定の値は、名前を指定して必要なものだけを出します。`.env` の全体、`docker compose config`、引数なしの `printenv` は秘密を出すので使いません。
- 本番のカードを試しに開きません。開くとその pid のセッションが始まり、`set-mode` と `activate-arm` が効かなくなります（`store.py` の `set_mode`・`activate_arm`）。

### 1.1 毎回の準備

サーバーのリポのフォルダ（compose.yaml のある所）で、bash で打ちます。いつもの起動に `-f` や project 名を付けているなら、下のすべての `docker compose` に同じものを付けます。

```bash
cd <サーバーのリポのフォルダ>
PRIV=<リポの外のフォルダ>/study1          # 研究者だけが読める場所。リポの中にしない
mkdir -p "$PRIV/freeze" && chmod 700 "$PRIV"
CLI="docker compose exec backend uv run --no-sync python -m course_core.research.cli"
docker compose exec backend uv run --no-sync python -c "from course_core.research.settings import research_data_dir; print(research_data_dir())"
```

最後の行が、backend と CLI が使う研究データの置き場所です。`RESEARCH_DATA_DIR` が無ければ `/backend_app/logs/research` と出ます。

## 2. 凍結を記録する

1. `.env` に次の2つを書きます（無ければ足し、ほかの行は変えません）。

   ```
   APP_COMMIT=<git rev-parse --short HEAD の値>+local
   AGENT_MODEL=gemini-3.8-flash
   ```

   - `APP_COMMIT` は、研究のログの各行の `app_version.backend` と、セッションの応答の `backend_version` に入ります（`store.py` の `_envelope`・`to_session_out`、`schemas/research.py`）。無いとログは `null`、応答は `"unknown"` です。`+local` は、コミットできない変更が乗っている印です（今の main なら `f2dba88+local`）。
   - `AGENT_MODEL` は事前登録 2.1 の model（gemini-3.8-flash）です。main（f2dba88）の `backend/src/course_core/config.py` の既定は `gemini-3.5-flash-lite` なので、書かないと事前登録と違うモデルで動きます。
2. `.env` を変えたら、参加者のいない時間に backend を作り直します。`env_file` の値はコンテナを作るときに読まれ、`docker compose restart` では変わりません。

   ```bash
   docker compose up -d --force-recreate backend
   ```

3. 2つの値を、ファイルと動いている backend の両方で確かめます。

   ```bash
   grep -E '^(APP_COMMIT|AGENT_MODEL)=' .env
   docker compose exec backend sh -c 'echo "APP_COMMIT=$APP_COMMIT"; echo "AGENT_MODEL=$AGENT_MODEL"'
   ```

4. コードの状態をリポの外に保存し、SHA-256 を控えます。

   ```bash
   git rev-parse HEAD > "$PRIV/freeze/head.txt"
   git status --short > "$PRIV/freeze/status.txt"
   git diff > "$PRIV/freeze/uncommitted.diff"
   date -Iseconds > "$PRIV/freeze/at.txt"
   sha256sum "$PRIV"/freeze/*.txt "$PRIV/freeze/uncommitted.diff" | tee "$PRIV/freeze.sha256"
   ```

   `git diff` に入るのは追跡しているファイルの変更だけです。`git status` で `??` のファイルと、`.gitignore` に入っている `compose.override.yaml` は入りません。`compose.override.yaml` を使っているなら `"$PRIV/freeze/"` に写して SHA-256 を取ります。`.env` は写しません。差分は公開の場所に貼らず、SHA-256 だけを共有します。
5. HEAD、`uncommitted.diff` の SHA-256、`APP_COMMIT`・`AGENT_MODEL` の値、時刻を実験者に渡します。実験者は、事前登録の変更記録と実験報告の「実行環境」に書きます。

## 3. 試しの study で1人分を通す

本番のカードを配る前に、別の study で最初から最後まで通します。値は本番と同じで、違うのは study-id・n・spares・cards-out だけです。n 1 なので、通るのは P01・系列 Q1（ブロック1 が V30＋P1、ブロック2 が V31＋P2）だけです。V31 が先の順（Q2・Q4）は通りません。

### 3.1 作る

```bash
$CLI create-study --study-id pilot-diag-ab-202611 --department kansai-enechem-2026 \
  --arm diag=N:W:V30,A:Y:V31 --task-sets P1,P2 --n 1 --spares 0 \
  --consent-version v1-diag-ab-202611 --questionnaires-per-block 2 --final-questionnaires 1 \
  --base-url https://gms-app-2.komazawa-u.ac.jp --cards-out /tmp/pilot-cards.csv
docker compose cp backend:/tmp/pilot-cards.csv "$PRIV/pilot-cards.csv"
docker compose exec backend rm /tmp/pilot-cards.csv
$CLI activate-arm --study-id pilot-diag-ab-202611 --arm diag --note "pilot; HEAD=<短いハッシュ>; diff sha256=<先頭12桁>; APP_COMMIT=<値>; AGENT_MODEL=<値>"
$CLI status --study-id pilot-diag-ab-202611
```

- `create-study` が出す「study を作りました: <パス>」が、1.1 の置き場所の下にあることを確かめます。割り付けの表は `P01,Q1,False,P1,P2` の1行です（トークンは画面に出ません）。
- `--base-url` は CSV の url 列にだけ効きます。省くと url 列は `/s/<トークン>` だけです。
- `activate-arm` は、その study にセッションが1つも無い間だけ通ります。

### 3.2 通す人がすること

CSV の url を、ブラウザのプライベートウィンドウで開きます（`/s/<トークン>` は `/navi/s/<トークン>` に移ります）。始めと終わりの時刻を控えます（自走の部分の見込みは約42分）。

| 段 | すること | 確かめること |
|---|---|---|
| 同意 | 同意書の番号の欄に試しの番号（例 `TEST-01`。英数字とハイフンで16文字まで）を入れ、「同意して始める」 | 画面の下に「同意文の版 v1-diag-ab-202611」と出る |
| 事前の質問 | 学年・学部・前に見たか | |
| 練習（ブロック0） | 練習のカード C。診断に答えてプランを出し、直して出す（課題は1つ。質問票は出ない） | 旗はブロック1と同じ（Q1 なので V30） |
| ブロック1 | カード（P1、A さん）→ 課題 a（診断に答えてプランを出す）→ 課題 b（直して「これで出す」）→ SUS・Q11・Q12 | AI の欄が無い |
| ブロック2 | 画面の案内 → カード（P2、B さん）で同じ流れ。「AIに直しを頼む」と、さがすの欄の［AIに聞く］を1回ずつ使う | AI の欄がある。待ちの長さ |
| 二択と理由 | 画面1と画面2のどちらを使いたいか | 終わりの画面まで進む |

### 3.3 終わったあと

```bash
$CLI status --study-id pilot-diag-ab-202611
$CLI check --study-id pilot-diag-ab-202611; echo "終了コード $?"
$CLI export --study-id pilot-diag-ab-202611 --out /tmp/pilot-events.jsonl
# ここで 5.3 のスクリプトを /tmp/pilot-events.jsonl に当てる
docker compose cp backend:/tmp/pilot-events.jsonl "$PRIV/pilot-events.jsonl"
docker compose exec backend rm /tmp/pilot-events.jsonl
sha256sum "$PRIV/pilot-events.jsonl"
```

「よい」の条件:

- `status`: Q1 が `割り当て 1・開始 1・完了 1・予備の使用 -`、ほかの系列は 0、`撤回: なし`。
- `check`: `セッション 1（完了 1・途中で終了 0・進行中 0）、欠け 0`、P01 の行が `complete … 印: なし`、終了コード 0。
- export（5.3 の出力）:
  - `同意の版` が `v1-diag-ab-202611`（`None` は同意の前に書かれた session_start などだけ）。`同意` の form_serial が試しの番号。
  - `backend` が `.env` の `APP_COMMIT` の1つだけ（`None` なら 2章の 1〜3 をやり直す）。
  - `印` が空。とくに `flags_mismatch`（画面とサーバーの旗の違い。事前登録 5.2 の前提）と `payload_missing:plan`（task_submit に最終プランが無い）が無いこと。
  - P01 の行が `qNone:事前の質問 0:P/V30/practice 1:W/V30/P1 q1:SUS q1:Q11-Q12 2:Y/V31/P2 q2:SUS q2:Q11-Q12 qNone:二択`。
  - `chat_response` がブロック2（V31）にだけあり、model が `gemini-3.8-flash`、error が `None`。「AIに直しを頼む」は path `static`・plan_delivery `delivered`、［AIに聞く］は path `mcp`・plan_delivery `None`（`api/routers/assist.py`、`agent/route_options.py` の `select_path`）。

試しのログは、効果の分析と判定（事前登録 4・5章）に使いません。study ごとにフォルダが分かれるので、本番の export には混ざりません。事前登録 3.3 の、score.py と画面の判定の照合には使います。直すことが出たら、直して変更記録に書き、2章を取り直し、別の study-id（例 `pilot2-diag-ab-202611`）で通し直します。同じ study-id は2度作れません。

## 4. 本番を運用する

### 4.1 始める前

```bash
$CLI status --study-id study1-diag-ab-202611
$CLI check --study-id study1-diag-ab-202611; echo "終了コード $?"
docker compose exec backend uv run --no-sync python -c "from course_core.research.store import default_store; s = default_store().load_study('study1-diag-ab-202611'); print(s.consent_version, s.active_arm, s.task_sets, s.questionnaires_per_block, s.final_questionnaires, len(s.participants))"
```

- `status` が `腕 diag` で、Q1〜Q4 がどれも `割り当て 3・開始 0・完了 0・予備の使用 -`、`撤回: なし`。「止めました: study … がありません」なら、本番の study は backend の置き場所にありません。配る前に実験者に知らせます。
- `check` が `セッション 0 … 欠け 0`、終了コード 0。3行目が `v1-diag-ab-202611 diag ['P1', 'P2'] 2 1 16`。
- 凍結の記録を本番のログにも残すときは、最初の参加者の前に、同じ腕でもう一度 `$CLI activate-arm --study-id study1-diag-ab-202611 --arm diag --note "<3.1 と同じ形の凍結の記録>"` を打ちます（腕は diag のまま、study_arm_activated が1行増える）。

### 4.2 カードを配る

- カードは P01 から順に重ね、来た人に上から渡します。研究者はカードを選びません（事前登録 2.3）。流れは 3.2 と同じで、同意書の番号の欄には紙の同意書の通し番号を入れます。
- 自宅から参加する人には、カードを送る前に `$CLI set-mode --study-id study1-diag-ab-202611 --pid <pid> --mode remote` を打ちます。セッションが始まった後は変えられません。

### 4.3 脱落と撤回

- 脱落（両ブロックを終えなかった人）が出たら、同じ系列の予備カードを次の人に渡します。R01 が Q1、R02 が Q2、R03 が Q3、R04 が Q4 です。脱落した人のカードは使い回しません。使った予備と理由を逸脱の表（事前登録 8.3）に書きます。
- 撤回は、本人の申し出を確かめてから `$CLI withdraw --study-id study1-diag-ab-202611 --pid <pid>` を打ちます。その pid の行とセッションの状態を研究データから消し、元に戻せません。消した行数と時刻は study.json に残り、そのカードは開けなくなります。書き出し済みのファイルがあれば別に消し、予備カードで補います（事前登録 5.5 の E1・E2）。

### 4.4 毎日の終わりと、最後の書き出し

毎日の終わりに `status` と `check` を打ちます（4.1 の1・2行目）。欠けや印があれば、日付・pid・中身を逸脱の表に書き、実験者に知らせます。全員が終わったら書き出します。

```bash
$CLI export --study-id study1-diag-ab-202611 --out /tmp/study1-events.jsonl
# ここで 5.3 のスクリプトを /tmp/study1-events.jsonl に当てる
docker compose cp backend:/tmp/study1-events.jsonl "$PRIV/study1-events.jsonl"
docker compose exec backend rm /tmp/study1-events.jsonl
sha256sum "$PRIV/study1-events.jsonl"
```

撤回した pid の行は入りません。書き出しは公開リポに入れず、分析のスクリプトにはこの場所を引数で渡します（事前登録 6.3）。

## 5. 結果を確かめる

### 5.1 status

```
study <study-id>（学科 kansai-enechem-2026、腕 <腕。無ければ 未決定>）
系列  割り当て  開始  完了  予備の使用
Q1           3     0     0  -
（Q2〜Q4 も同じ形）
撤回: <pid の並び。無ければ なし>
```

- 割り当ては、その系列の予備でないカードの数です。開始はセッションが始まった人の数（予備を含む）、完了はブロック2を終えた人の数、予備の使用はセッションが始まった予備の pid です。
- 終了コードはいつも 0 です（study が無いときだけ「止めました: …」で 1）。
- 「よい」の条件: 腕が diag。開始 − 完了が、今いる人と脱落した人の数に合う。予備の使用と撤回が、逸脱の表と合う。

### 5.2 check

```
study <study-id>: セッション <数>（完了 <数>・途中で終了 <数>・進行中 <数>）、欠け <数>
  <pid>（<系列>）<complete | ended_incomplete | in_progress> seq 1..<最後の seq> 印: <印×数。無ければ なし>
    欠け: <中身>
```

- complete はブロック2を終えた人、ended_incomplete は終えずにセッションが閉じた人、in_progress はまだ閉じていない人です。
- 欠け（`store.py` の `check_completeness`）: seq の欠け・重なり、event_id の重なり、session_start が無い、同意の記録が無いのにブロックがある、終えたブロックの task_start・task_submit が2件でない、終えたブロックの questionnaire_submit が2件より少ない、閉じたセッションで最後のブロックの後の questionnaire_submit が1件より少ない。終えていないブロックは数えません。
- 印（`store.py` の `_client_event_warnings`、`events.py` の `payload_warnings`）: `flags_mismatch`、`seq_gap`・`seq_out_of_order`、`task_not_in_block`・`task_id_missing`、`payload_missing:<項目>`・`payload_invalid:<項目>`・`payload_unknown:<項目>`、`ts_client_naive`。
- 終了コードは、欠けが0なら 0、1つでもあれば 1 です（study が無いときも 1）。印は終了コードに効かないので、目で見ます。
- 「よい」の条件: 終了コード 0。終えた人が complete。印が「なし」（出たら種類を記録し、理由を調べる）。

### 5.3 export の中身を見る

コンテナの中の書き出しに当てます（`<書き出し>` を `/tmp/pilot-events.jsonl` などに替える）。標準のライブラリだけで動きます。

```bash
docker compose exec -T backend python - <書き出し> <<'EOF'
import json, sys
from collections import Counter, defaultdict
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
mine = [r for r in rows if r["pid"]]
print("同意の版:", dict(Counter(r["consent_version"] for r in mine)))
print("同意:", [(r["pid"], r["payload"]["form_serial"], r["payload"]["agreed"]) for r in mine if r["event_type"] == "consent_recorded"])
print("backend:", dict(Counter(r["app_version"]["backend"] for r in mine)))
print("印:", dict(Counter(w for r in mine for w in r["warnings"])))
people = defaultdict(list)
for r in mine:
    p = r["payload"]
    if r["event_type"] == "block_start":
        people[(r["pid"], r["sequence_id"])].append(f'{p["block"]}:{p["condition_id"]}/{r["variant_id"]}/{p["task_set_id"]}')
    elif r["event_type"] == "questionnaire_submit":
        people[(r["pid"], r["sequence_id"])].append(f'q{r["block"]}:{p.get("scale")}')
for (pid, seq), items in sorted(people.items()):
    print(pid, seq, " ".join(items))
ai = Counter((r["block"], r["variant_id"], r["payload"]["model"], r["payload"]["path"], r["payload"]["plan_delivery"], r["payload"]["error"]) for r in mine if r["event_type"] == "chat_response")
print("chat_response:", dict(ai))
EOF
```

本番では、3.3 と同じ条件に加えて、人ごとの行が系列どおりであることを見ます（`study.py` の `_SEQUENCE_ORDER`。練習はブロック1の変種で記号 P）。質問票は、最初に `qNone:事前の質問`、ブロックごとに `SUS` と `Q11-Q12`、最後に `qNone:二択` です。`chat_response` の error（`timeout`・`llm`・`db`・`mcp_unavailable`・`other`）は F3 の分子に入ります（事前登録 5.6）。

| 系列 | 練習 | ブロック1 | ブロック2 |
|---|---|---|---|
| Q1 | 0:P/V30/practice | 1:W/V30/P1 | 2:Y/V31/P2 |
| Q2 | 0:P/V31/practice | 1:Y/V31/P1 | 2:W/V30/P2 |
| Q3 | 0:P/V30/practice | 1:W/V30/P2 | 2:Y/V31/P1 |
| Q4 | 0:P/V31/practice | 1:Y/V31/P2 | 2:W/V30/P1 |

## 6. 困ったとき

| 起きたこと | 原因（コードで分かること） | 直し方 |
|---|---|---|
| カードの URL を開くと「このカードの URL は使えません。研究者に知らせてください。」 | 404「カードのトークンが見つかりません。」（`api/routers/research.py`）。backend は自分の置き場所の study だけを探す。CLI を `run --rm` や別の `RESEARCH_DATA_DIR` で打つと、study が別の場所にできる。URL の写し間違いでも同じ | 1.1 の置き場所と、`create-study` の「study を作りました: …」のパスを比べる。`exec` の `status` で study が見えるかを確かめる |
| カードを開くと「いまは進めません（サーバーの準備か順番が合っていません）。…」 | 409。腕が未決定、撤回済み、終えたカード、DB に SIMILAR_TO がある（C8、`study.py` の `start_violations`）のどれか。理由は応答の本文（ブラウザの開発者ツールのネットワーク）に出る | `status` で腕と撤回を見る。腕が未決定なら `activate-arm`。終えたカードは開き直せない。C8 は Neo4j で `MATCH ()-[r:SIMILAR_TO]->() RETURN count(r)` が 0 かを見る |
| 同意を押すと「いまは進めません…」が出て進めない | 409「同意書の版 … は study の版 … と違います。」。画面の版（`frontend/src/navi/studyConfig.ts` の `CONSENT.version`。画面の下に出る）と study の `consent_version` が違う | 4.1 の3行目で study の版を出し、画面の下の版と比べる。study の版は作った後に変えられない。画面の版を変えるのはコードの変更なので変更記録へ |
| タブを閉じた・別の端末で開き直した | 同じカードの URL を開くと、サーバーが前のセッションを返して続きから進む。このタブに前の状態が無いと、ブロックの最初の課題からやり直し、`client_error`（`resumed_without_local_state`）が残る（`studyFlow.ts`） | 逸脱の表に書く。同じ課題をやり直すので、`check` で task_start・task_submit の数の欠けが出ることがある |
| `check` の終了コードが 1 | 5.2 の欠け | 欠けの行を逸脱の表に書く。seq の欠けはイベントが届かなかったこと。セッションのイベントの 10% を超えたら E3（事前登録 5.5） |
| 「止めました: … は既にあります（上書きしません）」か「… git の作業ツリーの中（…）には書きません」 | `--cards-out`・`--out` の書き先に同じ名前のファイルがあるか、ホストで CLI を直接打ち、書き先がリポの中 | `exec` と `/tmp` の別の名前を使う。`/tmp` に前のファイルが残っていれば消す |
| V31 で AI が答えない・遅い | サーバーは 170 秒で打ち切る（504）。`chat_response` の error に種類が残る | 5.3 で error を数える。`llm` が続くなら、2章の 3 で `AGENT_MODEL` を、別に API キーの枠を確かめる（値は出さない） |
| `.env` を変えたのに効かない | `env_file` はコンテナを作るときに読まれ、`restart` では変わらない | 2章の 2・3 |

## 7. 確かめていないこと

- サーバーのコミットできない変更（compose.yaml まわり、データの永続化）の中身。この手順は main の compose.yaml（`./backend:/backend_app`、`env_file: .env`、`fastapi dev`）を前提にしています。`RESEARCH_DATA_DIR` を置いているかは 1.1 の出力で、本番の study が backend の置き場所にあるかは 4.1 の `status` で確かめます。
- サーバーの OS とシェル（bash、`sha256sum`、Docker Compose v2 の `exec`・`cp` を前提にしています）。
- この手順の `docker compose` の行は、サーバーで打っていません。CLI の出力の形と止まり方（`create-study`・`activate-arm`・`status`・`check`・`export`、書き先の検査）と 5.3 のスクリプトは、手元で `RESEARCH_DATA_DIR` を一時フォルダにして、コンテナの外で確かめました。
- 3.2 の画面の流れは frontend のコード（`studyFlow.ts`・`studyConfig.ts`・`TaskCard.tsx`）から書きました。画面では通していません。
- gemini-3.8-flash が、サーバーの API キーで使えること（3.3 の `chat_response` で確かめる）。
