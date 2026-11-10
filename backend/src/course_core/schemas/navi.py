"""Pydantic schemas aligning with origin/frontend:frontend/src/navi/types.ts."""

from typing import List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

Term = Literal["春", "秋", "通年"]
Kind = Literal["必修", "選択", "他学部"]
GradCategory = Literal["必修", "選択", "教養"]


class TeacherKnown(BaseModel):
    status: Literal["known"] = "known"
    name: str


class TeacherNotInSyllabus(BaseModel):
    status: Literal["notInSyllabus"] = "notInSyllabus"


class TeacherNotDelivered(BaseModel):
    status: Literal["notDelivered"] = "notDelivered"


TeacherInfo = Union[TeacherKnown, TeacherNotInSyllabus, TeacherNotDelivered]


class Frame(BaseModel):
    id: str
    year: int
    name: str
    plain: str
    common: bool = False


class FrameEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(..., alias="from")
    to: str


class NaviCourse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str
    name: str
    short: Optional[str] = None
    frameId: Optional[str] = None
    faculty: Optional[str] = None
    year: int = 1
    yearRange: Optional[str] = None
    term: Term = "春"
    slots: List[str] = Field(default_factory=list)
    slotNote: Optional[str] = None
    credits: Optional[float] = None
    kind: Optional[Kind] = None
    grad: Optional[GradCategory] = None
    teacher: TeacherInfo = Field(default_factory=TeacherNotInSyllabus)
    learn: str = ""
    summary: str = ""
    plan: List[str] = Field(default_factory=list)
    grading: Optional[str] = None
    textbook: Optional[str] = None
    syllabusUrl: Optional[str] = None


class InterestExtra(BaseModel):
    code: str
    why: str
    source: str


class Interest(BaseModel):
    id: str
    label: str
    targets: List[str] = Field(default_factory=list)
    extras: List[InterestExtra] = Field(default_factory=list)


class GradNeed(BaseModel):
    category: GradCategory
    need: float


class Requirements(BaseModel):
    total: float
    termCap: float = 24.0
    needs: List[GradNeed] = Field(default_factory=list)


class Department(BaseModel):
    id: str
    university: str
    faculty: str
    name: str
    dataVersion: str = "2026.1"
    syllabusYear: int = 2026
    frames: List[Frame] = Field(default_factory=list)
    edges: List[FrameEdge] = Field(default_factory=list)
    courses: List[NaviCourse] = Field(default_factory=list)
    interests: List[Interest] = Field(default_factory=list)
    requirements: Optional[Requirements] = None
