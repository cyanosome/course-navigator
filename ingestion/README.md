# Ingestion (データパイプライン & GraphRAG 構築バッチ)

本ディレクトリは、大学シラバス、カリキュラム系統図、および外部学習資源を収集・抽出し、**Neo4j（GraphDB）** および **PostgreSQL** へ投入・グラフ構造化するための独立したデータパイプライン（バッチ処理基盤）です。

---

## 1. 概要と位置づけ

### 1.1 アーキテクチャ上の責務 (ADR-0008)

常時稼働する Web API (`backend/`) とはライフサイクルおよびコンテナランタイム要件を完全に分離し、ルート直下の独立サービスとして配置されています。

- **Web API (`backend/`)**: Alpine Linux ベース。軽量・高速な同期 API サーバー（FastAPI + Agent）。
- **Ingestion (`ingestion/`)**: Debian ベース。PDF 解析、スクレイピング、テキスト抽出、および Neo4j APOC を用いた大規模バッチ投入を担うデータ基盤。

### 1.2 Phase 3 における注力方針: 関西大学 Ingestion へのピボット (ADR-0014)

> [!WARNING]
> **方針変更 (2026-10-08 / ADR-0011): 駒澤大学 Web 停止に伴う一時停止と関西大学へのピボット (ADR-0014)**
> 長崎大学の専門科目シラバス PDF が学外非公開であることが判明したため、教養教育科目のみの PDF 解析は一時停止（凍結）としました。
> 代替として、開発メンバーのアクセス性とドメイン知識を活かせる **駒澤大学のシラバス・カリキュラムデータ** を対象とした Ingestion パイプラインの構築へピボットしています（詳細は [ADR-0011](../docs/adr/0011-pivot-from-nagasaki-to-komazawa-ingestion.md) を参照）。

- **目的**: 最速で実データに基づくエンドツーエンドのプロトタイプ検索アプリを成立させ、学生による実証インタビュー実験を行うこと。
- **対象データ**:
  - 関西大学 開講科目のシラバス（静的 HTML）および環境都市工学部等の履修系統図（ベクター PDF）
- **設計上の配慮**: Phase 3 の段階では CS2023 オントロジーへのマッピングは行わず、実シラバスと大学内カリキュラム構造のグラフ化に集中します（CS2023 / Web教材マッピングは Phase 4 にて実施）。

---

## 2. ディレクトリ構成（想定）

```text
ingestion/
├── README.md               # 本ドキュメント
├── Dockerfile              # Python (Debian Slim) ベースのバッチコンテナ定義
├── pyproject.toml          # uv パッケージ管理設定 (pypdf, beautifulsoup4, neo4j 等)
├── uv.lock                 # 依存関係ロックファイル
├── data/                   # 収集元データおよび中間成果物
│   ├── raw/                # 取得した生 PDF / HTML シラバス
│   ├── parsed/             # 構造化抽出済み JSON / CSV データ
│   └── curriculum/         # カリキュラムマップ・履修系統図定義
└── src/
    ├── fetchers/           # 【Extract】シラバス等の生データ収集 (Fetcher)
    │   ├── kansai/         # [NEW] 関西大学用フェッチャー (HTML, PDF)
    │   ├── komazawa/       # 駒澤大学用フェッチャー (凍結保持)
    │   └── nagasaki/       # 長崎大学用フェッチャー (凍結保持)
    ├── transformers/       # 【Transform】PDF / Web シラバス解析・構造化 (Transformer)
    │   ├── kansai/         # [NEW] 関西大学用パーサー
    │   │   ├── schema.py   # シラバス詳細データスキーマ
    │   │   ├── syllabus_parser.py # 静的 HTML シラバスパーサー (全33 DOM ID 抽出)
    │   │   ├── tree_schema.py # [NEW] 履修系統図グループ DAG スキーマ
    │   │   └── curriculum_tree_parser.py # [NEW] 系統図 PDF ベクター解析・DAG 抽出パーサー
    │   ├── komazawa/       # 駒澤大学用パーサー群 (凍結保持)
    │   └── nagasaki/       # 長崎大学用パーサー (凍結保持)
    └── loaders/            # 【Load】データベース一括投入 (Loader)
        ├── __init__.py     # Loader エクスポートインターフェース
        ├── postgres/       # [NEW] PostgreSQL 用ローダー・検証基盤 (ADR-0015)
        │   ├── db.py       # DB 接続マネージャー (psycopg v3)
        │   ├── schema.py   # courses テーブル DDL 定義
        │   ├── loader.py   # [NEW] コース一括 Upsert & トランザクションローダー
        │   └── verify_data.py # データ検証・完全突合 CLI ツール
        └── graph/          # Neo4j 投入ロジック（UNWIND バッチ・Cypher制約）
            ├── __init__.py # モジュールエクスポート
            ├── schema.py   # ノード・リレーション定義・Cypher クエリ
            ├── loader.py   # 駒澤大学用レガシーローダー
            ├── curriculum_loader.py # [NEW] 関西大学 カリキュラムDAG & コース一括ローダー
            └── verify_graph.py # [NEW] Neo4j & PostgreSQL クロスDB整合性検証 CLI
```

