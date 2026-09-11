# [ADR-0001] Traefik v3 によるリバースプロキシ導入と外部ネットワーク gateway を介したマルチコンテナ疎通アーキテクチャ

- **ステータス**: 承認済 (Accepted)
- **起票日**: 2026-06-20
- **決定者 / 議論の場**: yuto (@cyanosome)
- **関連リンク**: Commit `69197f6`, Commit `bb06fa4`, `compose.yaml`, `proxy/compose.yaml`, `db/compose.yaml`

---

## 1. 背景と課題 (Context & Problem Statement)

- **デプロイの簡素化と環境差異（Development/Production Parity）の極小化**
  - 開発者間で異なる OS（Windows, macOS, Linux）や環境の差異によるトラブルを最小限に抑え、GitHub 経由で配布すれば誰でも同一の環境が立ち上がる再現性を確保したい。
  - ローカル開発環境と本番環境（サーバー上）の挙動を可能な限り一致させ、本番デプロイ時の予期せぬ不具合（パス不一致、CORS エラー、ポート衝突等）を排除したい。
- **マルチサービス（Web, DB, Proxy）の独立性とルーティングの統合**
  - 本システムは Frontend (React), Backend (FastAPI), Database (PostgreSQL, Neo4j) など多岐にわたるサービスで構成される。
  - フロントエンドからバックエンドへの通信を開発時専用の回避策（CORS の全開放や Vite 開発サーバー内部のプロキシ設定）に依存させず、本番同様の単一ドメイン・パスベースルーティングで通信させたい。
  - 同時に、データベース層（Postgres/Neo4j）とアプリケーション層（Web）、プロキシ層のライフサイクル（起動・停止・再ビルド）を互いに影響を与えずに疎結合に保ちたい。

---

## 2. 決定の判断基準 (Decision Drivers)

- **開発・本番環境の完全な同一性**: ローカルでも本番と同一の単一エンドポイント・パス構造で動作すること。
- **インフラ・運用コストの抑制**: 開発初期から高価な共有サーバーを常時稼働させる金銭的・保守的コストを避けること。
- **サービスの疎結合性**: DB だけを立ち上げ直す、あるいは Web だけをリビルドする際に他サービスに影響を与えないこと。
- **設定・ディスカバリの自動化**: コンテナの追加・変更時にプロキシの設定ファイルを書き直してリロードする必要がないこと。
- **チームの技術的親和性と実績**: 過去の構築・運用実績（cyanosome でのノウハウ）を活かせること。

---

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A: クラウド上の共有開発サーバー（VPS / EC2 等）に環境を集約し、SSH 通信で開発する案**
   - リモートサーバー上にすべてのコンテナを展開し、開発者は VS Code Remote-SSH 等で接続して開発を行う。
2. **選択肢 B: 静的リバースプロキシとして Nginx を採用する案**
   - クラシカルな Nginx コンテナを用意し、`nginx.conf` に各サービスのプロキシパス（`/api/`, `/` 等）を静的に記述してルーティングする。
3. **選択肢 C: Docker Compose + Traefik v3 (Docker Provider) + 共有外部ネットワーク `gateway` を採用する案 【採用】**
   - 全コンテナが共通の外部 Docker ネットワーク `gateway` を参照。Traefik が Docker ソケット経由で各コンテナのラベル（Labels）を自動検出し、動的にルーティングテーブルとミドルウェアを構成する。

---

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 C: Traefik v3 と共有外部ネットワーク `gateway` によるアーキテクチャ**

### 選定理由
1. **共有サーバーのコストと保守負荷の排除**:
   - 共有サーバー案は常時クラウド利用料金が発生し、サーバーのセキュリティ管理や障害対応の負担が大きい。ローカル Docker 完結型にすることで、金銭的コストをゼロにしつつオフライン開発を可能にした。
2. **Nginx に対する Traefik の優位性（Docker ラベルによる自動ディスカバリ）**:
   - Nginx はコンテナを追加・変更するたびに `nginx.conf` の編集・リロードが必要であり、コンテナの起動順序や IP アドレス変動に弱い。
   - Traefik は Docker ソケット（`/var/run/docker.sock`）を監視し、`compose.yaml` 内のラベル記述（例: `traefik.http.routers.backend.rule=PathPrefix('/api')`）を読み取って自動構成するため、設定が各サービスの Compose ファイル内にカプセル化される。
