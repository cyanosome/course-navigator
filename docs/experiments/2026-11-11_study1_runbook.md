# Study 1 の運用手順書（GMS サーバー）

| 項目 | 内容 |
|---|---|
| 読む人 | GMS サーバー（https://gms-app-2.komazawa-u.ac.jp）の運用担当と実験者 |
| 作成 | 2026-11-11（同じ日に、研究者が立ち会わずリンクで配る形に直した） |
| 元の計画 | [事前登録 Study 1](2026-11-07_prereg_study1_diag-ab.md)（2.3〜2.5 の配り方・1人の流れ、5.5 の除外、8.3 の変更記録と逸脱の表）。食い違ったら事前登録が正です。リンクで配る形への変更は、事前登録の変更記録の 2026-11-11 の行に書いてあります |
| 対象の study | 本番 `study1-diag-ab-202611`（作成・activate 済み。同意の版が `v1-diag-ab-202611` ならそのまま使う。違えば作り直す。4.1）。試し `pilot2-link-202611`（これから作る）。前の試し `pilot-diag-ab-202611` は使いません（消しません） |
| 一言 | CLI は動いている backend の中で `docker compose exec` で打ちます。凍結を記録し、試しの study で2人分（V30 が先・V31 が先）を通してから、本番のリンクを1人に1つずつ送ります。研究者は立ち会わず、参加者はひとりで最後まで進めます |

## 1. 範囲と守ること

この手順書は、凍結の記録、試しの通し、本番の運用、出力の読み方、困ったときの直し方を書きます。分析（事前登録 4・5章）は書きません。

- **CLI は動いている backend の中で打ちます。** GMS は main の compose.yaml に、データの永続化のコミットしていない変更を足して動いています（compose.eval.yaml は使っていません。11/11 の運用担当の連絡）。11/11 の試しの study は `docker compose run` で作り、そのカードは動いている backend で開けたので、研究データの置き場所は `run` と `exec` で同じです。それでも `docker compose run --rm` は、その時点の compose.yaml と .env から新しいコンテナを作るので、backend の起動後に .env を変えていると backend と違う設定で動きえます。`exec` なら、コード（`./backend` を `/backend_app` にマウント）、環境変数、研究データの置き場所が、動いている backend と必ず同じです。backend の Dockerfile は `WORKDIR /backend_app` で、`uv sync --frozen` が backend を editable で入れるので、`exec` で `python -m course_core.research.cli` が動きます。
- 研究データの置き場所は `research_data_dir()`（`backend/src/course_core/research/settings.py`）です。環境変数 `RESEARCH_DATA_DIR` があればそこ、無ければ backend の直下の `logs/research`（コンテナでは `/backend_app/logs/research`、ホストでは `backend/logs/research`。`backend/.gitignore` の `logs/` で git の対象外）です。
- **カードの CSV（トークンの平文）、誰にどのリンクを送ったかの控え、書き出し、研究データを公開リポと vault に入れません。** 置き場所は、研究者だけが読めるリポの外のフォルダ（以下 `$PRIV`）です。CLI は、書き先が既にあるか、親に `.git` があると止まります（`cli.py` の `_private_output`）。ただしコンテナの中からはホストの `.git` が見えないので、`/backend_app` の下（ホストの `backend/`）を指定しても止まりません。**コンテナの中では `/tmp` に書き**、`docker compose cp` でリポの外へ出し、コンテナの中のものを消します。
- **凍結の後は、コード・.env・DB（PostgreSQL・Neo4j）を変えません。** backend は `fastapi dev`、frontend は `npm run dev` で動き、マウントしたファイルを変えるとすぐ読み込み直します。サーバーの作業ツリーで pull・ブランチの切り替え・編集をすると、その時点で条件が変わります。変えたら、事前登録の変更記録（参加者の前）か逸脱の表（参加者の後）に書きます。
- 設定の値は、名前を指定して必要なものだけを出します。`.env` の全体、`docker compose config`、引数なしの `printenv` は秘密を出すので使いません。
- 本番のリンクを試しに開きません。開くとその pid のセッションが始まり、`set-mode` と `activate-arm` が効かなくなります（`store.py` の `set_mode`・`activate_arm`）。

### 1.1 毎回の準備

サーバーのリポのフォルダ（compose.yaml のある所）で、bash で打ちます。いつもの起動に `-f` や project 名を付けているなら、下のすべての `docker compose` に同じものを付けます。

```bash
cd <サーバーのリポのフォルダ>
PRIV=<リポの外のフォルダ>/study1          # 研究者だけが読める場所。リポの中にしない
mkdir -p "$PRIV/freeze" && chmod 700 "$PRIV"
CLI="docker compose exec backend uv run --no-sync python -m course_core.research.cli"
RUN="docker compose exec backend uv run --no-sync python -m"   # 分析の道具（backend/eval/study1/）
docker compose exec backend uv run --no-sync python -c "from course_core.research.settings import research_data_dir; print(research_data_dir())"
```

最後の行が、backend と CLI が使う研究データの置き場所です。`RESEARCH_DATA_DIR` が無ければ `/backend_app/logs/research` と出ます。

分析の道具（`backend/eval/study1/`。使い方はその README の「GMS での打ち方」）は、別の PR で main に入れます。`RUN` で打つ手順（2.1、3.3、4.4、4.5）は、**`backend/eval/study1/` が GMS に入ってから**打ちます。道具も研究者用 CLI と同じく、書き先が既にあるか git の作業ツリーの中なら止まるので、コンテナの中では `/tmp` に書き、`docker compose cp` でリポの外へ出し、コンテナの中のものを消します。

