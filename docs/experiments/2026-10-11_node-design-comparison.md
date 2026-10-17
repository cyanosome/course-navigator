# エージェントのノード設計の比較（golden 14問 × 4条件、各1回）

| 項目 | 内容 |
|---|---|
| 実験者 | Aki_Ha（個人の予備実験。チームの本実験である Vector vs Graph の比較（Yuto が計画）とは別） |
| 実施日 | 事前登録のコミットは 2026-10-11 23:49 JST。LLM を使う実行は 2026-10-12 00:07〜00:27 JST（UTC では 10-11 15:07〜15:27。結果ファイル名の日付は UTC） |
| 何を確かめたか | 同じ golden 14問・同じモデル（gemini-3.8-flash）のまま、エージェントのノード構成だけを変えた4条件（S0・S1・M1・M2）を各1回流し、回答の正しさ・出典の検証・コストを並べた |
| 結論 | 期待する科目を挙げた割合（recall）は4条件とも 1.00 で差が無かった。差が出たのは、LLM にグラフ探索を任せる M1・M2 が期待外の科目も挙げたこと（precision 0.76・0.82。静的探索を使う S0・S1 は 1.00）と、科目を挙げずに聞き返すべき問いで科目を挙げたこと（unclear 合格 1/4。S0・S1 は 4/4）。コストは検索系10問で、静的探索の後ろで LLM が文章だけを書く S1 が LLM 1回・latency 中央値 8.8 秒、M1・M2 が LLM 平均 6.7回・7.8回、latency 中央値 29.7 秒・32.9 秒。n=14・各1回の記述統計で、統計的な有意性は主張しない |

## 1. 目的と問い

10/7 の MTG で、Yuto から Aki_Ha への TODO に「ノードを洗練する」があった。Yuto は「ノードにこだわってみてほしい」と話し、ノードの設計を変えたら評価がどう変わったかを比べると面白い、とも言っていた。

ここでいう「ノードの設計」は、回答までの処理のどこを決定論的な関数で行い、どこを LLM に任せるかのことである。具体的には次の3点を変えた。

- LLM を使うか、使うなら文章を書くだけか、グラフの探索まで任せるか
- LLM が RDB（PostgreSQL）の詳細を読むツールを持つか
- LLM の回答の後ろに、引用された科目コードを DB で引き直して出典を付けるノード（attach_sources）を置くか

知りたかったこと:

1. 静的探索の後ろに、LLM が文章を書くノードを足すと、推薦する科目の集合は変わるか（S0 と S1）
2. LLM にグラフの探索を任せると、正しさはどう変わるか（S0・S1 と M1・M2）
3. RDB ツールと出典ノードを足すと、何が変わるか（M1 と M2）
4. それぞれのコスト（LLM のリクエスト数・時間・トークン数）

これは Vector と Graph の比較ではない。4条件とも Neo4j のグラフを使う。結果は 10/14 の MTG と、チームの本実験の条件を決める材料に使う。

## 2. 仮説

事前登録: [`backend/eval/prereg_node_compare.md`](../../backend/eval/prereg_node_compare.md)（コミット `33ff759`、2026-10-11 23:49 JST）。LLM を使う実行を1回も行う前にコミットした。条件の組み立て方・指標の式・判定規則・閾値・予算をここで固定した。

仮説（事前登録 §6 の要約。判定は `backend/eval/metrics.py` の関数で機械的に行う）:

| 仮説 | 内容 | 支持の条件 |
|---|---|---|
| H5（妥当性の確認） | S0 は golden で満点になる | 検索系10問すべてで recall = 1・precision = 1・forbidden = 0、かつ unclear 4/4 合格。満たさなければハーネスか DB の不具合とみなし、LLM の実行に進まない |
| H1（出典の検証） | M2 は DB に無いコードを出さず、M1 より余計な科目が少ない | (a) M2 の unverified の合計が0、(b) M2 と M1 の precision の平均差が +0.10 以上かつ符号カウントが3以上。両方で支持、片方で一部支持 |
| H2（コスト） | MCP で探索する条件は S1 より大幅に重い | 検索系で (a) latency の中央値が M1・M2 とも S1 の10倍以上、(b) LLM リクエスト数の平均が M1・M2 とも S1 の5倍以上。両方で支持、片方で一部支持 |
| H3（S1 は S0 の候補を保つ） | LLM が文章を書いても候補の集合は変わらない | 検索系10問のうち9問以上で、S1 と S0 の引用集合（起点科目を除く）が一致 |
| H4（unclear で候補を作らない） | 静的系は答えるべきでない問いで科目を挙げず、MCP 系は挙げる | S0・S1 が unclear 4/4 合格、かつ M1・M2 がそれぞれ 3/4 以下 |

「意味のある差」の基準（事前登録 §7。仮説以外の比較にも使う。検定ではなく記述上の約束）:

- 率の指標（recall・precision）: 両条件で値がある質問について、平均の差の絶対値が 0.10 以上かつ符号カウントの差が3以上なら「差あり」。片方だけなら「差は小さい」。
- 質問数で数える指標（forbidden・unverified に当たった質問数、unclear 合格数）: 2問以上の差なら「差あり」。1問差は「1問差（1回の試行では偶然と区別できない）」。
- コストの指標（latency・LLM リクエスト数・ツール呼び出し数）: 比が1.5倍以上（または1/1.5以下）なら「差あり」。

## 3. 実行環境

