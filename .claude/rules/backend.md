---
paths: ["backend/**"]
---

# backend 運用ルール

- FastAPI（Python >=3.14）、依存管理は uv。追加時は `uv add` を使い `uv.lock` をコミットに含める。
- DB 接続情報は環境変数から取得し、秘密値をコードに直書きしない。ホスト・ポート・DB 名・ユーザー名など非秘密の接続先は `os.getenv(..., デフォルト値)` でフォールバックを設けてよい。パスワード等の秘密値にはデフォルト値を置かず `os.getenv(名前)` のみとし、未設定なら起動時（`lifespan` から呼ぶ `config.validate_required_env()`）に明示的なエラーで停止させる。
- PostgreSQL 接続プール・Neo4j ドライバの初期化は `lifespan` 内に閉じ込め、モジュールトップレベルで DB 接続を行わない（`import main` だけで副作用が起きないように保つ）。
- 新規テーブル定義・スキーマ変更は `lifespan` 内の `CREATE TABLE IF NOT EXISTS` に追記する形で行う。
- エンドポイント追加時は Pydantic の `BaseModel` で入力スキーマを定義する。
- コミット前に `uv run python -c "import main"` が通ることを確認する。