## 2. 凍結を記録する

凍結は、リンクで配る形への変更（必修のチェック・同意の文・振り返り）が main に入り、GMS に反映された後のコミットで取り直します。前の凍結（試しの study `pilot-diag-ab-202611` を通したときのもの）は使いません。

1. `.env` に次の3つを書きます（無ければ足し、ほかの行は変えません）。

   ```
   APP_COMMIT=<git rev-parse --short HEAD の値>+local
   VITE_APP_COMMIT=<APP_COMMIT と同じ値>
   AGENT_MODEL=gemini-3.8-flash
   ```

   - `APP_COMMIT` は、研究のログの各行の `app_version.backend` と、セッションの応答の `backend_version` に入ります（`store.py` の `_envelope`・`to_session_out`、`schemas/research.py`）。無いとログは `null`、応答は `"unknown"` です。`+local` は、コミットしていない変更（compose.yaml のデータの永続化など）が乗っている印です。`git status --short` が空なら `+local` を付けません。
   - `VITE_APP_COMMIT` は frontend の版です。compose.yaml の frontend は `env_file: .env` で環境変数を受け取り、Vite（8.0.16）は起動したときの環境変数のうち `VITE_` で始まるものを `import.meta.env` に入れます（`node_modules/vite/dist/node/chunks/node.js` の `loadEnv`）。画面はこの値を `X-Navi-Frontend` ヘッダで送り、研究のログの `app_version.frontend` に入ります（`frontend/src/navi/research.ts` の `FRONTEND_VERSION`。無ければ `dev`）。
   - `AGENT_MODEL` は事前登録 2.1 の model（gemini-3.8-flash）です。`backend/src/course_core/config.py` の既定は `gemini-3.5-flash-lite` なので、書かないと事前登録と違うモデルで動きます。
2. `.env` を変えたら、参加者のいない時間に backend と frontend を作り直します。`env_file` の値はコンテナを作るときに読まれ、`docker compose restart` では変わりません。Vite は起動したときに環境変数を読むので、frontend も作り直します。

   ```bash
   docker compose up -d --force-recreate backend frontend
   ```

3. 3つの値を、ファイルと動いているコンテナの両方で確かめます。

   ```bash
   grep -E '^(APP_COMMIT|VITE_APP_COMMIT|AGENT_MODEL)=' .env
   docker compose exec backend sh -c 'echo "APP_COMMIT=$APP_COMMIT"; echo "AGENT_MODEL=$AGENT_MODEL"'
   docker compose exec frontend sh -c 'echo "VITE_APP_COMMIT=$VITE_APP_COMMIT"'
   ```

4. コードの状態をリポの外に保存し、SHA-256 を控えます。compose.yaml のコミットしていない変更（データの永続化）は、全体の差分とは別に、compose.yaml だけの差分も取ります。

   ```bash
   git rev-parse HEAD > "$PRIV/freeze/head.txt"
   git status --short > "$PRIV/freeze/status.txt"
   git diff > "$PRIV/freeze/uncommitted.diff"
   git diff -- compose.yaml > "$PRIV/freeze/compose.diff"
   date -Iseconds > "$PRIV/freeze/at.txt"
   sha256sum "$PRIV"/freeze/*.txt "$PRIV"/freeze/*.diff | tee "$PRIV/freeze.sha256"
   ```

   `git diff` に入るのは追跡しているファイルの変更だけです。`git status` で `??` のファイルと、`.gitignore` に入っている `compose.override.yaml` は入りません。`compose.override.yaml` を使っているなら `"$PRIV/freeze/"` に写して SHA-256 を取ります。`.env` は写しません。差分は公開の場所に貼らず、SHA-256 だけを共有します。
5. HEAD、`uncommitted.diff` と `compose.diff` の SHA-256、`APP_COMMIT`・`VITE_APP_COMMIT`・`AGENT_MODEL` の値、時刻、2.1 の科目のスナップショットの SHA-256 を実験者に渡します。実験者は、事前登録の変更記録と実験報告の「実行環境」に書きます。

### 2.1 凍結の DB で下調べを流す（試しの前に1回）

`backend/eval/study1/` が GMS に入ってから打ちます。凍結の取り直し（上の 1〜4）の後、試し（3章）の前に打ちます。

```bash
# 科目のスナップショット（凍結の DB の、採点に要る科目の属性）。score・metrics の入力になる
$RUN eval.study1.catalog_snapshot --out /tmp/study1-catalog.json
docker compose cp backend:/tmp/study1-catalog.json "$PRIV/freeze/study1-catalog.json"
# 下調べ（凍結の設定とデータで、事前登録 3.3・3.4 の値を数え直す）
$RUN eval.study1.feasibility --git-sha "$(git rev-parse --short HEAD)" --json-out /tmp/study1-feasibility.json; echo "終了コード $?"
docker compose cp backend:/tmp/study1-feasibility.json "$PRIV/freeze/study1-feasibility.json"
docker compose exec backend rm /tmp/study1-catalog.json /tmp/study1-feasibility.json
sha256sum "$PRIV/freeze/study1-catalog.json" "$PRIV/freeze/study1-feasibility.json" | tee -a "$PRIV/freeze.sha256"
```

- スナップショットの SHA-256 を凍結の記録に足します（上の 5 で渡し、3.1・4.1 の `activate-arm` の記録にも書く）。`$PRIV/freeze/study1-catalog.json` が以後の正本で、score・metrics に使うときはここからコンテナへ写します。
- feasibility の終了コードが 0 で、各カードの行が「下調べの値（registered）と 同じ」なら、3.3・3.4 の値は事前登録と同じです。違う（終了コード 1、「違う: …」「問題: …」の行）なら、**最初の参加者の前に**実験者が事前登録の変更記録に書きます。