| 項目 | 値 |
|---|---|
| 日時（JST） | 煙テスト 2026-10-12 00:07:53〜00:09:24、本実行 00:10:56〜00:26:50（manifest の UTC 時刻を JST に直したもの） |
| 機械 | Aki_Ha の Windows 11 機のローカル Docker |
| コンテナ構成 | backend（FastAPI、イメージ `ghcr.io/astral-sh/uv:python3.14-bookworm-slim`、Python 3.14.2）/ Neo4j 5.26.27 Community + APOC / PostgreSQL 18.4 / Traefik v3.6。ハーネスは backend コンテナの中で直接 Python から各条件を呼んだので、HTTP と Traefik は通らない |
| コード | ハーネスはコミット `74817be`（manifest の git_sha）。本番コード（`backend/src`）は PR #14 の `ca94e4a` と同じ（`ca94e4a..74817be` は `backend/eval/` にファイルを足しただけ） |
| LLM | `gemini-3.8-flash`（`config.AGENT_MODEL` の既定値）。LLM を使った全実行で、API の応答が返した model_version も `gemini-3.8-flash` だった |
| API の枠 | Gemini API の有料枠のキー（[test3-2 の e2e](2026-10-11_test3-2-e2e.md) のために 10-11 23:21 に読み込ませたキーのまま。その後コンテナは作り直していない）。429 / 503 は一度も返らなかった |
| 生成設定 | 温度・思考量などは指定しておらず、API の既定値。本番の組み立て関数がどれも `generate_content_config` を渡しておらず、ハーネスでも足していない。`config.AGENT_TEMPERATURE`（既定 0.2）は定義だけあって、どのコードからも使われていない。思考トークンは出ていた（8節のトークン数） |
| MCP サーバー | neo4j-mcp-server 1.6.0。`uv run neo4j-mcp-server` を stdio のサブプロセスとして起動。読み取り専用（`NEO4J_READ_ONLY=true`）、テレメトリ無効、セッション確立の待ち時間 30 秒。M1・M2 の1実行ごとに起動して止める |
| ライブラリ | google-adk 2.8.0、google-genai 2.21.0、mcp 1.30.0、neo4j-mcp-server 1.6.0（manifest に記録） |
| DB の件数 | PostgreSQL の `test_postgres_syllabus` 20行、Neo4j の `Course` 20ノード（実行前にハーネスが数え、20でなければ止める） |
| プロンプトの SHA-256（先頭16桁） | `compose_answer.md` c899ffa897378fbd、`grounded_addendum.md` c480b9ee68df78ac、S1 の指示文 4c673fab62c998e9 |

## 4. データ

### 4.1 シード

`backend/seed/courses.json` の20科目（GMS-101〜GMS-404）。開発用に用意したダミーの情報系カリキュラム（docs/roadmap.md の「シードデータ」）で、実在の大学のシラバスではない。1科目に、科目コード・科目名・別名、前提科目のコード（0〜2個）、トピック（1〜2個）、担当教員・開講時期（学期・曜日・時限）・単位数（20科目とも2単位）、シラバス本文（1文）がある。

- Neo4j: `Course` ノード（id・code・title だけ）、`Topic` ノード、`(:Course)-[:REQUIRES_PREREQUISITE]->(:Course)`（科目 → 前提科目）、`(:Course)-[:COVERS_TOPIC]->(:Topic)`。担当教員・開講時期は Neo4j には無い。
- PostgreSQL: `test_postgres_syllabus`（code・title・instructor・schedule・credits・syllabus_text）。

### 4.2 質問と正解（golden 14問）

`backend/tests/golden/questions.json` の14問をすべて使った。この golden は、規則ベースの意図解析と静的なグラフ探索（S0 の経路）の回帰テストのために作られたもので、期待する科目の集合は静的探索が返す集合に合わせてある（`docs/adr/0006-deterministic-intent-parser-and-golden-tests.md`、`backend/tests/test_workflow.py`）。

| ID | 質問 | 種別 | 起点科目 | expected_codes（挙げるべき科目） | forbidden_codes（挙げてはいけない科目） |
|---|---|---|---|---|---|
| q01 | データサイエンス入門の次に取れる科目は? | next_step | GMS-301 | 303, 401 | 101, 201 |
| q02 | GMS-201 の後に進める授業を教えて | next_step | GMS-201 | 301, 302, 303, 401, 402 | 101 |
| q03 | プログラミング入門を取ったら次は何が受けられる? | next_step | GMS-201 | 301, 302, 303, 401, 402 | 101 |
| q04 | 線形代数の先にある科目は? | next_step | GMS-202 | 303 | 102 |
| q05 | 機械学習を取るのに必要な前提科目は? | prereq | GMS-303 | 101, 102, 201, 202, 203, 301 | 401, 402 |
| q06 | GMS-401 の履修条件は? | prereq | GMS-401 | 101, 102, 201, 203, 301 | 202, 303 |
| q07 | データベースを受ける前に何が要る? | prereq | GMS-302 | 101, 201 | 402 |
| q08 | データベースに近い分野の科目は? | topic | GMS-302 | 201, 301, 402 | 102, 202 |
| q09 | 統計学基礎と関連する授業は? | topic | GMS-203 | 102, 202, 301, 303, 401 | 101 |
| q10 | メディア情報論に似た科目は? | topic | GMS-402 | 302 | 201 |
| q11 | 何かおすすめの授業ある? | unclear（no_mode） | なし | なし | なし |
| q12 | 金曜3限に空いてる授業は? | unclear（out_of_scope） | なし | なし | なし |
| q13 | この授業難しい? | unclear（decline） | なし | なし | なし |
| q14 | データサイエンスの次は? | unclear（ambiguous） | なし | なし | なし（alternatives = GMS-301, GMS-401） |

科目コードは「GMS-」を省いた。

- 検索系（next_step・prereq・topic）の10問: expected_codes は起点科目から静的探索で得られる候補の全集合（後続・前提は3段まで、topic はトピックを共有する科目）。起点科目自身は含まない。
- unclear の4問: 科目を1つも提示しないのが期待される動き。q14 の alternatives（GMS-301, GMS-401）は聞き返すときの選択肢で、探索の結果ではない。

出どころと偏り:

- golden は静的 DAG の出力に合わせて作られているので、S0 が満点になるのは作り方からくる前提であり、方式の優劣の証拠にはならない（H5 は妥当性の確認として置いた）。
- 質問文は規則ベースの意図解析が読める形にそろっている。
- unclear の正解は「静的 DAG が答えない問い」を表している。RDB を読める条件にとっては答えられる問いが混ざる（8.5 の q12）。

## 5. 条件

| ID | 名前 | 入口（コード） | 誰の実装か | LLM の回数 |
|---|---|---|---|---|
| S0 | static | `agent.runner.run_course_navigator` | 既存（チーム） | 0回 |
| S1 | static_llm | `agent.workflow.build_agent_workflow(enable_mcp=False, instruction=STATIC_LLM_INSTRUCTION)` | 既存の組み立て関数（Yuto、`3e36a2f`）+ ハーネスの指示文 | 検索系で1回、unclear で0回 |
| M1 | mcp_free | `agent.workflow.build_mcp_first_workflow()` | Yuto（`3e36a2f`、`test/agent-communication`） | LLM が決める |
| M2 | mcp_grounded | `agent.runner.run_mcp_grounded(question, agent=build_grounded_mcp_agent())` | Aki_Ha（PR #14、test3-2） | LLM が決める |

