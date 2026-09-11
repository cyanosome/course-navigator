# [ADR-0002] PostgreSQL と Neo4j による Polyglot Persistence（複合DB）構成の採用

- **ステータス**: 承認済 (Accepted)
- **起票日**: 2026-06-20
- **決定者 / 議論の場**: yuto (@cyanosome)
- **関連リンク**: Commit `f55eaf1`, Commit `430aec6`, Commit `9bebe27`, `db/compose.yaml`, `docs/architecture.md`

---

## 1. 背景と課題 (Context & Problem Statement)

- **チーム結成前の汎用的なインフラ基盤の整備**
  - 本プロジェクトの初期構想時（開発メンバーが集まる前段）において、今後参加するメンバーが多様なデータ構造や RAG（Retrieval-Augmented Generation）のアプローチを柔軟に試行・受容できるインフラ環境をあらかじめ整えておく必要があった。
- **Web システム要件と履修支援 RAG 要件の二面性**
  - Web アプリケーションとして、ユーザー認証、履修登録履歴、各種メタデータの整合性管理、テキストのあいまい検索など、リレーショナルデータベース（RDB）が最も得意とする領域は確実に存在する。
  - 一方で、本研究のコアである「履修支援 AI」においては、単なるテキストの全文検索にとどまらず、**科目間の前提条件チェーン、履修系統図のトポロジー、学問分野の階層構造を探索できるデータ構造** が不可欠であると考えた。
- **インフラ段階での柔軟性の担保**
  - 最終的なデータ構造や検索アルゴリズムの詳細は開発を進めながら決定する方針であったため、インフラの構築段階では特定の単一技術に縛られず、十分な表現力と汎用性を備えたデータベース層を用意することが求められた。

---

## 2. 決定の判断基準 (Decision Drivers)

- **グラフ構造の表現力**: 前提科目ツリーやカリキュラムマップの多段探索を直感的・高速に実行できること。
- **RAG / ベクトル検索の受容性**: 単語検索だけでなく、意味類似度検索や GraphRAG にスムーズに対応できること。
- **Web システムとしての基本堅牢性**: ユーザー情報や履修トランザクションを ACID 特性のもとで安全に管理できること。
- **コンテナ運用の複雑性とリソース負荷**: 開発者個人のローカル PC（Docker）で無理なく稼働し、保守が破綻しない構成であること。

---

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A: PostgreSQL のみ（RDB 単一構成）**
   - すべてのデータ（ユーザー、シラバス、前提条件）を PostgreSQL のテーブルおよび再帰的クエリ（`WITH RECURSIVE`）で管理する。
2. **選択肢 B: PostgreSQL + 専用 VectorDB (Chroma 等) + GraphDB (Neo4j) の 3 DB 構成**
   - バックエンド言語が Python に内定していたため、軽量な VectorDB（Chroma など）を追加し、RDB・Vector・Graph の 3 コンテナを個別に立ち上げて併用する。
3. **選択肢 C: PostgreSQL + Neo4j (APOC プラグイン導入) の 2 DB 複合構成 【採用】**
   - 整合性とトランザクションを担う PostgreSQL と、関係性探索およびベクトル検索を兼ね備える Neo4j の 2 つを採用し、Polyglot Persistence（用途特化型永続化）を実現する。

---

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 C: PostgreSQL と Neo4j による 2 DB 複合構成**

### 選定理由

1. **RDB 単一構成（選択肢 A）の限界回避**:
   - PostgreSQL でも隣接リストモデル等でグラフを模倣できるが、前提条件が複雑に分岐・合流する履修系統図の多段探索や、学問分野オントロジーの横断検索を SQL で記述・保守するのは認知負荷が高く、パフォーマンス・表現力の面で限界が生じると判断した。
