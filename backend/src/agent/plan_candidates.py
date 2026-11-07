"""A1 の微修正（plan_context に診断の答えがあるとき）で LLM に渡す「今のプラン」と「選べる科目」を作る純関数。

- 選べる科目: プランの学期ごとに、診断のエンジンの候補（その学期に取れる科目。engine.ranked_candidates の並び）から、
  次の3つの経路で入れる（同じ学期で同じ科目は1回。経路の優先は top → same_name → named）。
  - top: 同じ名前の科目がプランのどの学期にも無いものを、点の高い順に最大 CANDIDATES_PER_TERM 件
  - same_name: その学期のプランの科目と同じ名前の別クラス（その学期に取れるもの全部）。外す科目と組にして「移す」ときだけ足せる
  - named: 頼みの文に科目名（全体か、括弧の中の主な部分）が出てくる科目（同じ名前がプランに無いもの、最大 NAMED_PER_TERM 件）
  埋める学期（診断の設定の terms）に無い学期には出さない
- 系統図に載る（外さない）: プランの科目のうち、系統図のまとまりに属するもの（Catalog の group_id がある）。
  同じ学期の同じ名前の別クラスへ移す（外す＋足すの組）のはよい（事前登録 study1 の K5 のとおり）
- 科目名・曜限・単位・まとまりは Catalog（DB の行を診断と同じ読み方にしたもの）から引く
I/O を持たない（設定と科目の一覧は呼ぶ側が読む）。
"""

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from agent.grounding import normalize_codes
from course_core.diagnose.answers import Answers
from course_core.diagnose.engine import DiagnoseEngine
from course_core.diagnose.model import TERM_ORDER, Catalog, DiagCourse, PlanTerm, normalize_text

__all__ = [
    "CANDIDATES_HEADING",
    "CANDIDATES_PER_TERM",
    "CANDIDATE_SOURCES",
    "LOCK_MARK",
    "NAMED_PER_TERM",
    "NAME_PART_MIN_CHARS",
    "PLAN_HEADING",
    "CandidateCourse",
    "CandidateSource",
    "RefineContext",
    "TermCandidates",
    "build_refine_context",
    "locked_plan_ids",
    "name_parts",
    "render_refine_block",
    "term_candidates",
]

CandidateSource = Literal["top", "same_name", "named"]
CANDIDATE_SOURCES: Final[tuple[CandidateSource, ...]] = ("top", "same_name", "named")
CANDIDATES_PER_TERM: Final = 30
NAMED_PER_TERM: Final = 30
# 科目名の部分で頼みの文と照らす最短の字数（「Ａ」などの短い括弧の中身で当たらないように）
NAME_PART_MIN_CHARS: Final = 3
PLAN_HEADING: Final = (
    "## 今のプラン（利用者の診断から作ったもの。科目名・曜限・単位・まとまりはサーバーが DB で引いた値）"
)
CANDIDATES_HEADING: Final = (
    "## 選べる科目（学期ごとの、その学期に取れる科目。足してよいのはここにある科目だけ。"
    "点は診断の答えに合う度合いで、高いほど合う）"
)
LOCK_MARK: Final = "［系統図の科目・外さない。同じ学期の別クラスへ移すのはよい］"
_SAME_NAME_MARK: Final = "［今のプランの {plan_id} の別クラス。{plan_id} を外す案と組にして移すときだけ足せる］"
_NAMED_MARK: Final = "［頼みに名前が出た科目］"
_SUMMARY_PREFIX: Final = "診断のまとめ: "
_NOT_IN_CATALOG: Final = "（DB に無い syllabus_id）"
_EMPTY_PLAN_TERM: Final = "- （科目なし）"
_EMPTY_CANDIDATES: Final = "- （選べる科目なし）"
_NO_SLOT: Final = "曜限なし"
_FULL_YEAR: Final = "通年"
_SLOT_SEPARATOR: Final = "/"
_PART_SEPARATOR: Final = "、"
_BRACKET_RE: Final = re.compile(r"[（(]([^（）()]+)[）)]")


class PlanTermLike(Protocol):
    """プランの1学期分（route_options.PlanTerm）。"""

    year: int
    term: str
    syllabus_ids: list[str]


@dataclass(frozen=True)
class CandidateCourse:
    course: DiagCourse
    score: float
    source: CandidateSource = "top"
    move_from: str | None = None  # same_name のとき、移す元（同じ学期のプランの同じ名前の科目）の syllabus_id


@dataclass(frozen=True)
class TermCandidates:
    """プランの1学期分の選べる科目（top の点の高い順 → same_name → named）。"""

    year: int
    term: str
    courses: tuple[CandidateCourse, ...]


@dataclass(frozen=True)
class RefineContext:
    """LLM に渡す文と、照合に使う集合。"""

    plan_ids: list[str]  # プランの全学期の syllabus_id（正規化して出現順、重複なし）
    locked_ids: frozenset[str]  # 系統図に載るプランの科目（外す提案は、移す組でなければ locked で外す）
    candidates: tuple[TermCandidates, ...]
    block: str  # 「今のプラン」と「選べる科目」の文（相談の後ろに付ける）

    @property
    def candidate_ids(self) -> frozenset[str]:
        """選べる科目の syllabus_id（学期をまたいだ重なりは1つ）。足す提案はこの中のものだけ。"""
        return frozenset(item.course.syllabus_id for term in self.candidates for item in term.courses)

    @property
    def move_pairs(self) -> dict[str, frozenset[str]]:
        """プランの科目 → 同じ学期の同じ名前の別クラス（same_name の候補）。外す＋足すの組を「移す」と認める。"""
        pairs: dict[str, set[str]] = {}
        for term in self.candidates:
            for item in term.courses:
                if item.source == "same_name" and item.move_from is not None:
                    pairs.setdefault(item.move_from, set()).add(item.course.syllabus_id)
        return {plan_id: frozenset(targets) for plan_id, targets in pairs.items()}

    @property
    def source_counts(self) -> dict[str, int]:
        """選べる科目の syllabus_id の数を、入った経路ごとに（学期をまたいで経路が違えば、優先の高い経路で1回数える）。"""
        best: dict[str, int] = {}
        for term in self.candidates:
            for item in term.courses:
                rank = CANDIDATE_SOURCES.index(item.source)
                best[item.course.syllabus_id] = min(rank, best.get(item.course.syllabus_id, rank))
        counted = Counter(CANDIDATE_SOURCES[rank] for rank in best.values())
        return {source: counted.get(source, 0) for source in CANDIDATE_SOURCES}


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


