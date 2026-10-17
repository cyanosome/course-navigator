# 検索方式比較（シード）の結果サマリー

`python -m eval.retrieval_compare summarize` が生成した。事前登録は `eval/prereg_retrieval_seed.md`。
シードの golden は静的探索の出力に合わせて作られているので、C3 が満点に近いのは設計上の前提で、方式の優劣の証拠にはならない。

## 実行条件

- 検索の run_id: 20261013T103324Z（git 067fdc22b4f940d93760b5efd8a40531aa923f9e、作業ツリー clean=True、ソースの指紋 77 ファイル a3c25f785413a4a3…）。マージ: origin/test/vector-graph-eval @ 9766c06
- コーパス: PostgreSQL 20 行（sha256 73f5e455e421511a…）、seed/courses.json（842408505adffcfe…）、Neo4j {'nodes': 20, 'prereqs': 19, 'topics': 36}（f3859a79fb814d96…、5.26.27）
- 実験用 DB: PostgreSQL 18.6 (Debian 18.6-1.pgdg12+2) on x86_64-pc-linux-gnu, compiled by gcc (Debian 12.2.0-14+deb12u1) 12.2.0, 64-bit、pgvector 0.8.7。厳密検索の確認: enable_indexscan=['off', 'off']、HNSW 使用=False、計画ノード ['Hash', 'Hash Join', 'Limit', 'Seq Scan', 'Sort']
- 埋め込み: gemini-embedding-2、1536 次元、API の自動正規化（文書どおり）＋保存前に L2 正規化。質問 `task: search result | query: {content}`、文書 `title: {title} | text: {content}`
- パラメータ: K=[5, 10]（主は 5）、取得件数 11、繰り返し 5 回、hybrid の入口 m=3、RRF k=60、全文検索 eval_course_topic_fulltext（cjk）
- 生成: モデル ['gemini-3.8-flash']、応答の model_version ['gemini-3.8-flash']、生成設定は API 既定値
- リクエスト数（manifest の全セッション、煙テストを含む）: LLM 40 / 50、埋め込み 15 / 60

## 検索（検索系10問）

| 条件 | Recall@5 | NDCG@5 | Recall@10 | NDCG@10 | forbidden@5（問） | 返却件数@5 平均 | 所要時間 中央値 ms | DB クエリ数 平均 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C1 pure_vector | 0.70 | 0.60 | 0.88 | 0.68 | 7（7） | 5.0 | 5.7 | 1.0 |
| C2 vector_metadata | 0.70 | 0.60 | 0.88 | 0.68 | 7（7） | 5.0 | 6.2 | 1.0 |
| C3 pure_graph | 0.98 | 1.00 | 1.00 | 1.00 | 0（0） | 3.4 | 16.5 | 1.0 |
| C4 hybrid | 0.90 | 0.88 | 1.00 | 0.93 | 4（4） | 5.0 | 45.5 | 4.0 |
| 参考: ランダム（解析解） | 0.26 | 0.23 | 0.53 | 0.35 | — | 5.0 | — | — |

列の意味: Recall@K は期待科目のうち上位 K 件に入った割合、NDCG@K は期待科目が上位に来るほど高い順位の質（1が最良）。どちらも起点科目を除いた順位で測り、10問の平均。forbidden@5 は出してはいけない科目が上位5件に入った件数の合計（括弧は該当した質問数）。返却件数は上位5件に実際に入った件数（グラフは5件に満たないことがある）。所要時間は各問5回の中央値をさらに10問で中央値にしたもので、質問の埋め込みを作る時間は含まない。K=10 は記述のみ（20科目では差が縮む）。

### 問いの種類別（@5 の平均）

| 条件 | 向きあり7問 Recall@5 | 向きあり NDCG@5 | topic3問 Recall@5 | topic NDCG@5 | next_step4問 前提違反@5 合計 | 前提違反率 平均 | 履修済みの推薦 合計 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C1 pure_vector | 0.68 | 0.60 | 0.76 | 0.58 | 7 | 0.35 | 5 |
| C2 vector_metadata | 0.68 | 0.60 | 0.76 | 0.58 | 7 | 0.35 | 5 |
| C3 pure_graph | 0.98 | 1.00 | 1.00 | 1.00 | 10 | 0.78 | 0 |
| C4 hybrid | 0.89 | 0.91 | 0.93 | 0.82 | 13 | 0.65 | 2 |

前提違反@5: next_step の問いで、起点科目とその前提科目をすべて履修済みとみなしたとき、上位5件のうち直接の前提科目に未履修のものがある科目の数。違反率はそれを返却件数で割ったもの。履修済みの推薦は、履修済みとみなした科目（起点を除く）を推薦してしまった数。