## 3. 試しの study で2人分を通す

本番のリンクを送る前に、別の study で最初から最後まで通します。値は本番と同じで、違うのは study-id・n・spares・cards-out だけです。n 2 なので、P01 が系列 Q1（ブロック1 が V30＋P1、ブロック2 が V31＋P2）、P02 が系列 Q2（ブロック1 が V31＋P1、ブロック2 が V30＋P2）です。11/11 の試しで通らなかった V31 が先の順（V31 での練習、ブロック2の V30 の案内）を、P02 で通します。

### 3.1 作る

```bash
$CLI create-study --study-id pilot2-link-202611 --department kansai-enechem-2026 \
  --arm diag=N:W:V30,A:Y:V31 --task-sets P1,P2 --n 2 --spares 0 \
  --consent-version v1-diag-ab-202611 --questionnaires-per-block 2 --final-questionnaires 2 \
  --base-url https://gms-app-2.komazawa-u.ac.jp --cards-out /tmp/pilot2-cards.csv
docker compose cp backend:/tmp/pilot2-cards.csv "$PRIV/pilot2-cards.csv"
docker compose exec backend rm /tmp/pilot2-cards.csv
for pid in P01 P02; do $CLI set-mode --study-id pilot2-link-202611 --pid "$pid" --mode remote || break; done
$CLI activate-arm --study-id pilot2-link-202611 --arm diag --note "pilot2; HEAD=<短いハッシュ>; diff sha256=<先頭12桁>; compose.diff sha256=<先頭12桁>; catalog sha256=<先頭12桁>; APP_COMMIT=<値>; VITE_APP_COMMIT=<値>; AGENT_MODEL=<値>"
$CLI status --study-id pilot2-link-202611
```

- `create-study` が出す「study を作りました: <パス>」が、1.1 の置き場所の下にあることを確かめます。割り付けの表は `P01,Q1,False,P1,P2` と `P02,Q2,False,P1,P2` の2行です（トークンは画面に出ません）。
- `set-mode` は、pid ごとに「… の mode を remote にしました。」と出ます。セッションが始まった pid では止まります（その前に打つ）。
- `--base-url` は CSV の url 列にだけ効きます。省くと url 列は `/s/<トークン>` だけです。
- `activate-arm` は、その study にセッションが1つも無い間だけ通ります。
- `status` は Q1・Q2 が `割り当て 1・開始 0・完了 0・予備の使用 -`、Q3・Q4 が 0 です。

### 3.2 通す人がすること

参加者と同じように、付録の文の雛形でリンクを自分に送り、ブラウザのプライベートウィンドウで開きます（`/s/<トークン>` は `/navi/s/<トークン>` に移ります）。P01 と P02 は別のプライベートウィンドウで、1つずつ通します。始めと終わりの時刻を控えます（自走の見込みは約45分）。

| 段 | すること | 確かめること |
|---|---|---|
| 同意 | 文を読み、「同意して始める」 | 番号の欄が無い。「すること」に「ひとりで進めます」「45分ほど」、「AI の欄」に Gemini API、「記録を消してほしいとき」に7日以内とある。画面の下に「同意文の版 v1-diag-ab-202611」 |
| 事前の質問 | 学年・学部・前に見たか | |
| 練習（ブロック0） | 練習のカード C。診断に答えてプランを出し、直して出す（課題は1つ。質問票は出ない） | 旗はブロック1と同じ（P01 は V30 で AI の欄が無い。P02 は V31 で AI の欄がある） |
| ブロック1 | カード（P1、A さん）→ 課題 a（診断に答えてプランを出す）→ 課題 b（直して「これで出す」）→ SUS・Q11・Q12 | P01 は AI の欄が無い。P02 は AI の欄がある。課題 b で同じ名前の別のクラスへ移しても、「必修」のチェックが「ありません」と出ない |
| ブロック2 | 画面の案内 → カード（P2、B さん）で同じ流れ。AI の欄がある画面では「AIに直しを頼む」と、さがすの欄の［AIに聞く］を1回ずつ使う | P01 は案内に AI の段落があり、AI の欄がある。P02 は案内に AI の段落が無く、AI の欄が無い。AI の待ちの長さ |
| 二択と振り返り | 画面1と画面2のどちらを使いたいかと理由、続けて振り返り（任意の自由記述6問。1つは書いてみる） | 振り返りの上に「どれも書かなくてもかまいません」とある |
| 終わり | | 「ご協力ありがとうございました。これで全部終わりです。このタブは閉じてかまいません。」 |

課題 b（P1・P2）の「これで出す」を押す前に、画面のチェックの一覧の判定（満たす・満たさない・判定できない）を書き留めます（スクリーンショットでよい）。3.3 で score の採点と比べます。カードの条件に当たるチェック（空ける曜日・時限、学期ごとの単位）を画面で足しておくと比べやすくなります。

### 3.3 終わったあと