### S0: 静的 DAG（LLM なし）

```
質問 → parse_intent（規則で意図と起点科目を判定）→ route_by_mode
         ├ next_step → expand_forward（後続科目を1〜3段たどる）  ┐
         ├ prereq    → expand_backward（前提科目を1〜3段たどる）  ├→ rank_candidates → compose_answer（関数）
         ├ topic     → search_by_topic（トピックを共有する科目）  ┘
         └ unclear   → respond_unclear（定型文。科目コードを出さない）
```

- compose_answer は、候補ごとの根拠文（evidence）をつなげて回答文にし、候補のコードを cited_codes にする関数。
- コード: `backend/src/agent/workflow.py`（`build_workflow`）、`nodes.py`、`intent_rules.py`、`rank.py`、`backend/src/course_core/graph/traversal.py`。

### S1: S0 の終端を LLM に替えたもの

```
（S0 と同じ）… → rank_candidates → compose_agent（LlmAgent。ツール無し）
                └ unclear は respond_unclear で終わる（LLM を通らないので S0 と同じ回答）
```

- compose_agent は `build_compose_agent`（`backend/src/agent/compose_agent.py`）で作る LlmAgent。ツールを持たず、出力の形は AnswerPayload（answer と cited_codes）。入力は rank_candidates が出す候補の集合（CandidateSet）の JSON。
- プロンプトは本番の `compose_answer.md` を使わない。このプロンプトは「必ず最初に MCP ツールで探索せよ」と指示しており、ツールを持たない S1 では成り立たない。代わりに「渡された候補だけから書く」指示文をハーネスに置いた（`backend/eval/node_compare.py` の `STATIC_LLM_INSTRUCTION`。本文は事前登録 §2.1 に凍結した）。要点: 入力 JSON の内容だけを根拠にする、主観的な評価をしない、言及した科目のコードを cited_codes に漏れなく入れる、「科目名 [科目コード]」の形で挙げる、候補が空なら見つからなかったと伝える。

### M1: LLM が MCP で探索して回答まで書く

```
START → route_initial ─ mcp → mcp_agent（LlmAgent。Neo4j MCP ツールのみ）→ 終わり
```

- mcp_agent は既定の `build_mcp_agent()`（`backend/src/agent/mcp_agent.py`）。ツールは Neo4j の MCP ツール（`get-schema`・`read-cypher` などで、LLM が Cypher を書いてグラフを読む）だけ。プロンプトは共有の `backend/src/agent/prompts/compose_answer.md`。RDB ツールも出典ノードも無い。
- ハーネスは、M2 の本番経路と同じく LLM を動かす前に MCP のツール一覧を取得できるか確かめる（事前接続）。失敗したら静的経路には倒さず、その実行を失敗として記録する決まりにした（一度も起きなかった）。

### M2: M1 に RDB ツールと出典ノードを足したもの（test3-2）

```
START → route_initial ─ mcp → mcp_agent（Neo4j MCP + get_course_details）→ attach_sources → 終わり
```

- mcp_agent は `build_grounded_mcp_agent()`。ツールは Neo4j の MCP ツールと `get_course_details`（`backend/src/agent/rdb_tools.py`。PostgreSQL から担当教員・開講時期・単位数・本文を返す）。プロンプトは `compose_answer.md` に `grounded_addendum.md`（RDB の手順）をつなげたもの。
- attach_sources（`backend/src/agent/nodes.py`、`grounding.py`）は LLM を使わない。cited_codes を正規化して PostgreSQL で引き直し、行があるものを sources に、無いものを unverified_codes に入れる。cited_codes そのものは削らない。
- M2 が route="static" で返った（事前接続に失敗して静的経路に倒れた）場合は失敗として記録する決まりにした（一度も起きなかった）。

M1 と M2 の違いは (i) RDB ツールと追補プロンプトの有無、(ii) attach_sources の有無の2つ。attach_sources は cited_codes を変えないので、cited_codes から計算する指標の差は (i) によるエージェントの振る舞いの差として読む（事前登録 §2）。

### 計測のしかた（全条件共通）

- 本番コードの挙動は変えていない。ハーネスは各 LlmAgent に before_model_callback と after_model_callback を付けて数えるだけで、リクエストの中身は変えない（`backend/eval/node_compare.py` の `LlmMeter`）。
  - LLM リクエスト数 = before_model_callback が呼ばれた回数 = Gemini API へのリクエスト数（google-genai の HTTP 再試行は既定で無効なので一致する）。
  - トークン数 = after_model_callback で受け取った応答の usage_metadata（入力 prompt_token_count、出力 candidates_token_count、思考 thoughts_token_count）の合計。
  - ADK の Workflow は構築時に LlmAgent を複製するので、S1・M1 はグラフの中のノードにコールバックを付けた。M2 は run_mcp_grounded に渡す前のエージェントに付けた。
- 予算の上限は before_model_callback の中で、リクエストを送る前に例外で止める。
- 出典の検証（unverified）は、全条件の cited_codes を、ハーネスが attach_sources と同じ純関数（`agent.grounding.build_grounded_answer`）で PostgreSQL と突き合わせて求めた（以下「事後検証」）。M1 の値もこの事後検証によるもので、パイプラインの中で検証したものではない。M2 はパイプラインの中の attach_sources の結果も別に記録し、事後検証と比べた。
- M1 の事前接続・ツールセットの終了・node_sequence の抽出は、M2 と同じ処理にそろえるため `agent.runner` の内部関数（`_preflight_toolsets`・`_close_toolsets` など）をそのまま呼んでいる。

## 6. 手順

