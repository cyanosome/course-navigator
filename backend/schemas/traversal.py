"""グラフ探索およびアンカー検索用のスキーマ定義。"""

from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """共通レスポンスエンベロープ。"""

    data: T | None = None
    status: str = "success"
    message: str | None = None


class AnchorHit(BaseModel):
    """PostgreSQL シラバス検索で特定されたアンカー講義。"""

    id: str
    code: str
    title: str
    instructor: str | None = None
    schedule: str | None = None
    credits: int | None = None
    syllabus_text: str | None = None


class Candidate(BaseModel):
    """Neo4j グラフ探索で抽出された関連・前提・後続講義の候補。"""

    id: str | None = None
    code: str | None = None
    title: str | None = None
    distance: int | None = None
    topics: list[str] = []
