"""診断の設定（configs/<department_id>.json）の読み込みと検査。

形は事前登録（comp-diag/protocol.md の「設定の形」）のとおり。誤りは止めずに一覧（ConfigIssue）で返し、
その件数が審査の M1（JSON が読めない・形の違反・未定義の primitive・存在しないまとまり ID・質問が8問を超える）になる。
まとまり ID の有無は系統図を読んでから見る（known_groups）。読む前は形だけを見る。

形の決めごと（事前登録に書かれていない細部。報告に書く）:
- 項目はすべて必須で、知らない項目は形の違反。base_effects は空の配列でよい
- 質問の id・選択肢の id は英数字と _（1〜32 文字）。質問どうし・同じ質問の選択肢どうしで重ならない
- single と multi は選択肢が1つ以上。multi は max_select（1〜選択肢の数）が要り、ほかの kind には書かない
- scale5 は選択肢をちょうど5つ書く（答えの 1〜5 が選択肢の 1〜5 番目に当たる）
- 埋める学期は {year: 1〜4, term: 春|秋}、重ならない。credit_cap_per_term は正の数か null
- weight は選択肢の effect なら -3〜+3 の数、base_effects なら有限の数（設定の形の `<数>` のとおり範囲は無い）
- tie_break は syllabus_id・year_then_syllabus_id か、引数の要らない primitive の名前
- reason_templates の鍵は primitive の名前、値は空でない文字列。{ } の書き方が読めない文は形の違反。
  知らない差し込みは誤りに数えない（文を作るときに空にする。変更記録 2026-11-07 (3)）
"""

import json
import math
import re
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final, Literal, get_args

from course_core.catalog.registry import load_departments
from course_core.diagnose.model import TERM_ORDER, ConfigIssue, PlanTerm
from course_core.diagnose.primitives import PRIMITIVES, Primitive

__all__ = [
    "MAX_QUESTIONS",
    "SCALE5_POINTS",
    "TIE_BREAK_FIXED",
    "ConfigError",
    "ConfigNotFoundError",
    "DiagnoseConfig",
    "Effect",
    "LoadedConfig",
    "Option",
    "Question",
    "QuestionKind",
    "load_config",
    "load_config_text",
    "parse_config",
    "read_config_text",
    "validate_config",
]

MAX_QUESTIONS: Final = 8
SCALE5_POINTS: Final = 5
WEIGHT_LIMIT: Final = 3.0
TIE_BREAK_FIXED: Final = ("syllabus_id", "year_then_syllabus_id")
QuestionKind = Literal["single", "multi", "scale5"]
_KINDS: Final = get_args(QuestionKind)
_ID_RE: Final = re.compile(r"^[A-Za-z0-9_]{1,32}$")
_VERSION_MAX: Final = 64
_TOP_KEYS: Final = (
    "version",
    "department_id",
    "scope",
    "questions",
    "base_effects",
    "tie_break",
    "reason_templates",
)
_CONFIG_DIR: Final = Path(__file__).resolve().parent / "configs"


# --- 読み込んだ後の型 --------------------------------------------------------------------


@dataclass(frozen=True)
class Effect:
    primitive: Primitive
    weight: float


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    effects: tuple[Effect, ...]


@dataclass(frozen=True)
class Question:
    id: str
    text: str
    kind: QuestionKind
    max_select: int | None  # multi だけ
    options: tuple[Option, ...]

    def option_ids(self) -> tuple[str, ...]:
        return tuple(option.id for option in self.options)


@dataclass(frozen=True)
class DiagnoseConfig:
    version: str
    department_id: str
    terms: tuple[PlanTerm, ...]  # 時系列の順（年 → 春 → 秋）に並べ直したもの
    credit_cap_per_term: float | None
    questions: tuple[Question, ...]
    base_effects: tuple[Effect, ...]
    tie_break: str
    reason_templates: Mapping[str, str]

    def question(self, question_id: str) -> Question | None:
        return next((question for question in self.questions if question.id == question_id), None)


@dataclass(frozen=True)
class LoadedConfig:
    raw: dict[str, Any]  # ファイルの JSON のまま（GET /diagnose/config が返す）
    config: DiagnoseConfig


class ConfigError(ValueError):
    def __init__(self, source: str, issues: Sequence[ConfigIssue]) -> None:
        self.issues = tuple(issues)
        lines = "; ".join(f"{issue.path}: {issue.message}" for issue in self.issues)
        super().__init__(f"診断の設定 {source} に誤りが {len(self.issues)} 件あります: {lines}")


class ConfigNotFoundError(LookupError):
    pass


# --- JSON の読み込み ---------------------------------------------------------------------


