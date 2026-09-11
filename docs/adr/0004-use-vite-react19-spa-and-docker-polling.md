# [ADR-0004] フロントエンドにおける Vite + React 19 SPA の選定と Docker ポーリング監視

- **ステータス**: 承認済 (Accepted)
- **起票日**: 2026-06-19
- **決定者 / 議論の場**: yuto (@cyanosome)
- **関連リンク**: Commit `7c018b0`, `frontend/package.json`, `frontend/vite.config.ts`, `frontend/Dockerfile`, `compose.yaml`

---

## 1. 背景と課題 (Context & Problem Statement)

- **フロントエンドのアーキテクチャ選定と責務分離**
  - バックエンドとして FastAPI (Python) を独立して開発・運用する構成において、フロントエンドをどのようなフレームワーク・配信形態にするかを決定する必要があった。
  - チームメンバーがフロントエンド専任ではない状況でも、複雑なサーバーサイド設定やレンダリング機構に悩まされず、直感的に UI を開発・検証できる軽量な構成が求められた。
- **最新エコシステムへの追従と将来的なバージョン負債の回避**
  - バックエンドで Python 3.14 を選定した方針（ADR-0003）と同様に、フロントエンドもプロジェクト立ち上げ時点で最も新しい安定・長期サポート（LTS）仕様を採用し、早期のサポート終了（EOL）やアップグレード負債を回避したいという方針があった。
- **Windows / Docker 環境特有のホットリロード不全問題**
  - 開発者が Windows ホスト（WSL2 / Docker Desktop）から Linux コンテナへソースコードをバインドマウントした場合、Linux の標準ファイル変更検知機構（`inotify`）がホスト側の変更イベントを正しく拾えず、**「コードを保存してもブラウザが自動更新（HMR: Hot Module Replacement）されない」** という重大な開発体験上の課題が存在した。
- **ホストとコンテナ間での依存関係競合防止**
  - ホスト側（Windows 等）で不用意に `npm install` された `node_modules` と、コンテナ内部（`node:24-alpine`）の Linux 向けネイティブバイナリが衝突・破損することを防ぐ必要があった。

---

## 2. 決定の判断基準 (Decision Drivers)

- **インフラ・運用構成のシンプルさ**: バックエンドの FastAPI に加え、さらに Node.js サーバーを常時稼働させるような二重運用の複雑さを避けること。
- **最新・長期サポート（LTS）スタックの確保**: React 19、TypeScript 6、Vite 8、Node.js 24 LTS 等、最新仕様でベースラインを揃えること。
- **開発体験（DX）とホットリロードの確実性**: Windows / macOS / Linux を問わず、コード変更が即座にブラウザに反映されること。
- **依存関係の保護**: コンテナ内の `node_modules` がホスト側のマウントによって汚染・破壊されないこと。

---

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A: Next.js / Remix などのフルスタック SSR（Server-Side Rendering）フレームワーク**
   - Node.js サーバーをコンテナとして常時起動し、サーバーサイドレンダリングや API Routes を利用する。
2. **選択肢 B: 従来の Webpack ベースの SPA（Create React App 等）**
   - 枯れたビルドツールで SPA を構築する。
3. **選択肢 C: Vite + React 19 SPA + Docker ポーリング監視 (`usePolling: true`) 【採用】**
   - 純粋な Vite SPA（TypeScript）を `node:24-alpine` でコンテナ化。`vite.config.ts` で明示的にポーリング監視を有効化し、`compose.yaml` で `node_modules` を匿名ボリューム保護する。

---

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 C: Vite + React 19 SPA と Docker ポーリング監視**

### 選定理由
1. **SSR 不要とインフラの極小化**:
   - 本システムはバックエンド（FastAPI）が API 提供および GraphRAG オーケストレーションを一括して担っている。フロントエンドで独自のバックエンド（BFF / SSR サーバー）を常時運用する必要はなく、純粋な SPA（Single Page Application）とすることでインフラを最もシンプルに保てる。
   - 本番デプロイ時も、ビルド後の静的ファイル（HTML/JS/CSS）を Traefik や軽量な Web サーバーで配信するだけで完結する。
