# [ADR-0005] グラフ多段探索モジュール (traversal.py) の合意契約と Envelope パターンの採用

- **ステータス**: 提案中 (Proposed)
- **起票日**: 2026-08-12
- **決定者 / 議論の場**: akiha (@Akitoshi-Hasegawa), yuto (@cyanosome)
- **関連リンク**: Commit `032033c`, Commit `010d046`, PR #2, `backend/graph/traversal.py`, `backend/src/course_core/schemas/traversal.py`

---

## 1. 背景と課題 (Context & Problem Statement)

- **MCP サーバーと Agent ワークフロー共通の探索基盤の必要性**
  - 実験 3-1（MCP サーバー）と実験 3-2（Google ADK による履修系統図ワークフロー）を実装するにあたり、PostgreSQL のシラバス情報と Neo4j の前提条件グラフを探索する共通モジュール `backend/graph/traversal.py` の新設が必要となった。
- **並列開発に伴うインターフェース破綻のリスク**
  - 本プロジェクトでは、Yuto 氏がデータ構造・DB 検索確定（ステップ 0 ➔ 2 ➔ 3）を担い、Aki_Ha 氏が意図パーサ・Evidence 生成・ワークフロー構築（ステップ 1 ➔ 4 ➔ 5）を並列で分担する体制をとっていた。
  - 両者が合流してワークフローを通電させる際、関数の戻り値の形式、エラー処理、結果の並び順、引数がブレていると手戻りが非常に大きくなる懸念があった。
- **Agent（ワークフローノード）における例外ハンドリングの課題**
  - Google ADK などのエージェントフレームワークでは、ノード内部で広範な `try...except` を記述すると、フレームワーク標準のリトライ機構や HITL（Human-in-the-Loop）が意図通りに機能しなくなる。
  - そのため、DB アクセスを行う層（層A）と、ワークフロー制御を行う層（層B）の間で、例外を外に投げない明確な契約を結ぶ必要があった。

---

## 2. 決定の判断基準 (Decision Drivers)

- **並列開発の円滑化**: 入出力シグネチャを早期に厳密固定し、DB 実装と Agent ワークフロー実装を完全に独立して進められること。
- **結果の決定論性（再現性）**: 同一の質問に対して何度実行しても、Neo4j の探索結果が完全に同一の順序で返却されること（Golden テストの再現性担保）。
- **堅牢なエラーハンドリング**: データベース障害時にも Python 例外をワークフロー層へリークさせず、エージェント側で安全に分岐できること。
- **未検証要素の局所化**: 初版（v1）の段階で可変長パスのパラメータ化や APOC の未検証機能を持ち込まず、探索範囲を安全に制約すること。

---

## 3. 検討した選択肢 (Considered Options)

1. **選択肢 A: 個別クエリ発行 & 標準 Python 例外送出方式**
   - 関数ごとに素の辞書やリストを返し、DB 接続エラーやクエリエラー時はそのまま例外を上位のワークフローへ送出する。探索深さや並び順は呼び出し側に委ねる。
2. **選択肢 B: Envelope パターン ＋ 厳密な合意契約（深さ 1..3 固定・例外吸収・決定論的ソート）の採用 【採用案】**
   - すべての探索関数が `Envelope[T]`（`ok`, `error_code`, `message_ja`）を返却する契約を結ぶ。
   - DB 例外は層A（`traversal.py`）内で捕捉して `Envelope(ok=False)` に変換。
   - 探索深さは `*1..3` のリテラル固定とし、ソート順を `hops DESC, code ASC` で決定論化する。

---

## 4. 決定事項と選定理由 (Decision & Rationale)

**採用**: **選択肢 B: Envelope パターンと 6 つの設計合意契約**

### 合意された 4 関数のシグネチャ
```python
def resolve_anchor(conn, text: str) -> Envelope[AnchorHit]: ...
def find_next_courses(session, code: str) -> Envelope[list[Candidate]]: ...
def find_prerequisites(session, code: str) -> Envelope[list[Candidate]]: ...
def find_related_by_topic(session, code: str, limit: int = 5) -> Envelope[list[Candidate]]: ...
```

