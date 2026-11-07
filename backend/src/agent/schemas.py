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
    "CourseGroundedAnswer",
    "DropReason",
    "DroppedSuggestion",
    "Evidence",
    "GroundedAnswer",
    "Mode",
    "PlanAnswerPayload",
    "PlanChange",
    "PlanSuggestion",
    "PlanSuggestions",
    "SearchIntent",
    "Source",
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


class Source(BaseModel):
    """回答の出典1件。LLM の生成テキストではなく DB の行だけから組み立てる。"""

    code: str  # courses の行なら syllabus_id、シードの表の行なら科目コード
    title: str
    instructor: str | None = None
    schedule: str | None = None
    credits: float | None = None  # courses は numeric(3,1)（例 2.0）
    excerpt: str = ""  # シラバス本文の冒頭抜粋
    origin: str  # 例 "postgres:courses"（どの DB のどこから引いたか）
    url: str | None = None  # courses の detail_url（シラバスの原文）。シードの表には無いので None


class GroundedAnswer(BaseModel):
    """attach_sources の出力。AnswerPayload に DB 由来の出典と検証結果を足したもの。"""

    answer: str
    cited_codes: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    # LLM が引用したが DB に存在しない（または検証できなかった）コード。出典には出さない。
    unverified_codes: list[str] = Field(default_factory=list)
    # 検証できなかった理由など（サイレント失敗の禁止）。
    notes: list[str] = Field(default_factory=list)


# --- 関西（courses）向け: プランの微修正（A1 の plan_context） ----------------------------


class PlanChange(BaseModel):
    """LLM が出す、プランに足す・外す科目1件。"""

    syllabus_id: str
    reason: str = ""  # ツールで確かめた事実に基づく理由（曜限・学期・まとまりなど）


class PlanAnswerPayload(AnswerPayload):
    """関西向けの LLM の出力。今のプランが渡されたときだけ add・remove を埋める。"""

    add: list[PlanChange] = Field(default_factory=list)
    remove: list[PlanChange] = Field(default_factory=list)


class PlanSuggestion(BaseModel):
    """照合を通った提案1件。title は DB の科目名（外す科目がプランにだけあって DB に無いときは None）。

    status は外す科目が登録済み（plan_context.registered にある）なら registered。ほかは planned。
    """

    syllabus_id: str
    title: str | None = None
    reason: str = ""
    status: Literal["planned", "registered"] = "planned"


# already_in_plan: 足す科目がもうプランにある。診断の答えがある微修正では、同じ名前の別クラスを、元の科目を外す案と
#   組にせずに足す案も含む（同じ科目が2つになるため）
# not_candidate: 足す科目が、サーバーが渡した「選べる科目」に無い（診断の答えがある微修正だけ）
# locked: 外す科目が、系統図に載る科目（外さない印を付けて渡したもの）で、同じ学期の別クラスへ移す組でもない
#   （診断の答えがある微修正だけ。登録済みの科目は locked にしない）
# completed: 足す科目が、履修済み（plan_context.completed）の科目と同じ名前（診断の答えがある微修正で、completed を送ったときだけ）
DropReason = Literal["not_in_db", "already_in_plan", "not_in_plan", "not_candidate", "locked", "completed"]


class DroppedSuggestion(BaseModel):
    """照合で外した提案。action は LLM が足す（add）・外す（remove）のどちらで出したか。"""

    action: Literal["add", "remove"]
    syllabus_id: str
    reason: DropReason


class PlanSuggestions(BaseModel):
    """プランの微修正の提案（照合の後）。足す科目は DB に実在しプランに無いもの、外す科目はプランにあるもの。

    診断の答えがある微修正では、さらに足す科目は「選べる科目」の中のもの、外す科目は系統図に載らないものだけ。
    ただし同じ学期の同じ名前の別クラスへ移す組（外す＋足す）は、系統図の科目でも残す。
    登録済みの科目を外す案は残し、status を registered にする。履修済みと同じ名前の科目を足す案は completed で外す。
    """

    add: list[PlanSuggestion] = Field(default_factory=list)
    remove: list[PlanSuggestion] = Field(default_factory=list)
    dropped: list[DroppedSuggestion] = Field(default_factory=list)


class CourseGroundedAnswer(GroundedAnswer):
    """関西の出典付与ノードの出力。プランが渡されなかったときは plan_suggestions が None。"""

    plan_suggestions: PlanSuggestions | None = None
