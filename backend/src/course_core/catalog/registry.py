"""学科の登録（departments.json）と、まとまりの補足（group_meta/<dept_id>.json）の読み込み。

DB に学科の表は無いので、dept_id を PostgreSQL のキー（年度・学部コード・学科コード）と
Neo4j の CourseGroup の faculty・department の名前に結びつける（api-contract.md 2.9）。
"""

import json
from functools import cache
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "DepartmentEntry",
    "GroupMeta",
    "GroupMetaEntry",
    "InterestMeta",
    "load_departments",
    "load_group_meta",
]

_CATALOG_DIR: Final = Path(__file__).resolve().parent
_DEPARTMENTS_PATH: Final = _CATALOG_DIR / "departments.json"
_GROUP_META_DIR: Final = _CATALOG_DIR / "group_meta"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PgKey(_Strict):
    academic_year: int
    faculty_code: str  # graduation_requirements.faculty_code（例 "320"）
    department_code: str  # graduation_requirements / course_requirements の department_code（例 "031"）


class Neo4jKey(_Strict):
    faculty: str  # CourseGroup.faculty と同じ文字列
    department: str  # CourseGroup.department と同じ文字列


class DepartmentEntry(_Strict):
    id: str
    university: str
    faculty: str
    name: str
    syllabus_year: int
    data_version: str
    pg: PgKey
    neo4j: Neo4jKey


class GroupMetaEntry(_Strict):
    name: str | None = None  # 画面の表記。無ければ label から作る
    plain: str | None = None  # 「なぜ」の文で使う短い呼び名
    common: bool = False  # 全学共通のまとまりか


class InterestExtraMeta(_Strict):
    syllabus_id: str
    why: str
    source: str


class InterestMeta(_Strict):
    id: str
    label: str
    targets: list[str]  # group_id
    extras: list[InterestExtraMeta] = Field(default_factory=list)


class GroupMeta(_Strict):
    note: str | None = None
    groups: dict[str, GroupMetaEntry] = Field(default_factory=dict)
    interests: list[InterestMeta] = Field(default_factory=list)


@cache
def load_departments() -> dict[str, DepartmentEntry]:
    """登録の全学科を id → 登録の値で返す。id の重複は設定の誤りとして止める。"""
    raw = json.loads(_DEPARTMENTS_PATH.read_text(encoding="utf-8"))
    entries = [DepartmentEntry.model_validate(item) for item in raw]
    departments = {entry.id: entry for entry in entries}
    if len(departments) != len(entries):
        raise ValueError(f"{_DEPARTMENTS_PATH.name} に同じ id の学科が複数あります。")
    return departments


@cache
def load_group_meta(dept_id: str) -> GroupMeta:
    """学科のまとまりの補足。ファイルが無ければ止める（登録した学科には必ず置く）。"""
    if dept_id not in load_departments():  # 登録に無い id でファイルの道を作らない
        raise KeyError(f"登録に無い学科です: {dept_id}")
    path = _GROUP_META_DIR / f"{dept_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"まとまりの補足のファイルがありません: group_meta/{path.name}")
    return GroupMeta.model_validate(json.loads(path.read_text(encoding="utf-8")))
