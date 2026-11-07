"""研究の API（R1〜R9、api-contract.md 3 章）の入力と応答の型。"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from course_core.research.events import ClientEventType
from course_core.research.variants import VariantFlags

__all__ = [
    "BlockPlan",
    "BlockStartOut",
    "ClientEvent",
    "ConsentIn",
    "EventBatchIn",
    "EventBatchOut",
    "SessionOut",
    "SessionStartIn",
    "VariantOut",
]

MAX_EVENTS_PER_BATCH = 100


class SessionStartIn(BaseModel):
    token: str = Field(..., min_length=12, max_length=64)


class BlockPlan(BaseModel):
    block: int  # 0 = 練習、1・2
    condition_id: str  # 伏せた記号（K/M/J/L。練習は "P"）
    task_set_id: str  # P1・P2・練習は "practice"
    task_ids: list[str]


class VariantOut(BaseModel):
    variant_id: str
    condition_id: str | None
    flags: VariantFlags
    flags_version: str


class SessionOut(BaseModel):
    session_id: str
    pid: str
    study_id: str
    sequence_id: str
    mode: Literal["onsite", "remote"]
    department_id: str
    consent_version: str
    consent_recorded: bool
    blocks: list[BlockPlan]
    current_block: int | None  # 開いているブロック。開いていなければ None
    variant: VariantOut | None  # 開いているブロックの旗
    backend_version: str  # 環境変数 APP_COMMIT（未設定なら "unknown"）
    completed_blocks: list[int]  # 終えたブロック（開き直したときにどこから続けるか）
    last_seq: int  # 受け付けた seq の最大（開き直したときに seq を続けるため。まだ無ければ 0）


class ConsentIn(BaseModel):
    consent_version: str = Field(..., min_length=1, max_length=32)
    form_serial: str = Field(..., pattern=r"^[0-9A-Za-z-]{1,16}$")  # 紙の同意書の通し番号
    agreed: bool


class BlockStartOut(BaseModel):
    plan: BlockPlan
    variant: VariantOut


class ClientEvent(BaseModel):
    event_id: UUID
    event_type: ClientEventType
    seq: int = Field(..., ge=1)
    ts_client: datetime
    task_id: str | None = Field(None, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)  # 境界の型。種類ごとの検査は events.payload_warnings


class EventBatchIn(BaseModel):
    events: list[ClientEvent] = Field(..., min_length=1, max_length=MAX_EVENTS_PER_BATCH)


class EventBatchOut(BaseModel):
    accepted: int
    duplicates: int
    last_seq: int
    warnings: list[str]
