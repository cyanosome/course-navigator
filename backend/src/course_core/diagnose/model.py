"""診断のエンジンが扱う型（I/O を持たない）。

科目は B1 の写像（CourseSummary）に、keyword で使う概要・到達目標と、自学部かどうかを足したもの。
"""

import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Literal

__all__ = [
    "Catalog",
    "ConfigIssue",
    "DiagCourse",
    "GroupInfo",
    "IssueKind",
    "PlanTerm",
    "PlanTermName",
    "TERM_ORDER",
    "TEXT_FIELDS",
    "normalize_text",
    "reachability",
]

PlanTermName = Literal["春", "秋"]
# 埋める学期の並び（年 → 春 → 秋）。プランはこの順に埋める。
TERM_ORDER: Final[Mapping[str, int]] = {"春": 0, "秋": 1}
# keyword が見る欄（name = 科目名、summary = 授業の概要、goals = 到達目標）
TEXT_FIELDS: Final = ("name", "summary", "goals")

# M1 の内訳（事前登録の「JSON が読めない・形の違反・未定義の primitive・存在しないまとまり ID・質問が8問を超える」）
IssueKind = Literal["json", "shape", "primitive", "group", "too_many_questions"]


@dataclass(frozen=True)
class ConfigIssue:
    """設定の誤りの1件（M1 は件数）。path は JSON の中の場所（例 questions[0].options[1].effects[0].weight）。"""

    kind: IssueKind
    path: str
    message: str


def normalize_text(value: str) -> str:
    """keyword の照合用（NFKC のあと大文字小文字を区別しない）。"""
    return unicodedata.normalize("NFKC", value).casefold()


@dataclass(frozen=True)
class DiagCourse:
    syllabus_id: str
    name: str  # 同じ名前の別クラスがある（プランには1つだけ入れる）
    credits: float | None
    year_min: int | None
    year_max: int | None
    term: str | None  # 春・秋・通年。読めないもの（集中・隔年など）は None
    slots: tuple[str, ...]  # 例 ("火2",)。読めなければ ()
    slot_note: str | None  # 読めなかった曜限の元の文字列（例「他」）
    group_id: str | None  # 系統図のまとまり（載っていなければ None）
    own_department: bool
    texts: Mapping[str, str]  # TEXT_FIELDS → normalize_text 済みの文


@dataclass(frozen=True)
class GroupInfo:
    group_id: str
    name: str  # 理由の文で使う呼び名（source.group_name。系統図の表記の崩れを直したもの）
    academic_year: int


@dataclass(frozen=True)
class PlanTerm:
    year: int
    term: PlanTermName

    @property
    def sort_key(self) -> tuple[int, int]:
        return self.year, TERM_ORDER[self.term]


def reachability(group_ids: Iterable[str], edges: Iterable[tuple[str, str]]) -> dict[str, frozenset[str]]:
    """まとまり → 線（source → target）をたどって届くまとまり（自分を含む）。循環があっても止まる。"""
    forward: dict[str, list[str]] = {}
    for source, target in edges:
        forward.setdefault(source, []).append(target)
    reach: dict[str, frozenset[str]] = {}
    for start in group_ids:
        seen = {start}
        stack = [start]
        while stack:
            for nxt in forward.get(stack.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        reach[start] = frozenset(seen)
    return reach


@dataclass(frozen=True)
class Catalog:
    """学科の科目（syllabus_id の昇順）と系統図。"""

    department_id: str
    data_version: str
    courses: tuple[DiagCourse, ...]
    groups: Mapping[str, GroupInfo]
    edges: tuple[tuple[str, str], ...]  # まとまりどうしの線（D3 の既定の edge_types）
    reach: Mapping[str, frozenset[str]]

    @classmethod
    def build(
        cls,
        *,
        department_id: str,
        data_version: str,
        courses: Iterable[DiagCourse],
        groups: Iterable[GroupInfo],
        edges: Iterable[tuple[str, str]],
    ) -> "Catalog":
        group_map = {group.group_id: group for group in groups}
        edge_list = tuple(edges)
        return cls(
            department_id=department_id,
            data_version=data_version,
            courses=tuple(sorted(courses, key=lambda course: course.syllabus_id)),
            groups=group_map,
            edges=edge_list,
            reach=reachability(group_map, edge_list),
        )

    @property
    def group_ids(self) -> frozenset[str]:
        return frozenset(self.groups)
