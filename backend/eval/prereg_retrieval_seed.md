# 検索方式比較（シード）の事前登録（2026-10-13）

この文書は、埋め込み API と LLM を1回も呼ぶ前にコミットする。登録後に変えたことは、
結果のサマリー（`results/2026-10-13_retrieval_seed_summary.md`）の「事前登録からの逸脱」に理由と一緒に書く。

## 1. 目的と位置づけ

Aki_Ha 個人の実験で、チーム全体の本実験ではない。論文（情報処理学会 DBS 研究会、原稿 11/13）の技術実験
「履修相談の検索で、グラフ探索はベクトル類似度より良い結果を返すか」の実験基盤を、駒澤のデータが揃う前に
シード20科目（GMS-101〜404）で組み立てて通すことが目的である。条件は Yuto の計画書
（`docs/experiments/vector-vs-graph-evaluation.md` §4）の4手法に合わせる。

シードの golden 14問は静的グラフ探索の出力に合わせて作られているので、この実験の結果を
「グラフがベクトルより良い」証拠としては使わない（§10）。ここで確かめたいのは、(1) 4条件が同じ
QuerySpec・同じ採点で動くこと、(2) 指標が想定どおりに計算されること、(3) どの指標がシードで
差を出し、どの指標が出せないか、の3点である。仮説の判定は記録するが、主張は記述統計に留める。

## 2. コーパスと DB

- コーパス: dev の PostgreSQL（`postgres` コンテナ）の `test_postgres_syllabus` 20行を、別に立てた実験用
  PostgreSQL（`cn-eval-pgvector`、pgvector 入り、専用ボリューム、`gateway` ネットワーク、ホストにポートを
  出さない）へ `pg_dump -t test_postgres_syllabus` でコピーする。UUID はそのまま保つ（Neo4j の `Course.id`
  と一致させるため）。dev の DB とボリュームには書き込まない。
- 埋め込みは実験用 DB の `test_course_embeddings`（Yuto の DDL: `vector(1536)`、`course_id` は
  `test_postgres_syllabus(id)` への外部キー、HNSW インデックス `vector_cosine_ops`）に入れる。DDL は
  `course_core.repositories.postgres_repo` の定数をそのまま実行する。
- グラフは dev の Neo4j（シード20科目、REQUIRES_PREREQUISITE 19本、COVERS_TOPIC 36本、Topic 20個）を読み取りで使う。
  追加するのは全文検索インデックス1つだけ（§3.3）。再投入はしない。
- トピックと前提関係の正本は `backend/seed/courses.json`（Postgres の表にトピック列が無いため）。
- スナップショット: コピーした20行（id, code, title, instructor, schedule, credits, syllabus_text をコード順に
  並べた JSON）、`seed/courses.json`、Neo4j のノードとエッジ（コード順）のそれぞれの SHA-256 を manifest に残す。

## 3. 部品

### 3.1 埋め込み

- モデル: `gemini-embedding-2`（2026-10-13 に `models.list()` で embedContent 対応を確認した中で最新の GA 版。
  ほかに `gemini-embedding-001` と `gemini-embedding-2-preview` がある）。`output_dimensionality=1536`。
  返ってきた長さが 1536 でなければ止める。
- 参照した公式文書: https://ai.google.dev/gemini-api/docs/embeddings （Last updated 2026-10-09 UTC）。
  次の3点に従う。
  - 正規化: gemini-embedding-2 は 3072 以外の次元でも自動で正規化し直す、とある（001 は手で正規化が要る）。
    実装では返ってきた L2 ノルムを記録し、そのうえで L2 正規化をかけてから保存する（既に単位長なら値は変わらない）。
    コサイン距離は長さに依存しないので、順位はこの処理で変わらない。
  - タスク種別: gemini-embedding-2 は `task_type` を受け付けず、テキストの先頭に指示を書く。
    検索（非対称）の形式に合わせ、質問は `task: search result | query: {質問文}`、
    文書は `title: {科目名} | text: {本文}` とする。
  - 一括: 複数の入力をそのまま並べると1本に集約されるので、各入力を `types.Content` に包んで渡す。
- 文書の本文（`text:` の部分）は `トピック: {topics を「、」で連結}。{syllabus_text}`。つまり
  文書全体は `title: {title} | text: トピック: {topics}。{syllabus_text}` で、科目名・トピック・シラバス本文を含み、
  科目コードは含まない。title と syllabus_text は実験用 DB の行、topics は `seed/courses.json` から取る。
