# [ADR-0007] Agent オーケストレーション基盤としての Google ADK (Agent Development Kit) 採用

- **ステータス**: 提案中 (Proposed)
- **起票日**: 2026-08-24
- **決定者 / 議論の場**: akiha (@Akitoshi-Hasegawa), yuto (@cyanosome)
- **関連リンク**: Commit `8560726`, Commit `bcc55ad`, `backend/agent/src/agent/workflow.py`, `backend/agent/src/agent/nodes.py`, `backend/agent/src/agent/runner.py`, `backend/agent/src/agent/trace.py`

---

## 1. 背景と課題 (Context & Problem Statement)

- **ブラックボックスな自律ループを排した、制御可能・検証可能なワークフローの必要性**
  - 実験 3-2（履修系統図に沿った検索・推薦）において、単に質問文を LLM に丸投げして自律探索させるプロンプト型アプローチでは、探索経路の再現性や制約事項の検証が困難であった。
  - 「意図解析 ➔ モード判定（4分岐） ➔ グラフ多段探索（3経路） ➔ 候補集約・ランキング ➔ 回答生成」という明確な有向非循環グラフ（DAG）構造をコードとして明示し、各ステップの実行ログ（trace JSONL）を厳密に記録・検証できるオーケストレーション基盤が必要となった。
- **段階的通電（段階的開発）の実現**
  - 最初から外部 LLM API を組み込むと、結合障害が発生した際に「ワークフローの配線ミスなのか」「プロンプトの問題なのか」「LLM の出力形式違反なのか」の切り分けが困難になる。
  - そのため、まずは「関数ノード（Pure Function / 決定論的ノード）」だけでグラフ全体を通電させ、最後の回答生成ノードだけを後から安全に LLM Agent に差し替えられるアーキテクチャが求められた。
- **Python 3.14 ランタイムおよび MCP との互換性**
  - プロジェクト共通基盤である Python 3.14（ADR-0003）を維持したまま導入でき、かつ実験 3-1 で構築した MCP（Model Context Protocol）サーバーとの親和性が高いツールを選定する必要があった。

---

## 2. 決定の判断基準 (Decision Drivers)

- **ワークフロー（DAG）の明示的・宣言的表現力**: ノードとエッジ（分岐・合流）をコード上で直感的に定義でき、構造自体のバリデーションが効くこと。
- **決定論的関数ノードと LLM ノードのシームレスな統合**: LLM を呼ばないスタブ・純関数で先行通電でき、ノード単位での差し替えが容易であること。
- **Python 3.14 および uv 環境下での安定動作**: CPython 3.14 環境で依存解決・ビルドが壊れないこと。
- **MCP (Model Context Protocol) との親和性**: ツール呼び出し規格として MCP クライアント/サーバー機能が統合されていること。
- **実行トレーサビリティ**: 各ノードの入出力と証拠データ（Evidence）が JSONL 等で完全追跡できること。

---

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A: LangChain / LangGraph**
   - Agent 開発で最も知名度が高く機能も豊富だが、抽象化レイヤーが非常に深く、内部仕様の変更が激しい。また Python 3.14 への追従や依存関係の解決が重い。
2. **選択肢 B: 独自ステートマシン（Pure Python の if-else / match-case 実装）**
   - 外部ライブラリを一切使わず自作する。最も軽量だが、将来的なリトライ、HITL（Human-in-the-Loop）、セッション管理、MCP 統合を自前実装する必要があり車輪の再発明になる。
3. **選択肢 C: Google ADK (Agent Development Kit 2.0 / 2.7.x) 【採用案】**
   - Google が提供する現代的なエージェント開発キット。明示的な `Workflow` 構文、軽量な `Context` / `Event` 管理、公式の `[mcp]` サポートを備える。

---

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 C: Google ADK (Agent Development Kit)**