```bash
$CLI status --study-id pilot2-link-202611
$CLI check --study-id pilot2-link-202611; echo "終了コード $?"
$CLI export --study-id pilot2-link-202611 --out /tmp/pilot2-events.jsonl
# ここで 5.3 のスクリプトを /tmp/pilot2-events.jsonl に当てる

# 分析の道具（backend/eval/study1/ が GMS に入ってから）: 完全性の検査と、課題 b の最終プランの採点
$RUN eval.study1.integrity --events /tmp/pilot2-events.jsonl --study-id pilot2-link-202611; echo "終了コード $?"
docker compose cp "$PRIV/freeze/study1-catalog.json" backend:/tmp/study1-catalog.json
docker compose exec -T backend python - /tmp/pilot2-events.jsonl <<'EOF'
import json, sys
for line in open(sys.argv[1], encoding="utf-8"):
    r = json.loads(line)
    if r["event_type"] == "task_submit" and r["task_id"] in ("P1-b", "P2-b"):
        out = f'/tmp/pilot2-plan-{r["pid"]}-{r["task_id"]}.json'
        with open(out, "x", encoding="utf-8") as f:
            json.dump({"plan": r["payload"]["plan"]}, f, ensure_ascii=False)
        print(out)
EOF
for pid in P01 P02; do for ts in P1 P2; do
  echo "== $pid $ts"
  $RUN eval.study1.score --catalog /tmp/study1-catalog.json --plan "/tmp/pilot2-plan-$pid-$ts-b.json" --task-set "$ts"
done; done
docker compose exec backend sh -c 'rm /tmp/study1-catalog.json /tmp/pilot2-plan-*.json'

docker compose cp backend:/tmp/pilot2-events.jsonl "$PRIV/pilot2-events.jsonl"
docker compose exec backend rm /tmp/pilot2-events.jsonl
sha256sum "$PRIV/pilot2-events.jsonl"
```

「よい」の条件:

- `status`: Q1・Q2 がどちらも `割り当て 1・開始 1・完了 1・予備の使用 -`、Q3・Q4 は 0、`撤回: なし`。
- `check`: `セッション 2（完了 2・途中で終了 0・進行中 0）、欠け 0`、P01・P02 の行がどちらも `complete … 印: なし`、終了コード 0。
- export（5.3 の出力）:
  - `同意の版` が `v1-diag-ab-202611`（`None` は同意の前に書かれた session_start などだけ）。`同意` が P01・P02 とも form_serial `ONLINE`・agreed `True`。
  - `mode` が `remote` だけ。
  - `backend` が `.env` の `APP_COMMIT` の1つだけ、`frontend` が `VITE_APP_COMMIT` の1つだけ（`backend` が `None`、`frontend` が `dev` なら 2章の 1〜3 をやり直す）。
  - `質問票の版` が `2026-11-11` だけで14件（1人7件: 事前の質問1・ブロックごとに2・最後に2）。
  - `印` が空。とくに `flags_mismatch`（画面とサーバーの旗の違い。事前登録 5.2 の前提）と `payload_missing:plan`（task_submit に最終プランが無い）が無いこと。
  - P01 の行が `qNone:事前の質問 0:P/V30/practice 1:W/V30/P1 q1:SUS q1:Q11-Q12 2:Y/V31/P2 q2:SUS q2:Q11-Q12 qNone:二択 qNone:振り返り`。
  - P02 の行が `qNone:事前の質問 0:P/V31/practice 1:Y/V31/P1 q1:SUS q1:Q11-Q12 2:W/V30/P2 q2:SUS q2:Q11-Q12 qNone:二択 qNone:振り返り`。
  - `chat_response` が V31 のブロックにだけあり、model が `gemini-3.8-flash`、error が `None`。「AIに直しを頼む」は path `static`・plan_delivery `delivered`、［AIに聞く］は path `mcp`・plan_delivery `None`（`api/routers/assist.py`、`agent/route_options.py` の `select_path`）。
- `integrity`: 終了コード 0（1 なら欠けがあり、2 なら書き出しが読めない）。同意の版（既定 `v1-diag-ab-202611`）、最後の質問票（既定 `二択,振り返り`）も見るので、check で気づけない振り返りの欠けもここで分かる。
- `score`: 4つのプランとも1行ずつ `y=… a=…/6 | K1 … | … | K6 …` が出て、「スナップショットに無い科目」が出ない。K2（空ける曜日・時限）・K3（単位）・K6（重なり）の判定が、3.2 で書き留めた画面のチェックの判定と食い違わない（事前登録 3.3 の、画面の判定との一致の確かめの一部）。K1 は、画面のチェックがプランの全部の学期を数え、採点は 3年春・3年秋だけを数えるので、違ってもよい。K4・K5 は採点だけの規則で、画面にはない。食い違ったら、プランと両方の判定を実験者に渡す。

試しのログは、効果の分析と判定（事前登録 4・5章）に使いません。study ごとにフォルダが分かれるので、本番の export には混ざりません。事前登録 3.3 の、score.py と画面の判定の照合には使います。直すことが出たら、直して変更記録に書き、2章を取り直し、別の study-id（例 `pilot3-link-202611`）で通し直します。同じ study-id は2度作れません。

## 4. 本番を運用する

### 4.1 始める前

```bash
STUDY=study1-diag-ab-202611
$CLI status --study-id "$STUDY"
$CLI check --study-id "$STUDY"; echo "終了コード $?"
docker compose exec backend uv run --no-sync python -c "from course_core.research.store import default_store; s = default_store().load_study('$STUDY'); print(s.consent_version, s.active_arm, s.task_sets, s.questionnaires_per_block, s.final_questionnaires, len(s.participants))"
```

