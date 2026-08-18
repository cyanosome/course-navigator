"""ADK ノードの入出力スキーマ（設計書 実験3-2 §3 準拠）。

`AnchorStatus` / `Reason` / `EvidenceKind` / `Envelope` / `AnchorHit` / `Evidence` /
`Candidate` は層A（`course_core.graph.traversal`）と共有する契約なので
`course_core.schemas.traversal` の定義をそのまま使う。ここで再定義すると
層A と層B で別の型ができてしまい、Envelope の中身をそのまま流せなくなる。
"""

from typing import Literal

from pydantic import BaseModel, Field

from course_core.schemas.traversal import AnchorStatus, Candidate, Evidence

__all__ = [
    "AnchorStatus",
    "AnswerPayload",
    "Candidate",
    "CandidateSet",
    "Evidence",
    "Mode",
    "SearchIntent",
    "UnclearKind",
]

Mode = Literal["next_step", "prereq", "topic", "unclear"]
UnclearKind = Literal["no_mode", "not_found", "ambiguous", "out_of_scope", "decline"]


class SearchIntent(BaseModel):
    """parse_intent の出力。LLM を使わず決定論的に生成する。"""

    mode: Mode
    anchor_code: str | None = None  # 例 "GMS-301"
    anchor_title: str | None = None  # 例 "データサイエンス入門"
    anchor_status: AnchorStatus = "no_anchor"
    alternatives: list[str] = Field(default_factory=list)  # ambiguous / not_found 時の上位3件
    unclear_kind: UnclearKind | None = None
    raw_question: str
    matched_rule: str = ""  # トレース用 例 "keyword:次 / alias:データサイエンス入門"


class CandidateSet(BaseModel):
    """expand_* / search_by_topic → rank_candidates → compose_answer を流れる唯一の入れ物。

    Event.output が1つという ADK の制約下で trace に必要な情報（mode / anchor /
    anchor_status / matched_rule）を最終ノードまで運ぶため、intent を丸ごと抱える。
    """

    intent: SearchIntent
    candidates: list[Candidate] = Field(default_factory=list)
    traversed_edges: list[str] = Field(default_factory=list)
    # 例: "GMS-301 <-REQUIRES_PREREQUISITE- GMS-303"（矢印の向きが実際のリレーション方向）
    notes: list[str] = Field(default_factory=list)


class AnswerPayload(BaseModel):
    answer: str  # 日本語の回答文
    cited_codes: list[str] = Field(default_factory=list)  # 回答文で言及した科目コード
