"""Neo4j 疎通テスト用の入力スキーマ。"""

from pydantic import BaseModel


class Neo4jTestInput(BaseModel):
    title: str
    description: str | None = None
    prerequisite_title: str | None = None
