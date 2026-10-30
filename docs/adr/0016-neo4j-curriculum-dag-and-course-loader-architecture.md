# [ADR-0016] 履修系統図DAG・コースデータのNeo4jオントロジー設計とクロスDB検証アーキテクチャ

- **ステータス**: 決定 (Accepted)
- **起票日**: 2026-10-31
- **決定者 / 議論の場**: yuto (@cyanosome)
- **関連リンク**: [ADR-0002](0002-use-polyglot-persistence-postgres-and-neo4j.md), [ADR-0014](0014-pivot-from-komazawa-to-kansai-ingestion.md), [ADR-0015](0015-postgres-schema-and-verification-tool-for-course-ingestion.md), `ingestion/README.md`

---

## 1. 背景と課題 (Context & Problem Statement)

### 客観的事実 (Facts)
1. **データソースの整備完了**:
   - 関西大学のシラバス詳細データ（`courses_detail.json`、全1,029件）が抽出され、PostgreSQL の `courses` テーブルに一括永続化された（ADR-0015）。
   - 環境都市工学部エネルギー環境・化学工学科の履修系統図ベクターPDF（Page 6）から、科目グループ枠（21件）、グループ所属科目（70件）、およびグループ間有向前提エッジ（25本）からなる DAG 構造（`curriculum_group_graph.json`）が抽出された。
2. **Neo4j GraphDB の役割**:
   - シラバスの長大テキスト（授業計画、評価方法など）は PostgreSQL で保持し、科目間の前提履修関係や学修段階（クラスター）、ディプロマポリシー（DP）への寄与関係は Neo4j でグラフ構造として管理するポリグロット・パーシステンス方針（ADR-0002）を採用している。

### 課題と分析・意見 (Opinions / Assessment)
- **推測的機能（APOC/GDS/ベクトル埋め込み）の混入回避**:
  - プロトタイプ初期段階でベクトル検索やグラフデータサイエンス（GDS）等の推測的アルゴリズムを導入すると、データ投入の再現性やデバッグ性が損なわれ、障害発生時の原因切り分けが困難になる。純粋な Cypher バッチローディングによる決定論的オントロジーの構築が最優先である。
- **データ取得元の二重化の防止**:
  - ローダーの入力元として「PostgreSQL DB 接続」と「JSON ファイル」の双方をサポートすると、接続管理やフォールバック処理が冗長となり、保守負担が増大する。一貫して JSON を単一のデータ入力元とするべきである。
- **ハルシネーション混入リスクの排除 (`requirement_type`)**:
  - 科目の必修・選択必修区分（`requirement_type`）をグラフ投入段階で機械推論・補完しようとすると、誤った判定が GraphDB に直接混入（汚染）するリスクがある。履修要件の詳細は正確なシラバス・マスターデータを保持する PostgreSQL で管理し、Neo4j のスキーマには `requirement_type` を含めないことが望ましい。
- **検証 CLI の責務定義**:
  - Neo4j には公式の優れたブラウザ可視化 GUI（Neo4j Browser / port 7474）が存在するため、CUI 上でのアスキーアート的なグラフ描画機能は不要である。CLI は「Neo4j と PostgreSQL が同一の `syllabus_id` で 100% 破綻なく結合できるか」を高速に判定する検証目的に特化すべきである。

---

## 2. 決定の判断基準 (Decision Drivers)

- **完全性と決定論性**: 抽出済みの履修系統図グループ DAG およびコース詳細を 1 件の欠損もなく決定論的に Neo4j へ投入できること。
- **オントロジーの明確性**: 科目ノード（`Course`）、グループ枠ノード（`CourseGroup`）、教育目標ノード（`DiplomaPolicy`）のセマンティクスが明確に分離されていること。
- **シンプルさと疎結合性**: ローダー入力は JSON ファイル（`curriculum_group_graph.json` および `courses_detail.json`）のみに絞り、DB 接続の密結合を避けること。
- **推測技術の排除**: APOC、GDS、ベクトル埋め込みは使用せず、標準の Cypher `UNWIND $batch` のみで構成すること。
- **クロスDB 相互結合性の自動検証**: Neo4j のグラフ探索結果から PostgreSQL の詳細データを即座に結合・取得できることを検証する CLI を整備すること。

---

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A: 単一 JSON 入力による純粋 Cypher ローダー + クロスDB検証 CLI の導入 【採用】**
   - ローダー入力は JSON のみ。純粋な Cypher `UNWIND $batch` によりコースノードおよび DAG を投入。
   - `requirement_type` は Neo4j スキーマに含めず PostgreSQL 側に委任。
   - クロスDB検証 CLI（`verify_graph.py`）により、件数突合・トポロジー検証・特定科目のクロスDB結合確認を提供する。