- `status` が `腕 diag` で、Q1〜Q4 がどれも `割り当て 3・開始 0・完了 0・予備の使用 -`、`撤回: なし`。「止めました: study … がありません」なら、本番の study は backend の置き場所にありません。`開始` が 0 でない系列があれば、どれかのリンクがもう開かれています。どちらも、送る前に実験者に知らせます。
- `check` が `セッション 0 … 欠け 0`、終了コード 0。
- 3行目は `v1-diag-ab-202611 diag ['P1', 'P2'] 2 1 16` の見込みです（作ったときの CLI の既定。最後の数は `--final-questionnaires` の値で、2 で作っていれば `2 2 16`）。
  - **同意の版（最初の値）が `v1-diag-ab-202611` なら、この study をそのまま使います。** 画面の同意の版は `v1-diag-ab-202611` のまま、文だけを 11/11 に差し替えました（事前登録の変更記録）。
  - **同意の版が違う（例 `v0-draft`）ときだけ**、全員が同意の画面で止まる（409。版は作った後に変えられない）ので、新しい study を作り直します。同じ study-id は2度作れないので、別の id にします。前の study は使わず、消しません。作り直したことと新しい id を事前登録の変更記録に書き、以下の `STUDY` を新しい id に替えます。

    ```bash
    STUDY=study1-link-202611
    $CLI create-study --study-id "$STUDY" --department kansai-enechem-2026 \
      --arm diag=N:W:V30,A:Y:V31 --task-sets P1,P2 --n 12 --spares 4 \
      --consent-version v1-diag-ab-202611 --questionnaires-per-block 2 --final-questionnaires 2 \
      --base-url https://gms-app-2.komazawa-u.ac.jp --cards-out /tmp/study1-cards.csv
    docker compose cp backend:/tmp/study1-cards.csv "$PRIV/study1-cards.csv"
    docker compose exec backend rm /tmp/study1-cards.csv
    ```

  - 最後の質問票の数が 1 でも、そのまま使えます。check は、最後のブロックの後の questionnaire_submit が study の数「以上」あるかを見るだけで（`store.py` の `check_completeness`）、2件目（振り返り）も捨てずに記録します（画面は最後の質問票を全部送ってから session_end を送る）。ただし **check では振り返りの欠けに気づけないので、integrity.py で見ます**（4.4、事前登録 6.3）。
- 次に、どのリンクも開かれていないうちに、全 pid（P01〜P12、予備の R01〜R04）を remote にします。全員がリンクを受け取ってひとりで進めるので、全員が remote です。どれかの pid で「セッションは始まっています」と出て止まったら、そのリンクは開かれています。実験者に知らせます。

  ```bash
  for pid in P{01..12} R{01..04}; do $CLI set-mode --study-id "$STUDY" --pid "$pid" --mode remote || break; done
  ```

- 最後に、凍結の記録を本番のログに残します（腕は diag のまま、study_arm_activated が1行増える）。

  ```bash
  $CLI activate-arm --study-id "$STUDY" --arm diag --note "<3.1 と同じ形の凍結の記録>"
  ```

### 4.2 リンクを送る

- **リンクは1人に1つです。** 同じ URL を2人が開くと、2人目は1人目のセッションの続きになります（サーバーは同じトークンに前のセッションを返す。`frontend/src/navi/studyFlow.ts` の `openStudy`）。グループや掲示に1つのリンクを貼る配り方はできません。
- 参加を申し出た順に、カードの CSV の P01 から順に、次の pid のリンクを送ります。研究者は pid を選びません（事前登録 2.3）。文は付録の雛形を使います。
- 誰にどの pid を送ったか（送った日時、送った手段、相手）を、研究者だけが読める場所（リポと vault の外。`$PRIV` の下など）に控えます。撤回の申し出（4.3）を受けたときに、この控えで pid を引きます。あわせて、送った pid だけを送った順に `$PRIV/sent-order.txt` に1行に1つ書き足します（名前・連絡先・送った手段は書かない。4.4 の `integrity --sent-order` に渡す）。
- リンクが開かれたかは、`check` の行にその pid があるかで分かります（`status` は系列ごとの人数だけ）。**送ってから3日開かれなければ脱落とみなし、同じ系列の予備（4.3）を次の人に送ります。** 脱落とみなしたリンクは開けなくはなりません。後で開かれたら、その記録は残し、逸脱の表に書きます（分析に入れるかは実験者が決めます）。

### 4.3 脱落と撤回

- 脱落（両ブロックを終えなかった人と、3日開かれなかったリンク）が出たら、同じ系列の予備のリンクを次の人に送ります。R01 が Q1、R02 が Q2、R03 が Q3、R04 が Q4 です。脱落した pid のリンクは使い回しません。使った予備と理由を逸脱の表（事前登録 8.3）に書きます。
- 撤回は、参加した日から7日以内に、リンクを送ったメッセージへの返信で受けます（同意の画面の文）。4.2 の控えで pid を引き、本人の申し出であることを確かめてから `$CLI withdraw --study-id "$STUDY" --pid <pid>` を打ちます。その pid の行とセッションの状態を研究データから消し、元に戻せません。消した行数と時刻は study.json に残り、そのリンクは開けなくなります。書き出し済みのファイル（4.4 の毎日の控えを含む）からもその pid の行を消し、予備で補います（事前登録 5.5 の E1・E2）。参加した日は、その pid の session_start の日付です。7日を過ぎた申し出は、実験者に知らせて扱いを決めます。

### 4.4 毎日の終わりと、最後の書き出し

毎日の終わりに `status` と `check` を打ち、書き出しに `integrity` を当ててから、サーバーの外へ控えます。研究データはサーバーの1か所にしか無いので、毎日写します。欠けや印があれば、日付・pid・中身を逸脱の表に書き、実験者に知らせます。

