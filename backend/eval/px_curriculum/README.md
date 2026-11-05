# PX-1・PX-2 の事前登録・コード・結果（個人の予備実験）

Aki_Ha 個人の予備実験 PX-1・PX-2（2026-11-05）の一式のうち、公開リポに置けるものだけを置いたフォルダ。
記録の本文は [`docs/experiments/2026-11-05_px-curriculum-order.md`](../../../docs/experiments/2026-11-05_px-curriculum-order.md)。

- PX-2: 関西大学 環境都市工学部 エネルギー環境・化学工学科の履修系統図（tree_env.pdf の6ページ目）から取り出したグループ DAG と、科目に展開した DAG の構造を測った（LLM なし）
- PX-1: 系統図を渡さない LLM（agy 経由の Gemini 3.8 Flash (High) と Claude Sonnet 5.5 (Medium)）が、系統図の順序と関係をどこまで再現できるかを、事前登録して調べた

本番のコードからは読み込まない。CI の pytest（`backend/tests`）の対象にも入らない。

## 中身

配置は実行時のフォルダ（`<SP>\px`。`<SP>` は Claude Code のセッションの scratchpad）をそのまま写した。スクリプトは自分の1つ上のフォルダ（このフォルダ）を基準にした相対パスで読み書きする。

| パス | 中身 |
|---|---|
| `.gitattributes` | このフォルダの改行を変換しない（`* -text`）。実行時のファイルは LF と CRLF が混ざっていて、事前登録の第13節と `prereg.sha256` の SHA-256 はそのバイト列で取ってある |
| `prereg_PX1.md` | PX-1 の事前登録（LLM を呼ぶ前に保存。プロンプトの雛形と C0 の全文の例は第12節） |
| `prereg.sha256` | 事前登録の SHA-256 と保存の時刻（f019b58b…、2026-11-05 00:24:06 JST） |
| `deviations_PX1.md` | 事前登録からの逸脱と、実行中に起きたこと（E1〜E3） |
| `scripts/fetch_step1.py`・`fetch_step2.py` | 関西大学の学科の科目一覧・履修系統図・シラバス詳細（127件）の取得。リポの `KansaiSyllabusFetcher` を使う |
| `scripts/inspect_tree.py`・`check_membership.py`・`match_catalog.py`・`parse_syllabi.py`・`build_dataset.py` | 系統図の辺の抽出、所属表と PDF の座標の照合、科目一覧との対応、シラバスの解析、データセットの組み立て |
| `scripts/px2_structure.py` | PX-2 の指標（blocking factor・delay factor・幅など） |
| `scripts/px1_build.py` | PX-1 の標本・B-year・プロンプトの生成（種 20261105） |
| `scripts/selftest_synthetic.py` | 合成の答えで集計コードを確かめる（LLM を呼ぶ前に実行） |
| `scripts/px1_run.py` | agy の呼び出し（3並列、無効な返答は1回だけ再試行、予算 250 回） |
| `scripts/px1_analyze.py` | 集計と仮説の判定（逸脱 E3 の修正の後の版。SHA-256 331af193…） |
| `scripts/px1_analyze.prereg_version.py.txt` | 事前登録の時点の集計コード（SHA-256 2686f781…）。実行されないように拡張子を変えてある |
| `scripts/px1_supplement.py`・`px1_exploratory.py` | 内訳と、事前登録の外の分析 |
| `scripts/recheck_all.py`・`recheck_extra.py` | 別の書き方での再計算 |
| `px1/raw/calls.jsonl` | 1呼び出し1行の生データ（153行。smoke 2・本番 144・再試行 7）。依頼文の本文は入っていない（`prompt_sha256` で照合する）。答え・応答の本文・結果のメタデータ（トークン数など）・標準エラーの末尾が入っている |
| `px1/prompts_manifest.json` | プロンプト 72 本の SHA-256 の一覧 |
| `px1/items_O.json`・`items_D.json` | 向き課題 O・検出課題 D の 120 項目ずつ（科目名・正解・提示の順） |
| `px1/baseline_byear.json` | 年次の規則（B-year）の答え |
| `px1/calls_plan.json`・`sampling_stats.json` | 呼び出しの組み方と、標本の偏りの集計 |
| `px1/results.json` | 主な集計と仮説の判定 |
| `px1/item_answers.csv` | 項目 × モデル × 条件 × 回の答えと正誤（2880 行） |
| `px1/supplement.json`・`exploratory.json` | 内訳と、事前登録の外の分析 |
| `px1/analyze_stdout.txt`・`supplement_stdout.txt`・`run_main.log` | 集計と実行のログ |
| `px2_metrics.json` | PX-2 の結果 |
| `recheck_result.json`・`recheck_extra_result.json` | 再計算の照合の結果（全部一致） |
| `dataset/group_dag.json`・`dataset_summary.json` | グループ DAG（21 グループ・25 辺）とデータの要約（科目の対応、系統図とシラバスの食い違い） |
| `work/membership_check.json` | リポの手書きの所属表と、PDF の文字の座標の照合（70 科目） |