- 質問の埋め込みは質問ごとに1回だけ作り、全条件で同じベクトルを使う。

### 3.2 QuerySpec（全条件で共有）

質問ごとに1回だけ作り、`backend/eval/specs/seed_query_specs.json` にコミットする。各条件はこれを読むだけにする。

| 項目 | 作り方 |
|---|---|
| question / embedding_text | golden の質問文そのもの（埋め込みの接頭辞は §3.1 で付ける） |
| mode, anchor_code, anchor_title, anchor_status, alternatives, matched_rule | `agent.intent_rules.parse_intent`（シードの辞書照合。LLM も DB も使わない） |
| direction | mode が next_step なら forward、prereq なら backward、topic なら topic、unclear なら無し |
| constraints | 質問文から正規表現で取る: 学期 `(春|秋)学期`、曜日 `([月火水木金土日])曜`、時限 `(\d)限`、単位数 `(\d+)単位`。無ければ空 |
| fulltext_query | 質問文の Lucene 特殊文字をバックスラッシュでエスケープしたもの |

### 3.3 Neo4j 全文検索インデックス

`CREATE FULLTEXT INDEX eval_course_topic_fulltext IF NOT EXISTS FOR (n:Course|Topic) ON EACH [n.title, n.name]
OPTIONS {indexConfig: {`fulltext.analyzer`: 'cjk'}}`。cjk アナライザは日本語を2文字ずつに区切るので、
質問文をそのまま投げると、科目名・トピック名と2文字以上重なるノードが当たる。

### 3.4 検索条件（retriever）

共通の形は `retrieve(spec, k) -> list[RankedItem(code, title, score, evidence)]`。ハーネスは各条件を
k = 11 で1回呼び、spec の anchor_code を結果から除いて上位10件に切り、K=5 と K=10 で採点する
（起点科目は「ユーザーが既に名前を挙げた科目」で推薦ではないので、全条件で同じ後処理として除く）。

| 条件 | 処理 |
|---|---|
| C1 `pure_vector` | 質問ベクトルと全科目のコサイン類似度で並べる（厳密検索。距離の昇順、同点はコード昇順） |
| C2 `vector_metadata` | C1 の SQL に spec.constraints から作る WHERE を足す（schedule の部分一致で学期・曜日・時限、credits の一致）。constraints が空なら C1 と同じ SQL になる |
| C3 `pure_graph` | anchor があれば、direction に応じて既存の `course_core.graph.traversal` の関数を1本呼ぶ（forward: `find_next_courses`、backward: `find_prerequisites`、topic: `find_related_by_topic(limit=k)`）。順位は関数が返す順のまま。anchor が無ければ §3.3 の全文検索を入口にし、Topic に当たったらその Topic を扱う科目に置き換え、科目ごとの最大スコアで並べる（展開はしない） |
| C4 `hybrid`（C4a） | C1 の順位の上位 m=3 件を入口にし、各入口から spec の direction に沿って C3 と同じ traversal 関数で展開する。C1 の順位（上位 k 件）と、入口ごとの展開結果の順位（関数が返す順）を RRF（k_rrf=60、score = Σ 1/(60 + 順位)、同点はコード昇順）で統合する。direction が無い（unclear）ときは展開せず C1 の順位のまま |

- 厳密検索: 実験用 DB への接続ごとに `SET enable_indexscan = off` をかけ、HNSW を使わない（pgvector の README が
  厳密検索の方法として挙げる設定）。実行前に EXPLAIN でインデックスを使わない計画になることを確かめ、manifest に残す。
  HNSW インデックスそのものは Yuto の DDL どおり作る。
- DB クエリ数: 1回の retrieve で PostgreSQL と Neo4j に送ったクエリの数（接続設定の SET は数えない）。
  想定は C1・C2 が1、C3 が1、C4 が 1 + m = 4。
- 検索は各（条件, 質問）で5回繰り返す。5回の順位が一致しなければハーネスの不具合とみなして止める。
  所要時間は5回の中央値（質問の埋め込みを作る時間は含めず、別に記録する）。

### 3.5 回答生成（検索系10問 × 4条件のみ）