def name_parts(name: str) -> frozenset[str]:
    """頼みの文と照らす科目名の部分（normalize_text 済み）: 名前の全体と、括弧の中身（主な部分）。短すぎるものは使わない。

    例 "物理を学ぶ（電磁気学１）" → {"物理を学ぶ(電磁気学1)", "電磁気学1"}。括弧の外の「物理を学ぶ」は多くの科目に共通なので使わない。
    """
    normalized = normalize_text(name)
    parts = {normalized, *(inner.strip() for inner in _BRACKET_RE.findall(normalized))}
    return frozenset(part for part in parts if len(part) >= NAME_PART_MIN_CHARS)


def _mentioned(course: DiagCourse, request_text: str) -> bool:
    return any(part in request_text for part in name_parts(course.name))


def term_candidates(
    engine: DiagnoseEngine,
    answers: Answers,
    terms: Sequence[PlanTermLike],
    courses_by_id: Mapping[str, DiagCourse],
    request_text: str = "",
    limit: int = CANDIDATES_PER_TERM,
    named_limit: int = NAMED_PER_TERM,
) -> tuple[TermCandidates, ...]:
    """プランの学期ごとの選べる科目（top・same_name・named。モジュールの説明のとおり）。"""
    plan_ids = set(normalize_codes(syllabus_id for term in terms for syllabus_id in term.syllabus_ids))
    plan_names = frozenset(courses_by_id[syllabus_id].name for syllabus_id in plan_ids if syllabus_id in courses_by_id)
    text = normalize_text(request_text)
    result: list[TermCandidates] = []
    for term in terms:
        plan_term = _plan_term(term)
        ranked = engine.ranked_candidates(answers, plan_term) if plan_term is not None else []
        picked: dict[str, CandidateCourse] = {}
        for course, score in ranked:
            if len(picked) >= limit:
                break
            if course.name not in plan_names:
                picked[course.syllabus_id] = CandidateCourse(course, score)
        term_plan = [courses_by_id[sid] for sid in normalize_codes(term.syllabus_ids) if sid in courses_by_id]
        for plan_course in term_plan:
            for course, score in ranked:
                if course.name == plan_course.name and course.syllabus_id not in plan_ids and course.syllabus_id not in picked:
                    picked[course.syllabus_id] = CandidateCourse(
                        course, score, source="same_name", move_from=plan_course.syllabus_id
                    )
        named = [
            CandidateCourse(course, score, source="named")
            for course, score in ranked
            if text and course.name not in plan_names and course.syllabus_id not in picked and _mentioned(course, text)
        ]
        picked.update((item.course.syllabus_id, item) for item in named[:named_limit])
        result.append(TermCandidates(year=term.year, term=term.term, courses=tuple(picked.values())))
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


def _candidate_line(item: CandidateCourse, catalog: Catalog) -> str:
    mark = ""
    if item.source == "same_name" and item.move_from is not None:
        mark = _SAME_NAME_MARK.format(plan_id=item.move_from)
    elif item.source == "named":
        mark = _NAMED_MARK
    return f"- {item.course.syllabus_id} {_course_text(item.course, catalog, score=item.score)}{mark}"


def render_refine_block(
    *,
    answers_summary: str,
    terms: Sequence[PlanTermLike],
    catalog: Catalog,
    courses_by_id: Mapping[str, DiagCourse],
    locked_ids: frozenset[str],
    candidates: Sequence[TermCandidates],
) -> str:
    """「今のプラン」（学期ごとの合計単位と、系統図の科目の印）と「選べる科目」（経路の印つき）の文。"""
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
        lines.extend(_candidate_line(item, catalog) for item in term.courses)
    return "\n".join(lines)


def build_refine_context(
    *,
    engine: DiagnoseEngine,
    catalog: Catalog,
    answers: Answers,
    answers_summary: str,
    terms: Sequence[PlanTermLike],
    request_text: str = "",
) -> RefineContext:
    """診断の答え（answers.validate_answers を通したもの）と今のプランと頼みの文から、LLM に渡す文と照合の集合を作る。"""
    courses_by_id = {course.syllabus_id: course for course in catalog.courses}
    plan_ids = normalize_codes(syllabus_id for term in terms for syllabus_id in term.syllabus_ids)
    locked = locked_plan_ids(plan_ids, courses_by_id)
    candidates = term_candidates(engine, answers, terms, courses_by_id, request_text)
    block = render_refine_block(
        answers_summary=answers_summary,
        terms=terms,
        catalog=catalog,
        courses_by_id=courses_by_id,
        locked_ids=locked,
        candidates=candidates,
    )
    return RefineContext(plan_ids=plan_ids, locked_ids=locked, candidates=candidates, block=block)
