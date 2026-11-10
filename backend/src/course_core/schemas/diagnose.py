"""診断の API（GET /diagnose/config・POST /diagnose/plan、navi-v1）の入力と応答の型。項目名は snake_case。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

__all__ = [
    "DiagnoseConfigOut",
    "DiagnosePlanIn",
    "DiagnosePlanOut",
    "PlanCourseOut",
    "PlanTermOut",
    "ReasonOut",
]


class DiagnoseConfigOut(BaseModel):
    department_id: str
    version: str
    config: dict[str, Any]  # 設定のファイルの JSON のまま（境界）


class DiagnosePlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department_id: str
    config_version: str
    # single・multi は選択肢の id の配列、scale5 は 1〜5
    answers: dict[str, list[StrictStr] | StrictInt]


class ReasonOut(BaseModel):
    primitive: str
    text: str


class PlanCourseOut(BaseModel):
    syllabus_id: str
    name: str
    credits: float
    slots: list[str]  # 例 ["火2"]。曜限の読めない科目（集中など）は []
    slot_note: str | None  # 読めなかった曜限の元の文字列（例「他」）
    score: float
    reasons: list[ReasonOut]  # 寄与の大きい primitive から最大2つ


class PlanTermOut(BaseModel):
    year: int
    term: Literal["春", "秋"]
    credits_total: float
    courses: list[PlanCourseOut]  # 選んだ順（点の高い順）


class DiagnosePlanOut(BaseModel):
    config_version: str
    answers_digest: str
    terms: list[PlanTermOut]  # 時系列の順（年 → 春 → 秋）
