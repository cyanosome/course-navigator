# [ADR-0012] Ingestion 運用環境における Backend 自動シード投入の停止とオプトイン化

- **ステータス**: 提案中 (Proposed)
- **起票日**: 2026-10-10
- **決定者 / 議論の場**: yuto (@cyanosome), abuku, akiha (@Akitoshi-Hasegawa)
- **関連リンク**: [ADR-0002](0002-use-polyglot-persistence-postgres-and-neo4j.md), [ADR-0008](0008-refactor-uv-workspace-and-separate-ingestion.md), [ADR-0011](0011-pivot-from-nagasaki-to-komazawa-ingestion.md), `backend/src/course_core/seeder.py`, `backend/src/api/main.py`

---

## 1. 背景と課題 (Context & Problem Statement)

- **初期開発・Agent 疎通におけるシード自動投入の導入**
  - プロジェクト初期および Agent 疎通検証フェーズ（Phase 2）において、開発・検証環境の立ち上げを容易にするため、FastAPI サーバー起動時（`lifespan`）に `backend/seed/courses.json`（20件のダミー講義データ: `GMS-101` 情報リテラシー等）を自動投入する Seeder 機構（コミット `c82de1b`）が導入された。
  - Seeder の自動実行判定ロジック（`is_db_empty()`）は、「PostgreSQL または Neo4j のいずれかに講義レコードが 0 件の場合」に自動投入を実行する仕様となっている。
- **Phase 3（実データ Ingestion）稼働に伴う課題**
  - Phase 3 においてルート直下の `ingestion/` パイプラインが整備され、駒澤大学などの実シラバスデータ（全6,803件）を収集・構造化し、Neo4j グラフデータベースへ一括投入する環境が確立された。
  - しかし、この実データ運用環境においてバックエンド（`backend/`）を起動すると、PostgreSQL 側が空（未投入）であるなどの理由から「DB が空である」と判定され、**Neo4j の実データ空間（6,803件）に対してダミー講義 20 件が意図せず混入・上書き投入されてしまう** 事象が発生する。
- **関心の分離（SoC）と安全性の欠如**
  - 大規模なシラバスデータの投入・更新は本来 Ingestion（または独立したバッチ処理）の責務であり、Web API サーバーが起動時に暗黙的な書き込み副作用を持つことは関心の分離（ADR-0008）に反する。
  - 実データを取り扱う環境において、サンプルデータの自動投入を安全に停止（無効化）できる仕組みが必須となった。

---

## 2. 決定の判断基準 (Decision Drivers)

- **実データ環境の保護（データ整合性・安全性）**: Ingestion パイプラインで投入された数千件の本番/実データに、テスト用のダミーデータが混入しないこと。
- **安全なデフォルト値（Secure by Default）**: 環境変数が未指定の場合でも、予期せぬダミーデータ自動投入が発生しないこと。
- **後方互換性と開発・テストの利便性**: 既存のゴールデンテストやローカルでの簡易 Agent 動作確認において、必要に応じてダミーシードを投入・利用できる柔軟性を残すこと。
- **関心の分離（Separation of Concerns）**: Web API サーバーのライフサイクルとデータ投入バッチのライフサイクルを明確に切り離すこと。

---

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A: Seeder コードおよびシード JSON の完全削除**
   - `seeder.py` と `courses.json` をコードベースから完全に削除し、データ投入はすべて Ingestion パイプラインに一本化する。
2. **選択肢 B: 環境変数 `AUTO_SEED_DATA` による制御（デフォルト `true` / 有効）**
   - 環境変数を新設するが、後方互換性を優先して未設定時は自動投入を実行し、Ingestion 運用環境でのみ `.env` で `AUTO_SEED_DATA=false` を指定して停止する。
3. **選択肢 C: 環境変数 `AUTO_SEED_DATA` によるオプトイン制御（デフォルト `false` / 安全重視） ＋ 手動 CLI 投入の維持 【採用】**
   - デフォルトでは起動時自動シード投入を完全に停止（無効化）し、明示的に `AUTO_SEED_DATA=true` が指定された場合のみ投入する（オプトイン化）。
   - 同時に、手動投入用 CLI（`python -m course_core.seeder`）は維持し、テストや初期検証時にワンショットで投入できる経路を確保する。

---

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 C: 環境変数 `AUTO_SEED_DATA` によるオプトイン制御（デフォルト無効）と手動 CLI の維持**

### 選定理由

1. **実データ運用の保護を最優先（安全重視）**:
   - Ingestion パイプラインが本格稼働した現在、開発者や CI が環境変数を明示的に指定しない限りダミーデータが投入されない設計（`AUTO_SEED_DATA=false` がデフォルト）が最も安全であり、実データ汚染の事故を根本から防止できる。
