# Study 1 の採点と分析（事前登録 6.3）

事前登録 [`docs/experiments/2026-11-07_prereg_study1_diag-ab.md`](../../../docs/experiments/2026-11-07_prereg_study1_diag-ab.md) の 6.3 が求める道具です。食い違ったら事前登録が正です。人のデータ（研究のイベントの JSONL、質問票、ここで作る表）はリポに入れません。どの道具も入出力のパスを引数で受け、書き先が既にあるか git の作業ツリーの中なら止めます（上書きしない）。

## ファイルと事前登録の節

| ファイル | 役目 | 事前登録 |
|---|---|---|
| `tasks.json` | カード P1・P2・練習 C の機械可読の定義（採点する学期、K1〜K6 の型と値、K5 の科目名、参照の答え、3.4 の下調べの値） | 3.1・3.2・3.3・3.4 |
| `score.py` | プランに K1〜K6 を当て、成否 y・達成度 a・初期の a0 を出す。手で作った例と画面の判定の突き合わせ（`--examples`） | 3.3・4.1 |
| `catalog_snapshot.py` | 凍結の DB から、採点に要る科目の属性（名前・学期・曜限・単位・まとまり）を JSON に書き出す。SHA-256 と中身の指紋を出す | 3.3・6.3 |
| `feasibility.py` | 実際のエンジンで参照の答えの初期プランを出し、最小の変更と参照の解、3.4 の基準1〜4、K5 の科目が落ちる答えの組の数を出す | 3.3・3.4 |
| `integrity.py` | 毎晩の完全性の検査（seq、課題・質問票の数、5.2 の前提、同意の版、配った順） | 5.1 の F2・5.2・5.5 の E3・E4・2.3 |
| `metrics.py` | 4章の指標を参加者 × 条件で出す（JSON） | 4.1〜4.5・5.6 |
| `report.py` | 5章の判定と表（Markdown） | 5.1・5.3〜5.7 |
| `eventlog.py` | 書き出しの読み込みと、セッション・ブロック・課題への分け方、5.2 の前提の検査（integrity と metrics が共有） | 6.1・5.2 |
| `stats.py` | t の区間、BCa ブートストラップ、Wilcoxon（補助）、二項の閾値（標準ライブラリだけ） | 4.1・5.3・5.4 |
| `files.py` | 書き先の検査と SHA-256 | 6.3 |

テストは `backend/tests/eval/test_study1_*.py`（データは `study1_fixtures.py` で作る合成のイベントと科目）。

```bash
cd backend
uv run --no-sync pytest tests/eval/test_study1_score.py tests/eval/test_study1_feasibility.py \
  tests/eval/test_study1_integrity.py tests/eval/test_study1_metrics.py tests/eval/test_study1_report.py -q
```

## GMS での打ち方

研究者用 CLI と同じく、動いている backend のコンテナの中（`/backend_app`。`./backend` をマウントしているので `eval` を `python -m` で読める）で打ちます。コンテナの中からはホストの `.git` が見えないので、書き先は `/tmp` にして `docker compose cp` でリポの外（以下 `$PRIV`。研究者だけが読める場所）へ出し、コンテナの中のものを消します。手順書（運用手順書 1.1）の準備をしてから打ちます。

```bash
RUN="docker compose exec backend uv run --no-sync python -m"
STUDY=study1-diag-ab-202611          # 試しは pilot2-link-202611

# 1. 科目のスナップショット（凍結の DB。試しの前に1回）
$RUN eval.study1.catalog_snapshot --out /tmp/study1-catalog.json
docker compose cp backend:/tmp/study1-catalog.json "$PRIV/study1-catalog.json"

# 2. 下調べ（凍結の設定とデータで 3.3・3.4 を数え直す。結果は変更記録へ）
$RUN eval.study1.feasibility --git-sha "$(git rev-parse --short HEAD)" --json-out /tmp/study1-feasibility.json
docker compose cp backend:/tmp/study1-feasibility.json "$PRIV/study1-feasibility.json"

# 3. 毎晩: 書き出しと完全性の検査（終了コード 0 なら欠け無し、1 なら欠けあり、2 なら読めない）
$RUN course_core.research.cli export --study-id "$STUDY" --out /tmp/study1-events.jsonl
$RUN eval.study1.integrity --events /tmp/study1-events.jsonl --study-id "$STUDY"; echo "終了コード $?"

# 4. 全員の後: 指標と判定の表
$RUN eval.study1.metrics --events /tmp/study1-events.jsonl --catalog /tmp/study1-catalog.json --out /tmp/study1-metrics.json
$RUN eval.study1.report --metrics /tmp/study1-metrics.json --out /tmp/study1-report.md

# リポの外へ出して、コンテナの中のものを消す
for f in study1-events.jsonl study1-metrics.json study1-report.md; do
  docker compose cp "backend:/tmp/$f" "$PRIV/$f" && docker compose exec backend rm "/tmp/$f"
done
docker compose exec backend rm /tmp/study1-catalog.json /tmp/study1-feasibility.json
sha256sum "$PRIV"/study1-*
```