### 条件の対比較（事前登録 §6 の「差あり」の基準）

| 問い | 比較 | 指標 | 問数 | 平均差 | 符号カウント | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| 向きあり | pure_graph − pure_vector | recall@5 | 7 | 0.30 | +4 | 差あり |
| 向きあり | pure_graph − pure_vector | ndcg@5 | 7 | 0.40 | +6 | 差あり |
| 向きあり | hybrid − pure_vector | recall@5 | 7 | 0.21 | +2 | 差は小さい |
| 向きあり | hybrid − pure_vector | ndcg@5 | 7 | 0.30 | +4 | 差あり |
| 向きあり | hybrid − pure_graph | recall@5 | 7 | -0.09 | -1 | 差なし |
| 向きあり | hybrid − pure_graph | ndcg@5 | 7 | -0.09 | -1 | 差なし |
| 向きあり | vector_metadata − pure_vector | recall@5 | 7 | 0.00 | +0 | 差なし |
| 向きあり | vector_metadata − pure_vector | ndcg@5 | 7 | 0.00 | +0 | 差なし |
| topic | pure_graph − pure_vector | recall@5 | 3 | 0.24 | +2 | 差は小さい |
| topic | pure_graph − pure_vector | ndcg@5 | 3 | 0.42 | +3 | 差あり |
| topic | hybrid − pure_vector | recall@5 | 3 | 0.18 | +2 | 差は小さい |
| topic | hybrid − pure_vector | ndcg@5 | 3 | 0.24 | +3 | 差あり |
| topic | hybrid − pure_graph | recall@5 | 3 | -0.07 | -1 | 差なし |
| topic | hybrid − pure_graph | ndcg@5 | 3 | -0.18 | -3 | 差あり |
| topic | vector_metadata − pure_vector | recall@5 | 3 | 0.00 | +0 | 差なし |
| topic | vector_metadata − pure_vector | ndcg@5 | 3 | 0.00 | +0 | 差なし |
| 検索系すべて | pure_graph − pure_vector | recall@5 | 10 | 0.28 | +6 | 差あり |
| 検索系すべて | pure_graph − pure_vector | ndcg@5 | 10 | 0.40 | +9 | 差あり |
| 検索系すべて | hybrid − pure_vector | recall@5 | 10 | 0.20 | +4 | 差あり |
| 検索系すべて | hybrid − pure_vector | ndcg@5 | 10 | 0.28 | +7 | 差あり |
| 検索系すべて | hybrid − pure_graph | recall@5 | 10 | -0.08 | -2 | 差なし |
| 検索系すべて | hybrid − pure_graph | ndcg@5 | 10 | -0.12 | -4 | 差あり |
| 検索系すべて | vector_metadata − pure_vector | recall@5 | 10 | 0.00 | +0 | 差なし |
| 検索系すべて | vector_metadata − pure_vector | ndcg@5 | 10 | 0.00 | +0 | 差なし |

コスト（検索系10問、比が1.5倍以上で「差あり」）:

| 比 | 所要時間の比 | 判定 | DB クエリ数の比 | 判定 |
| --- | --- | --- | --- | --- |
| vector_metadata / pure_vector | 1.07 | 差なし | 1.00 | 差なし |
| pure_graph / pure_vector | 2.87 | 差あり | 1.00 | 差なし |
| hybrid / pure_vector | 7.93 | 差あり | 4.00 | 差あり |

## 質問別（検索系、@5）

