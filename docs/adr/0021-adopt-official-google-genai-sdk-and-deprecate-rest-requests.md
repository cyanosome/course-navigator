# [ADR-0021] Google Generative AI APIにおける公式SDK採用とREST直呼び出しの廃止

- **ステータス**: 承認済 (Accepted)
- **起票日**: 2026-11-06
- **決定者 / 議論の場**: cyanosome
- **関連リンク**: PR #20, コミット `8c1452b`, `33c9d0e`, `9cc43da`, `e690fe0`, `dev/backend-for-cypher`

---

## 1. 背景と課題 (Context & Problem Statement)

- 本プロジェクトでは、シラバスの Embedding 生成（`gemini-embedding-001`）および履修相談 Agent の対話推論（`gemini-3.5-flash-lite` 等）に Google Gemini API を使用している。
- これまで `backend` および `ingestion` では、HTTP クライアント（`httpx`）を用いて Google AI の REST エンドポイント（`https://generativelanguage.googleapis.com/...`）へ直接リクエストを送っていた。
- 実装の進展に伴い、以下の技術的課題が生じた：
  1. **認証ヘッダーと新形式キーの非互換性**: Gemini API の新形式キー（`AQ.` プレフィックス）において、クエリパラメータ `?key=` による認証でエラーが発生し、`x-goog-api-key` ヘッダーの付与が必要となった。
  2. **URLプレフィックスとモデル名の不整合**: モデル指定時に `models/` プレフィックスを付けるか否かで REST のパスが変わり、パス構築ロジックが各ファイルに散在。
  3. **エラーハンドリングとリトライ処理の重複**: 503（Service Unavailable）やレートリミット（429）発生時の再試行ロジックを backend と ingestion で別個に実装しており、保守コストが増加していた。

## 2. 決定の判断基準 (Decision Drivers)

- **公式サポートへの追従**: Google 公式の最新 SDK を利用し、API仕様変更や新モデル追加へ対応できること。
- **認証・エラーハンドリングの共通化**: 認証ヘッダーの付与、リトライ制御、モデル名正規化の処理が単一のモジュールで完結すること。
- **診断の容易性**: APIキーの不備やクォータ超過時に、CLIツールを用いて原因を特定できること。

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A (採用案)**: **Google 公式 SDK（`google-genai`）への一本化 & REST 直接呼び出しの廃止**
   - `backend` および `ingestion` の依存関係に Google 公式 SDK を導入。
   - API通信ロジックを `services/embedding.py` 等のサービスクラスに集約し、モデル指定やリトライをSDKに委譲。
   - 疎通診断ツール `verify_gemini.py` を実装し、認証状態を確認可能にする。
2. **選択肢 B**: **自作の共通 REST クライアントモジュールを維持・拡張**
   - `httpx` をベースとした自前ラッパー関数を作り、ヘッダー付与やリトライロジックを修正して使い続ける。
3. **選択肢 C**: **サードパーティフレームワーク（LangChain / LlamaIndex 等）の導入**
   - LangChain の `GoogleGenerativeAIEmbeddings` 等を利用して抽象化する。

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 A: Google 公式 SDK（`google-genai`）への一本化 & REST 直接呼び出しの廃止**

### 選定理由

- **公式 SDK による認証仕様への準拠**: Google 公式 SDK を利用することで、`AQ.` プレフィックスを含む API キー形式に対する認証ヘッダー付与、エンドポイント URL 解決が SDK 内部で自動処理される。
- **HTTP通信コードの削減**: エンドポイント構築、JSONシリアライズ、ステータスコード別分岐の独自記述が不要となり、実装コード量を削減できる。
- **選択肢 B を見送った理由**: Google API の仕様変更（新モデル追加、URL体系の変更、レートリミット挙動）があるたびに自前クライアントの改修工数が発生するため。
- **選択肢 C を見送った理由**: 本プロジェクトは Python 3.14 環境（[ADR-0003](0003-use-uv-package-manager-and-python-3-14.md)）であり、推移的依存パッケージが多いフレームワークの導入は、依存関係解決の衝突要因となるため。

## 5. 各選択肢の評価 (Pros & Cons)

### 選択肢 A: Google 公式 SDK への一本化（採用案）

- **メリット (+)**:
  - Google 公式の例外クラスによるエラーハンドリング（`APIError`, `ResourceExhausted` 等）。
  - モデル名（`gemini-embedding-001`, `gemini-3.5-flash-lite`）の変更が引数指定で完結。
  - `verify_gemini` 診断ツールにより、APIキー設定の有効性を直接確認可能。
- **デメリット・受容するリスク (-)**:
  - SDK 自体のメジャーバージョンアップ時にインターフェース変更への追従が必要（uv.lock によりバージョンを固定）。
  - 他LLMとの連携には別の公式フレームワークを検討する必要がある｡

### 選択肢 B: 自作 REST クライアント維持（見送り案）

- **メリット (+)**:
  - 外部依存が `httpx` のみで済む。
- **デメリット・見送り理由 (-)**:
  - 認証ヘッダー仕様やAPI仕様の変更のたびにテストと修正が必要となり、保守工数が増加する。

### 選択肢 C: サードパーティフレームワーク（LangChain等）（見送り案）

- **メリット (+)**:
  - 他のLLMプロバイダへの差し替えインターフェースが共通化されている。
- **デメリット・見送り理由 (-)**:
  - 依存ライブラリ数が増加し、Python 3.14 環境でのパッケージ依存解決が複雑化する。

## 6. 影響と結果 (Consequences)

- **良い影響 (Positive)**:
  - `backend/src/services/embedding.py` および `ingestion/src/services/embedding.py` の構造が統一され、REST リクエストの分散が解消された。
  - 新形式キー（`AQ.`）での認証エラーが解消され、診断 CLI（`uv run python -m tools.verify_gemini`）によって API 疎通状態を確認できるようになった。
  - 503 エラー発生時のリトライ制御が SDK レベルで適用され、バッチ実行の安定性が向上した。
- **留意点・トレードオフ (Negative / Neutral)**:
  - `pyproject.toml` に公式 SDK の依存関係が追加された（uv による解決時間は数秒以内）。
- **次のアクション (Next Actions)**:
  - 後述の [ADR-0022](0022-eliminate-embedding-mock-fallback-and-enforce-fail-fast.md) に基づき、Embedding 生成時の不要なモックフォールバックを撤廃。

---

## 7. 参考資料 (References)

- Google GenAI SDK Documentation (GitHub: googleapis/python-genai)
- Gemini API Authentication & Headers Reference
- [ADR-0003: Python パッケージマネージャとしての uv 採用と Python 3.14 への追従](0003-use-uv-package-manager-and-python-3-14.md)
