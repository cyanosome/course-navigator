# [ADR-0015] シラバス詳細データの PostgreSQL スキーマ設計とロード検証ツールの先行導入

- **ステータス**: 提案中 (Proposed)
- **起票日**: 2026-10-30
- **決定者 / 議論の場**: yuto (@cyanosome)
- **関連リンク**: [ADR-0002](0002-use-polyglot-persistence-postgres-and-neo4j.md), [ADR-0014](0014-pivot-from-komazawa-to-kansai-ingestion.md), `ingestion/README.md`

---

## 1. 背景と課題 (Context & Problem Statement)

### 客観的事実 (Facts)
1. **シラバスデータの構造**:
   - 関西大学のシラバス詳細データ（`courses_detail.json`、全1,029件）は、科目名や単位数などの基本スカラー属性に加え、対象学部・学科（文字列リスト）、複数教員情報（氏名・公式コード・担任フラグのペア）、15週分の授業計画（回番号・トピック）、教科書・参考書（書籍リスト）などの多階層な構造化情報を含んでいる。
2. **インフラと接続環境**:
   - PostgreSQL 18 は Docker コンテナ内で稼働し、ホスト（`127.0.0.1:5432`）にバインドされている。
   - 既存の PostgreSQL データベースにはテスト用テーブル（`test_postgres`, `test_postgres_syllabus`）のみが存在し、シラバス本番データを格納する `courses` テーブルは未定義である。
   - ホスト環境（PowerShell 等）からコンテナ内のデータを直接閲覧するには `docker compose exec postgres psql ...` を実行する必要があり、長大な複数行テキストを含むシラバスデータの確認作業には一定の手間を要する。

### 課題と分析・意見 (Opinions / Assessment)
- **ロード先行による不整合リスク**:
  - 投入されたデータの正確性を検証する手段がない状態でローダーを実装・実行した場合、レコード欠損や値の切り捨て（不完全な文字コード変換やNULL化）が発生しても早期検知が困難である。
- **リレーショナルスキーマとネスト構造のバランス**:
  - 全てのネスト構造（15週計画、複数教員、教科書）を第3正規形まで細分化してテーブル分割した場合、投入時の一括処理コストおよびバックエンドAPIでの結合コストが増大する。
  - 一方で単一の JSON カラムに全データを集約した場合、科目名・単位・学期・曜限といった基本項目に対するインデックス検索や集計クエリの恩恵を損なう。
- **先行検証の必要性**:
  - データの投入を行う前に、投入結果が元データ（`courses_detail.json`）と完全一致しているかを決定論的に判定する「検証・突合ツール」を先行配備することが、データパイプラインの品質保証上有効である。

---

## 2. 決定の判断基準 (Decision Drivers)

- **完全性の保証**: 生データに含まれる属性を欠損なく保持し、投入前後で1件の狂いもないことを自動突合（Diff）できること。
- **アクセシビリティ**: 開発者がコンテナ内部に入ることなく、ホストターミナルから1コマンドでDBの状態・統計・個別科目を視覚的に把握できること。
- **クエリ性能と構造化の両立**: 検索キーとなる主要カラム（科目コード、時間割コード、単位、学期、曜限）はリレーショナル列としてインデックスを効かせ、リストやネストオブジェクトは PostgreSQL ネイティブ型（`TEXT[]`, `JSONB`）で保持すること。
- **テスト自動化への接続**: 検証ロジックが単体テスト（`pytest`）やCIからそのまま呼び出し可能であること。

---

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A: Python CLI による専用検証・突合ツールとハイブリッドスキーマ（TEXT[] + JSONB）の先行導入 【採用】**
   - テーブル `courses` を定義し、`psycopg` (v3) を用いてホストから実行可能な検証ツール（`verify_data.py`）を実装する。
   - サブコマンド（`stats`, `show`, `diff`, `query`）を提供し、元データ JSON との完全一致を自動判定する。
2. **選択肢 B: 軽量 Web GUI（Adminer / pgweb 等）コンテナの導入**
   - Docker Compose に DB 管理用 Web コンテナを追加し、ブラウザからスプレッドシート形式で閲覧する。
   - *見送り理由*: 目視確認には便利だが、1,029件の元データとの自動差分検出（Diff）を行えず、品質保証を自動化できない。
3. **選択肢 C: 検証ツールを設けず、手動 psql 確認にとどめる案**
   - スクリプトを用意せず、必要に応じて `docker exec psql` でアドホックにクエリを実行する。
   - *見送り理由*: 長大テキストの可読性が著しく低く、全属性の網羅的な突合を手動で行うのは現実的でない。

