# ノード設計比較の事前登録（2026-10-11）

この文書は、LLM を使う実行を1回も行う前にコミットする。登録後に変えたことは、
結果のサマリー（`results/2026-10-11_node_compare_summary.md`）の「事前登録からの逸脱」に理由と一緒に書く。

## 1. 目的

10/7 に Yuto から「ノードをこだわってみてほしい」と依頼があった。MTG では、ノードの設計を変えたら評価がどう変わったかを比べると面白い、という話も出た。
そこで、同じ golden 14問・同じモデルで、エージェントのノード構成だけを変えた4条件を流し、回答の正しさ・出典の検証結果・コストを並べる。
主張は記述統計に留め、有意性は主張しない（n=14、各1回）。

## 2. 条件

| ID | 名前 | 組み立て方（コード上の入口） | LLM |
|---|---|---|---|
| S0 | `static` | `agent.runner.run_course_navigator`（= `agent.workflow.workflow`）。parse_intent → route_by_mode → expand_forward / expand_backward / search_by_topic / respond_unclear → rank_candidates → compose_answer（関数ノード） | 0回 |
| S1 | `static_llm` | `agent.workflow.build_agent_workflow(enable_mcp=False, instruction=<§2.1 の指示文>)`。S0 の終端 compose_answer を LlmAgent（`build_compose_agent`、ツール無し、output_schema=AnswerPayload）に差し替えたもの。LLM への入力は rank_candidates が出す CandidateSet の JSON | 検索系の質問で1回の想定。unclear は respond_unclear で終わるので0回（S0 と同じ回答になる） |
| M1 | `mcp_free` | `agent.workflow.build_mcp_first_workflow()`（既定の `build_mcp_agent()`: Neo4j MCP ツールのみ、共有プロンプト `compose_answer.md`、RDB ツール無し、attach_sources 無し）。route_initial → mcp_agent で終わる | LLM が回数を決める |
| M2 | `mcp_grounded` | `agent.runner.run_mcp_grounded(question, agent=build_grounded_mcp_agent())`。route_initial → mcp_agent（Neo4j MCP + get_course_details、共有プロンプト + `grounded_addendum.md`）→ attach_sources | LLM が回数を決める |

共通事項:

- モデルは全 LLM 条件で `course_core.config.AGENT_MODEL` を使う。本実行の環境では環境変数 AGENT_MODEL が未設定なので既定値の `gemini-3.8-flash` になる。実行ごとにエージェントのモデル名と、応答が返す model_version を記録する。
- 温度などの生成設定は、本番の組み立て関数がどれも `generate_content_config` を渡していないので API の既定値のまま（`config.AGENT_TEMPERATURE` はコード中で使われていない）。ハーネスでも足さない。
- 本番コードの挙動は変えない。ハーネスは各 LlmAgent に before_model_callback / after_model_callback を付けて、LLM リクエスト数・トークン数・model_version を数えるだけにする（リクエストの中身は変えない）。Workflow は構築時に LlmAgent を複製するので、S1・M1 はグラフ内のノードに、M2 は run_mcp_grounded に渡す前のエージェントに付ける。
- M1 は、run_mcp_grounded と同じく LLM を動かす前に MCP ツールセットからツール一覧を取得できるか確かめる（事前接続）。取得に失敗したら静的経路には倒さず、その実行を失敗として記録する。M2 が route="static" で返った（MCP 事前接続に失敗して静的経路に倒れた）場合も失敗として記録する。
- M1 と M2 の違いは2つある。(i) エージェントが RDB ツール get_course_details と追補プロンプトを持つこと、(ii) 後段に attach_sources ノードがあること。attach_sources は cited_codes を削らず、DB に無いコードに印を付けて出典を足すだけなので、cited_codes から計算する指標（recall / precision / forbidden / unverified）の差は (i) によるエージェントの振る舞いの差として読む。
- 出典の検証（unverified）は、全条件の cited_codes をハーネスが同じ純関数 `agent.grounding.build_grounded_answer` で PostgreSQL（test_postgres_syllabus）と突き合わせて求める（以下「事後検証」）。M2 はパイプライン内の attach_sources の結果も別に記録し、事後検証と一致するかを確かめる。M1 の値は事後検証によるもので、パイプライン内の検証ではないことを明記して報告する。

### 2.1 S1 の指示文（ハーネスに置く。本番プロンプトは変えない）

本番の `compose_answer.md` は「必ず最初に MCP ツールで探索せよ」と指示しているので、ツールを持たない S1 には使えない（未宣言ツールの呼び出しで止まりうる）。
そのため、渡された候補だけから回答を書く指示文をハーネス側（`eval/node_compare.py` の `STATIC_LLM_INSTRUCTION`）に置く。本文は次のとおりで、規則の2と3は `compose_answer.md` の「客観性の維持」「引用科目コードの明記」と同じ趣旨にそろえた。

