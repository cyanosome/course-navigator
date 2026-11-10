"""履修の状況（今の学期 start・履修済み completed・登録済み registered）の検査と指紋（context_digest）。

どれも任意で、送られなければ（空の配列も）前と同じプランになる。履修の状況はサーバーに保存しない（検査して使うだけ）。
- start: この学期から先だけを埋める。設定の scope の学期のどれかでなければ誤り。scope に start より後が足りなければ、
  scope の最後の学期までで止める（設定は変えない）
- completed: 履修済みの科目。同じ科目名をプランに入れない（engine の「同じ科目名は1つまで」に足す）。単位は数えず、点も変えない
- registered: その学期にもう登録した科目。埋める学期（start から scope の最後まで）のどれかに置く。その学期の曜限をふさぎ、
  単位に数え、同じ科目名をプランに入れない。プランには登録済み（status=registered）として返す。
  配当年次・学期・曜限の重なりは見ない（利用者がもう登録したものなので、そのまま置く）
誤り（422 にする）: start が scope に無い、registered の学期が埋める学期に無い・2回ある、知らない syllabus_id、
同じ科目が completed に2回・registered に2回・completed と registered の両方にある。
指紋は answers_digest と別に作る（answers_digest は答えだけの指紋のまま）。
"""

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from course_core.diagnose.config import DiagnoseConfig
from course_core.diagnose.model import Catalog, DiagCourse, PlanTerm
from course_core.schemas.diagnose import RegisteredTermIn, TermIn

__all__ = ["NO_HISTORY", "PlanHistory", "context_digest", "filled_terms", "validate_history"]

_DIGEST_PREFIX: Final = "sha256:"
_LIST_SEPARATOR: Final = ", "


@dataclass(frozen=True)
class PlanHistory:
    """検査を通った履修の状況。科目は Catalog の科目（送られた順）。"""

    start: PlanTerm | None = None
    completed: tuple[DiagCourse, ...] = ()
    registered: Mapping[PlanTerm, tuple[DiagCourse, ...]] = field(default_factory=dict)

    @property
    def registered_courses(self) -> tuple[DiagCourse, ...]:
        return tuple(course for courses in self.registered.values() for course in courses)

    @property
    def completed_names(self) -> frozenset[str]:
        return frozenset(course.name for course in self.completed)

    @property
    def taken_names(self) -> frozenset[str]:
        """履修済みと登録済みの科目名（プランに同じ名前の科目を入れない）。"""
        return self.completed_names | {course.name for course in self.registered_courses}

    def registered_slots(self, term: PlanTerm) -> frozenset[str]:
        """その学期の登録済みの科目がふさぐ曜限。"""
        return frozenset(slot for course in self.registered.get(term, ()) for slot in course.slots)


NO_HISTORY: Final = PlanHistory()


def filled_terms(terms: Iterable[PlanTerm], start: PlanTerm | None) -> tuple[PlanTerm, ...]:
    """埋める学期: 設定の terms（時系列の順）のうち start から先。start が None なら全部。"""
    return tuple(term for term in terms if start is None or term.sort_key >= start.sort_key)


def _label(term: PlanTerm) -> str:
    return f"{term.year}年{term.term}"


def _duplicates(ids: Sequence[str]) -> list[str]:
    counts = Counter(ids)
    return [syllabus_id for syllabus_id in dict.fromkeys(ids) if counts[syllabus_id] > 1]


def validate_history(
    config: DiagnoseConfig,
    catalog: Catalog,
    *,
    start: TermIn | None = None,
    completed: Sequence[str] | None = None,
    registered: Sequence[RegisteredTermIn] | None = None,
) -> tuple[PlanHistory, list[str]]:
    """(検査を通った履修の状況, 誤りの一覧)。誤りが1つでもあれば履修の状況は使わない（NO_HISTORY を返す）。"""
    errors: list[str] = []
    start_term = PlanTerm(year=start.year, term=start.term) if start is not None else None
    if start_term is not None and start_term not in config.terms:
        errors.append(f"start の {_label(start_term)} は埋める学期（設定の scope）にありません")
    filled = filled_terms(config.terms, start_term)

    registered_ids: dict[PlanTerm, list[str]] = {}
    for entry in registered or ():
        term = PlanTerm(year=entry.year, term=entry.term)
        if term in registered_ids:
            errors.append(f"registered に {_label(term)} が2回あります")
            continue
        if term not in filled:
            errors.append(f"registered の {_label(term)} は埋める学期（start から設定の scope の最後まで）にありません")
        registered_ids[term] = list(entry.syllabus_ids)

    completed_ids = list(completed or ())
    all_registered = [syllabus_id for ids in registered_ids.values() for syllabus_id in ids]
    if repeated := _duplicates(completed_ids):
        errors.append(f"completed に同じ科目が2回あります: {_LIST_SEPARATOR.join(repeated)}")
    if repeated := _duplicates(all_registered):
        errors.append(f"registered に同じ科目が2回あります: {_LIST_SEPARATOR.join(repeated)}")
    registered_set = set(all_registered)
    if both := [syllabus_id for syllabus_id in dict.fromkeys(completed_ids) if syllabus_id in registered_set]:
        errors.append(f"completed と registered の両方にある科目です: {_LIST_SEPARATOR.join(both)}")
    courses_by_id = {course.syllabus_id: course for course in catalog.courses}
    if unknown := [sid for sid in dict.fromkeys([*completed_ids, *all_registered]) if sid not in courses_by_id]:
        errors.append(f"知らない科目です: {_LIST_SEPARATOR.join(unknown)}")
    if errors:
        return NO_HISTORY, errors

    return (
        PlanHistory(
            start=start_term,
            completed=tuple(courses_by_id[syllabus_id] for syllabus_id in completed_ids),
            registered={
                term: tuple(courses_by_id[syllabus_id] for syllabus_id in ids)
                for term, ids in sorted(registered_ids.items(), key=lambda item: item[0].sort_key)
            },
        ),
        [],
    )


def context_digest(history: PlanHistory) -> str | None:
    """履修の状況の指紋（ログで答え・状況とプランを突き合わせる）。科目の並びに左右されない。

    送られなかった項目と空の配列（科目の無い registered の学期も）は入れない。何も残らなければ None。
    """
    canonical: dict[str, Any] = {}
    if history.start is not None:
        canonical["start"] = {"year": history.start.year, "term": history.start.term}
    if history.completed:
        canonical["completed"] = sorted(course.syllabus_id for course in history.completed)
    registered = [
        {"year": term.year, "term": term.term, "syllabus_ids": sorted(course.syllabus_id for course in courses)}
        for term, courses in sorted(history.registered.items(), key=lambda item: item[0].sort_key)
        if courses
    ]
    if registered:
        canonical["registered"] = registered
    if not canonical:
        return None
    text = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _DIGEST_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()
