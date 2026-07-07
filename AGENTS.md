# course-navigator

## 概要
大学の履修選択を支援するAI（履修AI）。学生が自分に合った科目選択を効率的かつ
納得感を持って行えるようにするアプリケーション。

GitHub: https://github.com/cyanosome/course-navigator

## 構成
- `backend/`: FastAPI（Python >=3.14, uv 管理）。PostgreSQL は asyncpg、Neo4j は
  公式ドライバで接続。
- `frontend/`: React 19 + Vite + TypeScript（ESLint 設定あり）。
- `db/`: Neo4j（GraphRAG用に APOC プラグインを自動導入） + PostgreSQL。
- `proxy/`: Traefik によるリバースプロキシ・ドメインルーティング。

各サービスは Docker Compose で構成され、外部ネットワーク `gateway` を共有する。

## 起動方法
初回のみネットワークを作成:
```
docker network create gateway
```

各コンポーネントの起動:
```
docker compose -f proxy/compose.yaml up -d   # Traefik
docker compose -f db/compose.yaml up -d      # PostgreSQL / Neo4j
docker compose up -d                          # backend / frontend（ルート）
```

コンテナへのシェル接続:
```
make shell                    # デフォルト backend
make SERVICE=postgres shell   # postgres
make SERVICE=neo4j shell      # neo4j
```
（Windows以外では `./shell.sh [service]`、Windowsでは `shell.bat` も利用可）

## 規約
- コミットメッセージは Conventional Commits に従う（例: `feat:`, `fix:`, `chore:`）。
- 差分は最小限に保ち、要求に無関係なコードは触らない。
- リファクタと機能追加は必ず分離する。
- 構造変更は提案にとどめ、実施前に確認を取る。

## 環境変数ファイルの取り扱い
`.env` はリポジトリ全体で `.gitignore` 対象。`.env.sample` 以外の `.env`系ファイル
（ルート/backend/frontend/db/proxy 各所）は絶対にコミットしないこと。

## 5W1H運用
作業開始時に `C:\Users\haseg\Projects\vault\10_projects\course-navigator\_project.md`
と最新の session-log を読み、終了時に session-log を追記する（project-log スキル使用）。
