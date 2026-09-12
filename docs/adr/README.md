# Architecture Decision Records (ADR)

本ディレクトリは、「Course Navigator」プロジェクトにおける重要な **アーキテクチャ上の意思決定（技術選定、設計方針、構造変更等）の背景・理由・トレードオフ** を記録・管理する場所です。

---

## 1. ADR を導入する目的

- **「なぜその設計・技術を選んだのか」のブラックボックス化を防ぐ**
  - 数ヶ月後の自分たちや新しいメンバーが「なぜこのライブラリなのか」「なぜこのテーブル構造なのか」を迷わず理解できるようにします。
- **AI エージェント（Antigravity / Claude 等）のコンテキスト理解向上**
  - コーディング支援を行う AI が、過去の設計判断や制約事項を正確に把握した上で適切なコード変更を提案できるようにします。
- **不毛な議論の蒸し返しを防ぐ**
  - 過去に却下された選択肢（Pros/Cons）が記録されているため、同じ検討をゼロから繰り返す無駄を省きます。

---

## 2. ADR の作成ルールと運用フロー

### ① ファイル命名規則
```text
docs/adr/XXXX-kebab-case-title.md
```
- `XXXX` は 4 桁の連番（`0001`, `0002`, ...）
- タイトルは英語のケバブケース（ハイフン区切り）
- 例:
  - `0001-use-neo4j-for-graphrag.md`
  - `0002-prioritize-nagasaki-univ-ingestion-for-prototype.md`

### ② 作成手順
1. [`template.md`](template.md) をコピーして `XXXX-your-title.md` を作成する。
2. 背景、判断基準、検討した選択肢（Pros/Cons）、決定事項を記入する。
3. PR を作成し、チームレビュー・議論を経てステータスを `Accepted` に変更してマージする。

### ③ 不変の原則 (Immutability)
- **一度 Accepted（承認済）になった ADR は、原則として過去の決定内容を直接書き換えてはいけません。**
- 方針を変更・撤回する場合は、**新しい ADR を起票** し、古い ADR のステータスを `Superseded by ADR-XXXX`（後続の ADR により置換）に更新します。

---

## 3. ステータス一覧

| ステータス | 意味 |
| :--- | :--- |
| **Proposed** (提案中) | 議論・レビュー中。まだ正式決定していない状態。 |
| **Accepted** (承認済) | 正式に合意・決定され、実装基準として有効な状態。 |
| **Superseded** (置換済) | 後続の新しい ADR によって方針が上書き・変更された状態。 |
| **Deprecated** (廃止) | 技術や方針が不要となり、使われなくなった状態。 |

---

## 4. ADR 一覧 (Index)

| 番号 | タイトル | ステータス | 決定日 | 概要 |
| :--- | :--- | :---: | :---: | :--- |
| [0000](template.md) | (テンプレート) | - | - | ADR 作成用テンプレート |
| [0001](0001-use-traefik-and-gateway-network.md) | [Traefik v3 によるリバースプロキシ導入と外部ネットワーク gateway を介したマルチコンテナ疎通アーキテクチャ](0001-use-traefik-and-gateway-network.md) | Accepted | 2026-06-20 | 開発/本番環境差異の排除、Docker ラベル動的ルーティング、疎結合なマルチ Compose 連携 |
| [0002](0002-use-polyglot-persistence-postgres-and-neo4j.md) | [PostgreSQL と Neo4j による Polyglot Persistence（複合DB）構成の採用](0002-use-polyglot-persistence-postgres-and-neo4j.md) | Accepted | 2026-06-20 | RDB（整合性・メタデータ）と GraphDB（関係性・GraphRAG・Vector）の明確な役割分担 |
| [0003](0003-use-uv-package-manager-and-python-3-14.md) | [Python パッケージマネージャとしての uv 採用と Python 3.14 への追従](0003-use-uv-package-manager-and-python-3-14.md) | Accepted | 2026-06-18 | 高速な依存解決・Docker 公式イメージ利用・pyproject.toml/uv.lock による再現性確保 |
| [0004](0004-use-vite-react19-spa-and-docker-polling.md) | [フロントエンドにおける Vite + React 19 SPA の選定と Docker ポーリング監視](0004-use-vite-react19-spa-and-docker-polling.md) | Accepted | 2026-06-19 | SSR排除によるインフラ軽量化、最新スタック統一、Windows DockerでのHMRポーリング解決 |
| [0005](0005-graph-traversal-contract-and-envelope-pattern.md) | [グラフ多段探索モジュール (traversal.py) の合意契約と Envelope パターンの採用](0005-graph-traversal-contract-and-envelope-pattern.md) | Proposed | 2026-08-12 | 並列開発のためのシグネチャ固定、Envelope例外吸収、探索上限3段固定、決定論的ソート保証 |
| [0006](0006-deterministic-intent-parser-and-golden-tests.md) | [意図パーサと Evidence 生成の純関数設計および Golden テスト駆動開発](0006-deterministic-intent-parser-and-golden-tests.md) | Proposed | 2026-08-18 | ハルシネーションによるグラフ探索誤爆の防止、LLMへのコード直接出力禁止、DB/LLM不要の高速CI |
| [0007](0007-adopt-google-adk-for-agent-orchestration.md) | [Agent オーケストレーション基盤としての Google ADK (Agent Development Kit) 採用](0007-adopt-google-adk-for-agent-orchestration.md) | Proposed | 2026-08-24 | 明示的な DAG ワークフロー定義、関数ノードによる段階的通電、Python 3.14/MCP 互換性確保 |
| [0008](0008-refactor-uv-workspace-and-separate-ingestion.md) | [uv ワークスペース分割の試行とルート直下 Ingestion 分離への再編](0008-refactor-uv-workspace-and-separate-ingestion.md) | Accepted | 2026-09-02 | Alpine/Debianランタイム不整合の解消、Neo4j/APOCバッチ責務の独立、Backend構造の簡素化 |
| [0009](0009-prioritize-nagasaki-univ-ingestion-for-prototype.md) | [最速プロトタイプ検証のための長崎大学データ先行 Ingestion への方針転換](0009-prioritize-nagasaki-univ-ingestion-for-prototype.md) | Accepted | 2026-09-09 | PDF入手性、サークル連携テストベッド、後期登録時期、新設学部アクセスの利点を活かした先行実証 |
| [0010](0010-ci-test-isolation-strategy-for-db-and-llm.md) | [CI（GitHub Actions）における DB / LLM 依存テストの分離実行戦略](0010-ci-test-isolation-strategy-for-db-and-llm.md) | Proposed | 2026-08-24 | pytest マーカー（not db and not llm）による高速 CI（1分以内完走）、API コスト/Flaky 排除、テストダブル活用 |
| [0011](0011-adopt-neo4j-mcp-server-with-stdio-transport.md) | [Neo4j MCP サーバーの Backend 同居（stdio）方式の採用と動的探索基盤の確立](0011-adopt-neo4j-mcp-server-with-stdio-transport.md) | Proposed | 2026-09-12 | コンテナ増ゼロ（Backend同居+stdio）、ADK標準MCPToolset活用、Debian移行によるmanylinux互換性確保 |
