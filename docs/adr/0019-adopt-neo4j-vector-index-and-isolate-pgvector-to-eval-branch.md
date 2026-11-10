# [ADR-0019] 本番検索における Neo4j Vector Index 採用と pgvector 実験ブランチ分離方針

- **ステータス**: 承認済 (Accepted)
- **起票日**: 2026-11-02
- **決定者 / 議論の場**: cyanosome
- **関連リンク**: [ADR-0002](0002-use-polyglot-persistence-postgres-and-neo4j.md), [ADR-0018](0018-neo4j-cypher-three-mode-search-engine-and-api-contract.md), ブランチ `test/vector-graph-eval`,

---

## 1. 背景と課題 (Context & Problem Statement)

- 本プロジェクトは、メタデータ・整合性管理用の PostgreSQL と、リレーション・DAG走査用の Neo4j による Polyglot Persistence（複合DB）構成を採用している（[ADR-0002](0002-use-polyglot-persistence-postgres-and-neo4j.md)）。
- シラバスの自然言語検索を行うため、シラバステキストの Embedding ベクトル（Gemini 768次元 / OpenAI 1536次元）を永続化し、近似最近傍探索（ANN）を行うインフラが必要となった。
- ベクトル検索エンジンとして、PostgreSQL の拡張機能である `pgvector`（HNSWインデックス）と、Neo4j 5+ に標準統合された `Neo4j Vector Index` の2つの選択肢が存在した。
- 両方のDBにベクトルを格納して並行運用すると、データ更新パイプラインの重複、ストレージ使用量の増加、同期処理の実装コストが生じる。本番サービスおよび学術論文の比較実験において、両者の役割分担を決定する必要があった。

## 2. 決定の判断基準 (Decision Drivers)

- **GraphRAG パイプラインとの結合度**: ベクトル検索で特定したノードから前提条件DAGや履修系統図を単一クエリで展開できること。
- **アーキテクチャの単純性と運用性**: 本番環境でのコンテナ間通信、接続プール管理、スキーママイグレーションの対象コンポーネントを限定すること。
- **実験の学術的独立性**: DBS論文における「Pure Vector（pgvector） vs Pure Graph（Neo4j） vs Hybrid（Neo4j）」の比較実験を、本番コードベースに実験用コードを混入させることなく再現できること。

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A (採用案)**: **本番アプリケーションは Neo4j Vector Index に一本化し、pgvector は比較実験専用ブランチに分離**
   - 本番の `main` ブランチでは、シラバス Embedding を Neo4j の `Course.embedding` プロパティに格納し、`course_embedding_index`（コサイン類似度）を利用。
   - pgvector による Pure Vector 探索は、比較実験専用ブランチ（`test/vector-graph-eval`）に独立して実装・測定。
2. **選択肢 B**: **PostgreSQL (pgvector) を全ベクトル検索の単一基盤とする**
   - ベクトル検索はすべて PostgreSQL で行い、得られたコースIDを Neo4j に渡してグラフを展開する。
3. **選択肢 C**: **Postgres (pgvector) と Neo4j Vector Index のデュアル同期運用**
   - 両方のDBに常に Embedding を二重書き込みし、ユースケースに応じて呼び分ける。

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 A: 本番アプリケーションは Neo4j Vector Index に一本化し、pgvector は比較実験専用ブランチに分離**

### 選定理由

- **プロセス内でのグラフ結合**: Neo4j 内蔵の Vector Index を用いることで、Cypher クエリ内で `CALL db.index.vector.queryNodes('course_embedding_index', 10, $embedding)` を直接呼び出し、ノードのトポロジー（前提関係やグループ）へ展開できる。Postgres ⇄ Neo4j 間の外部ネットワーク通信やIDマッピング処理が発生しない。
- **データパイプラインの単一責任**: Ingestion 時に Embedding を Neo4j にのみ永続化すればよいため、ベクトルデータの二重管理およびトランザクション同期処理の実装が不要となる。
- **実験コードベースの隔離**: 学術実験用の pgvector 比較コード（SQLによるHNSW検索やベンチマーク測定スクリプト）を本番ブランチから切り離すことで、本番環境への専用C拡張の常駐や追加依存パッケージの混入を防止できる。

## 5. 各選択肢の評価 (Pros & Cons)

### 選択肢 A: 本番は Neo4j Vector Index 一本化、pgvector は実験ブランチ分離（採用案）

- **メリット (+)**:
  - 単一Cypherでベクトル検索とグラフ推論が完結し、低レイテンシで実行可能。
  - 本番 Docker Compose の構成がシンプルに保たれる（Postgres コンテナに pgvector C拡張を常駐させる必要がない）。
  - 実験用ブランチで独立して pgvector のパラメータチューニング（`m`, `ef_construction`）が可能。
- **デメリット・受容するリスク (-)**:
  - Neo4j の Vector Index は Lucene ベースの HNSW であり、数百万件規模では pgvector の方がメモリ効率で勝る場合がある（現在の大学カリキュラム規模である 1,000〜10,000件ではメモリ内に十分収まる）。

### 選択肢 B: pgvector を全ベクトル検索の単一基盤とする（見送り案）

- **メリット (+)**:
  - リレーショナルデータとベクトルデータをPostgres内で一元管理できる。
- **デメリット・見送り理由 (-)**:
  - グラフ走査を行うたびに「Postgresで検索 ➔ 得られたID群をNeo4jへ送信 ➔ グラフ走査」という2段階通信が必要となり、レイテンシが増加する。

### 選択肢 C: デュアル同期運用（見送り案）

- **メリット (+)**:
  - 双方のDBからベクトル検索が可能。
- **デメリット・見送り理由 (-)**:
  - Ingestion ローダーの二重化、データ整合性維持の実装コスト、ストレージ消費の増加が生じる。

## 6. 影響と結果 (Consequences)

- **良い影響 (Positive)**:
  - `ingestion/src/loaders/graph/vector_index_loader.py` により、Neo4j 上にコサイン類似度インデックス（768次元 / `course_embedding_index`）が決定論的に構築される基盤が完成した。
  - 本番バックエンドは Neo4j ドライバのみでハイブリッド検索（Mode C）を低遅延で実行できるようになった。
  - DBS論文の比較実験（実験3-5）は `test/vector-graph-eval` ブランチで同一のEmbeddingデータを用いて比較検証が行われた。
- **留意点・トレードオフ (Negative / Neutral)**:
  - 数十万件規模への全学展開を行う際は、Neo4j の Java Heap および Pagecache のメモリ割り当ての再評価が必要となる。
- **次のアクション (Next Actions)**:
  - 本番用 Docker Compose では標準の `postgres:16-alpine` を維持。
  - 類似度エッジ構築（[ADR-0023](0023-numpy-cosine-similarity-matrix-and-persistent-similar-to-edges.md)）と連携して Neo4j 内のグラフ構造を構築。

---

## 7. 参考資料 (References)

- Neo4j Vector Index Official Docs: Indexes for vector search
- pgvector GitHub: Open-source vector similarity search for Postgres
- [ADR-0002: PostgreSQL と Neo4j による Polyglot Persistence 構成の採用](0002-use-polyglot-persistence-postgres-and-neo4j.md)