## 除いたものとその理由

関西大学のシラバスの本文（授業概要・到達目標など）は、著作権の扱いで公開リポに入れない（ルートの `.gitignore` の「Copyright & IP Protection」）。
科目名・科目コード・配当年次は事実なので入れてある。
入れる前に、ここに置いた全ファイルを `dataset/courses.json` の授業概要・到達目標の文字列（空白を除き NFKC で正規化した 30 字の窓）と、シラバス詳細の解析結果の長い文字列で照合し、一致が 0 件であることを確かめた（JSON は `\uXXXX` を戻してから照合した）。

| 除いたもの | 理由 | どこにあるか |
|---|---|---|
| `px1/prompts/`（72 本の全文） | C1・C2 の 48 本は授業概要・到達目標の 300 字を含む。C0 の 24 本は科目名だけだが、まとめて扱った | Aki_Ha の非公開の vault（下記）。ハッシュは `px1/prompts_manifest.json` |
| `dataset/courses.json` | 授業概要・到達目標の先頭 300 字を含む | vault |
| `work/` の残り（`page6_text.txt`・`page6_words.json` などの PDF の文字、一覧との対応、取得のログ、`parsed/parse_report.json`） | 系統図の PDF の文字などを含む | vault |
| `work/parsed/courses_detail.json`・`courses_lookup.json`（シラバス詳細 127 件の全項目の解析結果） | 教員の個人情報（メールアドレス 5 件）とシラバスの全文を含む | どちらにも置かない。`fetch_step2.py`・`parse_syllabi.py` で取り直せる。集計のやり直しには `dataset/courses.json` で足りる |
| `px1/raw/stdout/`・`px1/raw/stderr/`（呼び出しごとの agy の stream-json と標準エラー、各 153 本） | 照合では本文は 0 件だったが、要る情報（答え・応答・メタデータ・標準エラーの末尾）は `calls.jsonl` に入っているので、リポには置かなかった | vault |
| `data_raw/`（シラバスの HTML 127 件、学科の科目一覧の HTML、`catalog_index.json`、`tree_env.pdf`） | 関西大学の著作物。公開サイトから取り直せる | どちらにも置かない。tree_env.pdf と catalog_index.json の SHA-256 は事前登録の第13節 |
| `code/` | origin/main `14f8d570dd954059dd9756c5f9fe3ba1584dbc75` の `git archive` そのもの | リポから作り直せる |
| `venv/` | uv で作り直せる | — |
| `agy_profile/`・`agy_ws/` | agy の専用プロファイル（認証や会話の記録が入りうる）と、空の作業フォルダ | どちらにも置かない |
| `ref_docs/`（Heileman et al. 2018 の PDF と、それを文字にしたもの） | 第三者の論文 | arXiv:1811.09676 |
| `selftest/calls_synthetic.jsonl`、`code_sha.txt`・`data_prep_start.txt`・`request_log.jsonl` | 合成の答え（`selftest_synthetic.py` で作り直せる）と、実行の付帯記録 | vault |

vault の場所: `10_projects/course-navigator/notes/research/2026-11-05_novelty-models-experiments/px_raw/`（非公開。中身が要るときは Aki_Ha に頼む）。