2. **最新エコシステムの統一導入（React 19 + Vite 8 + Node.js 24 LTS）**:
   - 当時の最新・安定版である **React 19, TypeScript 6, Vite 8, Node.js 24 LTS (`node:24-alpine`)** でテンプレートを初期化。
   - プロジェクト発足時から最新のベースラインを採用することで、今後数年間の研究・開発においてフレームワークの破壊的変更や EOL に振り回されるリスクを未然に排除した。
3. **Windows Docker でのホットリロード問題の解決 (`usePolling: true`)**:
   - `frontend/vite.config.ts` に以下の設定を追加：
     ```ts
     server: {
       watch: {
         usePolling: true,
       },
     },
     ```
   - これにより、Windows ホストからのバインドマウントであっても、Vite 開発サーバーが定期的にファイルのタイムスタンプをポーリング検知し、保存と同時に瞬時にブラウザが HMR で更新される環境を確立した。
4. **匿名ボリュームによる `node_modules` の保護**:
   - `compose.yaml` で以下のように設定：
     ```yaml
     volumes:
       - ./frontend:/frontend_app
       - /frontend_app/node_modules
     ```
   - コンテナ内の `/frontend_app/node_modules` を専用の匿名ボリュームでシャドウイングすることで、ホスト側のファイル群による上書き・破損を完全に隔離・保護した。

---

## 5. 各選択肢の評価 (Pros & Cons)

### 選択肢 A: Next.js 等の SSR フレームワーク
- **メリット (+)**:
  - 初期表示速度の最適化や SEO（検索エンジン最適化）に有利。
- **デメリット・見送り理由 (-)**:
  - FastAPI に加えて Node.js サーバーの常時稼働が必要になり、コンテナ運用のリソース・保守コストが倍増する。
  - 本システムは学内・学生向けの対話型履修支援システムであり、公開 Web サイトのような高度な SEO 要件は優先度が低い。

### 選択肢 B: 従来の Webpack / CRA
- **メリット (+)**:
  - 古い情報やノウハウが Web 上に多い。
- **デメリット・見送り理由 (-)**:
  - CRA は非推奨（Deprecated）となっており、ビルド・起動速度が Vite に比べて極めて遅い。

### 選択肢 C: Vite + React 19 SPA + ポーリング監視 【採用案】
- **メリット (+)**:
  - Vite の ES モジュールネイティブ機能による超高速な起動・HMR。
  - 最新の React 19 によるクリーンで宣言的な UI コンポーネント開発。
  - Windows / macOS を問わず確実に動作するホットリロード環境。
- **デメリット・受容するリスク (-)**:
  - ポーリング監視（`usePolling: true`）は標準のイベント監視（inotify）と比べてわずかに CPU 負荷が生じる。

---

## 6. 影響と結果 (Consequences)

- **良い影響 (Positive)**:
  - 開発者がコードを保存するだけで瞬時にブラウザが再レンダリングされ、ストレスのないフロントエンド開発体験が実現した。
  - Traefik 経由でバックエンド（`/api`）と同一ドメイン上でルーティングされるため、フロントエンド側で CORS や複雑な API 接続先切り替えを意識する必要がなくなった。
  - Node.js 24 LTS の公式 Alpine イメージ（`node:24-alpine`）により、コンテナサイズが最小限に抑えられた。
- **留意点・開発運用上のトレードオフ (Caveat)**:
  - プロジェクトが将来的に数千ファイル規模に肥大化した場合は、ポーリング監視による負荷を抑えるためにポーリング間隔（`interval`）のチューニングを検討する。
  - パッケージの追加を行う際は、ホスト側ではなくコンテナ内で `npm install` を実行するか、ホスト側で実行後にコンテナを再ビルド（`docker compose build frontend`）する運用をとる。

---

## 7. 参考資料 (References)

- [Vite Official Documentation: Server Watch Options](https://vite.dev/config/server-options.html#server-watch)
- [React 19 Official Documentation](https://react.dev/)
- [Node.js 24 LTS Release Schedule](https://nodejs.org/en/about/previous-releases)
- [Docker Documentation: Managing Data in Containers (Anonymous Volumes)](https://docs.docker.com/engine/storage/volumes/)
