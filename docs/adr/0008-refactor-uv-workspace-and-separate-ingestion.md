# [ADR-0008] uv ワークスペース分割の試行とルート直下 Ingestion 分離への再編

- **ステータス**: 承認済 (Accepted)
- **起票日**: 2026-09-02
- **決定者 / 議論の場**: yuto (@cyanosome)
- **関連リンク**: Commit `728e762`, Commit `072fba0`, Commit `ff2850e`, `backend/Dockerfile`, `ingestion/`, `compose.yaml`

---

## 1. 背景と課題 (Context & Problem Statement)

- **初期の設計思想（Python / uv ワークスペース中心主義）**
  - プロジェクト初期（2026年8月中旬）において、Python 基準でシステムを動かすのであれば `uv` ワークスペース（Workspace）を活用してコードを共通化するのが最も効率的であると考えた。
  - アプリケーション（FastAPI）側に意味を持たせ、DB スキーマやモデル定義を `core` に集中させ、`backend/` 配下に `api`, `core`, `ingestion`, `agent` の多重ワークスペースを導入した（コミット `728e762`）。
- **発生した課題 1: コンテナランタイム要件の乖離（Alpine vs Debian）**
  - 常時稼働する Web API（FastAPI）は、起動速度とイメージサイズの小ささから **Alpine Linux** をベースとしたい。
  - 一方で、シラバス収集・PDF/Web スクレイピング・データクレンジングを行う Ingestion は、多数の外部ライブラリやビルドツールを必要とし、**Debian Slim** が適していた。
  - Alpine（musl libc）と Debian（glibc）では Python の C 拡張バイナリが非互換となるため、同一の `backend/` ワークスペース内で `.venv-api` と `.venv-ingestion` に仮想環境を分離せざるを得ず、Dockerfile の配置やボリュームマウントが複雑化した（コミット `072fba0`）。
- **発生した課題 2: Neo4j / APOC の理解による Ingestion 責務の再定義**
  - Neo4j や APOC（Awesome Procedures on Cypher）を学習・検証していく中で、シラバスの取り込みは単なる「Web API のための DB への CRUD 操作」ではないことが明確になった。
  - Ingestion は、大規模なシラバスデータのバッチ変換、APOC プロシージャを活用した一括グラフ構築、オントロジーマッピング、ベクトル埋め込み生成を担う **「独立したデータパイプライン（バッチ処理基盤）」** であるべきであり、Web API サーバーの傘下に押し込めるのは関心の分離（SoC）に反するという認識に至った。

---

## 2. 決定の判断基準 (Decision Drivers)

- **関心の分離（Separation of Concerns）**: 常時稼働する同期型 Web API サーバーと、不定期・バッチ実行されるデータ収集/グラフ構築パイプラインのライフサイクルを完全に分離すること。
- **コンテナランタイムの最適化**: 各コンポーネントが最適なベース OS（API は Alpine、Ingestion は Debian）を自然に選択でき、バイナリ非互換問題を排除すること。
- **構成・CI のシンプルさ**: 複雑化した多重 uv ワークスペースや Dockerfile の二重管理を解消し、誰でも直感的に把握できるディレクトリ構造に戻すこと。

---

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A: `backend/` 配下での多重 uv ワークスペース維持（`.venv-api` / `.venv-ingestion` 分割運用）**
   - 単一の Git サブツリーに留めつつ、Docker ビルド時に引数で仮想環境を切り替える。
2. **選択肢 B: ルート直下への `ingestion/` サービス分離 ＋ `backend/` の単一 uv プロジェクト統合 【採用案】**
   - Ingestion をルート直下の独立したサービス（独立した Dockerfile と `uv` 環境）として新設。
   - `backend/` は FastAPI と Agent を統合した単一 uv プロジェクトへ戻し、`backend/src/` 配下に `api`, `agent`, `course_core` を集約する。

---

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 B: Ingestion のルート直下分離と Backend の単一プロジェクト統合**

### 選定理由

