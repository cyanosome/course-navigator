# Ingestion Pipeline

大学シラバス等のデータ収集（スクレイピング / PDFパース）、データ精査・構造化（LLM）、および GraphRAG 用インデックス構築（Embedding / ナレッジグラフ生成）を行い、PostgreSQL / Neo4j へ投入する独立バッチパイプラインです。

## 主な役割と構成

- **データ収集 (Extract)**: 大学Webシラバスのクローリング、PDFや構造化シラバスデータの取得。
- **データ構造化・GraphRAG構築 (Transform / Indexing)**:
  - LLMを用いた科目概要の構造化・前提/後続関係の抽出
  - 検索・レコメンド用テキストの Embedding 生成
- **データベース格納 (Load)**:
  - PostgreSQL へのシラバスメタデータ登録
  - Neo4j への科目ノード・リレーション投入（Cypher / APOC / LOAD CSV 活用）

## 実行方法

Docker Compose の `tools` プロファイルで管理されています。

```bash
# Ingestion コンテナのビルド・起動
docker compose --profile tools run --rm ingestion
```