---

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 A: Python CLI による専用検証・突合ツールとハイブリッドスキーマの先行導入**

### 選定理由
1. **差分検出の自動化 (`diff`)**:
   - `courses_detail.json` の1,029件と PostgreSQL の格納行を項目単位で総当たり比較し、未登録IDや値の不一致を自動検出できる。
2. **ハイブリッドデータ型の利点**:
   - 基本検索カラム（`subject_name`, `timetable_code`, `credits`, `semester` 等）を通常列とし、学部・学科・教科書などのリストを `TEXT[]`、教員リストや15回分の講義計画を `JSONB` とすることで、スキーマ正規化の過度な複雑化を避けつつ、完全な情報保持を実現できる。
3. **日常的な開発生産性向上**:
   - `stats`（総件数・NULL率）、`show <コード>`（1科目の全項目整形表示）、`query "<SQL>"`（手軽なクエリプレビュー）により、開発環境でのデータ観測性を大幅に向上できる。
4. **テスト連携**:
   - 検証ツールの突合ロジックをそのままローダーの統合テストに活用できる。

---

## 5. スキーマ設計概要 (`courses` テーブル)

| カラム名 | データ型 | 制約 / 備考 |
| :--- | :--- | :--- |
| `syllabus_id` | VARCHAR(20) | PRIMARY KEY（例: `'162242'`） |
| `academic_year` | INTEGER | NOT NULL（例: `2026`） |
| `course_code` | VARCHAR(20) | NOT NULL, INDEX（科目コード, 例: `'055060'`） |
| `timetable_code` | VARCHAR(20) | INDEX（時間割コード, 例: `'64214'`） |
| `subject_name` | VARCHAR(255) | NOT NULL, INDEX（科目名） |
| `subtitle` | TEXT | 副題 |
| `credits` | NUMERIC(3,1) | 単位数（例: `2.0`） |
| `credits_raw` | VARCHAR(20) | 生表記（例: `'2'`） |
| `year_range` | VARCHAR(50) | 配当年次（例: `'２年次'`） |
| `class_name` | VARCHAR(50) | クラス名（例: `'3'`） |
| `semester` | VARCHAR(50) | 開講期（例: `'春'`） |
| `term_schedule` | VARCHAR(50) | 曜限（例: `'火2'`） |
| `faculties` | TEXT[] | 対象学部リスト（例: `ARRAY['環']`） |
| `department_codes`| TEXT[] | 対象学科コードリスト |
| `subject_type_code`| VARCHAR(20) | 授業区分 |
| `language` | VARCHAR(50) | 使用言語 |
| `teaching_type` | VARCHAR(100) | 授業種別（対面型/オンデマンド等） |
| `teaching_methods`| TEXT[] | 授業手法リスト |
| `instructors` | JSONB | 教員構造化リスト（氏名, コード, 担任フラグ） |
| `contact_method` | TEXT | 問合せ方法 |
| `description` | TEXT | 授業概要 |
| `objectives` | TEXT | 到達目標 |
| `schedule_raw` | TEXT | 授業計画全文 |
| `schedule_sessions`| JSONB | 15週の回別講義計画リスト |
| `work_outside_class`| TEXT | 授業時間外学習 |
| `grading_policy` | TEXT | 成績評価方法 |
| `evaluation_criteria`| TEXT | 成績評価基準 |
| `feedback_method`| TEXT | フィードバック方法 |
| `textbooks` | TEXT[] | 教科書リスト |
| `textbook_notes` | TEXT | 教科書備考 |
| `references` | TEXT[] | 参考書リスト |
| `reference_notes` | TEXT | 参考書備考 |
| `notes` | TEXT | 備考 |
| `detail_url` | TEXT | Web参照URL |
| `relative_ref_path`| TEXT | ローカル生データパス |
| `created_at` | TIMESTAMP WITH TIME ZONE | DEFAULT CURRENT_TIMESTAMP |
| `updated_at` | TIMESTAMP WITH TIME ZONE | DEFAULT CURRENT_TIMESTAMP |

---

## 6. 影響と結果 (Consequences)

- **ロード工程の順序**:
  - Loader の実装に先立ち、検証ツールおよび接続基盤（`src/loaders/postgres/`）を先行実装する。
- **品質保証の自動化**:
  - 今後 Loader を実行した直後に `verify_data.py diff` を叩くことで、投入漏れや値の破損を即座に検知・修正できる。
- **ドキュメントの更新**:
  - `ingestion/README.md` に検証ツールの使用方法およびサブコマンド一覧を記載する。
