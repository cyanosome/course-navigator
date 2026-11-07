"""A1 の微修正（plan_context に診断の答えがあるとき）で LLM に渡す「今のプラン」と「選べる科目」を作る純関数。

- 選べる科目: プランの学期ごとに、診断のエンジンの候補（その学期に取れる科目。engine.ranked_candidates の並び）から、
  同じ名前の科目がプランのどの学期にも無いものを、点の高い順に最大 CANDIDATES_PER_TERM 件。
  埋める学期（診断の設定の terms）に無い学期には出さない
- 系統図に載る（外さない）: プランの科目のうち、系統図のまとまりに属するもの（Catalog の group_id がある）
- 科目名・曜限・単位・まとまりは Catalog（DB の行を診断と同じ読み方にしたもの）から引く
I/O を持たない（設定と科目の一覧は呼ぶ側が読む）。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from agent.grounding import normalize_codes
from course_core.diagnose.answers import Answers
from course_core.diagnose.engine import DiagnoseEngine
from course_core.diagnose.model import TERM_ORDER, Catalog, DiagCourse, PlanTerm

__all__ = [
    "CANDIDATES_HEADING",
    "CANDIDATES_PER_TERM",
    "LOCK_MARK",
    "PLAN_HEADING",
    "CandidateCourse",
    "RefineContext",
    "TermCandidates",
    "build_refine_context",
    "locked_plan_ids",
    "render_refine_block",
    "term_candidates",
]

CANDIDATES_PER_TERM: Final = 30
PLAN_HEADING: Final = (
    "## 今のプラン（利用者の診断から作ったもの。科目名・曜限・単位・まとまりはサーバーが DB で引いた値）"
)
CANDIDATES_HEADING: Final = (
    "## 選べる科目（学期ごとに、その学期に取れて同じ名前の科目がプランに無いもの。足してよいのはここにある科目だけ。"
    "点は診断の答えに合う度合いで、高いほど合う）"
)
LOCK_MARK: Final = "［系統図の科目・外さない］"
_SUMMARY_PREFIX: Final = "診断のまとめ: "
_NOT_IN_CATALOG: Final = "（DB に無い syllabus_id）"
_EMPTY_PLAN_TERM: Final = "- （科目なし）"
_EMPTY_CANDIDATES: Final = "- （選べる科目なし）"
_NO_SLOT: Final = "曜限なし"
_FULL_YEAR: Final = "通年"
_SLOT_SEPARATOR: Final = "/"
_PART_SEPARATOR: Final = "、"


class PlanTermLike(Protocol):
    """プランの1学期分（route_options.PlanTerm）。"""

    year: int
    term: str
    syllabus_ids: list[str]


@dataclass(frozen=True)
class CandidateCourse:
    course: DiagCourse
    score: float


@dataclass(frozen=True)
class TermCandidates:
    """プランの1学期分の選べる科目（点の高い順）。"""

    year: int
    term: str
    courses: tuple[CandidateCourse, ...]


@dataclass(frozen=True)
class RefineContext:
    """LLM に渡す文と、照合に使う集合。"""

    plan_ids: list[str]  # プランの全学期の syllabus_id（正規化して出現順、重複なし）
    locked_ids: frozenset[str]  # 系統図に載るプランの科目（外す提案は locked で外す）
    candidates: tuple[TermCandidates, ...]
    block: str  # 「今のプラン」と「選べる科目」の文（相談の後ろに付ける）

    @property
    def candidate_ids(self) -> frozenset[str]:
        """選べる科目の syllabus_id（学期をまたいだ重なりは1つ）。足す提案はこの中のものだけ。"""
        return frozenset(item.course.syllabus_id for term in self.candidates for item in term.courses)


def _plan_term(term: PlanTermLike) -> PlanTerm | None:
    """エンジンの学期にする。春・秋でなければ None（候補を出さない）。"""
    if term.term not in TERM_ORDER:
        return None
    return PlanTerm(year=term.year, term="春" if term.term == "春" else "秋")


def locked_plan_ids(plan_ids: Sequence[str], courses_by_id: Mapping[str, DiagCourse]) -> frozenset[str]:
    """プランの科目のうち、系統図のまとまりに属するもの。DB に無い科目は印を付けない。"""
    return frozenset(
        syllabus_id
        for syllabus_id in plan_ids
        if (course := courses_by_id.get(syllabus_id)) is not None and course.group_id is not None
    )


def term_candidates(
    engine: DiagnoseEngine,
    answers: Answers,
    terms: Sequence[PlanTermLike],
    plan_names: frozenset[str],
    limit: int = CANDIDATES_PER_TERM,
) -> tuple[TermCandidates, ...]:
    """プランの学期ごとの選べる科目。同じ名前の科目がプランにあるものは外し、点の高い順に limit 件まで。"""
    result: list[TermCandidates] = []
    for term in terms:
        plan_term = _plan_term(term)
        ranked = engine.ranked_candidates(answers, plan_term) if plan_term is not None else []
        picked = [CandidateCourse(course, score) for course, score in ranked if course.name not in plan_names][:limit]
        result.append(TermCandidates(year=term.year, term=term.term, courses=tuple(picked)))
    return tuple(result)


def _number(value: float) -> str:
    return f"{value:g}"


def _course_text(course: DiagCourse, catalog: Catalog, *, score: float | None = None) -> str:
    """「科目名（曜限、単位、まとまり、点）」。読めない値は書かない。"""
    parts = [_SLOT_SEPARATOR.join(course.slots) if course.slots else _NO_SLOT]
    if course.term == _FULL_YEAR:
        parts.append(_FULL_YEAR)
    if course.credits is not None:
        parts.append(f"{_number(course.credits)}単位")
    group = catalog.groups.get(course.group_id) if course.group_id is not None else None
    if group is not None:
        parts.append(f"まとまり: {group.name}")
    if score is not None:
        parts.append(f"点 {_number(score)}")
    return f"{course.name}（{_PART_SEPARATOR.join(parts)}）"


def render_refine_block(
    *,
    answers_summary: str,
    terms: Sequence[PlanTermLike],
    catalog: Catalog,
    courses_by_id: Mapping[str, DiagCourse],
    locked_ids: frozenset[str],
    candidates: Sequence[TermCandidates],
) -> str:
    """「今のプラン」（学期ごとの合計単位と、系統図の科目の印）と「選べる科目」の文。"""
    lines = [PLAN_HEADING]
    if answers_summary.strip():
        lines.append(_SUMMARY_PREFIX + answers_summary.strip())
    for term in terms:
        term_ids = normalize_codes(term.syllabus_ids)
        known = [courses_by_id[syllabus_id] for syllabus_id in term_ids if syllabus_id in courses_by_id]
        total = sum(course.credits for course in known if course.credits is not None)
        lines.append(f"### {term.year}年 {term.term}（合計 {_number(total)}単位）")
        if not term_ids:
            lines.append(_EMPTY_PLAN_TERM)
        for syllabus_id in term_ids:
            course = courses_by_id.get(syllabus_id)
            if course is None:
                lines.append(f"- {syllabus_id}{_NOT_IN_CATALOG}")
                continue
            mark = LOCK_MARK if syllabus_id in locked_ids else ""
            lines.append(f"- {syllabus_id} {_course_text(course, catalog)}{mark}")

    lines.append("")
    lines.append(CANDIDATES_HEADING)
    for term in candidates:
        lines.append(f"### {term.year}年 {term.term}")
        if not term.courses:
            lines.append(_EMPTY_CANDIDATES)
        lines.extend(
            f"- {item.course.syllabus_id} {_course_text(item.course, catalog, score=item.score)}" for item in term.courses
        )
    return "\n".join(lines)


def build_refine_context(
    *,
    engine: DiagnoseEngine,
    catalog: Catalog,
    answers: Answers,
    answers_summary: str,
    terms: Sequence[PlanTermLike],
) -> RefineContext:
    """診断の答え（answers.validate_answers を通したもの）と今のプランから、LLM に渡す文と照合の集合を作る。"""
    courses_by_id = {course.syllabus_id: course for course in catalog.courses}
    plan_ids = normalize_codes(syllabus_id for term in terms for syllabus_id in term.syllabus_ids)
    plan_names = frozenset(courses_by_id[syllabus_id].name for syllabus_id in plan_ids if syllabus_id in courses_by_id)
    locked = locked_plan_ids(plan_ids, courses_by_id)
    candidates = term_candidates(engine, answers, terms, plan_names)
    block = render_refine_block(
        answers_summary=answers_summary,
        terms=terms,
        catalog=catalog,
        courses_by_id=courses_by_id,
        locked_ids=locked,
        candidates=candidates,
    )
    return RefineContext(plan_ids=plan_ids, locked_ids=locked, candidates=candidates, block=block)