S1 と同じ形にする: LLM 1回で、検索結果の上位 K=5 件から回答を書く。組み立ては本番の
`agent.compose_agent.build_compose_agent(instruction=<下の指示文>, enable_mcp=False)`（ツール無し、
output_schema=AnswerPayload）を1ノードだけの Workflow で動かす。モデルは `config.AGENT_MODEL`（環境変数が未設定なので
既定値の `gemini-3.8-flash`）、生成設定は API の既定値。

LLM への入力は次の JSON 文字列:
`{"question": 質問文, "intent": {"mode", "anchor_code", "anchor_title"}, "candidates": [{"rank", "code", "title", "evidence": [文字列]}]}`。
evidence は条件ごとに決定的に作る（C1・C2: 類似度と順位、C2 で絞り込みをかけたときはその条件、
C3: 既存の `agent.rank.build_candidate_set` が作る根拠文、全文検索のときは一致したノード、
C4: C1 の根拠と、入口科目からの展開の根拠文の両方）。

指示文（`eval/retrieval_compare.py` の `GENERATION_INSTRUCTION`。昨日の S1 の指示文から、入力の説明と規則1・5の項目名だけを変えた）:

```text
あなたは大学の履修選択を支援する「履修アドバイザーAI（Course Navigator）」です。
入力は、検索部が返した候補科目の JSON（question、intent、candidates）です。あなたはツールを使えません。

1. 回答の根拠にしてよいのは入力 JSON の内容（question、intent、candidates の code / title / evidence）だけです。入力に無い科目を挙げたり、科目間の関係を推測で補ったりしてはいけません。
2. 「楽単」「単位が取りやすい」「おすすめ」「先生が厳しい」といった主観的・非公式な評価は述べないでください。
3. 回答文中で言及した科目の科目コードは、必ず cited_codes フィールドに漏れなくリストアップしてください。
4. 回答は日本語で、結論を先に書き、各候補を「科目名 [科目コード]」の形で挙げて evidence の内容を根拠として添えてください。
5. candidates が空のときは、該当する科目が見つからなかったことを伝えてください。
```

生成後、全条件の cited_codes を `agent.grounding.build_grounded_answer` で実験用 DB の
`test_postgres_syllabus`（dev からコピーした同じ20行）と突き合わせ、出典と未検証コードを求める。

実行順: 質問 q01 → q10 の順に、条件の順を質問ごとに1つずつずらす（q01: C1 C2 C3 C4、q02: C2 C3 C4 C1、…）。
C2 は検索系10問すべてで C1 と同じ候補になる見込みなので、C1 と C2 の生成結果の違いは、同じ入力に対する
LLM の揺れとして読む（§6 H7）。

## 4. 質問と正解

- `backend/tests/golden/questions.json` の14問（next_step 4: q01〜q04、prereq 3: q05〜q07、topic 3: q08〜q10、
  unclear 4: q11〜q14）。検索は全14問×4条件、生成は検索系10問×4条件。
- 正解: E = expected_codes（起点科目を含まない）、F = forbidden_codes。関連度は2値（E に入っていれば1）。
  expected_order は使わない。
- unclear の4問には正解の順位が無いので、返した件数と、q14 で返した科目が alternatives（GMS-301, GMS-401）に
  収まるかだけを別表に出す（判定には使わない）。

## 5. 指標と式

記号: 1回の検索について、R = 起点を除いた順位リスト、R_K = R の上位 K 件、a = spec の anchor_code。