### 選定理由
1. **Python 3.14 での完全な動作確認**:
   - 実機検証により、`requires-python = ">=3.14"` のまま `uv add "google-adk[mcp]"` が依存競合を起こさずに導入できることを確認（CPython 3.14.3 / `google-adk` 2.6.2〜2.7.1 / `google-genai` / `mcp` 1.29.0）。
   - Python バージョンの引き下げや、Agent だけを別コンテナに切り出すといったインフラの複雑化を一切回避できた。
2. **直感的な `Workflow` グラフ定義**:
   - `workflow.py` において、エッジリスト形式でグラフ構造を宣言的に記述：
     ```python
     workflow = Workflow(
         name=WORKFLOW_NAME,
         edges=[
             ("START", nodes.parse_intent, nodes.route_by_mode),
             (nodes.route_by_mode, {
                 "next_step": nodes.expand_forward,
                 "prereq": nodes.expand_backward,
                 "topic": nodes.search_by_topic,
                 "unclear": nodes.respond_unclear,
             }),
             (nodes.expand_forward, nodes.rank_candidates),
             (nodes.expand_backward, nodes.rank_candidates),
             (nodes.search_by_topic, nodes.rank_candidates),
             (nodes.rank_candidates, nodes.compose_answer),
         ],
     )
     ```
   - 分岐4本・合流1点・終端2箇所のトポロジーが可視化され、構造自体のテスト（A5/A6）が容易になった。
3. **段階的通電（LLM 呼び出し 0 回での通電実現）**:
   - ステップ 5 において、終端の `compose_answer` をまずは LLM Agent ではなく「Evidence 連結関数ノード」として実装。
   - 入出力を `CandidateSet` ➔ `AnswerPayload` に固定した状態でワークフロー全体の通電とトレース記録を確認し、ステップ 6 で右辺を LLM Agent に差し替えるだけの安全な移行パスを確立した。

---

## 5. 設計上の重要契約とプラクティス

1. **「ノード層（層B: `nodes.py`）には try...except を 1 つも書かない」原則**:
   - ADK はノード内で広範な例外捕捉を行うと、フレームワーク組み込みのリトライ機構や HITL（Human-in-the-Loop）が阻害される。
   - そのため、下位の DB 層（層A: `traversal.py`）が例外をすべて捕捉して `Envelope(ok=False)` を返す契約とし（ADR-0005）、ノード層は `if not envelope.ok:` による正常なデータフロー分岐のみで制御するように徹底した。
2. **状態管理（state）のミニマリズム**:
   - 大量データや候補リストを ADK のグローバルな `state` に保持させず、`temp:mode` のような必要最小限のルーティングキーのみを配置。
   - 実データはすべてノード間の `Event(output=<Pydantic>)` によるバトンリレーとして渡し、コンテキストの肥大化を防いだ。
3. **Pydantic モデル出力の明示**:
   - ADK の素の戻り値自動ラップ機構が Pydantic モデルを辞書型（dict）に変換してしまう挙動（実機確認済み）を回避するため、全ノードで `Event(output=<Pydantic>)` を明示的に返却する実装とした。

---

## 6. 影響と結果 (Consequences)

- **良い影響 (Positive)**:
  - コミット `8560726` において、全 7 ノードのワークフローが通電し、`trace.py` により各ノードの通過証拠が JSONL 形式で完全に追跡可能となった。
  - 実 DB を使わないスタブ（`fake_graph.py`）を用いた単体・結合テスト（A5/A6）が CI 上で瞬時に実行可能となった。
- **留意点・受容するリスク (Negative / Neutral)**:
  - `edges` の先頭には明示的に `"START"` 文字列が必要であるなど、ADK 特有のグラフバリデーション構文に習熟する必要がある（規約としてコメントに明記）。

---

## 7. 参考資料 (References)

- Commit `8560726`, Commit `bcc55ad`
- 実験 3-2 設計書: `experiment-3-2-design.md` (§2 ワークフロー仕様、§6 エラー契約、§9 ステップ5)
- [Google Agent Development Kit (ADK) GitHub Repository](https://github.com/google/agent-development-kit)
- `backend/agent/src/agent/workflow.py`, `nodes.py`, `runner.py`, `trace.py`
