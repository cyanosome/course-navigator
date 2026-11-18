# Phase 3: 関西大学データ Ingestion & プロトタイプ検索・実験基盤 【進行中】

_（方針改訂: 2026-10-29 / [ADR-0015](../adr/0015-pivot-from-komazawa-to-kansai-ingestion.md)）_

> [!NOTE]
> **長崎大学・駒澤大学から関西大学へのピボット経緯**
>
> 1. **長崎大学からのピボット ([ADR-0011](../adr/0011-pivot-from-nagasaki-to-komazawa-ingestion.md))**: 一般公開シラバスが教養科目のみで専門科目が学外非公開だったため、身近な駒澤大学へピボット。
> 2. **駒澤大学から関西大学へのピボット ([ADR-0015](../adr/0015-pivot-from-komazawa-to-kansai-ingestion.md))**: 駒澤大学の公式Webサーバー停止に伴い、シラバスインデックス等の外部取得が停止したため凍結保持。代替として、認証不要の静的HTMLシラバスおよび履修系統図ベクターPDFが取得可能で、研究チームに関西大学の所属学生が在籍する **関西大学（環境都市工学部等）へのピボット** を実施しました。

- **目的と基本方針**:
  - **学内公式データ（シラバス・系統図・要覧）の徹底的な構造化と高信頼な履修検索基盤の確立** にフォーカスする（[長期Ingestion実装計画書](../long_term_ingestion_plan.md) 参照）。
  - 意味的適合性とカリキュラム順序制約のトレードオフを解明する **直交探索アブレーション実験（Pure Vector vs Pure Graph vs Hybrid）** を実施し、その成果を査読付き研究会に論文投稿する。

## サブフェーズ進捗

- [x] **Phase 3.0: 関西大学シラバス & 履修系統図 Ingestion 基盤**
  - 関西大学シラバス全1,029科目の静的HTMLパース（固有DOM ID 33項目を完全抽出）。
  - 環境都市工学部 履修系統図ベクターPDFからのグループDAG（有向グラフ）抽出。
  - PostgreSQL（courses）および Neo4j（Course, CurriculumGroup, リレーション）へのロードとクロスDB完全突合検証ツールの実装（[ADR-0016](../adr/0016-neo4j-curriculum-dag-and-course-loader-architecture.md), [ADR-0017](../adr/0017-postgres-schema-and-verification-tool-for-course-ingestion.md)）。
- [x] **Phase 3.5: 大学要覧・履修要件パイプライン**
  - 大学要覧PDF（`all_page.pdf`）の学部スプリット処理。
  - 科目区分（必修/選必/選）および卒業要件の決定論的パースと DB（PostgreSQL & Neo4j）格納・整合性検証。
- [x] **Phase 3.6: シラバス Embedding 生成 & マルチベクトル基盤**
  - シラバス統合テキストから Embedding（Gemini 768次元 / text-embedding-3-small 1536次元）を生成・キャッシュ。
  - Neo4j Vector Index（`course_embedding_index`）の構築。
  - NumPy による高速コサイン類似度マトリクス計算と、セマンティック類似度エッジ（`[:SIMILAR_TO]`）の永続化。
  - _（※本番アプリでは Neo4j Vector Index を採用し、pgvector による Pure Vector 探索は比較実験専用ブランチに分離）_
- [x] **Phase 3.7: 3モード探索エンジン & 評価ハーネス基盤（実装完了・評価実施中）**
  - Neo4j Cypher による 3つの探索モード（Pure Graph / Similarity Vector / Proposed Hybrid）のバックエンド実装。
  - LLM Agent 用 Cypher 探索ツール群（`agent/cypher_tools.py`）の実装。
  - フロントエンド検証 UI（`/test4-1` CypherSearchTest）および Navi 統合 API の実装。

## 主なタスク・実験項目

- [x] **実験 3-1: 関西大学 シラバス & カリキュラムの Ingestion**
  - シラバス・履修系統図の収集・抽出・投入完了。
- [x] **実験 3-2: 実データに基づく GraphRAG 検索・推論の結合**
  - 1,029科目の実データに対する Neo4j Cypher 探索と Agent ツールの連携完了。
- [x] **タスク 3-3: Frontend の拡張とユーザー向け微調整**
  - 学生が実際に利用できるよう、チャット UI の洗練、前提科目ツリー表示補助、Navi画面の最適化を実施。
- [x] **実験 3-4: 学生インタビュー実験（定性評価）**
  - 関西大学の所属学生を対象にプロトタイプを試用してもらい、「履修判断の納得感や探索摩擦がどう変化したか」をインタビューにより定性検証。
- [x] **実験 3-5: データベースによる直交探索比較実験（Pure Vector vs Pure Graph vs Hybrid）**
  - 情報モダリティの観点で直交する 3方式（① PostgreSQL/pgvector による意味検索、② Neo4j によるトポロジー走査、③ Neo4j 内蔵 Vector+Cypher による提案ハイブリッド手法）を実装・比較。
  - 意味的適合度（Precision@10）、前提順序充足度（Path Coverage [%]）、および応答性能（P95 Latency [ms]）をベンチマーク測定し、意味適合性とカリキュラム順序制約の相補的トレードオフを定量的に実証。

## Phase 3 完了マイルストーン

- **学会論文投稿 & 発表: 冬のDBS/IFAT/DE合同研究会2026**
  - **対象会議**: 情報処理学会 第184回 DBS / 第165回 IFAT / 電子情報通信学会 DE 合同研究会（2026年12月18日〜19日、金沢＋オンライン）
  - **投稿締切**: **2026年11月13日（金）原稿締切**
  - **内容**: 学内データ構造化基盤および実験 3-5 の比較検証結果を取りまとめた研究論文を投稿（※発表と投稿のタイムラグを考慮し、論文投稿をもって Phase 3 の達成マイルストーンとする）。
  - [ ] **発表準備**: データベースワークショップ（DBS/IFAT/DE）に向けた発表動画とスライドの作成。
