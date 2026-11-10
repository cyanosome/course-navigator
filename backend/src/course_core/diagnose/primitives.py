"""設定で使える primitive 9つ（事前登録 comp-diag/protocol.md の「使える primitive」の定義どおり）。

1つの科目の点は Σ(weight × primitive の値)。値は科目と埋める学期（year_fit・term_fit が使う）で決まる。
各 primitive は、引数の検査（check）・引数の読み込み（parse）・値（value）・理由の文の差し込み（details）を持つ。
理由の文の差し込みは TEMPLATE_PLACEHOLDERS の6つ（変更記録 2026-11-07 (3)）。{target} は reaches_group、
{words} は keyword の値で、ほかの primitive では空。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Final, Protocol

from course_core.diagnose.model import TEXT_FIELDS, Catalog, ConfigIssue, DiagCourse, PlanTerm, normalize_text

__all__ = [
    "PRIMITIVES",
    "PRIMITIVE_ORDER",
    "TEMPLATE_PLACEHOLDERS",
    "Primitive",
    "PrimitiveType",
]

_DAYS: Final = ("月", "火", "水", "木", "金", "土")
_PERIOD_MIN: Final = 1
_PERIOD_MAX: Final = 7
_FULL_YEAR: Final = "通年"
_JOIN: Final = "・"
# 理由の文の差し込み（まとまりの名前・届く先のまとまりの名前・学年・学期・一致した語・単位数）。ほかの名前は空にする
TEMPLATE_PLACEHOLDERS: Final = ("group", "target", "year", "term", "words", "credits")

KnownGroups = frozenset[str] | None  # None なら まとまり ID の有無を見ない（DB を読む前の検査）


class Primitive(Protocol):
    NAME: ClassVar[str]
    TAKES_ARGS: ClassVar[bool]

    def value(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> float: ...

    def details(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> dict[str, str]: ...


class PrimitiveType(Protocol):
    NAME: ClassVar[str]
    TAKES_ARGS: ClassVar[bool]

    @staticmethod
    def check(args: Mapping[str, Any], path: str, known_groups: KnownGroups) -> list[ConfigIssue]: ...

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> Primitive: ...


# --- 引数の検査の部品 --------------------------------------------------------------------


def _shape(path: str, message: str) -> ConfigIssue:
    return ConfigIssue("shape", path, message)


def _keys(args: Mapping[str, Any], path: str, *, required: Sequence[str], optional: Sequence[str] = ()) -> list[ConfigIssue]:
    issues = [_shape(f"{path}.{key}", "必須の項目がありません") for key in required if key not in args]
    allowed = set(required) | set(optional)
    issues += [_shape(f"{path}.{key}", "知らない項目です") for key in args if key not in allowed]
    return issues


def _non_empty_list(value: Any, path: str) -> tuple[list[Any] | None, list[ConfigIssue]]:
    if not isinstance(value, list) or not value:
        return None, [_shape(path, "1つ以上の要素を持つ配列にしてください")]
    return value, []


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_group_id(value: Any, path: str, known_groups: KnownGroups) -> list[ConfigIssue]:
    if not isinstance(value, str) or not value:
        return [_shape(path, "まとまり ID は文字列にしてください")]
    if known_groups is not None and value not in known_groups:
        return [ConfigIssue("group", path, f"存在しないまとまり ID です: {value}")]
    return []


def _no_args(args: Mapping[str, Any], path: str) -> list[ConfigIssue]:
    return _keys(args, path, required=())


# --- primitive 9つ -----------------------------------------------------------------------


@dataclass(frozen=True)
class InGroup:
    """科目が指定のまとまりに属するなら 1。"""

    NAME: ClassVar[str] = "in_group"
    TAKES_ARGS: ClassVar[bool] = True

    groups: frozenset[str]

    @staticmethod
    def check(args: Mapping[str, Any], path: str, known_groups: KnownGroups) -> list[ConfigIssue]:
        issues = _keys(args, path, required=("groups",))
        if "groups" not in args:
            return issues
        groups, list_issues = _non_empty_list(args["groups"], f"{path}.groups")
        issues += list_issues
        for index, group_id in enumerate(groups or []):
            issues += _check_group_id(group_id, f"{path}.groups[{index}]", known_groups)
        return issues

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> "InGroup":
        return cls(groups=frozenset(args["groups"]))

    def value(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> float:
        return 1.0 if course.group_id in self.groups else 0.0

    def details(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> dict[str, str]:
        return {}


@dataclass(frozen=True)
class ReachesGroup:
    """科目のまとまりから、まとまりどうしの線をたどって target に届くなら 1（同じまとまりも 1）。"""

    NAME: ClassVar[str] = "reaches_group"
    TAKES_ARGS: ClassVar[bool] = True

    target: str

    @staticmethod
    def check(args: Mapping[str, Any], path: str, known_groups: KnownGroups) -> list[ConfigIssue]:
        issues = _keys(args, path, required=("target",))
        if "target" in args:
            issues += _check_group_id(args["target"], f"{path}.target", known_groups)
        return issues

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> "ReachesGroup":
        return cls(target=args["target"])

    def value(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> float:
        if course.group_id is None:
            return 0.0
        return 1.0 if self.target in catalog.reach.get(course.group_id, frozenset()) else 0.0

    def details(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> dict[str, str]:
        group = catalog.groups.get(self.target)
        return {"target": group.name if group is not None else self.target}


@dataclass(frozen=True)
class YearFit:
    """科目の配当年次の範囲に、埋める学期の学年が入るなら 1。"""

    NAME: ClassVar[str] = "year_fit"
    TAKES_ARGS: ClassVar[bool] = False

    @staticmethod
    def check(args: Mapping[str, Any], path: str, known_groups: KnownGroups) -> list[ConfigIssue]:
        return _no_args(args, path)

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> "YearFit":
        return cls()

    def value(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> float:
        if course.year_min is None or course.year_max is None:
            return 0.0
        return 1.0 if course.year_min <= term.year <= course.year_max else 0.0

    def details(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> dict[str, str]:
        return {}


@dataclass(frozen=True)
class TermFit:
    """科目の学期が埋める学期と合うなら 1（通年は春・秋どちらにも合う）。"""

    NAME: ClassVar[str] = "term_fit"
    TAKES_ARGS: ClassVar[bool] = False

    @staticmethod
    def check(args: Mapping[str, Any], path: str, known_groups: KnownGroups) -> list[ConfigIssue]:
        return _no_args(args, path)

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> "TermFit":
        return cls()

    def value(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> float:
        return 1.0 if course.term in (term.term, _FULL_YEAR) else 0.0

    def details(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> dict[str, str]:
        return {}


@dataclass(frozen=True)
class SlotAvoid:
    """指定の曜日・時限にかかるなら 1（重みを負にして避ける）。days・periods の片方を省くと「すべて」。"""

    NAME: ClassVar[str] = "slot_avoid"
    TAKES_ARGS: ClassVar[bool] = True

    days: frozenset[str] | None
    periods: frozenset[int] | None

    @staticmethod
    def check(args: Mapping[str, Any], path: str, known_groups: KnownGroups) -> list[ConfigIssue]:
        issues = _keys(args, path, required=(), optional=("days", "periods"))
        if "days" not in args and "periods" not in args:
            issues.append(_shape(path, "days か periods のどちらかを書いてください"))
        if "days" in args:
            days, list_issues = _non_empty_list(args["days"], f"{path}.days")
            issues += list_issues
            issues += [
                _shape(f"{path}.days[{index}]", f"曜日は {'・'.join(_DAYS)} のどれかにしてください")
                for index, day in enumerate(days or [])
                if day not in _DAYS
            ]
        if "periods" in args:
            periods, list_issues = _non_empty_list(args["periods"], f"{path}.periods")
            issues += list_issues
            issues += [
                _shape(f"{path}.periods[{index}]", f"時限は {_PERIOD_MIN}〜{_PERIOD_MAX} の整数にしてください")
                for index, period in enumerate(periods or [])
                if not _is_int(period) or not _PERIOD_MIN <= period <= _PERIOD_MAX
            ]
        return issues

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> "SlotAvoid":
        days = frozenset(args["days"]) if "days" in args else None
        periods = frozenset(args["periods"]) if "periods" in args else None
        return cls(days=days, periods=periods)

    def _hits(self, course: DiagCourse) -> list[str]:
        hits = []
        for slot in course.slots:
            day, period = slot[0], int(slot[1:])
            if (self.days is None or day in self.days) and (self.periods is None or period in self.periods):
                hits.append(slot)
        return hits

    def value(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> float:
        return 1.0 if self._hits(course) else 0.0

    def details(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> dict[str, str]:
        return {}


@dataclass(frozen=True)
class Keyword:
    """指定の欄（name・summary・goals）に語のどれかを含むなら 1（NFKC のあと大文字小文字を区別しない）。"""

    NAME: ClassVar[str] = "keyword"
    TAKES_ARGS: ClassVar[bool] = True

    words: tuple[str, ...]
    keys: tuple[str, ...]  # normalize_text 済みの words（同じ並び）
    fields: tuple[str, ...]

    @staticmethod
    def check(args: Mapping[str, Any], path: str, known_groups: KnownGroups) -> list[ConfigIssue]:
        issues = _keys(args, path, required=("words", "fields"))
        if "words" in args:
            words, list_issues = _non_empty_list(args["words"], f"{path}.words")
            issues += list_issues
            issues += [
                _shape(f"{path}.words[{index}]", "語は空でない文字列にしてください")
                for index, word in enumerate(words or [])
                if not isinstance(word, str) or not word.strip()
            ]
        if "fields" in args:
            fields, list_issues = _non_empty_list(args["fields"], f"{path}.fields")
            issues += list_issues
            issues += [
                _shape(f"{path}.fields[{index}]", f"欄は {', '.join(TEXT_FIELDS)} のどれかにしてください")
                for index, field in enumerate(fields or [])
                if field not in TEXT_FIELDS
            ]
        return issues

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> "Keyword":
        words = tuple(word.strip() for word in args["words"])
        return cls(
            words=words,
            keys=tuple(normalize_text(word) for word in words),
            fields=tuple(dict.fromkeys(args["fields"])),
        )

    def _matched(self, course: DiagCourse) -> list[str]:
        texts = [course.texts.get(field, "") for field in self.fields]
        return [word for word, key in zip(self.words, self.keys) if any(key in text for text in texts)]

    def value(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> float:
        texts = [course.texts.get(field, "") for field in self.fields]
        return 1.0 if any(key in text for key in self.keys for text in texts) else 0.0

    def details(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> dict[str, str]:
        return {"words": _JOIN.join(self._matched(course))}


@dataclass(frozen=True)
class OwnDepartment:
    """科目の対象学部が自学部だけなら 1（変更記録 2026-11-07 (1)。source.is_own_department）。"""

    NAME: ClassVar[str] = "own_department"
    TAKES_ARGS: ClassVar[bool] = False

    @staticmethod
    def check(args: Mapping[str, Any], path: str, known_groups: KnownGroups) -> list[ConfigIssue]:
        return _no_args(args, path)

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> "OwnDepartment":
        return cls()

    def value(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> float:
        return 1.0 if course.own_department else 0.0

    def details(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> dict[str, str]:
        return {}


@dataclass(frozen=True)
class Credits:
    """単位数（読めなければ 0）。"""

    NAME: ClassVar[str] = "credits"
    TAKES_ARGS: ClassVar[bool] = False

    @staticmethod
    def check(args: Mapping[str, Any], path: str, known_groups: KnownGroups) -> list[ConfigIssue]:
        return _no_args(args, path)

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> "Credits":
        return cls()

    def value(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> float:
        return course.credits if course.credits is not None else 0.0

    def details(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> dict[str, str]:
        return {}


@dataclass(frozen=True)
class OnCurriculum:
    """系統図に載る科目（まとまりに属する科目）なら 1。"""

    NAME: ClassVar[str] = "on_curriculum"
    TAKES_ARGS: ClassVar[bool] = False

    @staticmethod
    def check(args: Mapping[str, Any], path: str, known_groups: KnownGroups) -> list[ConfigIssue]:
        return _no_args(args, path)

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> "OnCurriculum":
        return cls()

    def value(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> float:
        return 1.0 if course.group_id is not None else 0.0

    def details(self, course: DiagCourse, term: PlanTerm, catalog: Catalog) -> dict[str, str]:
        return {}


# 事前登録の一覧の順。理由の文の同点はこの順で決める。
_ALL: Final[tuple[PrimitiveType, ...]] = (
    InGroup,
    ReachesGroup,
    YearFit,
    TermFit,
    SlotAvoid,
    Keyword,
    OwnDepartment,
    Credits,
    OnCurriculum,
)
PRIMITIVES: Final[Mapping[str, PrimitiveType]] = {primitive.NAME: primitive for primitive in _ALL}
PRIMITIVE_ORDER: Final[Mapping[str, int]] = {primitive.NAME: index for index, primitive in enumerate(_ALL)}
