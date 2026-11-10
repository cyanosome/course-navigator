# [ADR-0024] マルチ大学展開・学術オントロジー統合に向けた決定論的 UUIDv5 サロゲートキー基盤の策定

- **ステータス**: 提案中 (Proposed)
- **起票日**: 2026-11-10
- **決定者 / 議論の場**: cyanosome, Antigravity
- **関連リンク**: [ADR-0002](0002-use-polyglot-persistence-postgres-and-neo4j.md), [ADR-0016](0016-neo4j-curriculum-dag-and-course-loader-architecture.md), [ADR-0017](0017-postgres-schema-and-verification-tool-for-course-ingestion.md), `docs/experiments/vector-vs-graph-evaluation.md`

---

## 1. 背景と課題 (Context & Problem Statement)

### 客観的事実 (Facts)
1. **現行の自然キー運用**:
   - 現在の「Course Navigator」本番パイプライン（関西大学データ）では、大学シラバスシステム固有の識別子である `syllabus_id`（例: `'011877'`）を PostgreSQL の `courses.syllabus_id`（主キー）および Neo4j の `(:Course {syllabus_id})`（一意制約）として採用し、両 DB の双方向結合を行っている（[ADR-0016](0016-neo4j-curriculum-dag-and-course-loader-architecture.md), [ADR-0017](0017-postgres-schema-and-verification-tool-for-course-ingestion.md)）。
   - 単一大学・単一開講年度（2026年度）においては、各開講クラス・担当教員ごとに一意な `syllabus_id` が発行されているため、キーの衝突は発生せず正常に機能している。

2. **マルチ大学・オントロジー統合への展開課題**:
   - 今後のロードマップにおいて、長崎大学、駒澤大学、関西大学など **「複数大学のシラバスデータを同一データベース基盤へ同居させる」** 計画が存在する。
   - さらに、「ACM/IEEE CS2023 国際標準オントロジー」を共通ハブとし、大学シラバスと学外Web公開教材（Coursera、edX 等）を有機的に結びつける多層知識グラフの構築を目標としている（`docs/experiments/vector-vs-graph-evaluation.md`）。

### 課題と分析・意見 (Opinions / Assessment)
- **大学ローカル採番への依存リスク**:
  - `course_code`（科目コード）は同一科目名（例: 微分積分１）のクラス分け・担当教員違いで重複するため主キーには使えない。
  - 一方で `syllabus_id` は大学内部のWebシステム実装（URLパラメータ等）に強く依存しており、他大学のデータを取り込んだ際に同一文字列のIDが衝突するリスクが極めて高い。
- **ランダム UUID (UUIDv4) の破綻点**:
  - Ingestion 時にランダムな UUIDv4 を生成した場合、データパイプラインの再実行、インデックス再構築、差分更新を行うたびにエンティティの ID が変化してしまい、データベース間の整合性（冪等性・再現性）が崩壊する。
- **システム抽象化の必然性**:
  - 各大学のローカルな採番規則（桁数・英数字体系・フォーマット）を内部ロジックや API コントラクトから隠蔽し、グローバルに一意かつ永続的な「講義エンティティID」を定義する必要がある。

---

## 2. 決定の判断基準 (Decision Drivers)

- **決定論性と冪等性 (Determinism & Idempotency)**: 同一の大学コード、開講年度、シラバスIDから何度パイプラインを実行しても、100% 同一のエンティティ ID が生成されること。
- **大学非依存の抽象化 (Domain Agnostic Abstraction)**: 特定大学の内部採番規則に依存せず、グローバルに衝突しない標準的な識別子であること。
- **Polyglot Persistence 間の完全な相互結合性**: PostgreSQL（16バイト固定長 UUID 型）と Neo4j（文字列プロパティ）の間でゼロオーバーヘッド・高速インデックスで結合可能であること。
- **現行システム（単一大学 MVP）への非破壊的移行**: 現行の `syllabus_id` による動作を破壊せず、段階的・後方互換的に導入可能であること。

---

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A: 自然キーの複合文字列プレフィックス拡張**
   - 大学コード・年度・シラバスIDをコロン区切りで連結した文字列をキーとする（例: `"kansai:2026:011877"`）。
2. **選択肢 B: Ingestion 実行時のランダム UUID (UUIDv4) 生成**
   - パイプライン実行時に `uuid.uuid4()` を動的発行し、PostgreSQL と Neo4j に同一トランザクションで書き込む。
3. **選択肢 C: 名前空間ベースの決定論的 UUID (UUIDv5) によるサロゲートキー基盤の策定 【採用案 (Proposal)】**
   - RFC 4122 準拠の SHA-1 ハッシュベース名前空間 UUID（UUIDv5）を Ingestion パイプライン内で決定論的に生成し、共通サロゲートキーとして付与する。

---

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 C: 名前空間ベースの決定論的 UUID (UUIDv5) によるサロゲートキー基盤の策定**

