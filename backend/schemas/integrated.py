"""複合（Postgres + Neo4j）疎通テスト用の入力スキーマ。"""

from pydantic import BaseModel


class IntegratedSyllabusInput(BaseModel):
    code: str
    title: str
    instructor: str
    schedule: str
    credits: int
    syllabus_text: str | None = None
    prerequisite_codes: list[str] = []
    topics: list[str] = []