| 指標 | 対象 | 式 |
|---|---|---|
| Recall@K | 検索系10問 | \|R_K ∩ E\| / \|E\|。\|E\| > K の問い（K=5 では q05 の \|E\|=6）は上限が K/\|E\| になる |
| NDCG@K | 検索系10問 | DCG@K / IDCG@K。DCG@K = Σ_{i=1..\|R_K\|} rel_i / log2(i+1)、rel_i = 1（R_K の i 位が E に入る）/ 0。IDCG@K = Σ_{i=1..min(\|E\|,K)} 1 / log2(i+1) |
| forbidden@K | 検索系10問 | \|R_K ∩ F\|。NDCG では F も関連度0として扱う（追加の減点はしない） |
| 前提違反@K | next_step 4問 | 履修済み集合 D = {a} ∪ a の前提科目の推移閉包（`seed/courses.json` の prerequisite_codes をたどる）。R_K の科目 r は、直接の前提科目のうち1つでも D に無ければ違反。違反数 = 違反した r の数。違反率 = 違反数 / \|R_K\|（R_K が空なら未定義） |
| 履修済みの推薦@K（副次） | next_step 4問 | \|R_K ∩ (D − {a})\| |
| 返却件数 | 全問 | \|R_K\| |
| 所要時間 | 全問 | 5回の retrieve の壁時計時間の中央値（ms） |
| DB クエリ数 | 全問 | §3.4 |
| 生成の指標 | 生成した40回 | C = 正規化した cited_codes、C' = C − {a}。未検証コード数 = C のうち DB に行が無いコードの数。候補外の引用 = C' のうち LLM に渡した5件に無いコードの数。recall = \|C' ∩ E\| / \|E\|、precision = \|C' ∩ E\| / \|C'\|（C' が空なら未定義）、forbidden = \|C' ∩ F\|、LLM リクエスト数、トークン数、所要時間 |
| 埋め込み・LLM のリクエスト数 | 全体 | API を呼んだ回数（1回の呼び出しで複数のテキストを送っても1回） |

参考として、ランダムな順位の期待値（解析解）を同じ表に出す。候補数 N（anchor があれば19、無ければ20）について、
E[Recall@K] = min(K, N) / N、E[NDCG@K] = (\|E\| / N) × Σ_{i=1..K} 1/log2(i+1) / IDCG@K。

K の選び方: 主指標は K=5。20科目のうち起点を除く19件から10件を取ると、ランダムでも Recall@10 の期待値が
約0.53 になり差が縮むので、K=10 は記述のみで判定に使わない（q05 のように \|E\|=6 の問いを全部拾えるかを見るため）。

## 6. 仮説と判定規則

「差あり」の基準（記述上の約束で検定ではない。昨日の事前登録 §7 と同じ）:
率の指標は、質問ごとの値の平均差の絶対値 ≥ 0.10 かつ符号カウント（a > b の質問数 − a < b の質問数）の絶対値 ≥ 3 で、
向きが一致すれば「差あり」、片方だけなら「差は小さい」、どちらも満たさなければ「差なし」。
件数の指標は合計の差が2以上で「差あり」。コストは比が1.5倍以上（1/1.5以下）で「差あり」。

- H0（妥当性の確認）: 検索系10問すべてで spec の mode と anchor_code が golden と一致し、C3 の Recall@10 が1。
  golden は静的探索の出力に合わせて作られているので、満たさなければハーネスか DB の不具合とみなし、生成に進まない。
- H1（向きのある問いでグラフが勝つ）: next_step と prereq の7問で、C3 − C1 が Recall@5 と NDCG@5 のどちらも「差あり」（C3 が上）。両方で支持、片方で一部支持。
- H2（ハイブリッドもベクトルに勝つ）: 同じ7問で、C4 − C1 が Recall@5 と NDCG@5 のどちらも「差あり」（C4 が上）。両方で支持、片方で一部支持。
- H3（トピックの問いではベクトルも戦える）: topic の3問で、C1 の NDCG@5 の平均 ≥ C3 の平均 − 0.10 なら支持。3問しか無いので符号カウントは使わない。
- H4（ハイブリッドは単独の方式の良い方に劣らない）: 検索系10問の NDCG@5 で、C4 が C1 と C3 のどちらに対しても「差あり」で下回らなければ支持。
  C3 は golden と一致するように作られているので、シードでは C4 は C3 に並ぶのが上限で、上回ることは確かめられない。
- H5（前提違反）: next_step の4問の前提違反@5 の合計で、C3 ≤ C1 − 2 かつ C4 ≤ C1 − 2 なら支持、片方なら一部支持。
  注意: 静的探索の next_step は3段先までの後続をすべて返すので、別の前提科目が未履修の科目（例: q01 の GMS-303 は GMS-202 が要る）も含む。
  C3 も違反を出しうる。返却件数が条件で違うので違反率も並べる（判定は件数で行う）。
- H6（C2 はシードで検証できない）: 検索系10問すべてで C2 の順位が C1 と同じなら支持。constraints を持つのは q12（金曜3限）だけで、これは unclear に入る。
- H7（生成で DB に無いコードを作らない）: 生成した40回の未検証コード数の合計が0で、候補外の引用の合計も0なら支持。片方なら一部支持。
  あわせて C1 と C2（同じ候補）で cited_codes の集合が一致する質問数を、LLM の揺れの目安として出す。

