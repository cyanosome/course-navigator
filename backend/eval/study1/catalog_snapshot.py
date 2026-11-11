"""科目の属性のスナップショット（score.py・metrics.py が使う。事前登録 3.3・6.3）。

凍結の DB（PostgreSQL の courses と Neo4j の系統図）から、採点に要る項目だけを JSON に書き出す。読み方は診断の
エンジンと同じ（course_core.diagnose.source.load_catalog: 学期・曜限・単位・配当年次は B1 の写像、まとまりは
membership）。科目の本文（概要・到達目標）は書かない。それでも凍結の DB の写しなので、リポの外に置く。

GMS では動いている backend のコンテナの中（/backend_app）で打ち、コンテナの /tmp に書いて docker compose cp で出す:

    docker compose exec backend uv run --no-sync python -m eval.study1.catalog_snapshot --out /tmp/study1-catalog.json

DB を読まずに、診断の採点の道具が保存したデータ（eval.diag_metrics の --save-snapshot、形 diag-catalog-v1）から作る:

    uv run --no-sync python -m eval.study1.catalog_snapshot --from-diag-snapshot snap.json --out catalog.json

書き先が既にあるか git の作業ツリーの中なら止める（files.check_private_output）。書いたらファイルの SHA-256 と、
中身の指紋（科目の行の SHA-256。feasibility.py も同じ指紋を出すので、同じデータで流したかを突き合わせられる）を出す。

score.py・metrics.py の --catalog には、このファイルか diag-catalog-v1 のファイルのどちらも渡せる。
"""

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from eval.study1.files import OutputError, sha256_file, write_private_json

if TYPE_CHECKING:  # 実行時は読まない（DB を読むときだけ asyncpg が要る。手元の Windows では入らないことがある）
    from course_core.diagnose.model import Catalog

__all__ = [
    "CATALOG_FORMAT",
    "DIAG_SNAPSHOT_FORMAT",
    "CatalogError",
    "CourseCatalog",
    "CourseInfo",
    "catalog_from_dict",
    "course_catalog_from_engine",
    "fingerprint",
    "load_course_catalog",
    "load_engine_catalog",
    "snapshot_dict",
]

CATALOG_FORMAT: Final = "study1-catalog-v1"
DIAG_SNAPSHOT_FORMAT: Final = "diag-catalog-v1"  # eval.diag_metrics の保存の形（科目の本文を含む）
DEFAULT_DEPARTMENT: Final = "kansai-enechem-2026"
_COURSE_FIELDS: Final = (
    "syllabus_id",
    "name",
    "credits",
    "year_min",
    "year_max",
    "term",
    "slots",
    "slot_note",
    "group_id",
)
_FINGERPRINT_PREFIX: Final = "sha256:"


class CatalogError(ValueError):
    """スナップショットが読めない・形が違う。"""


@dataclass(frozen=True)
class CourseInfo:
    """採点に使う科目の属性。term は科目の学期（春・秋・通年。読めなければ None）、slots は読めた曜限（例 ("月1",)）。"""

    syllabus_id: str
    name: str
    credits: float | None
    year_min: int | None
    year_max: int | None
    term: str | None
    slots: tuple[str, ...]
    slot_note: str | None
    group_id: str | None

    def row(self) -> dict[str, Any]:
        return {
            "syllabus_id": self.syllabus_id,
            "name": self.name,
            "credits": self.credits,
            "year_min": self.year_min,
            "year_max": self.year_max,
            "term": self.term,
            "slots": list(self.slots),
            "slot_note": self.slot_note,
            "group_id": self.group_id,
        }


