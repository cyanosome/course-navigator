# [ADR-0011] Neo4j MCP サーバーの Backend 同居（stdio）方式の採用と動的探索基盤の確立

- **ステータス**: 提案中 (Proposed)
- **起票日**: 2026-09-12
- **決定者 / 議論の場**: akiha (@Akitoshi-Hasegawa), yuto (@cyanosome)
- **関連リンク**: `backend/pyproject.toml`, `backend/Dockerfile`, `backend/tests/test_mcp.py`, ADR-0003, ADR-0005, ADR-0007, ADR-0010

---

## 1. 背景と課題 (Context & Problem Statement)

- **静的探索モジュール (traversal.py) の表現力の限界**:
  - ADR-0005 において、並列開発のインターフェース固定および決定論的ソートの担保を目的に `traversal.py` の 4 関数（深さ `*1..3` 固定の前提・後続探索、およびトピック共有探索）を策定した。
  - しかし実際の履修相談では、「線形代数を前提とせず、データサイエンスに繋がる科目は何か」「特定の教員が関わる講義と同一分野の基礎科目は何か」など、多段階の条件組み合わせや可変長ホップ、多面的なグラフ探索が求められる。固定 Cypher クエリではこれらの複雑なクエリ意図に対応できず、エージェントによる動的グラフ探索（GraphRAG）への進化が急務となった。
- **MCP サーバーの配置場所とトポロジーの選択**:
  - Model Context Protocol (MCP) を導入するにあたり、「独立した Docker サービスコンテナとして切り出し SSE / HTTP で通信するのか」「Backend コンテナ内部に同居させてプロセス間通信（stdio）で結ぶのか」「PostgreSQL も含めた統合 MCP コンテナを自作するのか」というアーキテクチャ上のトポロジー選定が必要となった。
- **PostgreSQL と Neo4j に対する責務の非対称性**:
  - グラフ探索（Neo4j）は動的スキーマ認識と Cypher 生成による汎用探索の恩恵が大きい一方、シラバス検索や履修履歴照会（PostgreSQL）は定型的な全文検索（ILIKE）や厳密なトランザクション管理が主であり、生 SQL を LLM に委ねることはプロトコルオーバーヘッドと SQL インジェクションのリスクを招く。
- **Python 3.14 環境および OS ランタイム（Alpine vs Debian）の互換性**:
  - 公式 `neo4j-mcp-server` はネイティブ拡張を含むパッケージであり、PyPI 上では `manylinux`（glibc）向けの wheel のみが配布されている。従来の `backend/Dockerfile`（`python3.14-alpine` / musl libc）では wheel が解決できずビルド不能となる制約に直面した。

---

## 2. 決定の判断基準 (Decision Drivers)

- **インフラ・運用のシンプルさ（YAGNI 原則）**: コンテナ数、ポート開放、Traefik ルーティング、ネットワーク設定の増加を極力排除し、開発・デプロイのオーバーヘッドを最小化すること。
- **Google ADK エコシステムとの親和性**: ADK 標準の `MCPToolset` および `StdioConnectionParams` をそのまま活用し、車輪の再発明を行わないこと。
- **セキュリティと破壊的変更の防止**: LLM に不用意な書き込み権限を与えず、安全な読み取り専用（`READ_ONLY`）クエリ実行を徹底すること。
- **データソース特性に応じた責務分離**: グラフ探索（動的/MCP）と RDB アクセス（確定的/Backend内部リポジトリ）の関心事を明確に分けること。
- **テストの再現性と自動化（ADR-0010 整合性）**: CI を汚染せず、実 DB 結合環境で自動検証可能なテスト体系（`@pytest.mark.db`）を維持すること。

---

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A: 独立 Docker コンテナ（`neo4j-mcp`）新設 ＋ SSE/HTTP トランスポート接続方式**
   - ルートまたは `db/compose.yaml` に公式 Neo4j MCP サーバーのコンテナを追加し、コンテナ間ネットワーク（`gateway`）経由で SSE または HTTP で通信する。
2. **選択肢 B: 統合 Python MCP コンテナ（Postgres + Neo4j 自作ツール同梱）方式**
   - ルート直下に `mcp/` ディレクトリを作成し、Python の `mcp` SDK または FastMCP で Neo4j と PostgreSQL の両方のツールを提供する専用コンテナを構築する。
3. **選択肢 C: 公式 `neo4j-mcp-server` の Backend コンテナ同居（stdio 方式）＋ Postgres ツールの Backend 内部維持方式 【採用案】**
   - 新規コンテナは建てず、`backend` の uv 仮想環境に公式 `neo4j-mcp-server` を導入。ADK のエージェントから `stdio` サブプロセスとして直接起動・対話する。PostgreSQL ツールは Backend 内部の `postgres_repo.py` に維持する。

---

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 C: 公式 `neo4j-mcp-server` の Backend コンテナ同居（stdio 方式）＋ Postgres ツールの Backend 内部維持方式**

### 選定理由
1. **圧倒的なインフラ運用のシンプルさ**:
   - Google ADK の公式機能である `MCPToolset(connection_params=StdioConnectionParams(...))` を使用することで、Backend コンテナ内部のサブプロセスとして MCP サーバーが完全自律駆動する。
   - 新規コンテナの立ち上げ、ポートの開放、Traefik のリバースプロキシ設定、プロセス死活監視が一切不要となり、インフラ管理コストがゼロになる。