| 順 | 時刻（JST） | したこと | LLM リクエスト |
|---|---|---|---|
| 1 | 10-11 23:49 | 事前登録をコミット（`33ff759`） | 0 |
| 2 | 10-12 00:05 | ハーネスと純関数のテストをコミット（`74817be`） | 0 |
| 3 | 00:06 | S0 だけを14問流して H5 を確認（予算0で LLM を呼べない状態にして実行）。H5 は支持（検索系 10/10 満点、unclear 4/4）。この出力はコンテナの /tmp に書いただけで、リポには残していない | 0 |
| 4 | 00:07〜00:09 | 煙テスト: q01 で S1・M1・M2 を1回ずつ。計測と抽出が動くことを確かめた。事前登録どおり集計に使わず、コミットもしない | 16 |
| 5 | 00:10〜00:26 | 本実行: 14問 × 4条件 = 56実行（予算 384 = 400 − 16） | 197 |
| 6 | 00:27〜00:33 | サマリーを生成。集計表に行を足す修正（`6e16872`、9節の逸脱）の後に生成し直し、結果をコミット（`9c5a236`） | 0 |

本実行の順序: 質問は q01 → q14 の順。各質問で S0 → S1 → M1/M2 の順に流し、M1 と M2 の順は質問ごとに入れ替えた（q01・q03・…の奇数番目は M1 が先、偶数番目は M2 が先）。同じプロンプトを続けて送ったときのキャッシュなどの影響を片方に寄せないため。すべて逐次で、並列には流していない。JSONL の started_at で、この順序どおりだったことを確かめた。

予算と打ち切り（事前登録 §8）: LLM リクエストは煙テストと本実行を合わせて400回まで。1実行25回まで、1実行300秒でタイムアウト。429 / 503 は 30秒×試行回数だけ待って最大3回やり直す。本実行では、予算切れ・上限超過・タイムアウト・やり直しのどれも起きなかった。

実行したコマンド（リポのルートで。`$SHA` は当時の HEAD = `74817be`）:

```sh
# 3. S0 だけ（予算0）
docker compose exec -T -w /backend_app backend uv run --no-sync python -m eval.node_compare run \
  --out /tmp/nodecmp/s0_dryrun.jsonl --git-sha $SHA --conditions static --budget 0

# 4. 煙テスト
docker compose exec -T -w /backend_app backend uv run --no-sync python -m eval.node_compare run \
  --out /tmp/nodecmp/smoke.jsonl --git-sha $SHA --conditions static_llm,mcp_free,mcp_grounded --questions q01 --budget 60

# 5. 本実行
docker compose exec -T -w /backend_app backend uv run --no-sync python -m eval.node_compare run \
  --out eval/results/2026-10-11_node_compare.jsonl --git-sha $SHA --budget 384

# 6. 集計
docker compose exec -T -w /backend_app backend uv run --no-sync python -m eval.node_compare summarize \
  --input eval/results/2026-10-11_node_compare.jsonl
```

（Windows の Git Bash から流したので、実際には各行の先頭に `MSYS_NO_PATHCONV=1` を付けた。）

再現するには:

1. AGENTS.md の手順で proxy・db・backend を起動する。`.env` に `GEMINI_API_KEY`（有料枠。本実行だけで LLM を約200回呼ぶ）と DB のパスワードを入れる。`AGENT_MODEL` と `AGENT_ENABLE_MCP` は指定しない。DB はシードの20科目だけにする（20件でないとハーネスが止まる）。
2. このブランチ（`dev/akiha_node-eval`）をチェックアウトし、上の3〜6を流す。出力先には新しいファイル名を使う（既存のファイルがあると `--resume` を付けない限り止まる）。
3. 純関数とハーネスの単体テスト（DB と LLM は使わない、26件）: `docker compose exec -T -w /backend_app backend uv run --no-sync pytest eval/tests -q`（backend の依存が入った環境なら、backend ディレクトリで `uv run pytest eval/tests -q` でもよい）。CI（`.github/workflows/ci.yml`）は `tests/` だけを流すので、このテストは CI では動かない。10/13 に手元の仮想環境で流して 26 passed を確かめた。

LLM の出力は実行ごとに揺れるので、同じ数値が出るとは限らない。煙テストの q01 と本実行の q01 でも LLM の回数が違った（付録）。

## 7. 指標の定義

記号（1回の実行ごと）:

- C = 条件が返した cited_codes を正規化したもの（NFKC で半角にそろえ、前後の空白と括弧を外し、出現順を保って重複を除く。`agent.grounding.normalize_codes`）
- a = 質問の起点科目（golden の anchor_code。unclear には無い）
- C' = C から a を除いたもの
- E = expected_codes、F = forbidden_codes

起点科目を除く理由: golden の E は起点を含まない。一方、共有プロンプトと S1 の指示文は「回答で言及した科目のコードは漏れなく cited_codes に入れる」と指示しているので、起点を引用するのは指示どおりの振る舞いになる。起点を数えると、指示に従った条件ほど precision が下がる。実際に S1 は検索系10問すべてで起点を引用していた。起点以外の文脈上の言及（前提科目に触れるなど）は除かずに数える。

| 指標 | 対象 | 定義・式 |
|---|---|---|
| success | 全問 | 例外・タイムアウト・LLM 回数の上限超過・経路の取り違え（M1・M2 が LLM ノードを通らなかった）・計測漏れ（LLM ノードを通ったのに LLM リクエストが0）が無く、回答（AnswerPayload）が得られた |
| recall | 検索系10問 | \|C' ∩ E\| / \|E\|。挙げるべき科目のうち挙げた割合 |
| precision | 検索系10問 | \|C' ∩ E\| / \|C'\|。挙げた科目のうち挙げるべき科目だった割合。C' が空なら未定義 |
| forbidden_hits | 検索系10問 | \|C' ∩ F\|。挙げてはいけない科目を挙げた数 |
| unverified | 全問 | C のうち `test_postgres_syllabus` に行が無いコードの数（事後検証） |
| unclear_pass | unclear 4問 | C ⊆ alternatives なら合格。q11〜q13 は alternatives が空なので「C が空」、q14 は C ⊆ {GMS-301, GMS-401} |
| llm_requests | 全問 | before_model_callback が呼ばれた回数（Gemini API へのリクエスト数） |
| tool_calls | 全問 | イベント中の function_call の数。ADK が構造化出力のために差し込む set_model_response は除く |
| latency | 全問 | ハーネスが条件の実行関数を呼んでから戻るまでの壁時計時間。エージェントの組み立て、MCP サブプロセスの起動と事前接続、ツールセットの終了を含む |

失敗した実行の扱い（今回は0件）: recall は0、unclear は不合格として数える。precision・forbidden・unverified・llm_requests・tool_calls・latency の集計からは除く。