---

---

## 3. 実装状況サマリー (Status & Progress)

### 3.1 できている点 (Completed)

* **[Extract] 概要データの一括取得 (Fetcher)**:
  * [`src/fetchers/komazawa/fetch_data.py`](src/fetchers/komazawa/fetch_data.py)
  * `syllabus_information.js`（約35.2MB、全6,803科目）をストリーミングで安定ダウンロード。
  * べき等性（ダウンロード済みファイルのスキップ）および強制再取得フラグ（`--force`）を完備。
* **[Transform] 構造化解析・クレンジング (Parser)**:
  * [`src/transformers/komazawa/parser.py`](src/transformers/komazawa/parser.py)
  * 文字列内の制御文字（生改行・タブ等）に対応した安全な JSON パース（`strict=False`）。
  * `subject` テキストから **カナ読み、開講期（通年/前期/後期）、単位数、開講曜日、時限、教員カナ** を動的に抽出。
  * 全角スペースや連続空行のサニタイズ（全6,803件パース成功、エラー0件）。
* **[Load] ベース Graph の一括構築 (Graph Loader)**:
  * [`src/loaders/graph/loader.py`](src/loaders/graph/loader.py), [`src/loaders/graph/schema.py`](src/loaders/graph/schema.py)
  * `Course.code`, `Professor.name`, `Department.name` の一意制約（`CREATE CONSTRAINT`）の自動適用。
  * `UNWIND $batch`（1,000件単位）による一括 MERGE により、**8.66秒で全6,803件の投入完了**。
  * ノード: `Course` (6,803件), `Professor` (1,026件), `Department` (190件)
  * エッジ: `[:TAUGHT_BY]` (6,803件), `[:BELONGS_TO]` (6,803件)
* **[Quality] テストの完備**:
  * モックを活用した単体テスト（全22件）が Docker コンテナ内で 100% 通過。

### 3.2 出来ていない点・今後の課題 (Pending / To-Do)

* **PostgreSQL への永続化 (RDB Ingestion)**:
  * PostgreSQL 側の `courses` テーブル（マスターデータ）への一括投入スクリプトの実装（`asyncpg` 利用）。
* **詳細データの取り込み (HTML Parser / Detail Fetcher)**:
  * 個別詳細HTML（`detail/{rishu_code}.html`）のバッチ収集。
  * 第1回〜第15回の授業計画、評価方法の内訳（定期試験〇%、レポート〇%等）、教科書・参考書の表組み構造のパース。
  * RDB（`course_details` テーブル / JSONB）への格納。
* **履修系統図（カリキュラムツリー・学修系統図）との関係性の紐付け**:
  * 学部・学科ごとの履修系統図（PDF / 公開資料）の収集・構造化。
  * 学修段階（基礎・基幹・展開・発展）や学年配当、必修・選択区分ノードの生成と、シラバス科目とのリレーション接続 (`[:PART_OF_CURRICULUM]`, `[:RECOMMENDED_BEFORE]`)。