2. **選択肢 B: PostgreSQL 直接参照ローダー + Neo4j GDS / ベクトルインデックスの同時導入**
   - PostgreSQL に直接接続して科目を取得し、GDS のノード類似度やベクトル埋め込みを同時投入する。
   - *見送り理由*: 推測的技術の混入により投入処理が重厚化し、エラー再現性が低下する。また RDB 接続への依存が強まり疎結合性が損なわれる。
3. **選択肢 C: CUI ターミナルグラフ描画機能を含むローダー**
   - Rich や ASCII テーブルを用いて CUI 上に DAG のトポロジカルツリーを描画する。
   - *見送り理由*: ユーザーコメントに基づき見送り。Neo4j Browser（ポート 7474）で十分にリッチな可視化が可能であり、CLI は検証目的に特化すべきである。

---

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 A: 単一 JSON 入力による純粋 Cypher ローダー + クロスDB検証 CLI の導入**

### 選定理由
1. **堅牢性と高速性**:
   - 純粋な Cypher `UNWIND $batch` により、全 1,029 科目および DAG 全体を 7.98 秒で安定ロード可能。
2. **ハルシネーション汚染の防止**:
   - `requirement_type` を Neo4j スキーマから除外したことで、未確定な推測データが GraphDB に永続化されるリスクを完全に遮断。
3. **データの疎結合性**:
   - 入力を JSON に統一したことで、PostgreSQL が一時停止している状態でも Neo4j グラフ単体でのロード・再構築が可能。
4. **即時検証性**:
   - `verify_graph check-all` および `check-course <id>` により、開発者がいつでも 1 コマンドで両 DB の主キー（`syllabus_id`）の 100% 整合性を確認可能。

---

## 5. Neo4j オントロジー設計概要

```mermaid
classDiagram
    class Course {
        +string syllabus_id UNIQUE
        +string course_code
        +string timetable_code
        +string name
        +float credits
        +int academic_year
        +string semester
        +string term_schedule
        +string teaching_type
        +string detail_url
    }
    class CourseGroup {
        +string group_id UNIQUE
        +string label
        +int academic_year
        +string semester
        +string faculty
        +string department
    }
    class DiplomaPolicy {
        +string code UNIQUE
        +string name
        +string faculty
        +string department
    }
    class Professor {
        +string name UNIQUE
        +string code
    }
    class Department {
        +string code UNIQUE
    }
    class Faculty {
        +string name UNIQUE
    }

    Course --> CourseGroup : [:BELONGS_TO_GROUP]
    CourseGroup --> CourseGroup : [:PREREQUISITE_FOR {edge_type, is_major}]
    CourseGroup --> DiplomaPolicy : [:CONTRIBUTES_TO {edge_type}]
    Course --> Professor : [:TAUGHT_BY {is_primary}]
    Course --> Department : [:BELONGS_TO]
    Course --> Faculty : [:OFFERED_BY]
```

---

## 6. 影響と結果 (Consequences)

### ポジティブな影響 (Positive Consequences)
- **決定論的なグラフ構築**: APOC や GDS に依存しない純粋 Cypher バッチ投入により、環境差異やライブラリバージョンの影響を受けない確実な再現性を確保。
- **ポリグロット・パーシステンスの確立**: Neo4j でグラフ構造（前提関係・所属グループ・教育目標寄与）を探索し、`syllabus_id` をキーとして PostgreSQL からシラバス詳細（本文・評価方法・授業計画）を取得するハイブリッド検索クエリの基盤が完成。
- **データ品質の担保**: `verify_graph` による自動検証により、Course ノード 1,029 件と PostgreSQL 行数の 100% 一致および外部キー整合性が常時確認可能。

### トレードオフ・留意点 (Trade-offs & Considerations)
- **科目の必修・選択区分**:
  - Neo4j 単体では科目の必修区分を保持しないため、学生の履修要件判定時は PostgreSQL 側のマスターまたは履修要覧ルール定義を参照する必要がある（LLM の誤判定を防ぐための意図的なトレードオフ）。
- **推測的エッジの追加（次期 Phase）**:
  - CS2023 オントロジーとの対応付け（`[:MAPS_TO]`）やシラバス類似度エッジ（`[:SIMILAR_TO]`）等の高度な拡張は、本確定オントロジーが確立された後の次フェーズにて段階的に導入する。