副次指標（記述のみ）: 回答文に現れた科目コード（正規表現 `[A-Z]{2,5}-\d{3}`、NFKC の後）のうち C に無く起点でもないもの（引用漏れ）、入力・出力・思考のトークン数、M1 の MCP 事前接続の時間。

### 計算の例（q01「データサイエンス入門の次に取れる科目は?」）

a = GMS-301、E = {GMS-303, GMS-401}、F = {GMS-101, GMS-201}。

| 条件 | 返した cited_codes（C） | C'（起点を除く） | C' ∩ E | recall | precision | forbidden | unverified | LLM / ツール / 秒 |
|---|---|---|---|---|---|---|---|---|
| S0 | 303, 401 | 303, 401 | 303, 401 | 2/2 = 1.00 | 2/2 = 1.00 | 0 | 0 | 0 / 0 / 0.4 |
| S1 | 301, 303, 401 | 303, 401 | 303, 401 | 2/2 = 1.00 | 2/2 = 1.00 | 0 | 0 | 1 / 0 / 8.3 |
| M1 | 301, 401, 303, 202 | 401, 303, 202 | 401, 303 | 2/2 = 1.00 | 2/3 = 0.67 | 0 | 0 | 6 / 5 / 35.8 |
| M2 | 301, 303, 401, 202 | 303, 401, 202 | 303, 401 | 2/2 = 1.00 | 2/3 = 0.67 | 0 | 0 | 9 / 8 / 37.9 |

- S1 は起点の GMS-301 も引用したが、C' から除くので precision は 1.00 のまま。
- M1・M2 が足した GMS-202（線形代数）は、GMS-303（機械学習）のもう1つの前提科目（`backend/seed/courses.json` 137行目）。E に無いので precision が 2/3 に下がる。F にも無いので forbidden は0。
- 4つのコードはどれも PostgreSQL に行があるので unverified は0。M2 のパイプライン内の attach_sources の結果も unverified は空で、事後検証と一致した。
- M1 の 35.8 秒には MCP の事前接続 3.3 秒が含まれる。

unclear の例（q14「データサイエンスの次は?」、alternatives = {GMS-301, GMS-401}）: S0・S1 は「当てはまる科目が複数あります」と聞き返し、C は空なので合格。M1・M2 は聞き返さずに GMS-301 を起点と決めて後続を答え、C = {GMS-301, GMS-401, GMS-303, GMS-202} は alternatives に含まれないので不合格。

## 8. 結果

56実行（14問 × 4条件）すべてが成功した。

### 8.1 条件別の集計

| 指標 | S0 static | S1 static_llm | M1 mcp_free | M2 mcp_grounded |
|---|---|---|---|---|
| 成功 | 14/14 | 14/14 | 14/14 | 14/14 |
| recall 平均（検索系10問） | 1.00 | 1.00 | 1.00 | 1.00 |
| precision 平均（検索系10問） | 1.00 | 1.00 | 0.76 | 0.82 |
| precision が未定義（C' が空）の数 | 0 | 0 | 0 | 0 |
| forbidden 合計（該当した質問数） | 0（0） | 0（0） | 1（1） | 0（0） |
| unverified 合計（該当した質問数）※事後検証 | 0（0） | 0（0） | 0（0） | 0（0） |
| unclear 合格 | 4/4 | 4/4 | 1/4 | 1/4 |
| LLM リクエスト 平均 / 中央値（検索系） | 0.0 / 0.0 | 1.0 / 1.0 | 6.7 / 6.0 | 7.8 / 8.0 |
| ツール呼び出し 平均 / 中央値（検索系） | 0.0 / 0.0 | 0.0 / 0.0 | 5.7 / 5.0 | 6.8 / 7.0 |
| latency 平均 / 中央値 秒（検索系） | 0.3 / 0.3 | 8.9 / 8.8 | 30.7 / 29.7 | 35.0 / 32.9 |
| LLM リクエスト 平均 / 中央値（全14問） | 0.0 / 0.0 | 0.7 / 1.0 | 6.4 / 6.0 | 7.0 / 7.5 |
| latency 平均 / 中央値 秒（全14問） | 0.2 / 0.2 | 6.5 / 7.4 | 28.6 / 27.5 | 32.7 / 31.7 |
| MCP 事前接続の中央値 秒（latency に含む） | — | — | 1.9 | — |
| LLM リクエスト合計（予算の消費） | 0 | 10 | 89 | 98 |
| トークン合計 入力 / 出力 / 思考 | 0 / 0 / 0 | 9,247 / 2,679 / 6,937 | 216,005 / 13,937 / 14,028 | 287,684 / 17,696 / 17,686 |
| 入力トークンの平均（検索系1問） | 0 | 約0.9k | 約16k | 約23k |

各行の意味:

- 成功: 7節の success を満たした実行の数 / 実行の数。
- recall 平均・precision 平均: 検索系10問の質問ごとの値（7節）の算術平均。precision は値が定義される実行だけで平均する（今回は全実行で定義された）。
- forbidden 合計: 検索系で forbidden_codes に当たったコードの総数。括弧は1つ以上当たった質問の数。
- unverified 合計: 全14問で、引用したのに DB に行が無かったコードの総数。括弧は該当した質問の数。全条件とも事後検証の値。
- unclear 合格: unclear 4問のうち、7節の unclear_pass を満たした数。
- LLM リクエスト: 1実行あたりの Gemini API へのリクエスト数の平均と中央値。S1 は検索系で必ず1回、unclear で0回（respond_unclear で終わるため）。
- ツール呼び出し: 1実行あたりの function_call の数（set_model_response を除く）。M1・M2 では28実行すべてで「LLM リクエスト数 = ツール呼び出し数 + 1」だった（ツールを1つ呼ぶたびに LLM へ1回戻り、最後に set_model_response を返す1回がある）。
- latency: 7節の定義。M1 は MCP の事前接続（サブプロセスの起動を含む）を含む。M2 も run_mcp_grounded の中で同じ事前接続をしており、その時間を含む（M2 は事前接続だけの時間を別に取り出していない）。
- MCP 事前接続: M1 の事前接続にかかった時間の中央値（副次指標）。
- LLM リクエスト合計: 予算に数えた回数。本実行の合計は 10 + 89 + 98 = 197。煙テストの16回を足すと 213/400。
- トークン合計: 各条件の14実行の合計。思考トークンは、モデルが回答の前に内部で生成したトークン。
- 入力トークンの平均: 検索系10問の入力トークンの合計を10で割ったもの（S1 9,247 / 10、M1 164,446 / 10、M2 229,023 / 10）。

