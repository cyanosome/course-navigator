"""DB の行から API の応答の型への写像（純関数、api-contract.md 2.7）。

読めない値は推測で埋めず「読めない」として返す（年次・学期・曜限は None か [] と元の文字列）。
JSONB の列が壊れていたら ValueError を投げる（握りつぶさない。呼ぶ側の 500 とログに syllabus_id が残る）。
行は asyncpg.Record か dict（境界なので Mapping[str, Any] で受ける）。
"""

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final, get_args

from course_core.schemas.catalog import (
    BulletinInfo,
    CourseDetail,
    CourseSummary,
    CreditBucket,
    CreditBucketKey,
    GraduationRequirements,
    Instructor,
    KindCode,
    ScheduleItem,
    Term,
    ThesisRule,
)

__all__ = [
    "LEAD_MAX_CHARS",
    "course_detail_from_row",
    "course_summary_from_row",
    "graduation_requirements_from_row",
    "group_display_name",
    "lead_text",
    "parse_instructors",
    "parse_kind",
    "parse_schedule",
    "parse_slots",
    "parse_term",
    "parse_year_range",
    "primary_teacher",
    "to_float_credits",
]

# 概要の先頭の抜き出し。agent.grounding.truncate_text と同じ切り方（course_core から agent は import しない）。
LEAD_MAX_CHARS: Final = 120
_ELLIPSIS: Final = "…"
# 「３・４年次」（3年と4年）も範囲として読む。
_YEAR_RANGE_RE: Final = re.compile(r"(\d)(?:[〜~～\-・](\d))?年次")
_SLOT_RE: Final = re.compile(r"([月火水木金土日])(\d)")
_TERMS: Final[frozenset[str]] = frozenset(get_args(Term))
_KINDS: Final[frozenset[str]] = frozenset(get_args(KindCode))
_GROUP_LABEL_BRACKETS: Final = "【】"
_GROUP_LABEL_SUFFIX: Final = "グループ"

# 卒業要件の列 → 区分のキーと画面の名前（ingestion の bulletin_schema の説明に合わせた日本語）。
_CREDIT_BUCKETS: Final[tuple[tuple[CreditBucketKey, str, str], ...]] = (
    ("general_education", "general_education_credits", "共通教養科目"),
    ("general_designated", "general_designated_credits", "自己形成科目群の指定科目"),
    ("foreign_language", "foreign_language_credits", "外国語科目"),
    ("foreign_lang_first", "foreign_lang_first_credits", "外国語科目（第1選択）"),
    ("foreign_lang_second", "foreign_lang_second_credits", "外国語科目（第2選択）"),
    ("major", "major_credits", "専門教育科目"),
    ("major_required", "major_required_credits", "専門教育科目の必修"),
    ("major_elective_required", "major_elective_required_credits", "専門教育科目の選択必修"),
)


def _nfkc(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def parse_year_range(raw: str | None) -> tuple[int | None, int | None, str | None]:
    """"１〜４年次" → (1, 4, "1〜4年次")。"３・４年次" → (3, 4, "3・4年次")。読めなければ (None, None, NFKC の文字列)。"""
    if raw is None:
        return None, None, None
    normalized = _nfkc(raw)
    match = _YEAR_RANGE_RE.search(normalized)
    if match is None:
        return None, None, normalized or None
    year_min = int(match.group(1))
    year_max = int(match.group(2)) if match.group(2) else year_min
    return year_min, year_max, normalized


def parse_term(raw: str | None) -> Term | None:
    """春・秋・通年だけを受ける。ほかは None（呼ぶ側が term_raw に元の値を残す）。"""
    if raw is None:
        return None
    normalized = _nfkc(raw)
    return normalized if normalized in _TERMS else None  # type: ignore[return-value]


def parse_slots(raw: str | None) -> tuple[list[str], str | None]:
    """"火2" → (["火2"], None)。曜限を全部拾う。0 個なら ([], 元の文字列)。"""
    if raw is None:
        return [], None
    slots = [f"{day}{period}" for day, period in _SLOT_RE.findall(_nfkc(raw))]
    if not slots:
        return [], raw if raw.strip() else None
    return list(dict.fromkeys(slots)), None


def to_float_credits(value: Decimal | float | int | None) -> float | None:
    return None if value is None else float(value)


def lead_text(description: str | None) -> str:
    if not description:
        return ""
    if len(description) <= LEAD_MAX_CHARS:
        return description
    return description[:LEAD_MAX_CHARS] + _ELLIPSIS


def group_display_name(label: str, meta_name: str | None) -> str:
    """"【物理化学系グループ】" → "物理化学系"。補足ファイルの値があればそれを使う。"""
    if meta_name:
        return meta_name
    name = label.strip().strip(_GROUP_LABEL_BRACKETS).strip()
    if name.endswith(_GROUP_LABEL_SUFFIX) and len(name) > len(_GROUP_LABEL_SUFFIX):
        name = name[: -len(_GROUP_LABEL_SUFFIX)]
    return name or label


def parse_kind(value: str | None, syllabus_id: str) -> KindCode | None:
    """course_requirements.requirement_type。行が無ければ None、知らない値は止める。"""
    if value is None:
        return None
    if value not in _KINDS:
        raise ValueError(f"syllabus_id={syllabus_id}: 知らない区分 requirement_type={value!r}")
    return value  # type: ignore[return-value]


def _json_list(value: Any, column: str, syllabus_id: str) -> list[Any]:
    """JSONB の列（asyncpg の既定では文字列で届く）をリストにする。"""
    if value is None:
        return []
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise ValueError(f"syllabus_id={syllabus_id}: {column} が JSON として読めません") from exc
    if not isinstance(parsed, list):
        raise ValueError(f"syllabus_id={syllabus_id}: {column} が JSON の配列ではありません")
    return parsed


def parse_instructors(value: Any, syllabus_id: str) -> list[Instructor]:
    try:
        return [
            Instructor(name=item["name"], is_primary=bool(item.get("is_primary", False)))
            for item in _json_list(value, "instructors", syllabus_id)
        ]
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"syllabus_id={syllabus_id}: instructors の形が読めません") from exc


