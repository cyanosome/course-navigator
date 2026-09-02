"""PostgreSQL 疎通テスト用の入力スキーマ。"""

from pydantic import BaseModel


class PostgresTestInput(BaseModel):
    title: str
    description: str | None = None