2. **オプトインの柔軟性とテスト資産の保護**:
   - Agent 単体の意図解析テストやゴールデンテストでダミーデータ（20件）を用いたい場合は、`.env` で `AUTO_SEED_DATA=true` を指定するか、CLI コマンドを実行するだけで即座にテスト環境を再現できる。
3. **将来のマージ・統合における明確な指針**:
   - Agent 開発ブランチ（`dev/neo4j-mcp-communication` 等）と Ingestion 開発ブランチ（`dev/ingestion-komazawa`）を統合する際に、本方針に沿って `config.py` と `main.py` を改修することで、コンフリクトや予期せぬデータ破壊を防ぐことができる。

---

## 5. 各選択肢の評価 (Pros & Cons)

### 選択肢 A: Seeder コード完全削除
- **メリット (+)**:
  - コードベースが最もシンプルになり、シード用の重複コードが消える。
- **デメリット・見送り理由 (-)**:
  - 既存の Agent 意図解析テスト（81件）やゴールデンテストが 20 件のシードデータに依存しているため、テスト実行前に毎回 Ingestion を動かす必要が生じ、CI の実行速度と開発容易性が大きく低下する。

### 選択肢 B: 環境変数制御（デフォルト `true`）
- **メリット (+)**:
  - 既存の Agent 開発環境では設定変更なしでそのまま動く。
- **デメリット・見送り理由 (-)**:
  - 新規開発者や別ブランチから Ingestion を動かした際、`.env` へのフラグ追加を忘れると実 DB にダミーデータが混入するリスクが残り、「Secure by Default」の原則に反する。

### 選択肢 C: 環境変数によるオプトイン制御（デフォルト `false`） 【採用案】
- **メリット (+)**:
  - 実シラバスデータとダミーデータの混入リスクをゼロにできる。
  - 手動 CLI（`python -m course_core.seeder`）を残すため、開発者の自由度を損なわない。
- **デメリット・受容するリスク (-)**:
  - ダミーシードに依存するテストを実行する環境では、明示的に `AUTO_SEED_DATA=true` を設定するか事前に CLI で投入しておく必要がある。

---

## 6. 影響と結果 (Consequences)

- **良い影響 (Positive)**:
  - Ingestion パイプラインで構築された Neo4j の実講義ノード（6,803件）が、バックエンド起動によって上書き・汚染されることがなくなる。
  - Web API サーバーのライフサイクルが純粋なリクエスト待機となり、起動時の暗黙的なデータ書き込み副作用が排除される。
- **留意点・トレードオフ (Negative / Neutral)**:
  - 最小構成で Agent 動作確認を行う際は、`.env` で `AUTO_SEED_DATA=true` を明示するか、手動でシードを実行する必要がある。
- **次のアクション (Next Actions - マージ時実装内容)**:
  - Agent 関連ブランチ（`dev/neo4j-mcp-communication` 等）と本ブランチの統合時に、以下の修正を実施する：
    1. **`backend/src/course_core/config.py`**:
       ```python
       AUTO_SEED_DATA = os.getenv("AUTO_SEED_DATA", "false").lower() in ("true", "1", "yes")
       ```
    2. **`backend/src/api/main.py`**:
       ```python
       if config.AUTO_SEED_DATA:
           await seeder.seed_initial_data_if_empty(pool, neo4j_driver)
       else:
           logger.info("初期シードデータの自動投入は無効化されています (AUTO_SEED_DATA=false)。")
       ```
    3. **`.env.sample`**:
       `AUTO_SEED_DATA=false` の定義と説明コメントを追加。
    4. **既存混入データのクリーンアップ**:
       開発用 DB に既に混入しているテスト講義（`code: GMS-101` 等）を削除する Cypher クエリの共有・実行。

---

## 7. 参考資料 (References)

- コミット `c82de1b`: feat(backend): シードデータの20件拡充および起動時自動投入処理の実装
- コミット `d97492a`: chore(seed): seeder にテスト・開発用 CLI エントリポイントを追加
- [ADR-0002: PostgreSQL と Neo4j による Polyglot Persistence 構成の採用](0002-use-polyglot-persistence-postgres-and-neo4j.md)
- [ADR-0008: ルート直下 Ingestion 分離への再編](0008-refactor-uv-workspace-and-separate-ingestion.md)
- [ADR-0011: 駒澤大学データへのピボット](0011-pivot-from-nagasaki-to-komazawa-ingestion.md)