### 選定理由

1. **完全な決定論性と冪等性の保証**:
   - `uuid.uuid5(NAMESPACE_COURSE, f"{university_code}:{academic_year}:{syllabus_id}")` により生成される UUID は数学的に決定論的である。
   - データベースの全消去・再構築、別環境（開発機・CI・本番・ステージング）でのデータローディング、特定科目の差分アップデートを行っても、常に同一の UUID が算出されるため、DB 間の参照整合性が一切崩れない。
2. **データ型の最適化と標準仕様への準拠**:
   - PostgreSQL 側ではネイティブの `UUID` 型（16バイト固定長・B-Tree インデックス最適化）として格納可能。
   - Neo4j 側でも標準の文字列インデックス（`CREATE CONSTRAINT ... REQUIRE c.course_uuid IS UNIQUE`）として高速走査可能。
3. **大学固有仕様の完全なカプセル化**:
   - 外部システム（API、フロントエンド、CS2023 オントロジー、外部 MOOCs）からは抽象化された UUID として扱われ、大学ごとのシラバス URL や採番体系の差異がシステムの基盤設計に漏れ出さない。

---

## 5. 各選択肢の評価 (Pros & Cons)

### 選択肢 A: 自然キーの複合文字列プレフィックス拡張（見送り案）
- **メリット (+)**:
  - 人間が文字列を見ただけで大学・年度・シラバスIDが判読できる。
- **デメリット・見送り理由 (-)**:
  - 文字列長が可変となり、結合・インデックス走査時のメモリ効率が UUID 型（16バイト）に劣る。
  - 文字列フォーマットのパーシング依存がシステム全体に広がり、抽象度が低い。

### 選択肢 B: ランダム UUID (UUIDv4) 生成（見送り案）
- **メリット (+)**:
  - 実装が最も容易。
- **デメリット・見送り理由 (-)**:
  - パイプラインを再実行するたびに全科目の ID が刷新されてしまい、外部キャッシュ、評価ハーネスのログ、外部教材とのマッピング関係が全滅する致命的な欠陥がある。

### 選択肢 C: 決定論的 UUID (UUIDv5) サロゲートキー基盤（採用案）
- **メリット (+)**:
  - 冪等性・再現性・抽象度・インデックス性能のすべてを最高水準で満たす。
  - 自然キー `syllabus_id` を消す必要はなく、`course_uuid` を併設（サロゲートキー）として段階的に追加できる。
- **デメリット・受容するリスク (-)**:
  - デバッグ時、UUID 単体から大学名や科目を即座に肉眼判読できない（DB 側のメタデータ照会が必要）。

---

## 6. 実装・設計仕様

### 6.1 名前空間と UUID 生成仕様

```python
import uuid

# Course Navigator システム全体で固定するルート名前空間 (UUIDv4 で事前に確定)
NAMESPACE_COURSE_NAVIGATOR = uuid.UUID("7b3f3b92-5e1a-4d2c-8a1a-3a2e5d7c9f01")

def generate_course_uuid(university_code: str, academic_year: int, syllabus_id: str) -> uuid.UUID:
    """決定論的 UUIDv5 を生成する。
    
    Args:
        university_code: 大学識別コード (例: "kansai", "komazawa", "nagasaki")
        academic_year: 開講年度 (例: 2026)
        syllabus_id: 大学ローカルのシラバス一意識別子 (例: "011877")
    Returns:
        UUIDv5 インスタンス
    """
    domain_key = f"{university_code.lower()}:{academic_year}:{str(syllabus_id).strip()}"
    return uuid.uuid5(NAMESPACE_COURSE_NAVIGATOR, domain_key)
```

### 6.2 データベーススキーマ拡張イメージ

#### PostgreSQL スキーマ拡張
```sql
ALTER TABLE courses ADD COLUMN IF NOT EXISTS course_uuid UUID;
CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_course_uuid ON courses (course_uuid);
```

#### Neo4j スキーマ拡張
```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (c:Course) REQUIRE c.course_uuid IS UNIQUE;
```

---

## 7. 段階的移行ロードマップ (Migration Plan)

- **フェーズ 1 (現行 MVP・インタビュー維持)**:
  - 現行の `syllabus_id` を主軸とした API および UI をそのまま維持し、Study 1 インタビューを完遂する。
- **フェーズ 2 (Ingestion パイプラインへの UUIDv5 導入)**:
  - `ingestion/src/transformers/` およびローダーにおいて、投入データに `course_uuid` カラム・プロパティを生成・付与する。
  - 既存データへの後方互換性を維持するため、`syllabus_id` と `course_uuid` を両立（Dual-Key）させる。
- **フェーズ 3 (学術オントロジー・他大学統合)**:
  - 複数大学のシラバスおよび CS2023 オントロジーノード間の結合を `course_uuid` で一本化する。