判定は `eval/retrieval_metrics.py` の関数で機械的に行う。必要な実行が欠けたら「判定不能」とする。

## 7. 実行手順と予算

1. 事前登録（この文書）をコミットする。
2. ハーネスと純関数のテストを追加してコミットする。
3. 実験用 DB を立て、dev からシードの20行をコピーし、DDL を流す。Neo4j に全文検索インデックスを作る。
4. QuerySpec を作ってコミットする（API を使わない）。
5. 文書の埋め込みを作る（20件を1回の呼び出しで）。長さ 1536 とノルムを確かめる。
6. 質問の埋め込みを作る（14問、1問1回）。
7. 検索を全14問×4条件で流す（API を使わない。H0 を確かめる）。H0 を満たさなければここで止める。
8. 煙テスト: q01・C1 で生成を1回流し、計測と抽出が動くことを確かめる。結果は集計に使わずコミットしない。
9. 本実行の生成（検索系10問×4条件、40回）。
10. 集計とサマリーの生成。

予算と打ち切り:

- このタスク全体で LLM の生成リクエストは150回、埋め込みリクエストは100回が上限。想定は生成 41回、埋め込み 15回。
  上限に達したら次のリクエストを送る前に止め、その実行を失敗（budget_exhausted）として記録して全体を打ち切る。
- 1回の生成で LLM リクエストは3回まで（想定は1回）。超えたらその実行を失敗として記録して次へ進む。
- 1回の生成のタイムアウトは120秒。
- 429 / 503 が返ったら30秒×試行回数だけ待ってやり直す（最大3回）。やり直した回数と理由を記録する。

## 8. 出力

- `results/2026-10-13_retrieval_seed.jsonl`: 1行1レコード。kind=retrieval（条件×質問、順位・スコア・evidence・指標・所要時間・DB クエリ数）と
  kind=generation（条件×質問、回答文・cited_codes・未検証コード・指標・トークン・所要時間）。
- `results/2026-10-13_retrieval_seed_manifest.json`: git SHA、マージしたブランチ、コーパスのスナップショットのハッシュ、
  埋め込みモデル・次元・正規化・接頭辞、LLM モデルと model_version、指示文のハッシュ、K・m・RRF の k、
  厳密検索の確認結果、全文検索インデックスの設定、リクエスト数、ライブラリのバージョン、開始・終了時刻。
- `results/2026-10-13_retrieval_seed_summary.md`: 条件別の表、質問別の表、unclear の表、仮説の判定、逸脱。

## 9. 駒澤に差し替えるときに変えるもの

コーパスの読み込み（`eval/corpus.py`）、質問ファイルと QuerySpec の作り方（シードの intent_rules は
`seed/courses.json` の辞書照合なので、駒澤の科目名の辞書に差し替えるか、別の解決方法を事前登録する）、
正解（段階付きの関連度ラベル）、表名。検索条件・採点・manifest はそのまま使う。駒澤は前提関係とトピックが無いので、
前提違反の指標と topic の展開は使えない。

## 10. 事前に分かっている限界

- golden は静的探索（= C3 の anchor ありの経路）の出力に合わせて作られている。C3 が満点に近いのは設計上の前提で、
  方式の優劣の証拠にはならない。H1・H2・H4 の判定はこの偏りの中での結果として読む。
- シードは20科目、1科目の本文は平均約87字の1文。ベクトル側が使える情報が少ない。
- q02（GMS-201）・q06（GMS-401）は科目コードで尋ねる問いで、文書に科目コードを入れないので C1・C2 は
  コードを手がかりにできない。C3 は spec の anchor（辞書照合でコードを解決済み）を使える。
- 起点科目の除去と direction は spec（intent_rules）から来るので、C1・C2 も intent_rules の解決結果を一部
  使っている（起点の除去のみ）。C4 の入口はベクトル側だけで決める。
- 1回ずつの実行で、検索は決定的だが生成は揺れる。埋め込みモデルの1536次元は暫定。
- 所要時間はローカルの Docker（Windows ホスト）での値で、規模の違う駒澤には外挿できない。