| 質問 | mode | 期待科目 E | C1 pure_vector R/N・上位5件 | C2 vector_metadata R/N・上位5件 | C3 pure_graph R/N・上位5件 | C4 hybrid R/N・上位5件 |
| --- | --- | --- | --- | --- | --- | --- |
| q01 | next_step | GMS-303 GMS-401 | 0.50/0.61 GMS-401 GMS-201 GMS-203 GMS-102 GMS-302 | 0.50/0.61 GMS-401 GMS-201 GMS-203 GMS-102 GMS-302 | 1.00/1.00 GMS-303 GMS-401 | 1.00/1.00 GMS-401 GMS-303 GMS-302 GMS-201 GMS-203 |
| q02 | next_step | GMS-301 GMS-302 GMS-303 GMS-401 GMS-402 | 0.20/0.34 GMS-302 GMS-101 GMS-102 GMS-104 GMS-306 | 0.20/0.34 GMS-302 GMS-101 GMS-102 GMS-104 GMS-306 | 1.00/1.00 GMS-301 GMS-302 GMS-303 GMS-401 GMS-402 | 1.00/1.00 GMS-301 GMS-302 GMS-402 GMS-303 GMS-401 |
| q03 | next_step | GMS-301 GMS-302 GMS-303 GMS-401 GMS-402 | 0.40/0.55 GMS-301 GMS-302 GMS-102 GMS-205 GMS-403 | 0.40/0.55 GMS-301 GMS-302 GMS-102 GMS-205 GMS-403 | 1.00/1.00 GMS-301 GMS-302 GMS-303 GMS-401 GMS-402 | 1.00/1.00 GMS-301 GMS-303 GMS-302 GMS-402 GMS-401 |
| q04 | next_step | GMS-303 | 1.00/0.39 GMS-102 GMS-302 GMS-203 GMS-301 GMS-303 | 1.00/0.39 GMS-102 GMS-302 GMS-203 GMS-301 GMS-303 | 1.00/1.00 GMS-303 | 1.00/1.00 GMS-303 GMS-203 GMS-301 GMS-401 GMS-402 |
| q05 | prereq | GMS-101 GMS-102 GMS-201 GMS-202 GMS-203 GMS-301 | 0.83/1.00 GMS-202 GMS-102 GMS-201 GMS-203 GMS-301 | 0.83/1.00 GMS-202 GMS-102 GMS-201 GMS-203 GMS-301 | 0.83/1.00 GMS-101 GMS-102 GMS-201 GMS-203 GMS-202 | 0.83/1.00 GMS-102 GMS-202 GMS-201 GMS-101 GMS-203 |
| q06 | prereq | GMS-101 GMS-102 GMS-201 GMS-203 GMS-301 | 0.80/0.79 GMS-101 GMS-306 GMS-102 GMS-301 GMS-201 | 0.80/0.79 GMS-101 GMS-306 GMS-102 GMS-301 GMS-201 | 1.00/1.00 GMS-101 GMS-102 GMS-201 GMS-203 GMS-301 | 0.40/0.35 GMS-206 GMS-101 GMS-103 GMS-306 GMS-102 |
| q07 | prereq | GMS-101 GMS-201 | 1.00/0.54 GMS-402 GMS-102 GMS-101 GMS-203 GMS-201 | 1.00/0.54 GMS-402 GMS-102 GMS-101 GMS-203 GMS-201 | 1.00/1.00 GMS-101 GMS-201 | 1.00/1.00 GMS-101 GMS-201 GMS-402 GMS-102 GMS-203 |
| q08 | topic | GMS-201 GMS-301 GMS-402 | 0.67/0.70 GMS-402 GMS-102 GMS-201 GMS-101 GMS-401 | 0.67/0.70 GMS-402 GMS-102 GMS-201 GMS-101 GMS-401 | 1.00/1.00 GMS-201 GMS-301 GMS-402 | 1.00/0.97 GMS-201 GMS-402 GMS-203 GMS-301 GMS-202 |
| q09 | topic | GMS-102 GMS-202 GMS-301 GMS-303 GMS-401 | 0.60/0.65 GMS-102 GMS-101 GMS-401 GMS-301 GMS-201 | 0.60/0.65 GMS-102 GMS-101 GMS-401 GMS-301 GMS-201 | 1.00/1.00 GMS-303 GMS-102 GMS-202 GMS-301 GMS-401 | 0.80/0.85 GMS-202 GMS-303 GMS-102 GMS-201 GMS-301 |
| q10 | topic | GMS-302 | 1.00/0.39 GMS-101 GMS-104 GMS-201 GMS-206 GMS-302 | 1.00/0.39 GMS-101 GMS-104 GMS-201 GMS-206 GMS-302 | 1.00/1.00 GMS-302 | 1.00/0.63 GMS-201 GMS-302 GMS-305 GMS-205 GMS-101 |

R/N は Recall@5 / NDCG@5。上位5件は起点科目を除いた順位。

## unclear の4問（記述のみ。正解の順位は無い）

| 質問 | 質問文 | constraints | C1 pure_vector | C2 vector_metadata | C3 pure_graph | C4 hybrid |
| --- | --- | --- | --- | --- | --- | --- |
| q11 | 何かおすすめの授業ある? | — | 5件 GMS-102 GMS-104 GMS-201 GMS-101 GMS-305 | 5件 GMS-102 GMS-104 GMS-201 GMS-101 GMS-305 | 0件  | 5件 GMS-102 GMS-104 GMS-201 GMS-101 GMS-305 |
| q12 | 金曜3限に空いてる授業は? | {'day': '金', 'period': 3} | 5件 GMS-101 GMS-201 GMS-205 GMS-401 GMS-402 | 1件 GMS-205 | 0件  | 5件 GMS-101 GMS-201 GMS-205 GMS-401 GMS-402 |
| q13 | この授業難しい? | — | 5件 GMS-302 GMS-102 GMS-201 GMS-303 GMS-101 | 5件 GMS-302 GMS-102 GMS-201 GMS-303 GMS-101 | 0件  | 5件 GMS-302 GMS-102 GMS-201 GMS-303 GMS-101 |
| q14 | データサイエンスの次は? | — | 5件 GMS-301 GMS-401 GMS-303 GMS-202 GMS-102 | 5件 GMS-301 GMS-401 GMS-303 GMS-202 GMS-102 | 5件 GMS-301 GMS-401 GMS-302 GMS-203 GMS-303 | 5件 GMS-301 GMS-401 GMS-303 GMS-202 GMS-102 |

