# Course Navigator (大学履修選択支援AI)

[![CI](https://github.com/cyanosome/course-navigator/actions/workflows/ci.yml/badge.svg)](https://github.com/cyanosome/course-navigator/actions/workflows/ci.yml)
[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](docs/adr/0003-use-uv-package-manager-and-python-3-14.md)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](docs/adr/0004-use-vite-react19-spa-and-docker-polling.md)
[![Neo4j 5](https://img.shields.io/badge/Neo4j-5-008CC1?logo=neo4j&logoColor=white)](docs/adr/0002-use-polyglot-persistence-postgres-and-neo4j.md)

大学のシラバス・履修系統図・外部学習資源を知識グラフ（Neo4j）として構造化し、LLM Agent と GraphRAG を通じて学生が自己の関心や将来像に基づいた主体的な科目選択を行えるようにする学術研究・支援システムです。

---

## 1. プロジェクトの背景と目的

### 1.1 背景：なぜ学生は「防衛的な選択」に走るのか
* **「楽単」という損失回避行動**: 半年間の学修の質と生活リズムを左右する重要な決定であるにもかかわらず、講義内容や単位取得の不確実性が高いため、多くの学生は出席や課題の負担が少ない「楽単」を合理的に選択せざるを得なくなっています。
* **情報の不在ではなく「探索の摩擦」と「専門知識の非対称性」**: シラバスなどの公的データは公開されていますが、専門的な記述が多くカリキュラム全体を見通す知識がない学生にとって、それらを読み解くハードルが極めて高いのが実情です。
* **シラバスは「点」の情報**: 科目単体の説明にとどまり、学問分野の全体像の中でその科目がどこに位置し、自分の将来像や次の学修ステップにどう繋がるかという「線や面（文脈）」が見えません。

### 1.2 コアアプローチ：「点を繋ぐメディア」としての統合システム
本システムは、**客観的な標準知識体系（地図）** と **大学の開講科目（点）**、そして **学外の公開教材（OCW / MOOCs 等）** を有機的に接続し、LLM エージェントとの対話を通じて最適な学習パスを導き出します。

1. **CS2023 基準オントロジー（Ground Truth）**: ACM/IEEE CS2023 体系を共通軸とし、全大学・全科目の客観的な位置づけを規定。
2. **Neo4j 多層ナレッジグラフ**: 「標準オントロジー層」「大学カリキュラム層」「シラバス詳細層」「学習資源（Web教材）層」をリレーションで結合。
3. **LLM Agent × GraphRAG**: 学生の興味・将来像・時間割制約を解釈し、知識グラフに裏打ちされた再現性・説明性の高い履修プランを提案。

> より詳細な設計思想・データ構造・数理モデルについては [docs/architecture.md](docs/architecture.md) を参照してください。

---

## 2. システム構成

```text
course-navigator/
├── compose.yaml          # アプリケーション層（backend, frontend）のDocker Compose設定
├── Makefile              # 開発用共通コマンド
├── shell.sh / shell.bat  # コンテナ接続用スクリプト（Linux / Windows）
├── .env.sample           # アプリケーション層の環境変数サンプル
├── docs/                 # プロジェクト公式ドキュメント
│   ├── architecture.md   # システムアーキテクチャ設計書
│   ├── roadmap.md        # 研究・開発ロードマップ
│   └── adr/              # アーキテクチャ決定記録 (ADR-0001〜0010)
├── backend/              # バックエンド（FastAPI / Python 3.14 / uv 管理）
│   ├── src/
│   │   ├── api/          # FastAPI エンドポイント
│   │   ├── agent/        # ADK ワークフロー・意図パーサ・Evidence 生成
│   │   └── course_core/  # 共通モデル・スキーマ・DB接続
│   └── tests/            # ユニットテスト / Golden 14問テスト
├── frontend/             # フロントエンド（React 19 + Vite + TypeScript）
│   └── src/              # 対話 UI・グラフ可視化コンポーネント
├── db/                   # データベース層
│   ├── compose.yaml      # DB層 Compose設定 (PostgreSQL, Neo4j + APOC)
│   ├── postgres/         # PostgreSQL 設定・Dockerfile
│   └── neo4j/            # Neo4j 設定・Dockerfile
├── ingestion/            # シラバス・カリキュラムデータ収集・GraphRAG構築バッチ
└── proxy/                # リバースプロキシ層 (Traefik v3.6)
    ├── compose.yaml      # Traefik Compose設定
    └── traefik.yaml      # ルーティング・SSL設定
```

---

## 3. 研究・開発ロードマップ (Roadmap)

現在、プロジェクトは **Phase 2（Agent疎通 & GraphRAG入出力基盤確立）** から **Phase 3（長崎大学プロトタイプ先行検証）** へと進捗しています。

| フェーズ | 名称 | 状態 | 主な内容 |
| :---: | :--- | :---: | :--- |
| **Phase 1** | **フルスタック統合基盤の構築** | **完了** | Traefik / FastAPI / React 19 / PostgreSQL / Neo4j 疎通完了 |
| **Phase 2** | **LLM Agent 疎通 & GraphRAG 入出力基盤** | **進行中** | ADK Workflow、Golden 14問テスト、静的エージェント UI 疎通 |
| **Phase 3** | **長崎大データ Ingestion & プロトタイプ検索アプリ** | **次期** | 情報データ科学部データ先行投入、サークル実証実験、UI最適化 |
| **Phase 4** | **CS2023 オントロジー統合 & Web教材 Ingestion** | 未着手 | CS2023 知識マッピング、OCW / MOOCs 外部教材連携、多層グラフ化 |
| **Phase 5** | **パイロットデプロイ & 推薦精度向上実験** | 未着手 | 教員・研究室データ統合、近接性判定アルゴリズム検証、横断大学展開 |

> 各フェーズの詳細や実験計画は [docs/roadmap.md](docs/roadmap.md) を参照してください。

---

## 4. クイックスタート (Docker 起動手順)

各サービスはネットワーク分離と保守性向上のため、共有外部ネットワーク `gateway` を介して連携します。

### 前提条件
- Docker および Docker Compose がインストールされていること

### 起動手順

```bash
# 1. 共通ネットワークの作成（初回のみ）
docker network create gateway

# 2. 環境変数の準備
cp .env.sample .env
cp db/.env.sample db/.env
cp proxy/.env.sample proxy/.env

# 3. プロキシ層の起動 (Traefik)
docker compose -f proxy/compose.yaml up -d

# 4. データベース層の起動 (PostgreSQL / Neo4j)
docker compose -f db/compose.yaml up -d

# 5. アプリケーション層の起動 (Backend / Frontend)
docker compose up -d --build
```

### アクセス先一覧 (ローカル開発環境)

| サービス | URL | 役割 |
| :--- | :--- | :--- |
| **Frontend Web UI** | [http://course-navigator.localhost/](http://course-navigator.localhost/) | 授業検索・履修対話画面 |
| **Backend API** | [http://course-navigator.localhost/api/](http://course-navigator.localhost/api/) | FastAPI Swagger Docs: `/api/docs` |
| **Neo4j Browser** | [http://course-navigator.localhost/browser/](http://course-navigator.localhost/browser/) | グラフDB可視化・Cypher実行ツール |
| **Traefik Dashboard** | [http://localhost:8080/](http://localhost:8080/) | プロキシルーティング監視 |

---

## 5. 開発者向けガイド

### コンテナへのシェル接続
```bash
# Windows
shell.bat backend        # Backend (FastAPI / Agent)
shell.bat postgres       # PostgreSQL
shell.bat neo4j          # Neo4j

# Linux / macOS
./shell.sh backend
# または Makefile
make shell SERVICE=backend
```

### テスト実行 (Backend)
```bash
# CI と同様の高速テスト（DB/LLM 不要の純関数・Golden 14問テスト）
uv run pytest tests -q -m "not db and not llm"

# 実 DB（Neo4j / PostgreSQL）を起動した状態での結合テスト
uv run pytest tests -q -m "db"
```

### アーキテクチャ決定記録 (ADR)
本プロジェクトでは、重要な技術選定や構造変更を ADR として記録・管理しています。
過去の技術的経緯や決定事項の詳細は [docs/adr/README.md](docs/adr/README.md) を参照してください。
