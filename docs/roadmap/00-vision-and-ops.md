## 1. プロジェクト理念と運用情報

### 定例ミーティング

- **開催日時**: 毎週水曜日 20:00〜21:00（最大23:00まで延長可）
- **タイムゾーン**: Asia/Tokyo
- **ビデオ通話リンク**: [Google Meet](https://meet.google.com/zca-atth-zoh)

### 非営利プロジェクト方針

本プロジェクトは **非営利の学術研究目的** で実施されます。

- API 利用料金等の運用コストと相殺できるような持続可能な運用枠組みを目指します。
- 万が一、プロジェクト活動を通じて利潤が発生した場合は、関与したメンバーの所属大学（卒業済みの場合は出身大学）に研究振興費として均等に寄付します。大学在籍経験がないメンバーがいる場合は一般社団法人情報処理学会へ寄付します。

---

## 2. フェーズ別全体像 (Overview)

```mermaid
flowchart TD
    P1["Phase 1: フルスタック基盤・統合環境の構築<br/>(Traefik / FastAPI / React / Postgres / Neo4j)"]
    P2["Phase 2: LLM Agent 疎通 & GraphRAG 入出力基盤の確立<br/>(Agent Communication / シードデータ探索 / 入出力UI整合)"]
    P3["Phase 3: 関西大学データ Ingestion & プロトタイプ検索・実験基盤<br/>(シラバス・系統図DAG・要覧要件 / 3モード探索 / DBS論文投稿)"]

    P4_0["Phase 4-0: プロジェクト体制拡充 & 開発/PM基盤整備<br/>(Google AI Community人集め / カンバン・Notion・Zotero / DNS・draw.io)"]

    subgraph Phase4Parallel ["Phase 4: 知識基盤(研究)・工学的改善・大学展開の3軸並行展開"]
        direction TB
        P4A["【Phase 4A: カリキュラム・知識基盤拡張（研究調査メイン）】<br/>・論文調査 & 広く公式カリキュラム比較調査・汎用スキーマ設計<br/>(CS2023 / ASCE / GAPC / ACS / CUPM / 医学コアカリ / APA 等)<br/>・学外Web教材 (MOOCs/OCW) Ingestion / 全国大会発表"]
        P4B["【Phase 4B: 工学的システム改善（ログ・評価・Frontend/Backend/DB）】<br/>・Query/Taskログ可視化・判定画面・リファクタ(cyano-paper/course-navi)<br/>・4Cのテスト結果に基づくFrontend/Backend/DBの工学的改修"]
        P4C["【Phase 4C: 実大学への全学展開・連携実証・資金対策】<br/>・関西大学 / 開志創造大学 / 駒澤大学 / 長崎大学 / Zen大学等<br/>・その他: Google AI Ambassador連携による他大学順次展開<br/>・研究クレジット・競争資金・持続運用モデル"]
    end

    P5["Phase 5: 全学・複数大学での本番運用 & 継続的適応<br/>(マルチ大学運用 / ユーザーフィードバックによる自動適応 / Active Learning)"]

    P1 --> P2
    P2 --> P3
    P3 ==> P4_0
    P4_0 ==> P4A
    P4_0 ==> P4B
    P4_0 ==> P4C

    P4A -. "多分野オントロジー・研究知見" .-> P4C
    P4C -. "テスト結果・実クエリ・課題フィードバック" .-> P4B
    P4B -. "改修済みFrontend/Backend/DB還元" .-> P4C

    P4A --> P5
    P4B --> P5
    P4C --> P5

    classDef done fill:#e8f5e9,stroke:#388e3c,stroke-width:2px,color:#1b5e20;
    classDef current fill:#e1f5fe,stroke:#0288d1,stroke-width:2px,color:#01579b;
    classDef future fill:#f5f5f5,stroke:#9e9e9e,stroke-width:2px,color:#616161;
    class P1,P2 done;
    class P3 current;
    class P4_0,P4A,P4B,P4C,P5 future;
```
