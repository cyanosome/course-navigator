"""D4 の検索の語の切り方・ILIKE の型・Python の側の絞り込みと並べ方（純関数、api-contract.md 2.4）。

q の語の部分一致だけを SQL でかけ、学年・学期・曜限・まとまり・区分は写像の結果に対してここでかける
（学期も写像の結果で絞る。DB の semester の表記揺れで SQL の等号と画面の表示がずれないように）。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from course_core.schemas.catalog import CourseSummary, KindCode, Term

__all__ = [
    "MAX_QUERY_CHARS",
    "MAX_QUERY_WORDS",
    "CourseFilter",
    "QueryTooLongError",
    "filter_and_sort",
    "ilike_pattern",
    "split_query",
]

MAX_QUERY_WORDS: Final = 5
MAX_QUERY_CHARS: Final = 100
_LIKE_ESCAPE: Final = "\\"


class QueryTooLongError(ValueError):
    """q が語の数か文字数の上限を超えた（422 にする）。"""


@dataclass(frozen=True)
class CourseFilter:
    year: int | None = None
    term: Term | None = None
    slots: frozenset[str] = field(default_factory=frozenset)
    groups: frozenset[str] = field(default_factory=frozenset)
    kinds: frozenset[KindCode] = field(default_factory=frozenset)


def split_query(q: str | None) -> list[str]:
    """空白（半角・全角）区切りの語。重複は1つにする。上限を超えたら QueryTooLongError。"""
    if q is None:
        return []
    if len(q) > MAX_QUERY_CHARS:
        raise QueryTooLongError(f"q は {MAX_QUERY_CHARS} 文字までです。")
    words = list(dict.fromkeys(q.split()))  # str.split() は全角空白（U+3000）でも切る
    if len(words) > MAX_QUERY_WORDS:
        raise QueryTooLongError(f"q の語は {MAX_QUERY_WORDS} つまでです。")
    return words


def ilike_pattern(word: str) -> str:
    """部分一致の ILIKE の型。%・_・\\ は文字として扱う（ESCAPE '\\' と組で使う）。"""
    escaped = (
        word.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"


def _matches(course: CourseSummary, flt: CourseFilter) -> bool:
    if flt.year is not None:
        if course.year_min is None or course.year_max is None:
            return False
        if not course.year_min <= flt.year <= course.year_max:
            return False
    if flt.term is not None and course.term != flt.term:
        return False
    if flt.slots and not flt.slots.intersection(course.slots):
        return False
    if flt.groups and course.group_id not in flt.groups:
        return False
    if flt.kinds and course.kind not in flt.kinds:
        return False
    return True


def filter_and_sort(
    courses: Sequence[CourseSummary], flt: CourseFilter, words: Sequence[str]
) -> list[CourseSummary]:
    """絞り込んで並べる。科目名がすべての語を含むもの（大文字小文字を区別しない）を先に、次に syllabus_id の昇順。"""
    folded = [word.casefold() for word in words]

    def sort_key(course: CourseSummary) -> tuple[bool, str]:
        name = course.name.casefold()
        name_has_all = bool(folded) and all(word in name for word in folded)
        return (not name_has_all, course.syllabus_id)

    return sorted((course for course in courses if _matches(course, flt)), key=sort_key)
