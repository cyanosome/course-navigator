# 検索方式比較（シード）の再現実行の突き合わせ

`python -m eval.replication_compare` が生成した。事前登録は `eval/prereg_retrieval_seed_replication.md`。
元 = 元の実行（`2026-10-13_retrieval_seed.jsonl`）、R1 = 元の埋め込みのまま検索だけを流し直したもの、R2 = 新しいデータベースで setup-db から生成までをやり直したもの。

## 1. 出所

git の木: commit 067fdc22b4f940d93760b5efd8a40531aa923f9e、`git ls-tree --full-tree -r -z <commit> -- backend` から作った指紋 77 ファイル、sha256 a3c25f785413a4a3…

| 実行 | コマンド | run_id | 途中終了 | git_sha が commit と一致 | clean | ソースの指紋が git の木と一致 | 実験用 DB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R1 | retrieve | 20261013T103141Z | False | 一致 | True | 一致 | coursenavigator_eval |
| R2 | setup-db | 20261013T103214Z | False | 一致 | True | 一致 | coursenavigator_eval_replication |
| R2 | embed-docs | 20261013T103237Z | False | 一致 | True | 一致 | coursenavigator_eval_replication |
| R2 | embed-queries | 20261013T103252Z | False | 一致 | True | 一致 | coursenavigator_eval_replication |
| R2 | retrieve | 20261013T103324Z | False | 一致 | True | 一致 | coursenavigator_eval_replication |
| R2 | generate | 20261013T103355Z | False | 一致 | True | 一致 | coursenavigator_eval_replication |

列の意味: git_sha は実行時にホストで取った HEAD。clean はホストの `git status --porcelain` に、eval/results/ の未追跡の結果以外が無かったこと（あればハーネスが実行を拒む）。ソースの指紋は、コンテナから見えた backend 配下のファイル（隠しファイル・キャッシュ・logs/・eval/results/ を除く）の git blob SHA-1 の一覧の SHA-256 で、git の木から同じ規則で作った値と比べた。
元の実行のセッションには指紋が無い（git_sha は ['38016bca7c5985d5786986bb94f94db41cced7d2']、`code_commit` の注記のみ）。

## 2. スナップショット（manifest の値）