* **前提科目エッジ (`[:REQUIRES_PREREQUISITE]`) の構築**:
  * シラバス本文やカリキュラム資料から「〇〇履修済み」等の前提条件を抽出し、科目間エッジを接続。
* **GDS (Graph Data Science) によるセマンティック類似度エッジ (`[:SIMILAR_TO]`) の生成**:
  * 科目テキスト（`text`）の Embedding（ベクトル埋め込み）生成。
  * Neo4j Vector Index の作成。
  * Neo4j GDS（kNN / Node Similarity 等）を用いた `[:SIMILAR_TO {score: ...}]` エッジの自動導出。
* **CS2023 オントロジー統合 (Phase 4)**:
  * ACM/IEEE CS2023 基準オントロジーノード群の投入と、学内科目との自動推論マッピング (`[:MAPS_TO]`)。

---

## 4. データ処理フロー (Komazawa Univ.)

```mermaid
flowchart TD
    subgraph Extract["1. 収集 (Fetcher)"]
        RawJS["syllabus_information.js<br/>(35.2 MB / 6,803件)"]
        RawHTML["detail/*.html<br/>(未実装 / 詳細HTML)"]
        RawTree["履修系統図・カリキュラム資料<br/>(未実装 / 学修系統図)"]
    end

    subgraph Transform["2. 抽出・クレンジング (Parser)"]
        Parser["src/transformers/komazawa/parser.py"]
        RawJS --> Parser
        SummaryJSON["data/parsed/.../courses_summary.json<br/>(完了 / 6,803件)"]
        Parser --> SummaryJSON
    end

    subgraph LoadGraph["3. GraphDB 構築 (完了)"]
        SummaryJSON --> Loader["src/loaders/graph/loader.py"]
        Loader --> Neo4j[("Neo4j GraphDB<br/>・Course (6,803)<br/>・Professor (1,026)<br/>・Department (190)<br/>・TAUGHT_BY / BELONGS_TO")]
    end

    subgraph Pending["4. 今後の拡張 (未着手)"]
        SummaryJSON -.-> LoadPG["PostgreSQL 投入<br/>(courses マスター)"]
        RawHTML -.-> DetailParser["詳細HTML パース<br/>(各回計画・評価割合)"]
        DetailParser -.-> PG_Detail["PostgreSQL 投入<br/>(course_details)"]
        RawTree -.-> TreeParser["系統図パース<br/>(学修段階・推奨順序)"]
        TreeParser -.-> Neo4j
        SummaryJSON -.-> Embed["Embedding & GDS<br/>[:SIMILAR_TO] エッジ生成"]
        Embed -.-> Neo4j
    end
```

---

## 5. 実行方法（開発環境）

C 拡張ライブラリ（`asyncpg` 等）や PDF 解析ツールの環境差異を防ぐため、**Docker コンテナ内での実行を標準**としています。

### 前提条件: 共有ネットワークと DB の起動

```bash
# 共有ネットワークの作成（初回のみ）
docker network create gateway

# PostgreSQL / Neo4j の起動
docker compose -f db/compose.yaml up -d
```

### Docker 経由での実行（標準手順）

リポジトリルート直下から Docker Compose（`tools` プロファイル）経由で実行します。

```bash
# 1. コンテナイメージのビルド（初回および pyproject.toml / Dockerfile 更新時）
docker compose --profile tools build ingestion

# 2. シラバス等の公式データ取得 (Fetcher)
# 駒澤大学（全科目静的インデックス取得）
docker compose --profile tools run --rm ingestion uv run python -m src.fetchers.komazawa.fetch_data

# （参考）長崎大学（一時停止中）
docker compose --profile tools run --rm ingestion uv run python -m src.fetchers.nagasaki.fetch_data

# 3. 解析・テキスト抽出・構造化 (Parser)
docker compose --profile tools run --rm ingestion uv run python -m src.parsers.komazawa.parser

# 4. Neo4j へのベースグラフ一括投入 (Graph Loader: Course, Professor, Department)
docker compose --profile tools run --rm ingestion uv run python -m src.graph.loader
```

#### コンテナ内でインタラクティブに作業・デバッグする場合

