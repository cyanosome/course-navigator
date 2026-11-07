"""プランの組み立てと理由の文。LLM は使わず、同じ設定・同じデータ・同じ答えなら同じプランを返す。

事前登録の決まり（埋める学期ごとに点の高い順、同じ曜限に2つ入れない、上限を超えない、同点は tie_break）と
変更記録 2026-11-07 の (2)（同じ科目名は1つまで。同じ名前の別クラスは点の高い1つだけを残す）に、ここで次を決めた:
- 埋める学期は時系列の順（年 → 春 → 秋）に埋める。各学期で候補を点の高い順に見て、
  1) 点が 0 以下の科目は入れない（そこで打ち切る）
  2) 同じ科目名はプランに1つまで（前の学期までにプランに入った科目名も入れない）。同じ名前の別クラスは点の順に見て、
     上のクラスが曜限・上限で入らなければ次のクラスを見る（2026-11-07 の監査役の決定 P-a。前は最上位の1つだけを見た）
  3) 同じ曜限に2つ入れない
  4) 単位の上限（credit_cap_per_term）を超える科目は飛ばして次を見る。上限が null なら単位では止めない
- 候補（その学期に入れてよい科目）: 単位・配当年次・学期が読めて、配当年次にその学年が入り、学期が同じか通年のもの
  （変更記録 2026-11-07 (4)。year_fit・term_fit は重みとして点の計算にも残る）
  - 学期の読めない科目（夏集・冬集・春集・秋集・「春（隔・ク）」など。B1 の写像で term が null）は入れない
  - 曜限の読めない科目（「他」＝集中など。slots が空）は入れてよい。どの曜限もふさがない
  - 通年の科目は1回だけ入れ、単位は入れた学期に数える。春に入れたら同じ年の秋の同じ曜限もふさぐ
- 並び: 点（小数 9 桁で丸めたもの）の高い順 → tie_break → syllabus_id の昇順
  - tie_break "syllabus_id" は syllabus_id だけ、"year_then_syllabus_id" は配当年次の下限の小さい順、
    primitive の名前ならその値の大きい順
- 理由の文: 理由に使う effect（下）の寄与を primitive ごとに足し、正のものを大きい順（同点は primitive の一覧の順）に最大2つ。
  reason_templates に文の無い primitive は出さない。差し込みは TEMPLATE_PLACEHOLDERS の6つで、知らない名前は空。
  {target}・{words} の値は、理由に使う effect のうち、その primitive の中で寄与の最も大きい effect のもの
  - 理由に使う effect は、利用者が選んだ選択肢の effect と、base_effects のうち REASON_BASE_PRIMITIVES
    （in_group・reaches_group・on_curriculum。系統図の事実）のものだけ。答えに結びつかない base の keyword などは
    点には効くが理由にしない（答えていない質問を理由にした文を出さないため）
  - year_fit・term_fit は、どこから来ても理由にしない（候補の条件と同じ意味で、プランのどの科目にも当てはまる）
"""

import string
from collections.abc import Callable, Mapping, Sequence
from typing import Final

from course_core.diagnose.answers import Answers, answers_digest
from course_core.diagnose.config import DiagnoseConfig, Effect
from course_core.diagnose.model import Catalog, DiagCourse, PlanTerm
from course_core.diagnose.primitives import PRIMITIVE_ORDER, PRIMITIVES, TEMPLATE_PLACEHOLDERS, Primitive
from course_core.schemas.diagnose import DiagnosePlanOut, PlanCourseOut, PlanTermOut, ReasonOut

__all__ = ["MAX_REASONS", "REASON_BASE_PRIMITIVES", "DiagnoseEngine", "build_plan", "is_candidate", "render_template"]

MAX_REASONS: Final = 2
# base_effects のうち理由の文に使う primitive（答えに結びつかないが、系統図の事実を言うもの）
REASON_BASE_PRIMITIVES: Final = frozenset({"in_group", "reaches_group", "on_curriculum"})
# どこから来ても理由の文に使わない primitive（候補の条件と同じ意味）
_NO_REASON_PRIMITIVES: Final = frozenset({"year_fit", "term_fit"})
_SCORE_DIGITS: Final = 9
_OUT_DIGITS: Final = 6
_EPS: Final = 1e-9
_FULL_YEAR: Final = "通年"
_SPRING: Final = "春"
_AUTUMN: Final = "秋"
_YEAR_UNKNOWN_LAST: Final = 99

