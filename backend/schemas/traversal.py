"""グラフ探索およびアンカー検索用のスキーマ定義（設計書 実験3-2 §3 準拠）。"""

from typing import Generic, Literal, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")

AnchorStatus = Literal["exact", "alias", "ambiguous", "not_found", "no_anchor"]
Reason = Literal["prerequisite_of", "requires", "shares_topic"]
EvidenceKind = Literal["prereq_path", "topic_share"]
ErrorCode = Literal["GRAPH_UNAVAILABLE", "RDB_UNAVAILABLE", "NOT_FOUND"]


class Envelope(BaseModel, Generic[T]):
    """層A（graph/traversal.py）の戻り値。例外を外に投げない契約（§6）。

    層B（ADK 関数ノード）は try/except を書かず `ok` を見て分岐するだけなので、
    成功・失敗のどちらでも必ずこの器で値が返ることが前提になっている。
    """

    ok: bool
    data: T | None = None
    error_code: ErrorCode | None = None
    message_ja: str = ""


class AnchorHit(BaseModel):
    """PostgreSQL シラバス検索（ILIKE フォールバック）で特定されたアンカー講義。

    §4.3 の段3 と同じ扱いで、1件に確定したときだけ code / title が埋まる。
    2件以上ヒットした場合は anchor_status="ambiguous" とし、候補は返さずに
    alternatives へコード昇順の上位3件だけを入れる。
    """

    id: str | None = None
    code: str | None = None
    title: str | None = None
    anchor_status: AnchorStatus = "no_anchor"
    alternatives: list[str] = Field(default_factory=list)
    instructor: str | None = None
    schedule: str | None = None
    credits: int | None = None
    syllabus_text: str | None = None


class Evidence(BaseModel):
    """日本語の根拠断定文（§4.4）。生成するのは rank_candidates（層B）。

    層A は探索結果を返すだけなので、ここでは常に空のまま渡す。
    """

    kind: EvidenceKind
    text: str
    edge_refs: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    """Neo4j グラフ探索で抽出された前提・後続・関連講義の候補。"""

    code: str
    title: str
    hops: int  # アンカーからの距離（トピック検索では 1 固定）
    path_codes: list[str] = Field(default_factory=list)
    shared_topics: list[str] = Field(default_factory=list)
    reason: Reason
    evidence: list[Evidence] = Field(default_factory=list)