```bash
# ingestion コンテナをバックグラウンド起動
docker compose --profile tools up -d ingestion

# コンテナ内シェルへ接続
docker compose exec ingestion bash

# （コンテナ内で実行）
uv run python -m src.parsers.komazawa.parser
```

> [!NOTE]
> ローカルホスト（Windows等）上で直接 `uv run` を実行する場合、Python 3.14 用の C コンパイラ環境（Visual Studio C++ Build Tools 等）が必要になる場合があります。チーム開発時は上記の Docker コンテナ経由での実行を推奨します。

---

### 5.2 PostgreSQL コースデータローダー (`loader.py`)

構造化シラバス JSON（`courses_detail.json`）を PostgreSQL の `courses` テーブルへ高速・安全・かつべき等（再実行可能）に一括投入（Upsert）する CLI スクリプトです。単一トランザクション保証（All-or-Nothing）で動作し、投入完了後に自動で元データ突合検証（`diff`）を実行して差分ゼロを判定します。

```bash
# 1. 安全確認（ドライラン: コミットせず全件ロールバック）
python -m src.loaders.postgres.loader --dry-run

# 2. 本番一括投入（デフォルト設定: 500件バッチ + 自動 diff 検証）
python -m src.loaders.postgres.loader

# 3. カスタムパスおよびバッチサイズを指定して投入
python -m src.loaders.postgres.loader --json data/parsed/university/kansai/2026/courses_detail.json --batch-size 1000

# 4. 高速実行（ロード後の自動突合検証をスキップ）
python -m src.loaders.postgres.loader --skip-verify
```

#### CLI 引数と実行オプション

| オプション | 型 / デフォルト値 | 説明 |
| :--- | :--- | :--- |
| `--json PATH` | `Path` / `data/parsed/university/kansai/2026/courses_detail.json` | 投入元となる構造化シラバス JSON のパス指定 |
| `--batch-size N` | `int` / `500` | 1回の `executemany` で一括送信するレコード件数 |
| `--dry-run` | フラグ (`action="store_true"`) | 実際にはコミットせず、データのバインド・投入シミュレーションのみを行いロールバックする安全確認フラグ |
| `--skip-verify` | フラグ (`action="store_true"`) | ロード完了後の自動 `diff` 検証ステップをスキップする高速化フラグ |

---

### 5.3 PostgreSQL データ検証・完全突合ツール (`verify_data.py`) (ADR-0015)

PostgreSQL 内の `courses` テーブルのデータ整合性を開発者がホスト側から1コマンドで検証・確認するための CLI ツールです。

```bash
# 1. テーブルおよびインデックスの初期化 (初回のみ)
python -m src.loaders.postgres.verify_data init-db

# 2. テーブル総件数・カラム別 NOT NULL 充足率・分布の確認
python -m src.loaders.postgres.verify_data stats

# 3. 特定科目の詳細表示 (時間割コード 64214 または シラバスID 162242)
python -m src.loaders.postgres.verify_data show 64214

# 4. 元データ JSON との完全自動突合 (差分ゼロ・完全一致の検証)
python -m src.loaders.postgres.verify_data diff --json data/parsed/university/kansai/2026/courses_detail.json

# 5. 任意の読み取り SQL の直接実行・表形式プレビュー
python -m src.loaders.postgres.verify_data query "SELECT subject_name, credits, semester, term_schedule FROM courses WHERE subject_name LIKE '%化学%' LIMIT 5;"
```

---

### 5.4 カリキュラム系統図 DAG トランスフォーマー (`curriculum_tree_parser.py`)

履修系統図ベクター PDF（`tree_env.pdf`）から、**科目グループ枠（クラスター）**、**グループ所属科目**、および**グループ間の有向前提エッジ（DAG）**を幾何学的に抽出するスクリプトです。各科目は PostgreSQL の `courses` マスターデータと照合され、`syllabus_id` および `course_code` が自動付与されます（色解析は行わず、DB マスターデータを利用）。