def parse_schedule(value: Any, syllabus_id: str) -> list[ScheduleItem]:
    try:
        return [
            ScheduleItem(number=item.get("session_number"), topic=item["topic"])
            for item in _json_list(value, "schedule_sessions", syllabus_id)
        ]
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"syllabus_id={syllabus_id}: schedule_sessions の形が読めません") from exc


def primary_teacher(instructors: Sequence[Instructor]) -> str | None:
    """is_primary が真の最初の人、無ければ先頭、空なら None。"""
    for instructor in instructors:
        if instructor.is_primary:
            return instructor.name
    return instructors[0].name if instructors else None


def _text_list(value: Sequence[str] | None) -> list[str]:
    return list(value) if value else []


def course_summary_from_row(row: Mapping[str, Any], *, group_id: str | None) -> CourseSummary:
    """courses の1行（＋ LEFT JOIN の kind）から一覧の項目を作る。"""
    syllabus_id = row["syllabus_id"]
    year_min, year_max, year_range = parse_year_range(row["year_range"])
    slots, slot_note = parse_slots(row["term_schedule"])
    return CourseSummary(
        syllabus_id=syllabus_id,
        course_code=row["course_code"],
        name=row["subject_name"],
        subtitle=row["subtitle"],
        group_id=group_id,
        year_min=year_min,
        year_max=year_max,
        year_range=year_range,
        term=parse_term(row["semester"]),
        term_raw=row["semester"],
        slots=slots,
        slot_note=slot_note,
        credits=to_float_credits(row["credits"]),
        faculties=_text_list(row["faculties"]),
        teacher=primary_teacher(parse_instructors(row["instructors"], syllabus_id)),
        lead=lead_text(row["description"]),
        kind=parse_kind(row["kind"], syllabus_id),
        detail_url=row["detail_url"],
    )


def _bulletin_from_row(row: Mapping[str, Any], syllabus_id: str) -> BulletinInfo | None:
    if row["cr_subject_name_bulletin"] is None:
        return None
    kind = parse_kind(row["kind"], syllabus_id)
    if kind is None:
        raise ValueError(f"syllabus_id={syllabus_id}: course_requirements の区分が空です")
    return BulletinInfo(
        subject_name_bulletin=row["cr_subject_name_bulletin"],
        requirement_type=kind,
        credits=float(row["cr_credits"]),
        assigned_year=row["cr_assigned_year"],
        bulletin_code=row["cr_bulletin_code"],
        field_category=row["cr_field_category"],
    )


def course_detail_from_row(row: Mapping[str, Any], *, group_id: str | None) -> CourseDetail:
    """courses の1行（＋ course_requirements の cr_* 列）から詳細を作る。"""
    syllabus_id = row["syllabus_id"]
    summary = course_summary_from_row(row, group_id=group_id)
    return CourseDetail(
        **summary.model_dump(),
        academic_year=row["academic_year"],
        description=row["description"],
        objectives=row["objectives"],
        schedule=parse_schedule(row["schedule_sessions"], syllabus_id),
        work_outside_class=row["work_outside_class"],
        grading_policy=row["grading_policy"],
        evaluation_criteria=row["evaluation_criteria"],
        textbooks=_text_list(row["textbooks"]),
        textbook_notes=row["textbook_notes"],
        references=_text_list(row["references"]),
        notes=row["notes"],
        instructors=parse_instructors(row["instructors"], syllabus_id),
        language=row["language"],
        teaching_type=row["teaching_type"],
        bulletin=_bulletin_from_row(row, syllabus_id),
    )


def graduation_requirements_from_row(row: Mapping[str, Any]) -> GraduationRequirements:
    """graduation_requirements の1行から卒業要件を作る。thesis_requirements が読めなければ止める。"""
    requirement_id = row["requirement_id"]
    thesis_raw = row["thesis_requirements"]
    try:
        thesis = ThesisRule.model_validate(
            json.loads(thesis_raw) if isinstance(thesis_raw, str) else thesis_raw
        )
    except (ValueError, TypeError) as exc:
        raise ValueError(f"requirement_id={requirement_id}: thesis_requirements が読めません") from exc
    return GraduationRequirements(
        requirement_id=requirement_id,
        academic_year=row["academic_year"],
        total_credits=float(row["total_credits"]),
        buckets=[
            CreditBucket(key=key, label=label, credits=float(row[column]))
            for key, column, label in _CREDIT_BUCKETS
        ],
        thesis=thesis,
        rules_notes=_text_list(row["rules_notes"]),
    )