class _DuplicateKeyError(ValueError):
    pass


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise _DuplicateKeyError(f"同じ鍵が2回あります: {', '.join(duplicates)}")
    return dict(pairs)


def _reject_constant(name: str) -> Any:
    raise ValueError(f"JSON に無い値です: {name}")


def read_config_text(text: str) -> tuple[Any, list[ConfigIssue]]:
    """JSON の文字列を読む。読めなければ (None, [json の誤り1件])。同じ鍵の重なりと NaN・Infinity も読めない扱い。"""
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant), []
    except ValueError as exc:  # JSONDecodeError・_DuplicateKeyError を含む
        return None, [ConfigIssue("json", "$", f"JSON として読めません: {exc}")]


# --- 検査 --------------------------------------------------------------------------------


def _shape(path: str, message: str) -> ConfigIssue:
    return ConfigIssue("shape", path, message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _keys(obj: Mapping[str, Any], path: str, required: Sequence[str], optional: Sequence[str] = ()) -> list[ConfigIssue]:
    issues = [_shape(f"{path}.{key}", "必須の項目がありません") for key in required if key not in obj]
    allowed = set(required) | set(optional)
    issues += [_shape(f"{path}.{key}", "知らない項目です") for key in obj if key not in allowed]
    return issues


def _check_effects(
    value: Any, path: str, known_groups: frozenset[str] | None, *, weight_limit: float | None
) -> list[ConfigIssue]:
    """effect の配列。weight_limit が None なら重みは有限の数であればよい（base_effects）。"""
    if not isinstance(value, list):
        return [_shape(path, "effects は配列にしてください")]
    issues: list[ConfigIssue] = []
    for index, effect in enumerate(value):
        here = f"{path}[{index}]"
        if not isinstance(effect, dict):
            issues.append(_shape(here, "effect はオブジェクトにしてください"))
            continue
        issues += _keys(effect, here, required=("primitive", "args", "weight"))
        if "weight" in effect:
            weight = effect["weight"]
            if not _is_number(weight):
                issues.append(_shape(f"{here}.weight", "weight は数にしてください"))
            elif weight_limit is not None and abs(weight) > weight_limit:
                issues.append(_shape(f"{here}.weight", f"weight は -{weight_limit:g}〜+{weight_limit:g} の数にしてください"))
        name = effect.get("primitive")
        if "primitive" not in effect:
            continue
        primitive = PRIMITIVES.get(name) if isinstance(name, str) else None
        if primitive is None:
            issues.append(ConfigIssue("primitive", f"{here}.primitive", f"未定義の primitive です: {name!r}"))
            continue
        if "args" not in effect:
            continue
        if not isinstance(effect["args"], dict):
            issues.append(_shape(f"{here}.args", "args はオブジェクトにしてください"))
            continue
        issues += primitive.check(effect["args"], f"{here}.args", known_groups)
    return issues


def _check_options(question: Mapping[str, Any], path: str, known_groups: frozenset[str] | None) -> list[ConfigIssue]:
    options = question.get("options")
    if not isinstance(options, list) or not options:
        return [_shape(f"{path}.options", "選択肢を1つ以上の配列で書いてください")]
    issues: list[ConfigIssue] = []
    seen: set[str] = set()
    for index, option in enumerate(options):
        here = f"{path}.options[{index}]"
        if not isinstance(option, dict):
            issues.append(_shape(here, "選択肢はオブジェクトにしてください"))
            continue
        issues += _keys(option, here, required=("id", "label", "effects"))
        option_id = option.get("id")
        if "id" in option:
            if not isinstance(option_id, str) or not _ID_RE.match(option_id):
                issues.append(_shape(f"{here}.id", "id は英数字と _ の 1〜32 文字にしてください"))
            elif option_id in seen:
                issues.append(_shape(f"{here}.id", f"同じ質問の中で id が重なっています: {option_id}"))
            else:
                seen.add(option_id)
        if "label" in option and not _non_empty_str(option["label"]):
            issues.append(_shape(f"{here}.label", "label は空でない文字列にしてください"))
        if "effects" in option:
            issues += _check_effects(option["effects"], f"{here}.effects", known_groups, weight_limit=WEIGHT_LIMIT)
    return issues


def _check_question(question: Any, path: str, known_groups: frozenset[str] | None) -> list[ConfigIssue]:
    if not isinstance(question, dict):
        return [_shape(path, "質問はオブジェクトにしてください")]
    kind = question.get("kind")
    issues = _keys(question, path, required=("id", "text", "kind", "options"), optional=("max_select",))
    if kind == "multi" and "max_select" not in question:
        issues.append(_shape(f"{path}.max_select", "multi には max_select が要ります"))
    if kind != "multi" and "max_select" in question:
        issues.append(_shape(f"{path}.max_select", "max_select は multi のときだけ書きます"))
    if "id" in question and not (isinstance(question["id"], str) and _ID_RE.match(question["id"])):
        issues.append(_shape(f"{path}.id", "id は英数字と _ の 1〜32 文字にしてください"))
    if "text" in question and not _non_empty_str(question["text"]):
        issues.append(_shape(f"{path}.text", "text は空でない文字列にしてください"))
    if "kind" in question and kind not in _KINDS:
        issues.append(_shape(f"{path}.kind", f"kind は {', '.join(_KINDS)} のどれかにしてください"))
    if "options" in question:
        issues += _check_options(question, path, known_groups)
    options = question.get("options")
    option_count = len(options) if isinstance(options, list) else None
    if kind == "multi" and "max_select" in question:
        max_select = question["max_select"]
        if not _is_int(max_select) or max_select < 1 or (option_count is not None and max_select > option_count):
            issues.append(_shape(f"{path}.max_select", "max_select は 1〜選択肢の数の整数にしてください"))
    if kind == "scale5" and option_count is not None and option_count != SCALE5_POINTS:
        issues.append(_shape(f"{path}.options", f"scale5 の選択肢はちょうど {SCALE5_POINTS} つにしてください"))
    return issues


def _check_scope(scope: Any) -> list[ConfigIssue]:
    if not isinstance(scope, dict):
        return [_shape("scope", "scope はオブジェクトにしてください")]
    issues = _keys(scope, "scope", required=("terms", "credit_cap_per_term"))
    terms = scope.get("terms")
    if "terms" in scope:
        if not isinstance(terms, list) or not terms:
            issues.append(_shape("scope.terms", "埋める学期を1つ以上の配列で書いてください"))
            terms = []
        seen: set[tuple[Any, Any]] = set()
        for index, term in enumerate(terms):
            here = f"scope.terms[{index}]"
            if not isinstance(term, dict):
                issues.append(_shape(here, "学期は {\"year\": 1, \"term\": \"春\"} の形にしてください"))
                continue
            issues += _keys(term, here, required=("year", "term"))
            year, name = term.get("year"), term.get("term")
            if "year" in term and not (_is_int(year) and 1 <= year <= 4):
                issues.append(_shape(f"{here}.year", "year は 1〜4 の整数にしてください"))
            if "term" in term and not (isinstance(name, str) and name in TERM_ORDER):
                issues.append(_shape(f"{here}.term", "term は 春 か 秋 にしてください"))
            if not (_is_int(year) and isinstance(name, str)):
                continue  # 型の誤りは上で数えた（配列などは集合で照らせない）
            if (year, name) in seen:
                issues.append(_shape(here, f"同じ学期が2回あります: {year}年{name}"))
            seen.add((year, name))
    if "credit_cap_per_term" in scope:
        cap = scope["credit_cap_per_term"]
        if cap is not None and not (_is_number(cap) and cap > 0):
            issues.append(_shape("scope.credit_cap_per_term", "credit_cap_per_term は正の数か null にしてください"))
    return issues


def _check_tie_break(value: Any) -> list[ConfigIssue]:
    if not isinstance(value, str):
        return [_shape("tie_break", "tie_break は文字列にしてください")]
    if value in TIE_BREAK_FIXED:
        return []
    primitive = PRIMITIVES.get(value)
    if primitive is None:
        return [ConfigIssue("primitive", "tie_break", f"未定義の primitive です: {value!r}")]
    if primitive.TAKES_ARGS:
        return [_shape("tie_break", f"引数の要る primitive は tie_break に使えません: {value}")]
    return []


def _template_issues(template: str, path: str) -> list[ConfigIssue]:
    """{ } の書き方が読めるか（「{」の閉じ忘れなど）。差し込みの名前は見ない。"""
    try:
        list(string.Formatter().parse(template))
    except ValueError as exc:
        return [_shape(path, f"差し込みの書き方が読めません: {exc}")]
    return []


def _check_templates(value: Any) -> list[ConfigIssue]:
    if not isinstance(value, dict):
        return [_shape("reason_templates", "reason_templates はオブジェクトにしてください")]
    issues: list[ConfigIssue] = []
    for name, template in value.items():
        path = f"reason_templates.{name}"
        if name not in PRIMITIVES:
            issues.append(ConfigIssue("primitive", path, f"未定義の primitive です: {name!r}"))
            continue
        if not _non_empty_str(template):
            issues.append(_shape(path, "理由の文は空でない文字列にしてください"))
            continue
        issues += _template_issues(template, path)
    return issues


def validate_config(raw: Any, *, department_id: str, known_groups: frozenset[str] | None) -> list[ConfigIssue]:
    """設定の誤りを全部返す（空なら正しい）。known_groups が None ならまとまり ID の有無は見ない。"""
    if not isinstance(raw, dict):
        return [_shape("$", "設定は JSON のオブジェクトにしてください")]
    issues = _keys(raw, "$", required=_TOP_KEYS)
    if "version" in raw and not (_non_empty_str(raw["version"]) and len(raw["version"]) <= _VERSION_MAX):
        issues.append(_shape("version", f"version は空でない {_VERSION_MAX} 文字以内の文字列にしてください"))
    if "department_id" in raw and raw["department_id"] != department_id:
        issues.append(_shape("department_id", f"department_id が違います（{department_id} にしてください）"))
    if "scope" in raw:
        issues += _check_scope(raw["scope"])
    questions = raw.get("questions")
    if "questions" in raw:
        if not isinstance(questions, list) or not questions:
            issues.append(_shape("questions", "質問を1つ以上の配列で書いてください"))
        else:
            if len(questions) > MAX_QUESTIONS:
                issues.append(
                    ConfigIssue("too_many_questions", "questions", f"質問が {MAX_QUESTIONS} 問を超えています（{len(questions)} 問）")
                )
            seen: set[str] = set()
            for index, question in enumerate(questions):
                issues += _check_question(question, f"questions[{index}]", known_groups)
                question_id = question.get("id") if isinstance(question, dict) else None
                if isinstance(question_id, str) and _ID_RE.match(question_id):
                    if question_id in seen:
                        issues.append(_shape(f"questions[{index}].id", f"質問の id が重なっています: {question_id}"))
                    seen.add(question_id)
    if "base_effects" in raw:
        issues += _check_effects(raw["base_effects"], "base_effects", known_groups, weight_limit=None)
    if "tie_break" in raw:
        issues += _check_tie_break(raw["tie_break"])
    if "reason_templates" in raw:
        issues += _check_templates(raw["reason_templates"])
    return issues


# --- 検査を通った JSON から型へ -----------------------------------------------------------


def _effects(raw: list[dict[str, Any]]) -> tuple[Effect, ...]:
    return tuple(
        Effect(primitive=PRIMITIVES[item["primitive"]].parse(item["args"]), weight=float(item["weight"]))
        for item in raw
    )


def parse_config(raw: dict[str, Any]) -> DiagnoseConfig:
    """validate_config が空を返した JSON を型にする（検査していない JSON を渡さない）。"""
    scope = raw["scope"]
    terms = sorted(
        (PlanTerm(year=term["year"], term=term["term"]) for term in scope["terms"]),
        key=lambda term: term.sort_key,
    )
    cap = scope["credit_cap_per_term"]
    return DiagnoseConfig(
        version=raw["version"],
        department_id=raw["department_id"],
        terms=tuple(terms),
        credit_cap_per_term=float(cap) if cap is not None else None,
        questions=tuple(
            Question(
                id=question["id"],
                text=question["text"],
                kind=question["kind"],
                max_select=question.get("max_select"),
                options=tuple(
                    Option(id=option["id"], label=option["label"], effects=_effects(option["effects"]))
                    for option in question["options"]
                ),
            )
            for question in raw["questions"]
        ),
        base_effects=_effects(raw["base_effects"]),
        tie_break=raw["tie_break"],
        reason_templates=dict(raw["reason_templates"]),
    )


def load_config_text(text: str, *, department_id: str, source: str) -> LoadedConfig:
    """文字列の設定を読んで形を検査し、型にする。誤りがあれば ConfigError（まとまり ID は見ない）。"""
    raw, issues = read_config_text(text)
    if not issues:
        issues = validate_config(raw, department_id=department_id, known_groups=None)
    if issues:
        raise ConfigError(source, issues)
    return LoadedConfig(raw=raw, config=parse_config(raw))


@cache
def load_config(department_id: str) -> LoadedConfig:
    """学科のいま有効な設定。登録に無い学科とファイルの無い学科は ConfigNotFoundError、誤りは ConfigError。"""
    if department_id not in load_departments():  # 登録に無い id でファイルの道を作らない
        raise ConfigNotFoundError(f"登録に無い学科です: {department_id}")
    path = _CONFIG_DIR / f"{department_id}.json"
    if not path.is_file():
        raise ConfigNotFoundError(f"診断の設定がありません: configs/{path.name}")
    return load_config_text(path.read_text(encoding="utf-8"), department_id=department_id, source=f"configs/{path.name}")