2. **3 DB 構成（選択肢 B）のオーバーヘッド排除**:
   - Chroma 等の独立した VectorDB を導入すると、コンテナ数が増加してローカル PC のメモリ負荷が高まり、さらに 3 つの DB 間でデータの二重・三重の同期が必要となり保守性が悪化する。
   - Neo4j 5.x はネイティブで **Vector Index（ベクトル類似度検索）** をサポートしており、GraphDB 内部でナレッジグラフ探索とベクトル検索を一体化して処理できるため、独立した VectorDB を別途設ける必要性がないと判断した。
3. **役割の明確な分離（Polyglot Persistence の実現）**:
   - **PostgreSQL**: ユーザーアカウント、認証情報、履修履歴、構造化メタデータ（確実な整合性が求められるトランザクション）。
   - **Neo4j**: 科目間の前提関係（`REQUIRES`）、トピック包含（`COVERS_TOPIC`）、オントロジー、および GraphRAG 用の探索インデックス。
   - この明確な分担により、将来どのような要件や新メンバーが加わっても受容できる柔軟なインフラが完成した。

---

## 5. 各選択肢の評価 (Pros & Cons)

### 選択肢 A: PostgreSQL のみ

- **メリット (+)**:
  - 管理するコンテナが 1 つで済み、トランザクションが単一 DB 内で完結する。
- **デメリット・見送り理由 (-)**:
  - 深い階層の前提条件探索やパス検索が複雑化し、Cypher クエリのような直感的なグラフ操作ができない。

### 選択肢 B: PostgreSQL + VectorDB + Neo4j (3 DB)

- **メリット (+)**:
  - 各データモデルに完全に特化した専用ツールを揃えられる。
- **デメリット・見送り理由 (-)**:
  - インフラ構成が複雑化し、同期の不整合リスクが増大する。
  - Neo4j 単体でベクトル検索の要件を満たせるため、専用 VectorDB の追加は冗長。

### 選択肢 C: PostgreSQL + Neo4j (2 DB) 【採用案】

- **メリット (+)**:
  - グラフ探索の強力な表現力（Neo4j / Cypher）と、RDB の高い信頼性（PostgreSQL）を両立。
  - Neo4j 5.x の Vector Index と APOC プラグインにより、独立した VectorDB なしで高度な GraphRAG を実現可能。
  - 開発者のローカル Docker 環境でも軽快に動作する適切なコンポーネント規模。
- **デメリット・受容するリスク (-)**:
  - 2 つの DB を跨ぐデータの一貫性（整合性チェック・同期）をバックエンドのロジックで制御する必要がある。

---

## 6. 影響と結果 (Consequences)

- **良い影響 (Positive)**:
  - 将来的な「履修系統図のグラフ可視化」や「CS2023 オントロジー統合」に耐えうる強力なデータ表現基盤が初期から確保された。
  - `db/compose.yaml` として独立したスタックを構築でき、データ永続化ボリューム（`postgres_data`, `neo4j_data`）が安全に分離された。
- **留意点・トレードオフ (Negative / Neutral)**:
  - 科目コードや講義 ID など、両 DB で共有するキーの同期・整合性維持がアプリケーション側の責任となる。
- **次のアクション (Next Actions)**:
  - **ブランチ `test/db-communication` の実験実施**:
    - PostgreSQL と Neo4j の 2 つの DB に対する同時登録・検索における競合や整合性ハンドリングを検証する（コミット `9bebe27` にて、未登録の前提講義コードに対する自動プレースホルダー同期や、PostgreSQL あいまい検索 ＋ Neo4j 前提ツリー取得の複合シラバス疎通テスト `test3` として実装・検証完了）。

---

## 7. 参考資料 (References)

- [Neo4j Vector Index Official Documentation](https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/)
- [Neo4j APOC Core Documentation](https://neo4j.com/docs/apoc/current/)
- [PostgreSQL 18 Release Notes & Storage Configuration](https://www.postgresql.org/docs/)
- Martin Fowler: [Polyglot Persistence](https://martinfowler.com/bliki/PolyglotPersistence.html)