2. **自作ツールの不要化と公式実装の最大活用**:
   - 独自に Python ラッパーを書く（選択肢 B）のであれば Backend 内部に直接関数を書くのと変わらない。公式パッケージ `neo4j-mcp-server` をそのまま導入することで、Neo4j 社がメンテナンスする安全な Cypher バリデーションやスキーマ抽出ロジックの恩恵を直接享受できる。
3. **データソース特性に即した最適な責務分担**:
   - 探索の自由度が求められる Neo4j のみ動的 MCP 化し、定型アクセスである PostgreSQL は安全な内部リポジトリ（`postgres_repo.py`）に留めることで、不要なプロトコルオーバーヘッドと SQL インジェクションのリスクを回避した。
4. **Debian (bookworm-slim) への移行による安定性確保**:
   - `manylinux` wheel 互換性のため、`backend/Dockerfile` を `ghcr.io/astral-sh/uv:python3.14-bookworm-slim` に切り替えた。これにより特殊な Alpine（`musllinux`）に起因するバイナリ不整合を排除し、Debian Security Team の監視下にあるセキュアな標準環境へ昇格させた。

---

## 5. 各選択肢の評価 (Pros & Cons)

### 選択肢 A: 独立 Docker コンテナ + SSE/HTTP 方式
- **メリット (+)**:
  - ホスト PC（Cursor や Claude Desktop 等）から直接 `http://localhost:8080` で接続して手元デバッグが可能。
  - コンテナ単位でのリソース分離（CPU/メモリ）が明確。
- **デメリット・見送り理由 (-)**:
  - Compose サービスやポート管理が増加し構成が肥大化する。
  - SSE/HTTP トランスポートの設定やコンテナ間通信の接続エラー対応が必要となり、開発・運用コストが高い。

### 選択肢 B: 統合 Python MCP コンテナ自作方式
- **メリット (+)**:
  - Neo4j と PostgreSQL の両方のツールを 1 つのエンドポイントに集約できる。
- **デメリット・見送り理由 (-)**:
  - 自作ツールを書くのであれば Backend 内部の既存コードと二重管理になり、車輪の再発明となる。
  - MCP サーバー自体の保守・テストコストがプロジェクトに恒久的に乗る。

### 選択肢 C: Backend コンテナ同居（stdio 方式）＋ Postgres は Backend 維持 【採用案】
- **メリット (+)**:
  - `backend/pyproject.toml` にパッケージを追加するだけで完結（コンテナ増ゼロ）。
  - ADK がプロセスのライフサイクル（起動・終了）を自動管理するため接続漏れが起きない。
  - PostgreSQL の安全な既存資産（`resolve_anchor` 等）を 100% 温存できる。
- **デメリット・受容するリスク (-)**:
  - ホスト PC の外部クライアント（Cursor 等）から直接コンテナ内の MCP を突くことはできない（デバッグ時はホスト側で `uvx neo4j-mcp-server` を叩く運用で代替可能）。
  - Backend コンテナのメモリ消費がサブプロセス分微増する。

---

## 6. 影響と結果 (Consequences)

- **良い影響 (Positive)**:
  - インフラの追加変更なしに、Neo4j の動的探索ツール（`get-schema`, `read-cypher`）が Backend から即時利用可能となった。
  - ADR-0010 に準拠した実 Neo4j 疎通テスト（`backend/tests/test_mcp.py`）により、stdio 経由でのスキーマ取得および Cypher 読み取りが 100% 正常動作することを実証完了。
  - `traversal.py` の静的探索（ADR-0005）を「確定的な Fast-Path / 安全ツール」として温存しながら、エージェントの動的推論ループを安全に拡張できる土台が確立された。
- **留意点・トレードオフ (Negative / Neutral)**:
  - **Read-Only の強制**: 破壊的 Cypher の誤発行を防ぐため、`NEO4J_READ_ONLY=true` および Neo4j ユーザー権限での読み取り専用制御を恒久的に適用する必要がある。
  - **イメージサイズの微増**: Alpine から Debian bookworm-slim への移行に伴いイメージサイズが数十 MB 増加したが、C 拡張パッケージの安定性とビルド速度は大幅に向上した。
- **次のアクション (Next Actions)**:
  - Google ADK のワークフロー定義（`workflow.py` / `nodes.py`）において、`MCPToolset` をエージェントノードにバインドし、動的グラフ探索を活用した回答生成の結合実装を進める。

---

## 7. 参考資料 (References)

- [Neo4j Official MCP Repository (neo4j/mcp)](https://github.com/neo4j/mcp)
- [neo4j-mcp-server on PyPI](https://pypi.org/project/neo4j-mcp-server/)
- [Google Agent Development Kit (ADK) Documentation](https://github.com/google/agent-development-kit)
- ADR-0003: [Python パッケージマネージャとしての uv 採用と Python 3.14 への追従](0003-use-uv-package-manager-and-python-3-14.md)
- ADR-0005: [グラフ多段探索モジュール (traversal.py) の合意契約と Envelope パターンの採用](0005-graph-traversal-contract-and-envelope-pattern.md)
- ADR-0007: [Agent オーケストレーション基盤としての Google ADK (Agent Development Kit) 採用](0007-adopt-google-adk-for-agent-orchestration.md)
- ADR-0010: [CI（GitHub Actions）における DB / LLM 依存テストの分離実行戦略](0010-ci-test-isolation-strategy-for-db-and-llm.md)