- 同意の版は `--consent-version`（既定 `v1-diag-ab-202611`、空にすると見ない）、質問票の尺度は `--block-scales`（既定 `SUS,Q11-Q12`）・`--final-scales`（既定 `二択,振り返り`）・`--pre-scales`（既定 `事前の質問`）で変えられます。
- DB を読まずに流すときは、`eval.diag_metrics --save-snapshot` で保存したデータ（形 diag-catalog-v1）を `feasibility.py --snapshot` と `catalog_snapshot.py --from-diag-snapshot` に渡します。
- `metrics.py`・`report.py` は書き出しとスナップショットを手元に写せば、backend の環境（`uv run --no-sync`）で手元でも動きます。
- 手で作った例と画面の判定の突き合わせ（3.3）: 1行に `{"id", "task_set", "plan", "screen": {"K2": "met", …}}` の JSONL を作り、`python -m eval.study1.score --catalog <スナップショット> --examples <JSONL>`（違いがあれば終了コード 1）。

## 出力と公開

- `metrics.py` の JSON は pid と数を持ちます（自由記述は入れない。答えたかどうかだけ）。`report.py` の表は既定で pid を出しません（`--show-pids` は研究者の手元用）。実験報告（`docs/experiments/`）に載せるのは report の集計の表だけです。
- 各道具は入力の SHA-256（書き出し・tasks.json・指標）と、スナップショットの中身の指紋を出します。実験報告の「実行環境」に写します。

## 決めた細部（事前登録に書いていないこと）

採点（score.py）

- 通年の科目は、プランの学年の春と秋の両方に数える（単位も両方。画面の `termsOf` と同じ。画面は科目の配当の学年を使う）。
- K1（group_count）は採点する学期（3年春・3年秋）の科目だけを数える（事前登録 3.3）。画面のチェックはプランの全部の学期を数える。系統図に無いクラスは、同じ名前の系統図の科目のまとまりとみなす（画面の判定と同じ）。
- スナップショットに無い科目がプランにあると、その学期の条件は「判定できない」になりうる。判定できない条件は満たした数に入れない（件数を出す）。
- K4・K5 は科目名の完全一致で見る（クラスは区別しない）。

指標（metrics.py）

- ブロックの課題は block_start の task_set_id と tasks.json の task_ids で決め、課題のイベントは封筒の task_id で分ける。chat_response は payload の client_event_id で依頼に結ぶ。
- 課題 b の task_submit が2件以上なら最後のもの、task_start は使う task_submit より前の最後のもの（注に残す）。初期プランは課題 a の最初の plan_shown（無ければ課題 a の task_submit）。
- 画面が隠れていた時間は page_hidden から次の page_visible まで（閉じていなければ課題の終わりまで）。W は待ちの和集合のうち課題の区間に入る長さで、隠れていた時間と重なっても両方を引く（事前登録 4.2 の式のまま）。chat_response の無い依頼は W に入れず数える。
- D の「移す」は、payload の moved_from・moved_to の組を先に、次に同じ学期・同じ名前の外すと足すを組む。同じ syllabus_id を外して戻した組も名前が同じなので移すに数え、`readded` に別に数える。組の出どころは足した側。
- 誤りへの依存は、案の行を1つずつ依頼のときのプラン（plan_refine_send の plan）に当て、満たしていた条件を満たさなくする行を数える。入れる行の学期は、採った行なら plan_course_add の学期、採らなかった行なら画面の既定の置き場所（配当年次の下限、秋なら秋、ほかは春）。
- AI の失敗（5.6）は、chat_response の error がある・plan_delivery が not_delivered か static_fallback・chat_response が無い、のどれか。F3 は V31 のブロック（1・2）の課題 a・b の依頼で数え、練習の依頼は別に出す。
- 診断の答えのずれ（5.7）は、課題 a の最後の diag_submit の答えを、質問ごとの選んだ選択肢の集合で参照の答えと比べる。
- F4 は、二択に答えて最後のブロックを終えた人の、最初の端末のイベントから最後の questionnaire_submit まで（隠れていた時間を引かない）。

前提と除外（eventlog.py・report.py）

- 5.2 の (1): ブロックに variant_applied が無いときも外れ（確かめられない）。(2): 同じ（設定の版, answers_digest）の中でいちばん多いプランと違うブロックを外れにする（同数ならどれも基準にしない）。プランは学期ごとの syllabus_id の集合で比べる。(3): chat_response の時刻は、依頼の ts_client に latency_ms を足したもの。
- 主の分析に入るのは、両ブロックの課題 b を出して最後のブロックを終え（E1）、E3・E6 に当たらず、両ブロックとも E4・E5 に当たらない人。E2（撤回）は書き出しに現れないので、`--study-json` に study.json を渡すと数を出す。
- BCa の偏りの補正は「θ* < θ̂」の割合（scipy と同じ）。再標本の平均がすべて片側なら区間を作らず理由を出す。
- 5.4 の閾値は二項分布から計算する（n 6〜12 は事前登録の表と同じ値になることをテストで確かめた）。