3. **外部ネットワーク `gateway` による疎結合化**:
   - 単一の巨大な `compose.yaml` にまとめず、`proxy/compose.yaml`, `db/compose.yaml`, ルート `compose.yaml` (Web) に分割。
   - `gateway` ネットワークを共有することで、PostgreSQL や Neo4j のデータを保持したまま、Backend や Frontend のみを手軽に `docker compose restart` や再ビルドできる。
4. **React の通信設計の健全化**:
   - フロントエンドから `http://localhost:8000/api` のように別ポート・直接通信をさせるのではなく、Traefik 経由の同一オリジン・相対パス（`/api`）で通信させ、Traefik の `stripprefix` ミドルウェアで `/api` を剥がして FastAPI に渡す。これにより、CORS の複雑な設定や本番デプロイ時の URL 書き換えミスを根絶できる。
5. **cyanosome での実績と自動 TLS**:
   - cyanosome において Traefik の環境構築実績があり、ノウハウが蓄積されている。また、本番環境移行時も環境変数を `websecure` に切り替えるだけで Let's Encrypt による TLS 証明書自動発行へシームレスに移行できる。

---

## 5. 各選択肢の評価 (Pros & Cons)

### 選択肢 A: クラウド上の共有開発サーバー (SSH)
- **メリット (+)**:
  - メンバー全員が完全に同一のマシンリソース上で作業可能。
- **デメリット・見送り理由 (-)**:
  - サーバーの維持費用（コスト）が継続的に発生する。
  - 複数メンバーが同時に同一環境を触るとポート衝突や競合が起きやすい。

### 選択肢 B: Nginx による静的プロキシ
- **メリット (+)**:
  - Web サーバーとしての枯れた実績、情報量の豊富さ。
- **デメリット・見送り理由 (-)**:
  - コンテナのライフサイクルと設定ファイルが同期しづらく、設定変更のたびに再起動やリロードが必要。
  - TLS 自動更新や StripPrefix などの動的ミドルウェア設定が冗長。

### 選択肢 C: Traefik v3 + 外部ネットワーク gateway 【採用案】
- **メリット (+)**:
  - Docker Compose ラベルによる宣言的で局所化されたルーティング定義。
  - 各サブディレクトリ（proxy, db, root）ごとの Compose 分離による高い保守性。
  - 環境変数 `$DOMAIN` によるローカル/本番の環境切り替えが極めて容易。
  - Web UI ダッシュボード (`:8080` / Basic 認証付き) によるルーティング状態のリアルタイム可視化。
- **デメリット・受容するリスク (-)**:
  - 初回起動時のみ `docker network create gateway` を手動実行する必要がある（ワンタイムセットアップ）。
  - Traefik 特有のラベル構文（Middlewares, Routers, Services）の学習コストがわずかに存在する。

---

## 6. 影響と結果 (Consequences)

- **良い影響 (Positive)**:
  - ローカル開発時も本番環境と全く同一のパス構成（`/`, `/api`, `/browser`）でブラウザアクセス可能となった。
  - Neo4j へのアクセスも Traefik 経由のリダイレクト（`/neo4j` ➔ `/browser/`）により、ポート開放なしでセキュアに統一された。
  - 開発者は各自のローカル PC 上で安全にコード検証・リビルドが行える。
- **留意点・トレードオフ (Negative / Neutral)**:
  - 新規参加メンバーへのセットアップ手順として、`docker network create gateway` を事前に実行する規約を明記する必要がある（`AGENTS.md` に記載済み）。
  - Docker ソケットを Traefik にマウントするため、本番公開時のアクセス権限・セキュリティ管理に留意する。
- **次のアクション (Next Actions)**:
  - 新しいサービス（例: 将来の `ingestion` サービスや追加ツール）を公開する際も、同一の Traefik ラベル命名規約に沿って構成する。

---

## 7. 参考資料 (References)

- [Traefik v3.6 Official Documentation](https://doc.traefik.io/traefik/)
- [Traefik Docker Provider Reference](https://doc.traefik.io/traefik/providers/docker/)
- [Traefik Middlewares: StripPrefix](https://doc.traefik.io/traefik/middlewares/http/stripprefix/)
- [Docker Documentation: External Networks in Compose](https://docs.docker.com/compose/networking/#use-a-pre-existing-network)
- [The Twelve-Factor App: X. Dev/prod parity (開発/本番一致)](https://12factor.net/ja/dev-prod-parity)