```bash
DAY=$(date +%Y%m%d)
$CLI status --study-id "$STUDY"
$CLI check --study-id "$STUDY"; echo "終了コード $?"
$CLI export --study-id "$STUDY" --out "/tmp/study1-events-$DAY.jsonl"
# ここで 5.3 のスクリプトを /tmp/study1-events-$DAY.jsonl に当てる
# 完全性の検査（backend/eval/study1/ が GMS に入ってから）。check では振り返りの欠けに気づけないので、ここで見る
$RUN eval.study1.integrity --events "/tmp/study1-events-$DAY.jsonl" --study-id "$STUDY"; echo "終了コード $?"
#   送った順と比べるとき（参考。終了コードには入らない）: 4.2 の pid だけの控えをコンテナに写して渡し、使ったら消す
docker compose cp "$PRIV/sent-order.txt" backend:/tmp/sent-order.txt
$RUN eval.study1.integrity --events "/tmp/study1-events-$DAY.jsonl" --study-id "$STUDY" --sent-order /tmp/sent-order.txt
docker compose exec backend rm /tmp/sent-order.txt
docker compose cp "backend:/tmp/study1-events-$DAY.jsonl" "$PRIV/study1-events-$DAY.jsonl"
docker compose exec backend rm "/tmp/study1-events-$DAY.jsonl"
sha256sum "$PRIV/study1-events-$DAY.jsonl" | tee -a "$PRIV/exports.sha256"
```

- `integrity` の終了コードは欠け（seq・課題・質問票・同意の版・study-id・事前登録 5.2 の前提・読めない行）だけで決まります。欠けが無ければ 0、欠けがあれば 1、書き出しか `--sent-order` のファイルが読めなければ 2 です。途中の人（閉じていないセッション）は欠けに数えません。
- 始まった順（pid の番号の順か）は「参考」の欄に出るだけで、欠けにも終了コードにも入りません。リンクで送ると開く順は参加者が決め、開かれないリンクは予備に替えるためです。
- `--sent-order` には、4.2 の送った順の控え（`$PRIV/sent-order.txt`。**pid だけ**を1行に1つ。名前・連絡先・送った手段は書かない）を渡します。送った順と始まった順の違い、送ったがまだ始まっていない pid、送った順に無い pid が「参考」の欄に出ます。これも終了コードには入りません。pid の形（英大文字1つと数字。例 `P01`・`R02`）でない値や重なった pid があると、終了コード 2 で止まります。ファイルは `$PRIV` に置き、使うときだけコンテナの `/tmp` に写して、使ったら消します。
- 写し先の `$PRIV` は、サーバーの外の研究者だけが読める場所にします（サーバーのディスクが壊れたとき、作業ツリーで `git clean -x` やクローンのやり直しをしたときに、研究データと一緒に消えない場所）。
- 撤回した pid の行は入りません。同じ日に2回書き出すときは、`DAY` に時刻を足して名前を変えます（CLI は上書きしません）。
- 全員が終わったら、最後の書き出しを同じ手順で作り、SHA-256 と一緒に Aki_Ha へ渡します。**公開の場所やチャットに貼りません。** 渡す手段は、運用担当と実験者で決めます。分析のスクリプトにはこの場所を引数で渡します（事前登録 6.3）。

### 4.5 全員の後: 指標と判定の表

`backend/eval/study1/` が GMS に入ってから打ちます。4.4 の最後の書き出し（`$PRIV/study1-events-<日付>.jsonl`）と、2.1 の科目のスナップショットを使います。出力はリポの外に置きます。

```bash
LAST="$PRIV/study1-events-<最後の日付>.jsonl"
docker compose cp "$LAST" backend:/tmp/study1-events.jsonl
docker compose cp "$PRIV/freeze/study1-catalog.json" backend:/tmp/study1-catalog.json
$RUN eval.study1.metrics --events /tmp/study1-events.jsonl --catalog /tmp/study1-catalog.json --out /tmp/study1-metrics.json
$RUN eval.study1.report --metrics /tmp/study1-metrics.json --out /tmp/study1-report.md
for f in study1-metrics.json study1-report.md; do
  docker compose cp "backend:/tmp/$f" "$PRIV/$f" && docker compose exec backend rm "/tmp/$f"
done
docker compose exec backend rm /tmp/study1-events.jsonl /tmp/study1-catalog.json
sha256sum "$PRIV/study1-metrics.json" "$PRIV/study1-report.md" | tee -a "$PRIV/exports.sha256"
```

- `metrics` の JSON は pid と数を持ちます（自由記述は入れない）。`report` の表は既定で pid を出しません。どちらもリポと vault に入れず、書き出しと同じ手段で Aki_Ha へ渡します。実験報告（`docs/experiments/`）に載せるのは、report の集計の表だけです。
- 撤回の数（事前登録 5.5 の E2）を表に出すときは、study.json を `--study-json` で `report` に渡します（study.json は研究データの置き場所の `<study-id>/study.json`）。
- `metrics`・`report` は、書き出しとスナップショットを手元に写せば、backend の環境（`uv run --no-sync`）で手元でも動きます（`backend/eval/study1/README.md`）。

## 5. 結果を確かめる

### 5.1 status

```
study <study-id>（学科 kansai-enechem-2026、腕 <腕。無ければ 未決定>）
系列  割り当て  開始  完了  予備の使用
Q1           3     0     0  -
（Q2〜Q4 も同じ形）
撤回: <pid の並び。無ければ なし>
```

