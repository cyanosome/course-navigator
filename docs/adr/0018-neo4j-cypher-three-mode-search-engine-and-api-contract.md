# [ADR-0018] Neo4j Cypher による3モード直交探索エンジンとAPIコントラクトの策定

- **ステータス**: 承認済 (Accepted)
- **起票日**: 2026-11-05
- **決定者 / 議論の場**: cyanosome
- **関連リンク**: PR #19, `dev/backend-for-cypher`, [ADR-0016](0016-neo4j-curriculum-dag-and-course-loader-architecture.md), [ADR-0017](0017-postgres-schema-and-verification-tool-for-course-ingestion.md),

---

## 1. 背景と課題 (Context & Problem Statement)

- 「Course Navigator」プロジェクトにおいて、履修相談支援AIの開発では、**「ユーザーの興味・関心に対する意味的適合性（Semantic Relevance: Vector探索）」** と **「履修年次・前提科目などのカリキュラム順序制約の充足（Topological Constraint: Graph走査）」** のトレードオフが存在する。
- 情報処理学会 DBS/IFAT/DE 合同研究会（2026年冬）への論文投稿にあたり、上記トレードオフを定量的に比較検証するため、直交する3つの探索方式（① トポロジー走査のみ、② 類似度ベクトル検索のみ、③ 両者を結合した提案ハイブリッド探索）を同一データセット（関西大学1,029科目）上で測定できるバックエンド検索基盤が必要となった。
- 加えて、フロントエンド（`/navi` UI）および LLM Agent（ADK / Cypherツール）からこれらの探索を低遅延で呼び出すための統一的な API コントラクトを確定させる必要があった。

## 2. 決定の判断基準 (Decision Drivers)

- **探索の直交性と比較条件の同一性**: 3つの探索モードが同一の基盤・スキーマ上で比較測定可能であること。
- **目標応答速度（P95 < 200ms）**: エージェントや対話UIが複数回の探索を行っても実時間対話が可能なレイテンシに収まること。
- **クエリの処理完結性**: ベクトル探索とグラフ多段走査を、アプリケーション層での複数回クエリ発行とマージを挟まず単一トランザクションで完結できること。
- **Agent / UI とのインターフェース統合**: フロントエンドの型定義（`DepartmentNaviResponse`）および ADK Agent のツール群（`cypher_tools.py`）から整合して呼び出せること。

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A (採用案)**: **Neo4j Cypher による 3モード統合実装 & 単一 FastAPI /navi エンドポイント**
   - Pure Graph（Mode A）、Similarity Vector（Mode B）、Proposed Hybrid（Mode C）の3方式をすべて Neo4j Cypher クエリとして記述。
   - ベクトル検索には Neo4j Vector Index（`course_embedding_index`）と `[:SIMILAR_TO]` エッジ走査を活用。
   - バックエンドに `CypherSearchRepository` を設置し、`/api/search/courses` および `/api/navi/departments/{id}` から呼び出す。
2. **選択肢 B**: **アプリケーション層（Python/FastAPI）での分割検索 & メモリ上マージ**
   - ベクトル類似度検索とグラフ前提条件探索を別々にCypherクエリとして発行し、Python層で結果の積集合・ソート・制約判定を行う。
3. **選択肢 C**: **DB分割方式（PostgreSQL/pgvector ＋ Neo4j）**
   - ベクトル検索は PostgreSQL（pgvector）にリクエストし、得られたコースID一覧を Neo4j に渡してグラフを展開する。

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 A: Neo4j Cypher による 3モード統合実装 & 単一 FastAPI /navi エンドポイント**

### 選定理由