```text
あなたは大学の履修選択を支援する「履修アドバイザーAI（Course Navigator）」です。
入力は、静的なグラフ探索が返した候補科目の JSON（CandidateSet）です。あなたはツールを使えません。

1. 回答の根拠にしてよいのは入力 JSON の内容（intent、candidates の code / title / evidence、notes）だけです。入力に無い科目を挙げたり、科目間の関係を推測で補ったりしてはいけません。
2. 「楽単」「単位が取りやすい」「おすすめ」「先生が厳しい」といった主観的・非公式な評価は述べないでください。
3. 回答文中で言及した科目の科目コードは、必ず cited_codes フィールドに漏れなくリストアップしてください。
4. 回答は日本語で、結論を先に書き、各候補を「科目名 [科目コード]」の形で挙げて evidence の内容を根拠として添えてください。
5. candidates が空のときは、該当する科目が見つからなかったことと、notes があればその内容を伝えてください。
```

## 3. 質問と正解

- `backend/tests/golden/questions.json` の14問をすべて使う（next_step 4: q01〜q04、prereq 3: q05〜q07、topic 3: q08〜q10、unclear 4: q11〜q14）。
- 各条件×各質問を1回だけ実行する（計56実行。うち S0 の14実行と S1 の unclear 4実行は LLM を呼ばない）。
- golden の意味（`tests/test_workflow.py` と `tests/test_intent.py` から読んだもの）:
  - expected_codes: 起点科目（anchor_code）から静的探索で得られるべき候補の全集合。起点科目自身は含まない。
  - forbidden_codes: 候補として出してはいけない科目（例: q01 の前提側の科目）。
  - unclear（q11〜q14）: 科目を1件も提示しないのが期待動作（A10）。q14（ambiguous）の alternatives は聞き返しの選択肢で、探索結果ではない。

## 4. 指標と式

記号: 1回の実行について、C = `agent.grounding.normalize_codes(cited_codes)`（NFKC で半角化し、前後の空白と括弧を外し、出現順を保って重複を除く）、a = golden の anchor_code（unclear では無し）、C' = C から a を除いたもの、E = expected_codes、F = forbidden_codes。

起点科目を除く理由: golden の E は起点を含まない一方、共有プロンプトは「回答文中で言及した科目のコードは漏れなく cited_codes に入れる」と指示するので、LLM 条件は起点を引用するのが正しい振る舞いになる。起点を数えると、指示どおりに書いた条件ほど precision が下がってしまう。起点以外の文脈上の言及（例: 前提側の科目に触れる）は除かずに数える。

質問ごとの指標:

| 指標 | 対象 | 式 |
|---|---|---|
| success | 全問 | 例外・タイムアウト・LLM 回数の上限超過・経路の取り違え（M1/M2 が LLM ノードを通らなかった）・計測漏れ（LLM ノードを通ったのに LLM リクエスト数が0）が無く、AnswerPayload が得られた |
| recall | 検索系10問 | \|C' ∩ E\| / \|E\| |
| precision | 検索系10問 | \|C' ∩ E\| / \|C'\|。C' が空なら未定義 |
| forbidden_hits | 検索系10問 | \|C' ∩ F\| |
| unverified | 全問 | C のうち test_postgres_syllabus に行が無いコードの数（事後検証） |
| unclear_pass | unclear 4問 | C ⊆ alternatives なら合格。q11〜q13 は alternatives が空なので「C が空」、q14 は C ⊆ {GMS-301, GMS-401} |
| llm_requests | 全問 | before_model_callback が呼ばれた回数（= Gemini API へのリクエスト数。google-genai の HTTP 再試行は既定で無効なので一致する） |
| tool_calls | 全問 | イベント中の function_call の数。ADK が構造化出力のために差し込む set_model_response は除く |
| latency | 全問 | ハーネスが条件の実行関数を呼んでから戻るまでの壁時計時間。エージェントの構築、MCP サブプロセスの起動と事前接続、ツールセットの終了を含む（M2 の run_mcp_grounded が返す latency_ms は別に記録する） |

副次指標（記述のみ）: 回答文に現れた科目コード（正規表現 `[A-Z]{2,5}-\d{3}`、NFKC 後）のうち C に無く起点でもないもの（引用漏れ）、入出力・思考トークン数、M1 の MCP 事前接続時間。

失敗した実行の扱い: recall は0、unclear は不合格として数える。precision・forbidden・unverified・llm_requests・tool_calls・latency の集計からは除き、件数と理由を別に列挙する。失敗した実行の LLM リクエストも予算には数える。

## 5. 集計

条件ごとに出す値: 成功数/14、recall の平均と中央値（検索系10問）、precision の平均（定義される実行のみ）と未定義の件数、forbidden の合計と該当質問数、unverified の合計と該当質問数、unclear 合格数/4、llm_requests・tool_calls・latency の平均と中央値（全14問と検索系10問の両方）、トークン合計。

## 6. 仮説と判定規則

判定は `eval/metrics.py` の関数で機械的に行う。必要な実行が欠けている（予算切れなどで未実行）場合は「判定不能」とする。