- 割り当ては、その系列の予備でないリンクの数です。開始はセッションが始まった人の数（予備を含む）、完了はブロック2を終えた人の数、予備の使用はセッションが始まった予備の pid です。
- 終了コードはいつも 0 です（study が無いときだけ「止めました: …」で 1）。
- 「よい」の条件: 腕が diag。開始 − 完了が、今進めている人と脱落した人の数に合う。予備の使用と撤回が、逸脱の表と合う。

### 5.2 check

```
study <study-id>: セッション <数>（完了 <数>・途中で終了 <数>・進行中 <数>）、欠け <数>
  <pid>（<系列>）<complete | ended_incomplete | in_progress> seq 1..<最後の seq> 印: <印×数。無ければ なし>
    欠け: <中身>
```

- complete はブロック2を終えた人、ended_incomplete は終えずにセッションが閉じた人、in_progress はまだ閉じていない人です。タブを閉じただけではセッションは閉じないので、途中でやめた人は in_progress のまま残ります。
- 欠け（`store.py` の `check_completeness`）: seq の欠け・重なり、event_id の重なり、session_start が無い、同意の記録が無いのにブロックがある、終えたブロックの task_start・task_submit が2件でない、終えたブロックの questionnaire_submit が2件より少ない、閉じたセッションで最後のブロックの後の questionnaire_submit が study の final_questionnaires より少ない。終えていないブロックは数えません。final_questionnaires が 1 の study では、振り返りが無くても欠けになりません（4.1）。
- 印（`store.py` の `_client_event_warnings`、`events.py` の `payload_warnings`）: `flags_mismatch`、`seq_gap`・`seq_out_of_order`、`task_not_in_block`・`task_id_missing`、`payload_missing:<項目>`・`payload_invalid:<項目>`・`payload_unknown:<項目>`、`ts_client_naive`。
- 終了コードは、欠けが0なら 0、1つでもあれば 1 です（study が無いときも 1）。印は終了コードに効かないので、目で見ます。
- 「よい」の条件: 終了コード 0。終えた人が complete。印が「なし」（出たら種類を記録し、理由を調べる）。

### 5.3 export の中身を見る

コンテナの中の書き出しに当てます（`<書き出し>` を `/tmp/pilot2-events.jsonl` などに替える）。標準のライブラリだけで動きます。