| 項目 | 元 | R1 は元と | R2 は元と |
| --- | --- | --- | --- |
| retrieve.corpus.postgres_rows_sha256 | 73f5e455e421511a… | 一致 | 一致 |
| retrieve.corpus.postgres_rows | 20 | 一致 | 一致 |
| retrieve.corpus.seed_courses_json_sha256 | 842408505adffcfe… | 一致 | 一致 |
| retrieve.corpus.neo4j_graph_sha256 | f3859a79fb814d96… | 一致 | 一致 |
| retrieve.corpus.neo4j_counts | {"nodes": 20, "p… | 一致 | 一致 |
| retrieve.corpus.neo4j_version | {"edition": "community", "v": "5.26.27"} | 一致 | 一致 |
| retrieve.corpus.postgres_version | PostgreSQL 18.6 … | 一致 | 一致 |
| retrieve.corpus.pgvector_version | 0.8.7 | 一致 | 一致 |
| retrieve.corpus.document_embeddings_sha256 | 7a54e8c21dc06285… | 一致 | 一致 |
| retrieve.corpus.query_embeddings_sha256 | 9da17baf66fd4d2d… | 一致 | 一致 |
| retrieve.specs_sha256 | 7a30d69f4d96b2ea… | 一致 | 一致 |
| retrieve.golden_sha256 | 019dddbbd357ea24… | 一致 | 一致 |
| retrieve.exact_search | {"enable_indexsc… | 一致 | 一致 |
| retrieve.embedding | {"dimensions": 1… | 一致 | 一致 |
| retrieve.params | {"fulltext_analy… | 一致 | 一致 |
| retrieve.python | 3.14.2 | 一致 | 一致 |
| retrieve.libraries | {"asyncpg": "0.3… | 一致 | 一致 |
| generate.model | gemini-3.8-flash | — | 一致 |
| generate.instruction_sha256 | f0fd50a8385bd686… | — | 一致 |
| generate.generation_top_k | 5 | — | 一致 |
| generate.per_run_llm_cap | 3 | — | 一致 |
| generate.timeout_seconds | 120 | — | 一致 |

「—」はその実行にその記録が無いこと（R1 は生成をしていない）。

## 3. 埋め込み（R2 対 元）

| 種類 | 本数 | ビット一致 | 要素の差の絶対値の最大 | コサイン類似度の最小 | 対応の取れないキー |
| --- | --- | --- | --- | --- | --- |
| 文書 | 20 | 20 | 0 | 1.000000000 | なし |
| 質問 | 14 | 14 | 0 | 1.000000000 | なし |

分類（§4.1）: **ビット一致**（ほぼ一致の閾値はコサイン類似度 0.9999）。
DB と manifest の対応: 元の DB の埋め込みのハッシュが元の manifest と 一致、R2 の DB が R2 の manifest と 一致。（ハッシュは retrieve が manifest に残すのと同じ式で、DB の中身が記録に使われたものと同じことを示す。）

## 4. 検索の順位（56行 = 14問×4条件）

| 比較 | 条件 | 行 | 順位リスト一致 | 指標一致 | evidence 一致 | クエリ数一致 | スコアの差の最大 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R1 対 元 | pure_vector | 14 | 14 | 14 | 14 | 14 | 0 |
| R1 対 元 | vector_metadata | 14 | 14 | 14 | 14 | 14 | 0 |
| R1 対 元 | pure_graph | 14 | 14 | 14 | 14 | 14 | 0 |
| R1 対 元 | hybrid | 14 | 14 | 14 | 14 | 14 | 0 |
| R1 対 元 | all | 56 | 56 | 56 | 56 | 56 | 0 |
| R2 対 元 | pure_vector | 14 | 14 | 14 | 14 | 14 | 0 |
| R2 対 元 | vector_metadata | 14 | 14 | 14 | 14 | 14 | 0 |
| R2 対 元 | pure_graph | 14 | 14 | 14 | 14 | 14 | 0 |
| R2 対 元 | hybrid | 14 | 14 | 14 | 14 | 14 | 0 |
| R2 対 元 | all | 56 | 56 | 56 | 56 | 56 | 0 |

列の意味: 順位リスト一致は、起点を除いた上位10件の科目コードの列が順序も含めて同じ行の数。指標一致は K=5・10 のRecall・NDCG・forbidden・前提違反などがすべて同じ行の数。evidence は LLM に渡す根拠文（C1・C2 は類似度を小数3桁で含む）。クエリ数一致は SQL・Cypher の本数と、起点を除く前の件数が同じ行の数。スコアの差は同じ科目コードどうしの差の絶対値の最大（C1・C2 はコサイン類似度、C3 はグラフ探索の値、C4 は RRF の値）。

## 5. 検索の指標（条件別。検索系10問の平均、forbidden は合計、前提違反は next_step 4問の合計）

| 条件 | 実行 | Recall@5 | NDCG@5 | Recall@10 | NDCG@10 | forbidden@5 | 前提違反@5 | 返却件数@5 | 所要時間 中央値 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pure_vector | original | 0.70 | 0.60 | 0.88 | 0.68 | 7 | 7 | 5.0 | 6.1 |
| pure_vector | R1 | 0.70 | 0.60 | 0.88 | 0.68 | 7 | 7 | 5.0 | 5.4 |
| pure_vector | R2 | 0.70 | 0.60 | 0.88 | 0.68 | 7 | 7 | 5.0 | 5.7 |
| vector_metadata | original | 0.70 | 0.60 | 0.88 | 0.68 | 7 | 7 | 5.0 | 5.9 |
| vector_metadata | R1 | 0.70 | 0.60 | 0.88 | 0.68 | 7 | 7 | 5.0 | 5.1 |
| vector_metadata | R2 | 0.70 | 0.60 | 0.88 | 0.68 | 7 | 7 | 5.0 | 6.2 |
| pure_graph | original | 0.98 | 1.00 | 1.00 | 1.00 | 0 | 10 | 3.4 | 29.9 |
| pure_graph | R1 | 0.98 | 1.00 | 1.00 | 1.00 | 0 | 10 | 3.4 | 15.4 |
| pure_graph | R2 | 0.98 | 1.00 | 1.00 | 1.00 | 0 | 10 | 3.4 | 16.5 |
| hybrid | original | 0.90 | 0.88 | 1.00 | 0.93 | 4 | 13 | 5.0 | 82.0 |
| hybrid | R1 | 0.90 | 0.88 | 1.00 | 0.93 | 4 | 13 | 5.0 | 59.7 |
| hybrid | R2 | 0.90 | 0.88 | 1.00 | 0.93 | 4 | 13 | 5.0 | 45.5 |

所要時間は環境で変わるので判定に使わない（記述のみ）。

## 6. 仮説の判定（元の登録 §6 を同じ関数で適用）

| 仮説 | 元 | R1 | R2 |
| --- | --- | --- | --- |
| H0 妥当性（spec が golden と一致し、pure_graph の Recall@10 が1） | 支持 | 支持 | 支持 |
| H1 向きのある問いで pure_graph > pure_vector | 支持 | 支持 | 支持 |
| H2 向きのある問いで hybrid > pure_vector | 一部支持 | 一部支持 | 一部支持 |
| H3 トピックの問いで pure_vector も戦える（NDCG@5 が pure_graph − 0.10 以上） | 不支持 | 不支持 | 不支持 |
| H4 hybrid は pure_vector・pure_graph のどちらにも NDCG@5 で「差あり」で劣らない | 不支持 | 不支持 | 不支持 |
| H5 next_step の前提違反@5 の合計で pure_graph・hybrid が pure_vector より2件以上少ない | 不支持 | 不支持 | 不支持 |
| H6 制約の無い検索系10問で vector_metadata の順位が pure_vector と同じ | 支持 | 支持 | 支持 |
| H7 生成で DB に無いコードも候補外のコードも引用しない | 一部支持 | 判定不能 | 一部支持 |

R1 は生成をしていないので H7 は「判定不能」になる。根拠の数値は JSON の verdicts にある。

## 7. 生成（検索系10問×4条件。元 / R2）

| 条件 | 実行 | 成功 | 未検証コード | 候補外の引用 | うち根拠文に現れる | recall | precision | forbidden | LLM 回数 | 入力トークン | 出力トークン | 所要時間 中央値 s | model_version |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pure_vector | original | 10/10 | 0 | 0 | 0 | 0.70 | 0.44 | 7 | 10 | 538 | 260 | 8.0 | gemini-3.8-flash |
| pure_vector | R2 | 10/10 | 0 | 0 | 0 | 0.70 | 0.44 | 7 | 10 | 538 | 258 | 7.1 | gemini-3.8-flash |
| vector_metadata | original | 10/10 | 0 | 0 | 0 | 0.70 | 0.44 | 7 | 10 | 538 | 260 | 7.0 | gemini-3.8-flash |
| vector_metadata | R2 | 10/10 | 0 | 0 | 0 | 0.70 | 0.44 | 7 | 10 | 538 | 263 | 8.6 | gemini-3.8-flash |
| pure_graph | original | 10/10 | 0 | 1 | 1 | 1.00 | 1.00 | 0 | 10 | 535 | 253 | 8.5 | gemini-3.8-flash |
| pure_graph | R2 | 10/10 | 0 | 1 | 1 | 1.00 | 1.00 | 0 | 10 | 535 | 264 | 7.6 | gemini-3.8-flash |
| hybrid | original | 10/10 | 0 | 10 | 10 | 0.92 | 0.52 | 8 | 10 | 772 | 432 | 11.2 | gemini-3.8-flash |
| hybrid | R2 | 10/10 | 0 | 6 | 6 | 0.92 | 0.62 | 6 | 10 | 772 | 391 | 10.1 | gemini-3.8-flash |

列の意味: 未検証コードは引用したコードのうち実験用 DB に行が無いもの。候補外の引用は、起点以外で LLM に渡した5件に無いコードの数。recall・precision・forbidden は起点を除いた引用を golden と突き合わせたもの（平均・合計）。LLM 回数はやり直しを含む合計。
起点を除いた引用の集合が元と R2 で一致した（質問, 条件）: 37/40。生成は同じ入力でも揺れるので記述のみ。

## 8. 予測の照合と結論（事前登録 §4.2・§4.3）

| 項目 | 結果 | 根拠 |
| --- | --- | --- |
| P1 R1 の56行が元と完全一致 | 成り立つ | 順位一致 56/56、スコアの差の最大 0 |
| P2 R2 のコーパス・QuerySpec・golden のハッシュが元と一致 | 成り立つ | retrieve.corpus.postgres_rows_sha256=一致, retrieve.corpus.seed_courses_json_sha256=一致, retrieve.corpus.neo4j_graph_sha256=一致, retrieve.specs_sha256=一致, retrieve.golden_sha256=一致 |
| P3 R2 の埋め込み（予測なし） | ビット一致 | 文書 20/20・質問 14/14 がビット一致 |
| P4 R2 の検索（C3 は無条件、残りは埋め込みがビット一致かほぼ一致のとき） | 成り立つ | C3 一致 14/14、全体の順位一致 56/56、H0〜H6 の判定 一致 |
| P5 R2 の生成で未検証コード0・候補外の引用はすべて根拠文に現れる | 成り立つ | 成功 40/40、未検証 0、候補外 7（うち根拠文 7） |
| 出所（R1・R2 の全セッションで HEAD・clean・指紋が git の木と一致） | 成り立つ | commit 067fdc22b4f940d93760b5efd8a40531aa923f9e |

- 元の検索の結果はコミット済みのコードで成り立つ: **成り立つ**（P1 と出所の照合）
- 元の結果は再現した: **成り立つ**（上に加えて、R2 の56行の順位リストが一致・H0〜H6 の判定が一致・P5）