### 8.2 仮説の判定（事前登録 §6）

| 仮説 | 判定 | 根拠 |
|---|---|---|
| H5 S0 の妥当性 | 支持 | 検索系で満点 10/10、unclear 合格 4/4 |
| H1 出典の検証（M2 vs M1） | 一部支持 | (a) M2 の unverified 合計は0で満たす（ただし M1 も0）。(b) precision の平均差 M2 − M1 = +0.06、符号カウント +4（10問）。平均差が 0.10 に届かず満たさない |
| H2 コスト（M1・M2 vs S1、検索系） | 一部支持 | (a) latency 中央値の比は M1 3.4倍・M2 3.7倍で、基準の10倍に届かず満たさない。(b) LLM リクエスト平均の比は M1 6.7倍・M2 7.8倍で、基準の5倍を満たす |
| H3 S1 は S0 の候補を保つ | 支持 | 検索系10問すべてで C' の集合が一致（基準は9問以上） |
| H4 unclear で候補を作らない | 支持 | unclear 合格は S0 4/4、S1 4/4、M1 1/4、M2 1/4 |

符号カウントは「M2 の値が M1 より大きい質問の数 − 小さい質問の数」。precision で M2 > M1 だったのは q02・q03・q09・q10 の4問、M2 < M1 は0問、同じだったのが6問。

### 8.3 条件間の比較（事前登録 §7 の基準）

率の指標（検索系。平均差と符号カウントは「左 − 右」）:

| 比較 | 指標 | 質問数 | 平均差 | 符号カウント | 判定 |
|---|---|---|---|---|---|
| S1 vs S0 | recall | 10 | 0.00 | 0 | 差なし |
| S1 vs S0 | precision | 10 | 0.00 | 0 | 差なし |
| M1 vs S0 | recall | 10 | 0.00 | 0 | 差なし |
| M1 vs S0 | precision | 10 | −0.24 | −6 | 差あり |
| M2 vs S0 | recall | 10 | 0.00 | 0 | 差なし |
| M2 vs S0 | precision | 10 | −0.18 | −5 | 差あり |
| M2 vs M1 | recall | 10 | 0.00 | 0 | 差なし |
| M2 vs M1 | precision | 10 | +0.06 | +4 | 差は小さい |

コストの比（「左 ÷ 右」。latency は検索系の中央値、LLM リクエストは検索系の平均、ツール呼び出しは全問の平均）:

| 比較 | latency | LLM リクエスト | ツール呼び出し |
|---|---|---|---|
| S1 / S0 | 32.0（差あり） | 比較不能（S0 は0） | 比較不能（どちらも0） |
| M1 / S0 | 108.0（差あり） | 比較不能 | 比較不能 |
| M2 / S0 | 119.7（差あり） | 比較不能 | 比較不能 |
| M2 / M1 | 1.1（差なし） | 1.2（差なし） | 1.1（差なし） |

質問数で数える指標（「左 − 右」）: unclear 合格数は M1 − S0 と M2 − S0 がどちらも −3 で「差あり」。forbidden に当たった質問数は M1 − S0 が +1、M2 − M1 が −1 で「1問差（偶然と区別できない）」。それ以外の組（unverified に当たった質問数のすべて、S1 − S0 のすべて、M2 − S0 の forbidden、M2 − M1 の unclear）は差0。

### 8.4 質問別の結果（検索系）

正しさ（R = recall、P = precision、F = forbidden に当たったコード）:

| 質問 | 種別 | S0 | S1 | M1 | M2 |
|---|---|---|---|---|---|
| q01 | next_step | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 0.67 | R 1.00 / P 0.67 |
| q02 | next_step | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 0.71 | R 1.00 / P 0.83 |
| q03 | next_step | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 0.71 | R 1.00 / P 0.83 |
| q04 | next_step | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 0.50 | R 1.00 / P 0.50 |
| q05 | prereq | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 1.00 |
| q06 | prereq | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 1.00 |
| q07 | prereq | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 1.00 |
| q08 | topic | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 1.00 |
| q09 | topic | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 0.83 | R 1.00 / P 1.00 |
| q10 | topic | R 1.00 / P 1.00 | R 1.00 / P 1.00 | R 1.00 / P 0.12、F: GMS-201 | R 1.00 / P 0.33 |

M1・M2 が足した、E に無い科目（C' − E）とシード上の関係:

| 質問 | M1 が足した科目 | M2 が足した科目 | シード上の関係 |
|---|---|---|---|
| q01 | 202 | 202 | GMS-202 は後続科目 GMS-303 のもう1つの前提科目 |
| q02 | 202, 203 | 203 | GMS-203 は後続科目 GMS-301 のもう1つの前提科目、GMS-202 は GMS-303 のもう1つの前提科目 |
| q03 | 202, 203 | 203 | q02 と同じ（q03 は q02 と同じ起点を科目名で聞く問い） |
| q04 | 301 | 301 | GMS-301 は後続科目 GMS-303 のもう1つの前提科目 |
| q09 | 201 | なし | GMS-201 は、E にある GMS-301 のもう1つの前提科目（もう1つは起点の GMS-203）。起点とトピックを共有しない |
| q10 | 101, 201, 104, 205, 305, 304, 403（7件） | 104, 305（2件） | グラフ上で起点の GMS-402 とトピックを共有するのは GMS-302 だけ。M1 は GMS-402 の前提をさかのぼった科目（201・101）と、情報デザイン・Web・クラウド系の科目（104・205・305・304・403）を「関連する」として挙げた。M2 は情報デザイン系の2科目を「親和性が高い」として挙げた。どれも DB に実在するので unverified にはならないが、GMS-402 との関係はグラフに無い |

precision の低下は、q10 を除くと、どれも「E にある科目のもう1つの前提科目」への言及による。回答として不自然な言及ではないが、golden の E には入っていないので減点される（11節）。

### 8.5 質問別の結果（unclear）