@dataclass(frozen=True)
class CourseCatalog:
    department_id: str
    data_version: str
    courses: Mapping[str, CourseInfo]
    fingerprint: str
    source: str  # 読んだもの（ファイルの道と形、または engine）
    # 科目名 → 系統図のまとまり（その名前の科目のうち、まとまりのあるものの syllabus_id の最小のもの）
    groups_by_name: Mapping[str, str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_name: dict[str, str] = {}
        for syllabus_id in sorted(self.courses):
            course = self.courses[syllabus_id]
            if course.group_id is not None:
                by_name.setdefault(course.name, course.group_id)
        object.__setattr__(self, "groups_by_name", by_name)

    def get(self, syllabus_id: str) -> CourseInfo | None:
        return self.courses.get(syllabus_id)

    def group_of(self, course: CourseInfo) -> str | None:
        """科目のまとまり。系統図に無いクラス（group_id が無い）は、同じ名前の系統図の科目のまとまりとみなす
        （同じ名前の別クラスへ移した科目を、画面の判定と同じく系統図の科目と同じまとまりとして扱う）。"""
        return course.group_id or self.groups_by_name.get(course.name)


def fingerprint(courses: Iterable[CourseInfo]) -> str:
    """科目の行（syllabus_id の順、キー順・空白なしの JSON）の SHA-256。"""
    rows = [course.row() for course in sorted(courses, key=lambda course: course.syllabus_id)]
    text = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _FINGERPRINT_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _optional_number(value: Any, where: str, problems: list[str]) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append(f"{where}: 数でない（{value!r}）")
        return None
    return float(value)


def _optional_int(value: Any, where: str, problems: list[str]) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(f"{where}: 整数でない（{value!r}）")
        return None
    return value


def _optional_str(value: Any, where: str, problems: list[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        problems.append(f"{where}: 文字列でない（{value!r}）")
        return None
    return value


def _course(raw: Any, index: int, problems: list[str]) -> CourseInfo | None:
    where = f"courses[{index}]"
    if not isinstance(raw, dict):
        problems.append(f"{where}: 形が違う")
        return None
    missing = [key for key in _COURSE_FIELDS if key not in raw]
    if missing:
        problems.append(f"{where}: 項目が無い（{', '.join(missing)}）")
        return None
    syllabus_id, name, slots = raw["syllabus_id"], raw["name"], raw["slots"]
    if not isinstance(syllabus_id, str) or not isinstance(name, str):
        problems.append(f"{where}: syllabus_id か name が文字列でない")
        return None
    if not isinstance(slots, list) or not all(isinstance(slot, str) for slot in slots):
        problems.append(f"{where}: slots が文字列の配列でない")
        return None
    before = len(problems)
    course = CourseInfo(
        syllabus_id=syllabus_id,
        name=name,
        credits=_optional_number(raw["credits"], f"{where}.credits", problems),
        year_min=_optional_int(raw["year_min"], f"{where}.year_min", problems),
        year_max=_optional_int(raw["year_max"], f"{where}.year_max", problems),
        term=_optional_str(raw["term"], f"{where}.term", problems),
        slots=tuple(slots),
        slot_note=_optional_str(raw["slot_note"], f"{where}.slot_note", problems),
        group_id=_optional_str(raw["group_id"], f"{where}.group_id", problems),
    )
    return course if len(problems) == before else None


def catalog_from_dict(data: Any, *, source: str) -> CourseCatalog:
    """study1-catalog-v1 か diag-catalog-v1 の中身から。読めない行が1つでもあれば、件数と例を挙げて止める。"""
    if not isinstance(data, dict):
        raise CatalogError(f"{source}: JSON のオブジェクトではありません。")
    kind = data.get("format")
    if kind not in (CATALOG_FORMAT, DIAG_SNAPSHOT_FORMAT):
        raise CatalogError(f"{source}: 形 {kind!r} は読めません（{CATALOG_FORMAT} か {DIAG_SNAPSHOT_FORMAT}）。")
    department_id, data_version, raw_courses = data.get("department_id"), data.get("data_version"), data.get("courses")
    if not isinstance(department_id, str) or not isinstance(raw_courses, list):
        raise CatalogError(f"{source}: department_id か courses がありません。")
    problems: list[str] = []
    courses: dict[str, CourseInfo] = {}
    for index, raw in enumerate(raw_courses):
        course = _course(raw, index, problems)
        if course is None:
            continue
        if course.syllabus_id in courses:
            problems.append(f"courses[{index}]: syllabus_id {course.syllabus_id} が重なっている")
            continue
        courses[course.syllabus_id] = course
    if problems:
        shown = "; ".join(problems[:5])
        raise CatalogError(f"{source}: 読めない科目の行が {len(problems)} 件あります（{shown}）。")
    digest = fingerprint(courses.values())
    recorded = data.get("fingerprint")
    if kind == CATALOG_FORMAT and recorded != digest:
        raise CatalogError(
            f"{source}: 中身の指紋 {recorded} が科目の行から計算した {digest} と違います（書き換わっている）。"
        )
    return CourseCatalog(
        department_id=department_id,
        data_version=str(data_version),
        courses=courses,
        fingerprint=digest,
        source=f"{source}（{kind}）",
    )


def load_course_catalog(path: Path) -> CourseCatalog:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"{path} を読めません: {exc}") from exc
    return catalog_from_dict(data, source=str(path))


def course_catalog_from_engine(catalog: Catalog) -> CourseCatalog:
    """診断のエンジンの Catalog（course_core.diagnose.model）から。feasibility.py が使う。"""
    courses = {
        course.syllabus_id: CourseInfo(
            syllabus_id=course.syllabus_id,
            name=course.name,
            credits=course.credits,
            year_min=course.year_min,
            year_max=course.year_max,
            term=course.term,
            slots=tuple(course.slots),
            slot_note=course.slot_note,
            group_id=course.group_id,
        )
        for course in catalog.courses
    }
    return CourseCatalog(
        department_id=catalog.department_id,
        data_version=catalog.data_version,
        courses=courses,
        fingerprint=fingerprint(courses.values()),
        source="engine",
    )


def snapshot_dict(
    *,
    department_id: str,
    data_version: str,
    courses: Iterable[CourseInfo],
    groups: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    ordered = sorted(courses, key=lambda course: course.syllabus_id)
    return {
        "format": CATALOG_FORMAT,
        "department_id": department_id,
        "data_version": data_version,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": dict(source),
        "fingerprint": fingerprint(ordered),
        "course_count": len(ordered),
        "courses": [course.row() for course in ordered],
        "groups": [dict(group) for group in groups],
    }


def load_engine_catalog(department_id: str, snapshot: Path | None) -> Catalog:
    """診断のエンジンの Catalog を、DB か diag-catalog-v1 のファイルから読む（feasibility.py が使う）。

    どちらも eval.diag_metrics の関数を使う。diag_metrics は先頭で asyncpg を読むので、ここで読み込む
    （asyncpg の無い手元の環境でも、このモジュールの他の関数は使える）。
    """
    try:
        from eval import diag_metrics
    except ImportError as exc:
        raise CatalogError(
            f"eval.diag_metrics を読めません（{exc}）。asyncpg のある環境（GMS の backend のコンテナ）で打ってください。"
        ) from exc
    if snapshot is not None:
        return diag_metrics.catalog_from_snapshot(json.loads(snapshot.read_text(encoding="utf-8")))
    from course_core.catalog.registry import load_departments

    department = load_departments().get(department_id)
    if department is None:
        raise CatalogError(f"登録に無い学科です: {department_id}")
    return asyncio.run(diag_metrics._catalog_from_db(department))


def _groups_of(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups = data.get("groups")
    if not isinstance(groups, list):
        raise CatalogError("groups がありません。")
    return [{"group_id": g["group_id"], "name": g["name"], "academic_year": g["academic_year"]} for g in groups]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Study 1 の採点に使う科目の属性を JSON に書き出す（リポの外へ）")
    parser.add_argument("--out", type=Path, required=True, help="書き先（リポの外。コンテナでは /tmp の下）")
    parser.add_argument("--department", default=DEFAULT_DEPARTMENT)
    parser.add_argument("--from-diag-snapshot", type=Path, help="DB を読まず、diag-catalog-v1 のファイルから作る")
    args = parser.parse_args(argv)
    try:
        if args.from_diag_snapshot is not None:
            path: Path = args.from_diag_snapshot
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("format") != DIAG_SNAPSHOT_FORMAT:
                raise CatalogError(f"{path} の形が {DIAG_SNAPSHOT_FORMAT} ではありません。")
            catalog = catalog_from_dict(data, source=str(path))
            groups = _groups_of(data)
            source: dict[str, Any] = {"kind": DIAG_SNAPSHOT_FORMAT, "path": str(path), "sha256": sha256_file(path)}
        else:
            engine = load_engine_catalog(args.department, None)
            catalog = course_catalog_from_engine(engine)
            groups = [
                {"group_id": g.group_id, "name": g.name, "academic_year": g.academic_year}
                for g in engine.groups.values()
            ]
            source = {"kind": "db"}
        if catalog.department_id != args.department:
            raise CatalogError(f"データの学科 {catalog.department_id} が --department {args.department} と違います。")
        data_out = snapshot_dict(
            department_id=catalog.department_id,
            data_version=catalog.data_version,
            courses=catalog.courses.values(),
            groups=groups,
            source=source,
        )
        digest = write_private_json(args.out, data_out, "科目のスナップショット")
    except (CatalogError, OutputError, OSError, json.JSONDecodeError) as exc:
        print(f"止めました: {exc}", file=sys.stderr)
        return 1
    print(
        f"科目 {data_out['course_count']} 件を {args.out} に書きました（学科 {catalog.department_id}、データの版 {catalog.data_version}）。"
    )
    print(f"SHA-256 {digest}")
    print(f"中身の指紋 {data_out['fingerprint']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
