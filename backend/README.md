# Course Navigator Backend

Course Navigator のバックエンド API、エージェント（Google ADK / MCP）、Neo4j 連携サービスを提供します。

## 構成
- `src/api`: FastAPI ルーターおよびエンドポイント
- `src/agent`: Google ADK / MCP による対話型エージェント
- `src/services/embedding.py`: Google 公式 SDK (`google-genai`) による Embedding 生成サービス & 疎通診断 CLI
- `src/course_core`: 共通設定、DB リポジトリ、ドメインモデル

## Gemini API 疎通診断 (CLI)
Gemini Embedding API の疎通確認や API キーの形式チェックを実行できます。

```bash
# コンテナ内で実行（環境変数 GEMINI_API_KEY を検証）
docker compose exec backend python -m src.services.embedding

# 特定の API キーを直接指定してテスト
docker compose exec backend python -m src.services.embedding --key "YOUR_API_KEY"
```