```bash
# 1. Page 6（エネルギー環境・化学工学科）の DAG 抽出と Mermaid / JSON 出力
python -m src.transformers.kansai.curriculum_tree_parser --page 6

# 2. カスタムパスおよび出力先を指定して実行
python -m src.transformers.kansai.curriculum_tree_parser --pdf data/raw/university/kansai/2026/curriculum/tree_env.pdf --output-json data/parsed/university/kansai/2026/curriculum_group_graph.json --output-md data/parsed/university/kansai/2026/curriculum_extracted.md
```

---

### 5.5 Neo4j カリキュラム系統図 & コースデータローダー (`curriculum_loader.py`)

抽出された履修系統図グループ DAG（`curriculum_group_graph.json`）および詳細シラバスコースデータ（`courses_detail.json`）を Neo4j へ一括投入（Merge）するローダーです。APOC や GDS、ベクトル埋め込み等の推測的技術は使用せず、純粋な Cypher `UNWIND $batch` パランティア型オントロジーにより投入します。

```bash
# 1. デフォルト一括投入（Course, CourseGroup, DiplomaPolicy を Merge）
python -m src.loaders.graph.curriculum_loader

# 2. 該当学科の既存データをクリアしてから新規再ロード
python -m src.loaders.graph.curriculum_loader --clear-first

# 3. カスタムパスおよびバッチサイズを指定して投入
python -m src.loaders.graph.curriculum_loader --tree data/parsed/university/kansai/2026/curriculum_group_graph.json --courses data/parsed/university/kansai/2026/courses_detail.json --batch-size 1000
```

#### Neo4j グラフモデル・オントロジー
- **ノード**:
  - `(:Course {syllabus_id, course_code, timetable_code, name, credits, semester, term_schedule, detail_url})`
  - `(:CourseGroup {group_id, label, academic_year, semester, faculty, department})`
  - `(:DiplomaPolicy {code, name, faculty, department})`
  - `(:Professor {name, code})`, `(:Department {code})`, `(:Faculty {name})`
- **リレーション**:
  - `(:CourseGroup)-[:PREREQUISITE_FOR {edge_type, is_major}]->(:CourseGroup)`
  - `(:CourseGroup)-[:CONTRIBUTES_TO {edge_type}]->(:DiplomaPolicy)`
  - `(:Course)-[:BELONGS_TO_GROUP]->(:CourseGroup)`
  - `(:Course)-[:TAUGHT_BY {is_primary}]->(:Professor)`
  - `(:Course)-[:BELONGS_TO]->(:Department)`
  - `(:Course)-[:OFFERED_BY]->(:Faculty)`

---

### 5.6 Neo4j & PostgreSQL クロスデータベース整合性検証 CLI (`verify_graph.py`)

Neo4j GraphDB と PostgreSQL RDB の両方に接続し、データ件数、DAG トポロジー、および主キー（`syllabus_id`）の完全一致・相互結合性を検証する CLI ツールです。

```bash
# 1. 全体整合性・ノード数・エッジ数・クロスDB 100% 紐付け検証
python -m src.loaders.graph.verify_graph check-all

# 2. 特定科目のクロスDB結合インスペクション (Graph コンテキスト + RDB 詳細シラバス)
python -m src.loaders.graph.verify_graph check-course 162242

# 3. カリキュラム CourseGroup の DAG 前提・後続関係一覧表示
python -m src.loaders.graph.verify_graph check-groups
```

---

## 6. ロードマップと今後の展開

- [x] **Phase 3（現在）**: 駒澤大学 シラバスおよびカリキュラムデータの Ingestion 実装と Neo4j へのグラフ初期投入（完了: 6,803件 / ADR-0011）
- [ ] **Phase 3（現在）**: 前提科目ツリーおよび履修推奨エッジの結合検証
- [ ] **Phase 4（次期）**: ACM/IEEE CS2023 基準オントロジー投入パイプラインの実装
- [ ] **Phase 4（次期）**: LLM による学内科目 ↔ CS2023 オントロジーの自動推論マッピング (`[:MAPS_TO]`)
- [ ] **Phase 4（次期）**: Web 公開教材（OCW / MOOCs 等）の収集・グラフ化パイプラインの追加