### 6 つのコア契約と選定理由
1. **Envelope パターンの統一 (`ok`, `error_code`, `message_ja`)**:
   - 成功・失敗を問わず常に同一構造の Envelope を返却する。ワークフロー側（層B）は `try...except` を書くことなく、`envelope.ok` のフラグのみでシンプルにフォールバック分岐を行えるようにした。
2. **例外を外に投げない（層A での吸収）**:
   - Neo4j / asyncpg の例外はすべて `traversal.py` 内部で捕捉し、`Envelope(ok=False, error_code=..., message_ja=...)` へマッピングして返す。これにより ADK のリトライ／エラーハンドリング契約を保護した。
3. **探索深さの固定 (`*1..3`)**:
   - 引数に動的な `depth` を持たせず、Cypher クエリ内に `*1..3` をリテラルとして固定埋め込みした。これにより「可変長パスのパラメータ化 / APOC」という未検証要素を v1 から排除し、安定稼働を優先（可変化は実験 4-2 へ申し送り）。
4. **結果並び順の決定論化 (`hops DESC, code ASC`)**:
   - 前提科目探索（`find_prerequisites`）は「先に履修すべき基礎科目が先頭に来る」よう `hops DESC` とし、同深度は科目コード順 `code ASC` で tie-break を固定。同一クエリで 3 回実行しても完全一致する再現性を Cypher レベルで保証した。
5. **トピック関連科目のスコア順ソート (`shared_count DESC`)**:
   - 共通トピック探索（`find_related_by_topic`）に `shared_count` の集計と `ORDER BY shared_count DESC, code ASC` を追加し、結果の非決定性を排除。
6. **`Candidate` モデルへの経路情報 (`path_codes`) 付与**:
   - 後段の Evidence 生成ノードが「どの履修パスを通ってその科目に至ったか」を説明文として組み立てられるよう、候補データに通過した講義コード一覧を保持させた。

---

## 5. 各選択肢の評価 (Pros & Cons)

### 選択肢 A: 個別クエリ発行 & 例外送出
- **メリット (+)**:
  - 初期実装が最も早く、ラッパー型（Envelope）の定義が不要。
- **デメリット・見送り理由 (-)**:
  - ワークフローの各ノードで `try...except` が乱立し、エージェントの制御フローが破綻しやすい。
  - ソート順が未定義な場合、実行ごとに返却順が変わり Golden テストが不安定になる。

### 選択肢 B: Envelope パターン ＋ 厳密合意契約 【採用案】
- **メリット (+)**:
  - DB 側と Agent 側の担当者が完全に非同期で並列実装を進められる。
  - エージェントのノード実装が極めてクリーン（`if not envelope.ok: return ...`）になる。
  - テストの再現性が 100% 担保され、回帰テストが容易。
- **デメリット・受容するリスク (-)**:
  - 探索深さが 3 段固定であるため、より深い前提条件チェーンを辿りたい場合は将来的に Cypher の拡張が必要（実験 4-2 で対応予定）。

---

## 6. 影響と結果 (Consequences)

- **良い影響 (Positive)**:
  - コミット `032033c`（初版実装）および `010d046`（PR #2）を経て、設計書（`experiment-3-2-design.md`）とコードの整合性が完全に一致した。
  - 後続のステップ 4（意図パーサ・Evidence 生成: コミット `3027342`）およびステップ 5（ADK ワークフロー通電: コミット `8560726`）において、結合時のインターフェース不一致トラブルが一切発生せず、スムーズな通電が実現した。
  - 実験 3-1 の MCP サーバーも、`traversal.py` の同一の 4 関数を呼び出す薄いラッパーとして存続でき、コードの二重化を防いだ。
- **留意点・今後の申し送り事項**:
  - 探索パス長（現在 1..3 固定）の動的パラメータ化は、オントロジー統合フェーズ（Phase 4 / 実験 4-2）にて再検討する。

---

## 7. 参考資料 (References)

- PR #2: [fix: traversal.py を合意契約に整合（Envelope・返却順・探索上限・層A例外処理・Candidate）](https://github.com/cyanosome/course-navigator/pull/2)
- Commit `032033c`, Commit `010d046`
- [Google Agent Development Kit (ADK) Official Documentation](https://github.com/google/agent-development-kit)
- 実験 3-2 設計書: `experiment-3-2-design.md` (§3, §4.1, §4.2, §4.3, §6)
