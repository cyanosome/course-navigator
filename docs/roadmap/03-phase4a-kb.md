# Phase 4-0: プロジェクト体制拡充 & 開発/PM基盤整備 【次期フェーズ導入】

Phase 3（論文投稿・関西大学基盤確立）の完了後、プロジェクトは単一大学の限定領域から **「広く公式カリキュラムの知識基盤化（Phase 4A）」「Agentシステム研究の学術的深化（Phase 4B）」「複数大学での全学展開と教育共同研究（Phase 4C）」** の3軸が並行して相互フィードバックする体制へ移行します。

- **目的**: 3軸並行推進を支えるリソースとプロジェクト運用・開発基盤を整備し、開発・研究・各大学展開の持続可能な分業体制を確立する。
- **体制・人集め・PM基盤**:
  - **コミュニティ人集め**: Google AI Community 等の外部コミュニティから、プロジェクトメンバーを幅広く募集。
  - **役割の二層化**:
    - **コア技術・研究開発（Core Tech & Research）**: Agent推論設計、GraphRAG基盤、Neo4j/PostgreSQLアーキテクチャ、評価ベンチマーク（Phase 4A/4Bを牽引）。
    - **キャンパス展開・データパイプライン（Campus Ambassadors & Ingestion）**: 各大学のシラバス・系統図・要覧の収集・パース・整合性検証、学内学生ヒアリング、実証実験の運用を主軸に担当するメンバー（Phase 4Cを牽引）。
  - **オンボーディング基盤の整備**: Onboard MTG、スライド（パワポ）での紹介、キャンパスアンバサダーとの連携方法の確立。
  - **プロジェクト管理・論文整理環境の構築**:
    - タスクのカンバンビュー導入（誰が何をしていて進捗がどうなっているかを可視化）。
    - Ambassadors / Engineers の分業や長期化を見据えた Notion の整理・復活（議事録・論文・各種情報の保管ルール統一）。
    - Google Drive + Zotero 環境による論文整理・引用管理基盤の構築。
- **共通開発・インフラ基盤の整備**:
  - **DNS 設定**: 公開・検証環境向けのドメイン/DNSルーティング確立。
  - **設計・コードの可視化と抽象化**:
    - [draw.io](https://app.diagrams.net/) でシステム全体の流れを整理し、抽象化した設計を策定。
    - ディレクトリ構成と関数を整理し、`cyanosome` と `akiha` が互いに相手のコードを把握できる状態にする。

---

# Phase 4A: カリキュラム・知識基盤拡張 (Curriculum & Knowledge Base)

- **目的**: 情報分野（CS2023）に閉じず、大学教育における国内外の主要な公式基準カリキュラムを幅広く調査・統合し、学問横断的な汎用知識オントロジー基盤を構築する。学外Web教材（MOOCs/OCW）も統合し、多層的な知識グラフを完成させる。
- **タスク・実験項目**:
  - **Phase 4A-0: 論文調査**
    - カリキュラムオントロジー、教育標準知識ベース、シラバスと標準カリキュラムの自動マッピングに関する関連研究・既存手法の論文調査。
  - **Phase 4A-1: 広く公式カリキュラムの比較調査 & 汎用スキーマ設計**
    - 大学教育で採用される多分野の公式カリキュラムの構造（Knowledge Area, Unit, Topic, Learning Outcomes, Competencies）を調査・比較。
    - **調査対象候補（学問分野別BoK / 標準カリキュラム）**:
      - **全分野横断（上位メタ・フレームワーク）**:
        - 英国 QAA: Subject Benchmark Statements（全分野網羅・統一フォーマット）
        - 日本学術会議: 大学教育の分野別質保証のための教育課程編成上の参照基準（30以上の学問分野）
      - **情報・工学分野**:
        - 情報科学: ACM/IEEE CS2023
        - 土木工学: ASCE CEBOK3 (Civil Engineering Body of Knowledge)
        - システム工学: BKCASE SEBoK (Systems Engineering Body of Knowledge)
        - 製造・機械工学: SME MEBOK / Four Pillars of Manufacturing Knowledge
        - 工学汎用認定基準: IEA GAPC (Graduate Attributes and Professional Competencies / Washington Accord)
      - **自然科学・数理分野**:
        - 化学: ACS Guidelines and Evaluation Procedures for Bachelor's Degree Programs
        - 生物学・生命科学: AAAS/NSF Vision and Change & BioSkills Guide
        - 物理学: IOP The Core of Physics & Graduate Skills Base
        - 数学: MAA CUPM Curriculum Guide to Majors in the Mathematical Sciences
      - **医療・健康科学分野**:
        - 医学（日本）: 文部科学省 医学教育モデル・コア・カリキュラム（歯学・薬学・看護学含む）
        - 医学（国際）: Royal College of Physicians and Surgeons of Canada / CanMEDS Physician Competency Framework
        - 薬学（米国）: AACP CAPE Educational Outcomes
        - 看護学（米国）: AACN The Essentials (Core Competencies for Professional Nursing Education)
      - **社会科学分野**:
        - 心理学: APA Guidelines for the Undergraduate Psychology Major (Version 3.0)
        - 経済学: QAA Subject Benchmark Statement: Economics
        - 経営学: AACSB 2020 Guiding Principles and Standards for Business Accreditation
        - 法学: ABA Standards and Rules of Procedure (Chapter 3: Learning Outcomes)
        - 社会学: ASA The Sociology Major in the Changing Landscape of Higher Education
      - **人文学分野**:
        - 歴史学: AHA History Tuning Project (History Tuning Reference Points)
        - 哲学: QAA Subject Benchmark Statement: Philosophy
        - 言語学: LSA Guidelines for College and University Linguistics Programs
        - 文学・語学: QAA Subject Benchmark Statement: Languages, Cultures and Societies / MLA English
    - **成果物**: 専門分野を問わず統一的に格納可能な Neo4j 汎用カリキュラムオントロジースキーマの策定。
  - **Phase 4A-2: 多分野オントロジーのグラフモデリング & Ingestion**
    - 調査した各公式カリキュラムの決定論的パースと Neo4j ロード。
    - LLMを用いた学内科目と公式カリキュラムの知識単位との自動推論マッピング（`[:MAPS_TO]`）。
  - **Phase 4A-3: 学外Web教材 (MOOCs / OCW) との統合**
    - 大学公開講座（OCW）や MOOCsを収集し、公式カリキュラムのトピックに接続。学内科目だけでは満たせない学習目標を補完推薦できる多層グラフを完成。
  - **Phase 4A-4: 情報処理学会 第89回全国大会での発表（内容未定）**
    - 情報処理学会 第89回全国大会（3月発表 / 1月6日論文締切）に向けた発表（発表内容は Phase 4A の進捗・調査結果に応じて決定）。