- **H5（妥当性の確認）**: S0 は検索系10問すべてで recall = 1 かつ precision = 1 かつ forbidden = 0、unclear 4/4 合格。golden は静的探索の出力と一致するように作られているので、満たさなければハーネスか DB の不具合とみなす。S0 は LLM を使わないので本実行の前に単独で流し、満たさなければ LLM 実行に進まない。
- **H1（出典の検証）**: (a) M2 の unverified の合計が0。(b) 検索系で両条件の precision が定義される質問について、M2 の平均 precision − M1 の平均 precision ≥ 0.10 かつ、符号カウント（M2 > M1 の質問数 − M2 < M1 の質問数）≥ 3。(a) と (b) をともに満たせば支持、片方だけなら一部支持。
- **H2（コスト）**: 検索系10問の成功した実行について、(a) latency の中央値が M1・M2 とも S1 の10倍以上、(b) llm_requests の平均が M1・M2 とも S1 の5倍以上。両方満たせば支持、片方だけなら一部支持。
- **H3（S1 は S0 の候補を保つ）**: 検索系10問のうち、S1 の C' と S0 の C' が集合として一致する質問が9問以上なら支持。
- **H4（unclear で候補を作らない）**: S0 と S1 は unclear 4/4 合格で、M1 と M2 はそれぞれ 3/4 以下（少なくとも1問で alternatives に無い科目を提示する）なら支持。

## 7. 「意味のある差」の基準（仮説以外の比較にも使う）

n=14・各1回なので、次の基準を満たしたものだけを「差あり」と書き、それ以外は「差なし」または「差は小さい」とする。どれも記述上の約束で、検定ではない。

- 率の指標（recall、precision）: 両条件で値が定義される質問について、平均の差の絶対値 ≥ 0.10 かつ符号カウントの差 ≥ 3 なら「差あり」。片方だけ満たすなら「差は小さい」。
- 質問数で数える指標（forbidden の該当質問数、unverified の該当質問数、unclear 合格数）: 2問以上の差なら「差あり」。1問差は「1問差（1回の試行では偶然と区別できない）」と書く。
- コストの指標（latency、llm_requests、tool_calls）: 比が1.5倍以上（または1/1.5以下）なら「差あり」。H2 の10倍・5倍は仮説固有の閾値。

## 8. 実行手順と予算

1. ハーネスのコードと純関数のテストを、この事前登録の直後のコミットで追加する（LLM 実行より前）。
2. S0 を単独で14問流して H5 を確かめる（LLM 0回）。
3. 煙テスト: q01 で S1・M1・M2 を1回ずつ流し、計測と抽出が動くことを確かめる。結果は集計に使わず、コミットもしない。LLM リクエストは予算に数える。
4. 本実行: 質問 q01 → q14 の順に、各質問で S0 → S1 → M1/M2 を流す。M1 と M2 の順は質問ごとに入れ替える（奇数番目の質問は M1 が先、偶数番目は M2 が先）。同じプロンプトを続けて送ったときのキャッシュなどの影響を片方に寄せないため。すべて逐次実行する。
5. 集計とサマリーの生成（`python -m eval.node_compare summarize`）。

予算と打ち切り:

- LLM リクエストは煙テストと本実行を合わせて400回が上限。上限に達したら、次のリクエストを送る前に例外で止め、その実行を失敗（budget_exhausted）として記録して全体を打ち切る。
- 1実行あたりの LLM リクエストは25回まで。超えたらその実行を失敗（llm_request_cap）として記録し、次へ進む。
- 1実行のタイムアウトは300秒。超えたら失敗（timeout）として記録し、次へ進む。
- 429 / 503 が返ったら、30秒×試行回数だけ待ってその実行を最初からやり直す（最大3回）。やり直した回数と理由を記録する。

## 9. 出力

- `results/2026-10-11_node_compare.jsonl`: 1実行1行。question_id、condition、成否とエラー、モデル、cited_codes、各指標、ツール呼び出し（名前と引数）、node_sequence、latency、llm_requests、トークン、回答文。
- `results/2026-10-11_node_compare_manifest.json`: 実行条件（git SHA、モデル、プロンプトのハッシュ、DB の件数、予算と使用量、ライブラリのバージョン）。
- `results/2026-10-11_node_compare_summary.md`: 条件別の集計表、質問別の表、仮説の判定、失敗の一覧。

## 10. 事前に分かっている限界

- n=14・各1回。LLM 条件は同じ質問でも実行ごとに結果が揺れうるので、1問単位の差は偶然と区別できない。
- データはシードの20科目（GMS-101〜404）だけで、golden は静的探索の出力に合わせて作られている。S0 が満点になるのは設計上の前提で、方式の優劣の証拠にはならない。
- モデルは1種類（gemini-3.8-flash）で、温度は API の既定値。
- 共有プロンプトに、シードのスキーマに合わせた Cypher の例（後続・前提・共通トピック）がそのまま載っているので、M1・M2 の recall はこの例に助けられている。
- precision は golden の E に対する一致で測るので、回答として妥当な文脈上の言及（例: 前提科目への言及）も減点される。
- latency にはローカルの Docker 環境での MCP サブプロセス起動（`uv run neo4j-mcp-server`）が含まれ、本番の配置とは異なる。
