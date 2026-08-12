"""環境変数から DB 接続設定を読み込むモジュール。

秘密値（パスワード）にはフォールバック（デフォルト値）を設けない。
未設定の場合は起動時（lifespan）に明示的なエラーを送出する。
モジュール読み込みだけでは副作用を起こさない（`import main` を安全に保つ）。
"""

import os

# PostgreSQL 接続設定
DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "coursenavigator")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Neo4j 接続設定
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

# 未設定時に起動を止める必須（秘密）環境変数
REQUIRED_SECRETS = ("DB_PASSWORD", "NEO4J_PASSWORD")


def validate_required_env() -> None:
    """必須の秘密環境変数が設定されているか検証する。

    未設定のものがあれば RuntimeError を送出する。lifespan（起動時）から呼び出す。
    """
    missing = [name for name in REQUIRED_SECRETS if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "必須の環境変数が設定されていません: "
            + ", ".join(missing)
            + "。compose 実行時は .env から供給してください。"
        )