- **単一クエリ内での実行**: Neo4j 5+ の Vector Index と Cypher パイプラインを組み合わせることで、ベクトル検索によるシード特定から前提ノードの展開（`[:PREREQUISITE_OF*0..2]`）や類似ノード走査（`[:SIMILAR_TO]`）までを、DBエンジン内部の単一トランザクションで実行できる。
- **直交実験の測定条件統一**:
  - **Mode A (Pure Graph)**: 履修系統図DAGの深さ・幅優先走査のみで関連科目を抽出（意味スコアを評価から除外）。
  - **Mode B (Similarity Vector)**: `course_embedding_index` によるコサイン類似度上位探索（グラフ構造制約を走査から除外）。
  - **Mode C (Proposed Hybrid)**: ベクトル類似度上位科目を起点とし、系統図DAGおよび `[:SIMILAR_TO]` を重み付け走査してサブグラフを抽出。
  - この3方式が同一のDB・同一のネットワーク境界内で完結するため、ネットワーク遅延の差異を生じさせずにベンチマークが可能となる。
- **選択肢 B を見送った理由**: DB ⇄ Backend 間のラウンドトリップが複数回発生し、P95レイテンシが増加するため。
- **選択肢 C を見送った理由**: 後述の [ADR-0019](0019-adopt-neo4j-vector-index-and-isolate-pgvector-to-eval-branch.md) に記載の通り、本番APIにおいて2つのデータストア間の同期と通信オーバーヘッドが生じるため（pgvector はオフライン比較実験ブランチへ分離）。

## 5. 各選択肢の評価 (Pros & Cons)

### 選択肢 A: Neo4j Cypher による 3モード統合実装（採用案）

- **メリット (+)**:
  - 単一の Bolt 接続・単一 Cypher で結果が返るため、P95 レイテンシが数十ミリ秒台で応答可能。
  - Cypher クエリの調整のみで検索ロジックの変更（しきい値調整、ペナルティ重み付け等）が可能。
  - Agent ツール（`agent/cypher_tools.py`）から単一関数呼び出しで実行可能。
- **デメリット・受容するリスク (-)**:
  - サブクエリやUNION、ベクトルインデックス呼び出しを含む Cypher クエリの記述が長くなるため、リポジトリ層でカプセル化して管理する必要がある。

### 選択肢 B: アプリケーション層での分割検索 & メモリ上マージ（見送り案）

- **メリット (+)**:
  - 個々の Cypher クエリの行数は短くなる。
- **デメリット・見送り理由 (-)**:
  - グラフ探索の深度が増すにつれて中間データの転送量が増加し、アプリケーション側のメモリ消費とレイテンシが増大する。

### 選択肢 C: DB分割方式（PostgreSQL/pgvector ＋ Neo4j）（見送り案）

- **メリット (+)**:
  - RDB 側で SQL によるベクトル検索が実行可能。
- **デメリット・見送り理由 (-)**:
  - 2つのDB接続プールの管理が必要となり、データ同期処理の実装およびネットワーク障害の発生箇所が増加する。

## 6. 影響と結果 (Consequences)

- **良い影響 (Positive)**:
  - `/api/search/courses` に対する探索モード指定（`mode: pure_graph | similarity | hybrid`）により、フロントエンド検証UI（`/test4-1`）および評価ハーネスから即時にモード切り替えテストが可能となった。
  - `/api/navi/departments/{id}` において、フロントエンドの `DepartmentNaviResponse` 仕様に合致する科目一覧・カテゴリ集約・DAGツリーデータの一括取得が可能となった。
  - LLM Agent が自然言語の要求に応じて「ハイブリッド探索」「ピュアグラフ探索」をツール経由で使い分けられるようになった。
- **留意点・トレードオフ (Negative / Neutral)**:
  - Neo4j 側のメモリ構成（Pagecache / Heap）のサイジングが検索性能に影響するため、Docker Compose 設定でリソースを明示的に指定する必要がある。
- **次のアクション (Next Actions)**:
  - `backend/src/course_core/repositories/cypher_search_repo.py` に3モードの Cypher クエリを配置。
  - `backend/tests/test_cypher_search.py` で単体テスト（8件）を実施し、CI へ組み込み。

---

## 7. 参考資料 (References)

- Neo4j 5+ Vector Search Documentation: `db.index.vector.queryNodes`
- 情報処理学会 DBS研究会 投稿原稿「大学カリキュラムにおける直交探索アブレーション実験」
