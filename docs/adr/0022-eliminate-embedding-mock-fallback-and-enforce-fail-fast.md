# [ADR-0022] シラバスEmbedding生成におけるモック代替の完全撤廃とFail-Fast方針

- **ステータス**: 承認済 (Accepted)
- **起票日**: 2026-11-06
- **決定者 / 議論の場**: cyanosome
- **関連リンク**: コミット `ad94396`, PR #20, `dev/backend-for-cypher`, [ADR-0018](0018-neo4j-cypher-three-mode-search-engine-and-api-contract.md), [ADR-0021](0021-adopt-official-google-genai-sdk-and-deprecate-rest-requests.md)

---

## 1. 背景と課題 (Context & Problem Statement)

- 開発初期フェーズでは、外部APIキー（`GEMINI_API_KEY`）が未設定の開発環境やローカルCI環境でも動作を継続させるため、APIエラー時やキー不在時に「SHA-256ハッシュを用いた決定論的ダミーベクトル（モック）」を自動生成してフォールバックする仕組みを設けていた。
- しかし、関西大学シラバス1,029件の実データを取り込み、Neo4j Vector Index の構築（Phase 3.6）や3モード直交探索の学術評価実験（Phase 3.7 / 実験3-5）へ移行した段階で、以下の課題が生じた：
  1. **評価実験データの整合性**: APIの一時的エラー（503やクォータ枯渇）が発生した際、モックベクトルが混入すると、類似度エッジ（`[:SIMILAR_TO]`）やベクトル検索精度（Precision@10）の測定値に誤差が生じる。
  2. **障害の潜在化（サイレントフェイル）**: APIキーの入力ミスや期限切れが発生していても、モックによって処理が正常終了してしまい、設定不備の検知が遅れる。
- 論文での測定再現性と本番運用でのデータ品質を担保するため、Embedding生成におけるモックフォールバックの是非とエラーハンドリング方針を再定義する必要があった。

## 2. 決定の判断基準 (Decision Drivers)

- **データの整合性保証**: 本番DBおよび評価実験DBに、公式モデルAPIから取得したベクトル以外のデータが混入しないこと。
- **Fail-Fast 原則の徹底**: 認証不備やAPI障害が発生した場合、例外を送出して処理を停止させ、ログにエラー原因を出力すること。
- **単体テストとの分離**: 外部APIを呼ばない単体テストは、本番コード側でのフォールバックではなく、テストコード側でのモック注入（`unittest.mock` 等）で制御すること。

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A (採用案)**: **本番コードからモックフォールバックを撤廃し、Fail-Fast（明示的例外送出）を適用**
   - `services/embedding.py` および `embedding_generator.py` からハッシュ生成等のダミー代替ロジックを削除。
   - `GEMINI_API_KEY` 未設定時や API 通信失敗時は、即座に `ValueError` または `RuntimeError` を送出。
   - テストスイート（`test_cypher_search.py`, `test_embedding_generator.py`）は、テストコード側でモックをインジェクトする構成へ修正。
2. **選択肢 B**: **環境変数による切り替え（`ALLOW_MOCK_EMBEDDING=true`）**
   - デフォルトは本番モード（エラー送出）とし、特定の環境変数が与えられた場合のみモック生成を許可する。
3. **選択肢 C**: **モック生成時に警告ログを出力して処理を継続**
   - 既存のフォールバック動作を維持し、ログ出力のみを追加する。

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 A: 本番コードからモックフォールバックを撤廃し、Fail-Fast（明示的例外送出）を適用**

### 選定理由

- **データの整合性の担保**: 本番・検証パイプラインからモックロジックを削除することで、設定ミスや通信エラーによるダミーベクトルの混入を排除できる。
- **論文における測定条件の明確化**: DBS論文で報告する検索精度ベンチマークにおいて、全1,029科目が同一の埋め込みモデルによって生成されたベクトルであることを客観的に担保できる。
- **選択肢 B を見送った理由**: フラグを残した場合、環境設定の誤りによってモックモードでバッチが実行されるリスクが残るため。
- **選択肢 C を見送った理由**: バッチ処理のログ出力のみでは異常の検知漏れが生じる可能性があり、処理停止を伴わないため。

## 5. 各選択肢の評価 (Pros & Cons)

### 選択肢 A: モック撤廃 & Fail-Fast適用（採用案）

- **メリット (+)**:
  - コード量が削減され、条件分岐が整理される。
  - APIキーの未設定やネットワーク不通が実行直後に検知可能。
  - テストコード側でモック対象が明示される。
- **デメリット・受容するリスク (-)**:
  - 外部コントリビューターがローカルで統合テストを実行する際、有効なAPIキーの設定またはモック指定が必要となる（[ADR-0010](0010-ci-test-isolation-strategy-for-db-and-llm.md) の `pytest -m "not llm"` で分離可能）。

### 選択肢 B: 環境変数フラグによる切り替え（見送り案）

- **メリット (+)**:
  - 実行モードの切り替えが可能。
- **デメリット・見送り理由 (-)**:
  - 本番コードにモック生成コードが残り、設定不備による誤動作リスクが排除できない。

### 選択肢 C: 警告ログのみ（見送り案）

- **メリット (+)**:
  - 既存コードの変更箇所が少ない。
- **デメリット・見送り理由 (-)**:
  - 例外が発生しないため、ダミーデータがDBに書き込まれるリスクに対処できない。

## 6. 影響と結果 (Consequences)

- **良い影響 (Positive)**:
  - `backend/src/services/embedding.py` および `ingestion/src/transformers/kansai/embedding_generator.py` からハッシュ計算・ダミーベクトル生成コード（約100行）が削除された。
  - バックエンド起動時やIngestion実行時にAPIキーが無効な場合、エラーメッセージを出力して即座に停止するため、設定ミスの特定が容易になった。
  - 単体テスト（`backend/tests/test_cypher_search.py`）が明示的な `unittest.mock.patch` 構成に整理された。
- **留意点・トレードオフ (Negative / Neutral)**:
  - ローカルでベクトル関連機能を実行する際は、有効な `GEMINI_API_KEY` を `.env` に設定する必要がある。
- **次のアクション (Next Actions)**:
  - 診断ツール `verify_gemini.py`（[ADR-0021](0021-adopt-official-google-genai-sdk-and-deprecate-rest-requests.md)）と連携し、実行前の接続確認を行えるようにする。

---

## 7. 参考資料 (References)

- Martin Fowler: Fail Fast
- [ADR-0010: CI（GitHub Actions）における DB / LLM 依存テストの分離実行戦略](0010-ci-test-isolation-strategy-for-db-and-llm.md)
- [ADR-0021: Google Generative AI APIにおける公式SDK採用とREST直呼び出しの廃止](0021-adopt-official-google-genai-sdk-and-deprecate-rest-requests.md)