| 質問 | S0 | S1 | M1 | M2 |
|---|---|---|---|---|
| q11 何かおすすめの授業ある? | 合格 | 合格 | 不合格（20科目すべてを引用） | 不合格（16科目を引用） |
| q12 金曜3限に空いてる授業は? | 合格 | 合格 | 合格 | 不合格（GMS-205, 104, 305, 403） |
| q13 この授業難しい? | 合格 | 合格 | 不合格（GMS-101, 201） | 合格 |
| q14 データサイエンスの次は? | 合格 | 合格 | 不合格（GMS-301, 401, 303, 202） | 不合格（同左） |

- q11: S0・S1 は質問の形を案内し、登録科目の名前の一覧を添える（コードは出さず cited_codes は空）。M1・M2 は主観的な評価はしないと断ったうえで、系統別に科目を並べた。
- q12: M2 は get_course_details で全科目の開講時期を引き、金曜3限は GMS-205（秋学期 金曜3限）だけだと答えた。シード（97行目）と一致する正しい回答だが、golden はこの問いを静的探索の守備範囲外（候補を出さないのが正解）としているので不合格になる。M1 は「時間割の情報は登録されていない」と答えて合格した（Neo4j には開講時期が無い）。
- q13: M1・M2 とも「どの科目か」と聞き返した。M1 は例として挙げた GMS-101・GMS-201 を cited_codes に入れたので不合格、M2 は例の GMS-301 を本文にだけ書いたので合格になった。この2つの差は、例示したコードを cited_codes に入れたかどうかであり、振る舞いはほぼ同じだった。
- q14: 7節の unclear の例のとおり。M1・M2 とも聞き返さずに GMS-301 を起点と決めた。

### 8.6 質問別のコスト

LLM リクエスト / ツール呼び出し / latency 秒:

| 質問 | S0 | S1 | M1 | M2 |
|---|---|---|---|---|
| q01 | 0 / 0 / 0.4 | 1 / 0 / 8.3 | 6 / 5 / 35.8 | 9 / 8 / 37.9 |
| q02 | 0 / 0 / 0.3 | 1 / 0 / 9.5 | 5 / 4 / 31.0 | 5 / 4 / 30.8 |
| q03 | 0 / 0 / 0.3 | 1 / 0 / 10.7 | 9 / 8 / 45.2 | 8 / 7 / 47.5 |
| q04 | 0 / 0 / 0.6 | 1 / 0 / 9.0 | 9 / 8 / 34.4 | 9 / 8 / 32.6 |
| q05 | 0 / 0 / 0.3 | 1 / 0 / 10.4 | 5 / 4 / 23.1 | 5 / 4 / 27.9 |
| q06 | 0 / 0 / 0.2 | 1 / 0 / 15.2 | 5 / 4 / 20.2 | 5 / 4 / 26.5 |
| q07 | 0 / 0 / 0.4 | 1 / 0 / 5.7 | 6 / 5 / 28.0 | 8 / 7 / 33.2 |
| q08 | 0 / 0 / 0.2 | 1 / 0 / 8.7 | 7 / 6 / 28.3 | 10 / 9 / 39.0 |
| q09 | 0 / 0 / 0.1 | 1 / 0 / 6.5 | 6 / 5 / 25.5 | 7 / 6 / 29.6 |
| q10 | 0 / 0 / 0.3 | 1 / 0 / 5.5 | 9 / 8 / 35.8 | 12 / 11 / 44.9 |
| q11 | 0 / 0 / 0.1 | 0 / 0 / 0.3 | 4 / 3 / 25.7 | 4 / 3 / 37.1 |
| q12 | 0 / 0 / 0.1 | 0 / 0 / 0.1 | 8 / 7 / 25.9 | 5 / 4 / 24.1 |
| q13 | 0 / 0 / 0.1 | 0 / 0 / 0.2 | 3 / 2 / 14.7 | 2 / 1 / 16.3 |
| q14 | 0 / 0 / 0.1 | 0 / 0 / 0.2 | 7 / 6 / 27.0 | 9 / 8 / 30.5 |

### 8.7 その他の観察

- 失敗・やり直し: 0件。外れ値として扱った実行は無い。最も時間がかかったのは q03 の M2（47.5 秒）、LLM の回数が最も多かったのは q10 の M2（12回）で、どちらも上限（300秒・25回）の内側だった。
- M2 のパイプライン内の検証（attach_sources）と事後検証の unverified は14/14で一致した。
- 回答文にあるが cited_codes に無いコード（起点を除く）: q13 の M2（GMS-301。聞き返しの例として本文にだけ書いた）、q14 の S0・S1（GMS-301・GMS-401。聞き返しの選択肢で、候補の提示ではない）。
- RDB の詳細: M2 は14問中13問で get_course_details を呼んだ（呼ばなかったのは q13）。回答文に教員の肩書き（教授・准教授・講師）と「学期」の両方が出てくる回答は、M2 で13/14、M1 で0/14だった（文字列を探しただけで、値が正しいかは確かめていない）。
- M2 について、ハーネスが測った latency と run_mcp_grounded が返す latency_ms の差は中央値 0.2 秒（ツールセットの終了処理など）。

## 9. 事前登録との照合

- 手順・指標の式・判定規則・閾値は、事前登録から変えていない。
- 順序: 事前登録（`33ff759`）→ ハーネス（`74817be`）→ S0 だけで H5 を確認 → 煙テスト → 本実行。事前登録 §8 のとおり。
- 予算: 400回のうち213回（煙テスト16回 + 本実行197回）。本実行の予算を 384（= 400 − 16）として渡した。
- 結果を見た後の変更は1件: 事前登録 §5 で出すと決めていた集計値のうち、サマリーの表に出ていなかったもの（検索系の LLM リクエスト中央値・ツール呼び出しの平均と中央値・latency 平均、副次指標の M1 の事前接続時間）を足した（`6e16872`。`metrics.py` と `report.py` に集計値を足しただけで、式と判定は変えていない）。
- サマリー（`2026-10-11_node_compare_summary.md`）は `summarize` が JSONL から生成したもので、末尾の「事前登録からの逸脱と補足」の節だけを手で書いた。
- 仮説の判定は8.2のとおり（H5・H3・H4 は支持、H1・H2 は一部支持）。

## 10. 考察

言えること（どれも各条件1回ずつの実行から読んだもの）:

- 静的探索の後ろに LLM の文章化ノードを1つ足す設計（S1）は、推薦する科目の集合を変えずに文章だけを書いた（10/10 で一致）。追加のコストは LLM 1回と約9秒（検索系の中央値）。この golden の範囲では、推薦の中身を変えずに LLM を入れられる。
- LLM に探索まで任せる設計（M1・M2）でも、シードの検索系の問いでは期待する科目を落とさなかった（recall 1.00）。ただし共有プロンプト（`compose_answer.md`）には、後続・前提・共通トピックを引く Cypher の例が、シードのスキーマに合わせてほぼそのまま載っている。この結果はプロンプトの例に助けられている可能性が高い（例を外した条件は測っていない）。
- M1・M2 の弱さは、取りこぼしより「足しすぎ」と「答えるべきでない問いで答える」ことに出た。前提科目や似た分野の科目を自分の判断で足し（precision 0.76・0.82）、曖昧な問いで聞き返さずに起点を決めた（q14）。静的 DAG は、意図解析で unclear に振り分けた時点で候補を出さない作りになっている。
- M2 の RDB ツールと attach_sources は、今回は DB に無いコードを1件も捕まえていない。M1 も0件だったので、捕まえる対象が無かった。今回見えた M2 の違いは、担当教員・開講時期などを DB から回答に書けたことと、q12 のような時間割の問いに答えられたこと（golden 上は不合格）である。
- M2 の追加コストは M1 の1.1〜1.2倍で、§7 の基準では差なし。出典のためのツールとノードを足しても、MCP 探索そのものの費用（LLM 7回前後、入力 16〜23k トークン、約30秒）に比べれば小さかった。

言えないこと:

- 条件間の差が偶然でないこと。n=14・各1回で、LLM の条件は同じ問いでも実行ごとに変わる（付録の煙テストと本実行の q01 の違い）。
- 出典ノードが誤った引用を防ぐ効果。今回は誤った引用（DB に無いコード）が一度も出なかった。
- シード以外のデータ（駒澤大学のデータなど）や、別のモデル・温度での結果。
- M2 が回答に書いた担当教員・開講時期などが正しいか（機械では確かめていない）。

## 11. 限界

- n=14、各条件1回ずつ。1問単位の差は偶然と区別できない。
- データはシードの20科目だけで、golden は静的探索の出力に合わせて作られている。S0 の満点は作り方からくる前提で、方式の優劣の証拠にはならない。
- モデルは gemini-3.8-flash の1種類で、温度などの生成設定は API の既定値。
- 共有プロンプトにシードのスキーマに合わせた Cypher の例が載っているので、M1・M2 の recall はこの例に助けられている。
- precision は golden の E との一致で測るので、回答として妥当な前提科目への言及も減点される。
- unclear の合否は cited_codes だけで決めているので、q13 のように「例として挙げた科目を引用欄に入れたかどうか」で結果が変わる。また golden の unclear は静的 DAG の守備範囲を表しており、q12 のように RDB を読める条件には合わない問いが混ざる。
- latency には、ローカルの Docker で MCP サブプロセス（`uv run neo4j-mcp-server`）を毎回起動する時間が含まれる。本番の配置とは違う。また約40分前の [test3-2 の e2e](2026-10-11_test3-2-e2e.md) では、同じ構成のほぼ同じ問いが3倍近く遅かったので、時間の値は API 側の状況にも左右される。
- S0 だけで H5 を確かめた実行の出力と、煙テストの出力はリポに残していない（煙テストは事前登録で「コミットしない」と決めていた）。

## 12. 生データとコードの場所

すべてブランチ `dev/akiha_node-eval`。

| 内容 | 場所 | コミット |
|---|---|---|
| 事前登録 | `backend/eval/prereg_node_compare.md` | `33ff759` |
| ハーネス（条件の組み立て・実行・記録） | `backend/eval/node_compare.py` | `74817be` |
| 採点・集計・仮説判定の純関数 | `backend/eval/metrics.py` | `74817be`、`6e16872` |
| サマリーの生成 | `backend/eval/report.py` | `74817be`、`6e16872` |
| 単体テスト | `backend/eval/tests/test_metrics.py`、`test_node_compare.py` | `74817be`、`6e16872` |
| 生データ（1実行1行） | `backend/eval/results/2026-10-11_node_compare.jsonl` | `9c5a236` |
| 実行条件（git SHA・モデル・プロンプトのハッシュ・DB の件数・予算と使用量・ライブラリの版） | `backend/eval/results/2026-10-11_node_compare_manifest.json` | `9c5a236` |
| 生成したサマリー（集計表・仮説の判定・質問別の表・逸脱） | `backend/eval/results/2026-10-11_node_compare_summary.md` | `9c5a236` |
| 対象の本番コード | `backend/src/agent/`（`workflow.py`・`runner.py`・`mcp_agent.py`・`compose_agent.py`・`rdb_tools.py`・`nodes.py`・`grounding.py`・`prompts/`） | `ca94e4a` と同じ |
| 質問と正解 | `backend/tests/golden/questions.json` | — |
| シード | `backend/seed/courses.json` | — |

JSONL の主な列: question_id、condition、success・error、model・model_versions、cited_codes（正規化前）、score（C'・recall・precision・forbidden_hits・unclear_pass・回答文中のコード）、unverified_codes（事後検証）、pipeline_unverified_codes（M2 の attach_sources）、sources_count、llm_requests、トークン数、tool_calls（名前と引数）、tool_call_count、node_sequence、latency_ms、pipeline_latency_ms（M2）、mcp_preflight_ms（M1）、started_at（UTC）、answer（回答の全文）。

## 付録: 試行錯誤の経緯

- S0 だけの確認（予算0、00:06）: 14問とも成功し、H5 は支持。
- 煙テスト（q01、00:07〜00:09、run_id 20261011T150753Z）: S1 は LLM 1回・8.4秒、M1 は LLM 7回・ツール6回・34.9秒、M2 は LLM 8回・ツール7回・46.8秒。計16回。本実行の q01 では M1 が6回・35.8秒、M2 が9回・37.9秒だったので、同じ問いでも LLM の回数と時間は実行ごとに変わる。出力は Aki_Ha のローカルのログにだけ残っている。
- 本実行は1回で通った。失敗した実行・やり直しは無い。
- 集計の後、事前登録 §5 で約束した集計値の一部がサマリーの表に無いことに気づき、`6e16872` で足してサマリーを生成し直した（9節）。
- この実験の約40分前に [test3-2 の e2e](2026-10-11_test3-2-e2e.md) を同じキー・同じコンテナで流している。
