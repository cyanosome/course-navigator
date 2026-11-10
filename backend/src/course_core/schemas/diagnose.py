"""診断の API（GET /diagnose/config・POST /diagnose/plan、navi-v1）の入力と応答の型。項目名は snake_case。"""

from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, StringConstraints

__all__ = [
    "COMPLETED_MAX",
    "REGISTERED_IDS_PER_TERM_MAX",
    "REGISTERED_TERMS_MAX",
    "CourseStatus",
    "DiagnoseConfigOut",
    "DiagnosePlanIn",
    "DiagnosePlanOut",
    "HistorySyllabusId",
    "PlanCourseOut",
    "PlanTermOut",
    "ReasonOut",
    "RegisteredTermIn",
    "TermIn",
]

# 履修の状況（start・completed・registered）の大きさの上限（4年分の履修が入る程度）
COMPLETED_MAX: Final = 200
REGISTERED_TERMS_MAX: Final = 8
REGISTERED_IDS_PER_TERM_MAX: Final = 40

HistorySyllabusId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
# planned: 診断が選んだ科目、registered: 利用者がその学期にもう登録した科目（registered で送られたもの）
CourseStatus = Literal["planned", "registered"]


class DiagnoseConfigOut(BaseModel):
    department_id: str
    version: str
    config: dict[str, Any]  # 設定のファイルの JSON のまま（境界）


class TermIn(BaseModel):
    """学期（start）。設定の scope の学期のどれか。"""

    model_config = ConfigDict(extra="forbid")

    year: StrictInt
    term: Literal["春", "秋"]


class RegisteredTermIn(TermIn):
    """その学期にもう登録した科目（registered の1学期分）。"""

    syllabus_ids: list[HistorySyllabusId] = Field(..., max_length=REGISTERED_IDS_PER_TERM_MAX)


class DiagnosePlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department_id: str
    config_version: str
    # single・multi は選択肢の id の配列、scale5 は 1〜5
    answers: dict[str, list[StrictStr] | StrictInt]
    # 以下は任意（履修の状況。送らなければ前と同じプラン）。検査と効き方は course_core.diagnose.history
    start: TermIn | None = None  # この学期から先だけを埋める
    completed: list[HistorySyllabusId] | None = Field(None, max_length=COMPLETED_MAX)  # 履修済みの科目
    registered: list[RegisteredTermIn] | None = Field(None, max_length=REGISTERED_TERMS_MAX)  # 登録済みの科目


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
    reasons: list[ReasonOut]  # 寄与の大きい primitive から最大2つ（登録済みの科目は []）
    status: CourseStatus = "planned"


class PlanTermOut(BaseModel):
    year: int
    term: Literal["春", "秋"]
    credits_total: float  # 登録済みの科目の単位を含む
    courses: list[PlanCourseOut]  # 登録済みの科目（送られた順）→ 選んだ順（点の高い順）


class DiagnosePlanOut(BaseModel):
    config_version: str
    answers_digest: str
    # 履修の状況（start・completed・registered）の指紋。どれも送られなければ（空の配列も）None
    context_digest: str | None = None
    terms: list[PlanTermOut]  # 時系列の順（年 → 春 → 秋）。start があれば start から先だけ