## 実行時のパス

スクリプトの中には絶対パスは無い（どれも `Path(__file__).resolve().parent.parent` を基準にする）。
ただし `px2_metrics.json` の `source_dataset` と `deviations_PX1.md` には、実行時の絶対パス（scratchpad の下の `...\scratchpad\px\...`）がそのまま残っている。記録として書き換えていない。再現するときは、これを自分の作業フォルダに読み替える。

## 再現の手順

**このフォルダの中では実行しない。** 取得したシラバスの本文（`data_raw/`・`work/parsed/`・`dataset/courses.json`・`px1/prompts/`）が公開リポの作業ツリーに書き出されてしまう。リポの外に作業フォルダ `W` を作って写してから行う。

```
# 1. リポの外に写す（W はリポの外のフォルダ）
cp -r backend/eval/px_curriculum/. W/
mkdir -p W/code W/agy_ws W/agy_profile
git archive 14f8d570dd954059dd9756c5f9fe3ba1584dbc75 | tar -x -C W/code

# 2. Python（3.14.3 で実行した）
cd W
uv venv --python 3.14 venv
uv pip install --python venv/Scripts/python.exe "httpx>=0.28,<0.29" "pydantic>=2.13,<3" pdfplumber networkx scipy numpy
#   実行時の版: httpx 0.28.1、pydantic 2.14.2、pdfplumber 0.11.10、networkx 3.7、numpy 2.5.4、scipy 1.18.1

# 3. データの準備（関西大学への要求は合計 129 回、間隔 1.2 秒以上）
venv/Scripts/python.exe -I scripts/fetch_step1.py
venv/Scripts/python.exe -I scripts/inspect_tree.py
venv/Scripts/python.exe -I scripts/check_membership.py
venv/Scripts/python.exe -I scripts/match_catalog.py
venv/Scripts/python.exe -I scripts/fetch_step2.py
venv/Scripts/python.exe -I scripts/parse_syllabi.py
venv/Scripts/python.exe -I scripts/build_dataset.py

# 4. PX-2
venv/Scripts/python.exe -I scripts/px2_structure.py

# 5. PX-1 の標本・プロンプト、集計コードの自己確認
venv/Scripts/python.exe -I scripts/px1_build.py
venv/Scripts/python.exe -I scripts/selftest_synthetic.py
#   ここで prereg_PX1.md の第13節の SHA-256 と、px1/prompts_manifest.json のハッシュに一致するかを確かめる

# 6. LLM の呼び出し（agy が要る。--gemini_dir=W/agy_profile で起動し、cwd は空の W/agy_ws。
#    実行時は Aki_Ha の Google AI Pro の個人枠で、認証済みの専用プロファイルを使った。ANTHROPIC/GEMINI/GOOGLE_API_KEY は外して起動される）
venv/Scripts/python.exe -I scripts/px1_run.py smoke
venv/Scripts/python.exe -I scripts/px1_run.py main

# 7. 集計と再計算
venv/Scripts/python.exe -I scripts/px1_analyze.py
venv/Scripts/python.exe -I scripts/px1_supplement.py
venv/Scripts/python.exe -I scripts/px1_exploratory.py
venv/Scripts/python.exe -I scripts/recheck_all.py
venv/Scripts/python.exe -I scripts/recheck_extra.py
```

- 手順 1 でこのフォルダの結果のファイル（`px1/results.json` など）も写るので、手順 3 以降で上書きされる。元の値と比べるときは、別に残しておく
- LLM 以外の部分（標本・プロンプト・B-year・PX-2）は、取得したデータが同じならビット単位まで再現できる。シラバスや系統図が更新されていると、同じにならない。tree_env.pdf と catalog_index.json の SHA-256（事前登録の第13節）で確かめる
- 集計（手順 7）だけをやり直すには、`dataset/courses.json`（vault にある。または手順 3 で作る）が要る。`px1_supplement.py` は `px1/raw/stdout/`（vault）も読む
- LLM の答えは、同じプロンプトでも回ごとに揺れる（第8節の κ）。agy は実験の途中で 1.4.12 から 1.5.0 に自動更新された（逸脱 E1）