静的 DAG はこの4問で候補を出さないのが期待動作（聞き返す）。検索部だけを比べるこの実験では、どの条件も「聞き返す」判断を持たないので、返した件数と中身をそのまま記録する。

## 生成（検索系10問×4条件、上位5件から LLM 1回）

| 条件 | 成功 | 未検証コード 合計 | 候補外の引用 合計 | うち根拠文に現れるコード | recall 平均 | precision 平均 | forbidden 合計 | LLM 回数 平均 | 入力トークン 平均 | 出力トークン 平均 | 所要時間 中央値 s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C1 pure_vector | 10/10 | 0 | 0 | 0 | 0.70 | 0.44 | 7 | 1.0 | 538 | 258 | 7.1 |
| C2 vector_metadata | 10/10 | 0 | 0 | 0 | 0.70 | 0.44 | 7 | 1.0 | 538 | 263 | 8.6 |
| C3 pure_graph | 10/10 | 0 | 1 | 1 | 1.00 | 1.00 | 0 | 1.0 | 535 | 264 | 7.6 |
| C4 hybrid | 10/10 | 0 | 6 | 6 | 0.92 | 0.62 | 6 | 1.0 | 772 | 391 | 10.1 |

列の意味: 未検証コードは、回答が引用したコードのうち PostgreSQL に行が無いもの（存在しない科目）。候補外の引用は、起点以外で LLM に渡した5件に無いコードを引用した数。そのうち、渡した5件の根拠文（前提関係の経路の表記や入口科目の名前）に現れるコードの数を隣の列に出す（指示文の規則1は根拠文の内容を使うことを認めている）。recall / precision は引用（起点を除く）を golden の期待科目と突き合わせたもの。

## 事前登録に照らした判定

| 仮説 | 判定 | 根拠 |
| --- | --- | --- |
| H0 妥当性（spec が golden と一致し、pure_graph の Recall@10 が1） | 支持 | spec 不一致 なし、Recall@10<1 なし |
| H1 向きのある問いで pure_graph > pure_vector | 支持 | pure_graph − pure_vector: recall@5 差 +0.30・符号 +4（差あり）、ndcg@5 差 +0.40・符号 +6（差あり） |
| H2 向きのある問いで hybrid > pure_vector | 一部支持 | hybrid − pure_vector: recall@5 差 +0.21・符号 +2（差は小さい）、ndcg@5 差 +0.30・符号 +4（差あり） |
| H3 トピックの問いで pure_vector も戦える（NDCG@5 が pure_graph − 0.10 以上） | 不支持 | pure_vector 0.58、pure_graph 1.00（3問） |
| H4 hybrid は pure_vector・pure_graph のどちらにも NDCG@5 で「差あり」で劣らない | 不支持 | 対 pure_vector 差 +0.28・符号 +7（差あり）、対 pure_graph 差 -0.12・符号 -4（差あり） |
| H5 next_step の前提違反@5 の合計で pure_graph・hybrid が pure_vector より2件以上少ない | 不支持 | 違反の合計: pure_vector 7、pure_graph 10、hybrid 13（4問） |
| H6 制約の無い検索系10問で vector_metadata の順位が pure_vector と同じ | 支持 | 順位が違う質問: なし |
| H7 生成で DB に無いコードも候補外のコードも引用しない | 一部支持 | 未検証コードの合計 0、候補外の引用の合計 7（40 回）。同じ候補を渡した pure_vector と vector_metadata で引用集合が一致した質問 10/10 |

## 事前登録からの逸脱

- §3.4 の厳密検索の設定は、接続ごとの SET ではなく接続の起動パラメータ（server_settings）で enable_indexscan = off を渡した。asyncpg のプールは接続を返すたびに RESET ALL を流すので、SET だと2回目以降の取得で設定が消え、HNSW を使う計画になることを実行前の EXPLAIN の確認で見つけたため。効果（セッション単位でインデックス走査を使わない）は登録どおりで、検索結果を記録する前に直した。