1. **データパイプラインとしての `ingestion/` の完全な独立**:
   - シラバスのパース、APOC を用いた Neo4j への大規模バッチロード、将来の CS2023 オントロジーマッピングは、Web API とは実行タイミングも依存ライブラリも異なる。
   - ルート直下に `ingestion/` を独立配置することで、Web サーバーの起動状態に縛られず、独自のバッチ処理・スクレイピングタスクを自由に実行できる環境が整った。
2. **ランタイムバイナリ問題の根本解決**:
   - `backend/` は `ghcr.io/astral-sh/uv:python3.14-alpine` で軽量・高速に専念し、`ingestion/` は必要なライブラリに応じたコンテナイメージ（Debian 等）を個別に選択可能となり、仮想環境の衝突リスクがゼロになった。
3. **Backend ワークスペースの簡素化**:
   - 多重ワークスペース（api/agent/core/ingestion）を廃止し、`backend/src/` 配下にパッケージを集約。
   - 既存のインポートパス（`from course_core...`, `from agent...`）と内部ロジックを 1 行も壊すことなく、`backend/Dockerfile` の配置をフロントエンド（`frontend/Dockerfile`）と揃えて統一できた。
4. **CI および Docker Compose 設定の可読性向上**:
   - GitHub Actions（`.github/workflows/ci.yml`）での複雑なワークスペースパス指定が不要になり、CI の保守性が大幅に向上した。

---

## 5. 各選択肢の評価 (Pros & Cons)

### 選択肢 A: 多重 uv ワークスペース維持

- **メリット (+)**:
  - すべての Python コードが 1 つの `uv.lock` で固定される。
- **デメリット・見送り理由 (-)**:
  - Alpine 用と Debian 用のバイナリが同じリポジトリツリー内で競合しやすく、Docker 設定が著しく難解化する。
  - API を触りたいだけの開発者が Ingestion 側の重い依存解決に巻き込まれる。

### 選択肢 B: Ingestion 分離 ＋ Backend 単一統合 【採用案】

- **メリット (+)**:
  - Web サービス（FastAPI + Agent）とデータ収集（Ingestion）の境界線が極めて明確。
  - Docker Compose でも `backend` と `ingestion`（バッチ用）を独立したサービスとして直感的に扱える。
  - 将来の長崎大学データ取り込みや CS2023 投入を `ingestion/` 内で気兼ねなく開発できる。
- **デメリット・受容するリスク (-)**:
  - `backend` と `ingestion` で共通利用したいモデル（Pydantic スキーマ等）がある場合、コードの二重持ちまたはパッケージ参照の工夫が必要になる。

---

## 6. 影響と結果 (Consequences)

- **良い影響 (Positive)**:
  - コミット `ff2850e` において、`backend/` の構造が劇的にスッキリし、開発者の認知負荷が解消された。
  - ルート直下に `ingestion/` が新設されたことで、Phase 3（長崎大学シラバス Ingestion）および Phase 4（CS2023 オントロジー Ingestion）の受け皿となるデータパイプライン基盤が確立された。
  - `compose.yaml` においても、通常稼働用の `backend` サービスと、バッチ実行用の `ingestion` サービス（`profiles: ["tools"]` 等）として美しく整理された。
- **留意点・次のアクション**:
  - Ingestion から Neo4j へのデータ投入においては、APOC のインポートプロシージャ（`apoc.periodic.iterate` 等）を積極的に活用し、大量データの高速な一括書き込みを設計する。

---

## 7. 参考資料 (References)

- Commit `728e762` (uv ワークスペース導入)
- Commit `072fba0` (コンテナランタイム分離)
- Commit `ff2850e` (単一プロジェクト統合および Ingestion 分離新設)
- [Neo4j APOC Documentation](https://neo4j.com/docs/apoc/current/)
- [uv Workspaces Documentation](https://docs.astral.sh/uv/concepts/workspaces/)
- [はじめての知識グラフ構築ガイド](https://book.mynavi.jp/ec/products/detail/id=144556)