TieKey = Callable[[PlanTerm, int], tuple[float, ...]]


def is_candidate(course: DiagCourse, term: PlanTerm) -> bool:
    """その学期に入れてよい科目か（単位・配当年次・学期が読めて、学年と学期が合う）。"""
    if course.credits is None or course.year_min is None or course.year_max is None or course.term is None:
        return False
    if not course.year_min <= term.year <= course.year_max:
        return False
    return course.term in (term.term, _FULL_YEAR)


def _number_text(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else str(value)


def render_template(template: str, values: Mapping[str, str]) -> str:
    """理由の文を作る。TEMPLATE_PLACEHOLDERS にある名前は値に、知らない名前は空にする（書式の指定は使わない）。"""
    parts: list[str] = []
    for literal, field, _spec, _conversion in string.Formatter().parse(template):
        parts.append(literal)
        if field is not None and field in TEMPLATE_PLACEHOLDERS:
            parts.append(values.get(field, ""))
    return "".join(parts).strip()


class DiagnoseEngine:
    """設定と科目の一覧を受け取り、答えごとにプランを作る。値は学期と primitive ごとに覚えておく（採点の道具で繰り返し使う）。"""

    def __init__(self, config: DiagnoseConfig, catalog: Catalog) -> None:
        if config.department_id != catalog.department_id:
            raise ValueError(f"設定の学科 {config.department_id} とデータの学科 {catalog.department_id} が違います")
        self._config = config
        self._catalog = catalog
        self._candidates: dict[PlanTerm, tuple[DiagCourse, ...]] = {
            term: tuple(course for course in catalog.courses if is_candidate(course, term)) for term in config.terms
        }
        self._values_cache: dict[tuple[Primitive, PlanTerm], tuple[float, ...]] = {}
        self._tie_key = self._make_tie_key(config.tie_break)

    def _values(self, primitive: Primitive, term: PlanTerm) -> tuple[float, ...]:
        key = (primitive, term)
        values = self._values_cache.get(key)
        if values is None:
            values = tuple(primitive.value(course, term, self._catalog) for course in self._candidates[term])
            self._values_cache[key] = values
        return values

    def _make_tie_key(self, tie_break: str) -> TieKey:
        if tie_break == "syllabus_id":
            return lambda term, index: ()
        if tie_break == "year_then_syllabus_id":

            def by_year(term: PlanTerm, index: int) -> tuple[float, ...]:
                year_min = self._candidates[term][index].year_min
                return (float(year_min if year_min is not None else _YEAR_UNKNOWN_LAST),)

            return by_year
        primitive = PRIMITIVES[tie_break].parse({})

        def by_primitive(term: PlanTerm, index: int) -> tuple[float, ...]:
            return (-self._values(primitive, term)[index],)

        return by_primitive

    def _answer_effects(self, answers: Answers) -> list[Effect]:
        """選んだ選択肢の effect（質問 → 選択肢 → effect の設定の並び）。"""
        effects: list[Effect] = []
        for question in self._config.questions:
            chosen = set(answers.get(question.id, ()))
            for option in question.options:
                if option.id in chosen:
                    effects.extend(option.effects)
        return effects

    def effects_for(self, answers: Answers) -> list[Effect]:
        """点に効く effect: 選んだ選択肢の effect と base_effects。"""
        return [*self._answer_effects(answers), *self._config.base_effects]

    def reason_effects_for(self, answers: Answers) -> list[Effect]:
        """理由の文に使う effect: 選んだ選択肢の effect と、base_effects のうち REASON_BASE_PRIMITIVES のもの。
        year_fit・term_fit はどちらからも除く。"""
        base = [effect for effect in self._config.base_effects if effect.primitive.NAME in REASON_BASE_PRIMITIVES]
        return [
            effect
            for effect in [*self._answer_effects(answers), *base]
            if effect.primitive.NAME not in _NO_REASON_PRIMITIVES
        ]

    def _scores(self, term: PlanTerm, effects: Sequence[Effect]) -> list[float]:
        scores = [0.0] * len(self._candidates[term])
        for effect in effects:
            weight = effect.weight
            for index, value in enumerate(self._values(effect.primitive, term)):
                if value:
                    scores[index] += weight * value
        return [round(score, _SCORE_DIGITS) for score in scores]

    def _ranked(self, term: PlanTerm, scores: Sequence[float]) -> list[int]:
        """候補の添え字を、点の高い順 → tie_break → syllabus_id の昇順に並べる。"""
        candidates = self._candidates[term]
        return sorted(
            range(len(candidates)),
            key=lambda index: (-scores[index], *self._tie_key(term, index), candidates[index].syllabus_id),
        )

    def plan(self, answers: Answers) -> DiagnosePlanOut:
        """検査を通った答え（answers.validate_answers の結果）からプランを作る。"""
        effects = self.effects_for(answers)
        reason_effects = self.reason_effects_for(answers)
        cap = self._config.credit_cap_per_term
        placed_names: set[str] = set()  # プランに入った科目名（同じ科目名は1つまで）
        reserved: dict[PlanTerm, set[str]] = {}  # 通年の科目が先にふさいだ曜限
        terms: list[PlanTermOut] = []
        for term in self._config.terms:
            candidates = self._candidates[term]
            scores = self._scores(term, effects)
            order = self._ranked(term, scores)
            occupied = set(reserved.get(term, ()))
            total = 0.0
            chosen: list[int] = []
            for index in order:
                if scores[index] <= 0:
                    break
                course = candidates[index]
                credits = course.credits or 0.0
                if course.name in placed_names:  # 入らなかったクラスの名前は残し、下のクラスを見る
                    continue
                if occupied.intersection(course.slots):
                    continue
                if cap is not None and total + credits > cap + _EPS:
                    continue
                chosen.append(index)
                occupied.update(course.slots)
                total += credits
                placed_names.add(course.name)
                if course.term == _FULL_YEAR and term.term == _SPRING:
                    reserved.setdefault(PlanTerm(year=term.year, term=_AUTUMN), set()).update(course.slots)
                if cap is not None and total >= cap - _EPS:
                    break
            terms.append(
                PlanTermOut(
                    year=term.year,
                    term=term.term,
                    credits_total=round(total, _OUT_DIGITS),
                    courses=[self._course_out(term, index, scores[index], reason_effects) for index in chosen],
                )
            )
        return DiagnosePlanOut(
            config_version=self._config.version,
            answers_digest=answers_digest(answers),
            terms=terms,
        )

    def _course_out(self, term: PlanTerm, index: int, score: float, reason_effects: Sequence[Effect]) -> PlanCourseOut:
        course = self._candidates[term][index]
        return PlanCourseOut(
            syllabus_id=course.syllabus_id,
            name=course.name,
            credits=course.credits or 0.0,
            slots=list(course.slots),
            slot_note=course.slot_note,
            score=round(score, _OUT_DIGITS),
            reasons=self._reasons(term, index, reason_effects),
        )

    def _template_values(self, course: DiagCourse, term: PlanTerm) -> dict[str, str]:
        group = self._catalog.groups.get(course.group_id) if course.group_id is not None else None
        return {
            "group": group.name if group is not None else "",
            "year": str(term.year),
            "term": term.term,
            "credits": _number_text(course.credits),
        }

    def _reasons(self, term: PlanTerm, index: int, reason_effects: Sequence[Effect]) -> list[ReasonOut]:
        """reason_effects（reason_effects_for の結果）だけから理由の文を作る。"""
        templates: Mapping[str, str] = self._config.reason_templates
        totals: dict[str, float] = {}
        best: dict[str, tuple[float, Effect]] = {}
        for effect in reason_effects:
            contribution = round(effect.weight * self._values(effect.primitive, term)[index], _SCORE_DIGITS)
            if contribution == 0:
                continue
            name = effect.primitive.NAME
            totals[name] = totals.get(name, 0.0) + contribution
            if contribution > 0 and (name not in best or contribution > best[name][0]):
                best[name] = (contribution, effect)
        ranked = sorted(
            (name for name, total in totals.items() if round(total, _SCORE_DIGITS) > 0 and name in templates and name in best),
            key=lambda name: (-round(totals[name], _SCORE_DIGITS), PRIMITIVE_ORDER[name]),
        )
        course = self._candidates[term][index]
        reasons: list[ReasonOut] = []
        for name in ranked:
            values = self._template_values(course, term) | best[name][1].primitive.details(course, term, self._catalog)
            text = render_template(templates[name], values)
            if not text or any(reason.text == text for reason in reasons):
                continue
            reasons.append(ReasonOut(primitive=name, text=text))
            if len(reasons) == MAX_REASONS:
                break
        return reasons


def build_plan(config: DiagnoseConfig, catalog: Catalog, answers: Answers) -> DiagnosePlanOut:
    return DiagnoseEngine(config, catalog).plan(answers)