```bash
docker compose exec -T backend python - <書き出し> <<'EOF'
import json, sys
from collections import Counter, defaultdict
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
mine = [r for r in rows if r["pid"]]
print("同意の版:", dict(Counter(r["consent_version"] for r in mine)))
print("同意:", [(r["pid"], r["payload"]["form_serial"], r["payload"]["agreed"]) for r in mine if r["event_type"] == "consent_recorded"])
print("mode:", dict(Counter(r["mode"] for r in mine)))
print("backend:", dict(Counter(r["app_version"]["backend"] for r in mine)))
print("frontend:", dict(Counter(r["app_version"]["frontend"] for r in mine)))
print("質問票の版:", dict(Counter(r["payload"].get("version") for r in mine if r["event_type"] == "questionnaire_submit")))
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

本番では、3.3 と同じ条件に加えて、人ごとの行が系列どおりであることを見ます（`study.py` の `_SEQUENCE_ORDER`。練習はブロック1の変種で記号 P）。質問票は、最初に `qNone:事前の質問`、ブロックごとに `SUS` と `Q11-Q12`、最後に `qNone:二択` と `qNone:振り返り` です。`chat_response` の error（`timeout`・`llm`・`db`・`mcp_unavailable`・`other`）は F3 の分子に入ります（事前登録 5.6）。

| 系列 | 練習 | ブロック1 | ブロック2 |
|---|---|---|---|
| Q1 | 0:P/V30/practice | 1:W/V30/P1 | 2:Y/V31/P2 |
| Q2 | 0:P/V31/practice | 1:Y/V31/P1 | 2:W/V30/P2 |
| Q3 | 0:P/V30/practice | 1:W/V30/P2 | 2:Y/V31/P1 |
| Q4 | 0:P/V31/practice | 1:Y/V31/P2 | 2:W/V30/P1 |

## 6. 困ったとき

参加者は、画面のエラーの文に従って、リンクを送ったメッセージへ返信してきます。返信で、出た文をそのまま教えてもらいます。

| 起きたこと | 原因（コードで分かること） | 直し方 |
|---|---|---|
| リンクを開くと「このリンクは使えません。このリンクを受け取ったメッセージへ返信して知らせてください。」 | 404「カードのトークンが見つかりません。」（`api/routers/research.py`）。backend は自分の置き場所の study だけを探す。CLI を別の `RESEARCH_DATA_DIR` で打つと、study が別の場所にできる。URL の写し間違いでも同じ。開き直したときにセッションのクッキーが無い・セッションが終わっている（401・404）も同じ文になる | 1.1 の置き場所と、`create-study` の「study を作りました: …」のパスを比べる。`exec` の `status` で study が見えるかを確かめる。送ったリンクをカードの CSV と比べる |
| リンクを開くと「いまは進めません（サーバーの準備か順番が合っていません）。…」 | 409。腕が未決定、撤回済み、終えたリンク、DB に SIMILAR_TO がある（C8、`study.py` の `start_violations`）のどれか。理由は応答の本文（ブラウザの開発者ツールのネットワーク）に出る | `status` で腕と撤回を見る。腕が未決定なら `activate-arm`。終えたリンクは開き直せない。C8 は Neo4j で `MATCH ()-[r:SIMILAR_TO]->() RETURN count(r)` が 0 かを見る |
| 同意を押すと「いまは進めません…」が出て進めない | 409「同意書の版 … は study の版 … と違います。」。画面の版（`frontend/src/navi/studyConfig.ts` の `CONSENT.version`。画面の下に出る）と study の `consent_version` が違う | 4.1 の3行目で study の版を出し、画面の下の版と比べる。study の版は作った後に変えられないので、4.1 の分岐で study を作り直す。画面の版を変えるのはコードの変更なので変更記録へ |
| タブを閉じた・別の端末で開き直した | 同じリンクを開くと、サーバーが前のセッションを返して続きから進む。このタブに前の状態が無いと、ブロックの最初の課題からやり直し、`client_error`（`resumed_without_local_state`）が残る（`studyFlow.ts`） | 返信で聞かれたら、同じリンクを開き直してよいと伝える。逸脱の表に書く。同じ課題をやり直すので、`check` で task_start・task_submit の数の欠けが出ることがある |
| `check` の終了コードが 1 | 5.2 の欠け | 欠けの行を逸脱の表に書く。seq の欠けはイベントが届かなかったこと。セッションのイベントの 10% を超えたら E3（事前登録 5.5） |
| 「止めました: … は既にあります（上書きしません）」か「… git の作業ツリーの中（…）には書きません」 | `--cards-out`・`--out` の書き先に同じ名前のファイルがあるか、ホストで CLI を直接打ち、書き先がリポの中 | `exec` と `/tmp` の別の名前を使う。`/tmp` に前のファイルが残っていれば消す |
| V31 で AI が答えない・遅い | サーバーは 170 秒で打ち切る（504）。`chat_response` の error に種類が残る | 5.3 で error を数える。`llm` が続くなら、2章の 3 で `AGENT_MODEL` を、別に API キーの枠を確かめる（値は出さない） |
| `.env` を変えたのに効かない | `env_file` はコンテナを作るときに読まれ、`restart` では変わらない。Vite は起動したときに環境変数を読む | 2章の 2・3 |

## 7. 確かめていないこと

- サーバーの compose.yaml のコミットしていない変更（データの永続化）の中身は見ていません。この手順は、main の compose.yaml（`./backend:/backend_app`、`env_file: .env`、`fastapi dev`）にその変更を足したもの（compose.eval.yaml は使わない。11/11 の運用担当の連絡）を前提にしています。研究データの置き場所は 1.1 の出力で、本番の study が backend の置き場所にあるかは 4.1 の `status` で確かめます。
- 本番の study（`study1-diag-ab-202611`）の同意の版と最後の質問票の数を、誰も表示していません。4.1 の3行目で確かめます。
- 分析の道具（2.1、3.3、4.4、4.5 の `$RUN eval.study1.…`）は、GMS では打っていません。コマンドの形は `backend/eval/study1/README.md` の「GMS での打ち方」（コミット 26d898f、integrity の参考の欄と `--sent-order` は ed93344）に合わせました。3.3 の、書き出しから課題 b のプランを取り出す数行のスクリプトは、手元で作った書き出しの形の行（P01・P02 × 課題5つ）で、4つのファイルができることだけを確かめました（score には当てていません）。
- `VITE_APP_COMMIT` が `app_version.frontend` に入ることは、コード（compose.yaml の frontend の `env_file`、Vite 8.0.16 の `loadEnv`、`research.ts` の `FRONTEND_VERSION`、`api/routers/research.py` の `X-Navi-Frontend`）で確かめました。サーバーでは試していません（3.3 の `frontend` の行で確かめる）。
- サーバーの OS とシェル（bash、`sha256sum`、Docker Compose v2 の `exec`・`cp` を前提にしています）。
- この手順の `docker compose` の行は、サーバーで打っていません。CLI の出力の形と止まり方（`create-study`・`set-mode` のループ・`activate-arm`・`status`・`check`・`export`、書き先の検査）と 5.3 のスクリプトは、手元で `RESEARCH_DATA_DIR` を一時フォルダにして、コンテナの外で確かめました。
- 画面は、手元の開発サーバー（見本のデータと開発用の調査の口）で、同意の画面、最後の質問票（二択・振り返り）、終わりの画面、使えないリンクの文だけを見ました。練習からブロック2までをリンクの形で通すのは、3章の試しが初めてです。
- 3日で脱落とみなす、7日以内の撤回を受ける、という運用は、まだ回していません。
- スマホ・Safari・Edge での表示。gemini-3.8-flash が、サーバーの API キーで使えること（3.3 の `chat_response` で確かめる）。

## 付録. 参加者へ送る文の雛形

`<リンク>` をカードの CSV の url 列に替えます。1人に1通ずつ送り、同じ文に2つのリンクを入れません。研究者の個人の連絡先は書きません（問い合わせと撤回は、このメッセージへの返信で受けます）。

```
履修を選ぶアプリの使いやすさを調べる研究への協力のお願いです。

<リンク>

・全部で45分ほどです。できればパソコンで、静かな所で、途中でタブを閉じずに1回で終えてください。
・このリンクはあなた専用です。ほかの人に渡さないでください（同じリンクを2人が開くと、記録が混ざります）。
・ブラウザの自動翻訳は切ってください。日本語が読みにくい人は翻訳を使ってかまいませんが、その場合は、このメッセージへの返信で知らせてください。
・最初の画面に研究の説明があります。読んでから、参加するかどうかを決めてください。
・質問があるとき、途中で困ったとき、記録を消してほしいとき（参加した日から7日以内）は、このメッセージへ返信してください。
```
