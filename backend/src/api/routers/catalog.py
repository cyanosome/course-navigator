"""学科・科目のデータ API（navi-v1、api-contract.md 2 章の D1〜D6）。

画面はデータを JSON で抱えず、このルーターを通して DB に逐次問い合わせる。
区分・卒業要件は DB に問い合わせ、表か学科の行が無いときだけ status "pending" を返す（固定の pending は返さない）。
外から見えるパスは `/api` の後ろ（Traefik が `/api` を剥がす）。
"""

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Final, get_args

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.contract import set_contract_header
from course_core.catalog import mapping
from course_core.catalog.registry import DepartmentEntry, GroupMeta, GroupMetaEntry, load_departments, load_group_meta
from course_core.catalog.search import CourseFilter, QueryTooLongError, filter_and_sort, ilike_pattern, split_query
from course_core.repositories import neo4j_curriculum_repo, postgres_courses_repo, postgres_requirements_repo
from course_core.schemas.catalog import (
    CourseDetail,
    CoursePage,
    CourseSummary,
    DataStatus,
    DepartmentDataStatus,
    DepartmentGraph,
    DepartmentOverview,
    DepartmentSummary,
    EdgeType,
    GroupEdge,
    GroupNode,
    InterestExtraOut,
    InterestOut,
    KindCode,
    RequirementsOut,
    Term,
)

if TYPE_CHECKING:  # 実行時は asyncpg を読まない（型だけ）
    import asyncpg

router = APIRouter(tags=["catalog"], dependencies=[Depends(set_contract_header)])

logger = logging.getLogger(__name__)

_EDGE_TYPES: Final[tuple[EdgeType, ...]] = get_args(EdgeType)
_KIND_CODES: Final[tuple[KindCode, ...]] = get_args(KindCode)
_SYLLABUS_ID_RE: Final = re.compile(r"^[0-9A-Za-z_-]{1,20}$")
_SLOT_RE: Final = re.compile(r"^[月火水木金土日]\d$")
_REASON_NO_TABLE: Final = "表が無い"
_REASON_NO_ROWS: Final = "この学科の行が無い"
_AVAILABLE: Final = DataStatus(status="available")
_NO_GROUP_META: Final = GroupMetaEntry()


# --- 依存と共通の下ごしらえ ------------------------------------------------------------


def _department(dept_id: str) -> DepartmentEntry:
    department = load_departments().get(dept_id)
    if department is None:
        raise HTTPException(status_code=404, detail=f"学科が見つかりません: {dept_id}")
    return department


def _department_or_default(dept: str | None) -> DepartmentEntry:
    """クエリの dept。省略なら登録の唯一の学科（登録が2つ以上なら省略を受けない）。"""
    if dept is not None:
        return _department(dept)
    departments = load_departments()
    if len(departments) != 1:
        raise HTTPException(status_code=422, detail="dept を指定してください（学科が複数あります）。")
    return next(iter(departments.values()))


def _pool(request: Request) -> Any:  # app.state は型を持たない（境界）
    return request.app.state.db_pool


def _driver(request: Request) -> Any:  # app.state は型を持たない（境界）
    return request.app.state.neo4j_driver


@dataclass(frozen=True)
class _Kinds:
    status: DataStatus
    join_code: str | None  # course_requirements を JOIN するときの学科コード（表が無ければ None）
    counts: dict[str, int]


async def _kinds(
    conn: asyncpg.Connection,
    department: DepartmentEntry,
    tables: postgres_requirements_repo.RequirementsTables,
) -> _Kinds:
    if not tables.course:
        return _Kinds(DataStatus(status="pending", reason=_REASON_NO_TABLE), None, {})
    code = department.pg.department_code
    counts = await postgres_requirements_repo.count_course_kinds(conn, code)
    if not counts:
        return _Kinds(DataStatus(status="pending", reason=_REASON_NO_ROWS), code, counts)
    return _Kinds(_AVAILABLE, code, counts)


async def _graduation(
    conn: asyncpg.Connection,
    department: DepartmentEntry,
    tables: postgres_requirements_repo.RequirementsTables,
) -> tuple[DataStatus, asyncpg.Record | None]:
    if not tables.graduation:
        return DataStatus(status="pending", reason=_REASON_NO_TABLE), None
    pg = department.pg
    row = await postgres_requirements_repo.fetch_graduation_requirements(
        conn, pg.academic_year, pg.faculty_code, pg.department_code
    )
    if row is None:
        return DataStatus(status="pending", reason=_REASON_NO_ROWS), None
    return _AVAILABLE, row


def _membership(groups: Iterable[neo4j_curriculum_repo.GroupRecord]) -> dict[str, str]:
    """syllabus_id → まとまり。2つ以上に属する科目は先のまとまり（学年 → group_id の順）。"""
    membership: dict[str, str] = {}
    for group in groups:
        for syllabus_id in group.members:
            membership.setdefault(syllabus_id, group.group_id)
    return membership


async def _summary(request: Request, department: DepartmentEntry) -> DepartmentSummary:
    async with _pool(request).acquire() as conn:
        course_count = await postgres_courses_repo.count_courses(conn, department.pg.academic_year)
    async with _driver(request).session() as session:
        groups = await neo4j_curriculum_repo.fetch_groups(
            session, department.neo4j.faculty, department.neo4j.department
        )
    return DepartmentSummary(
        id=department.id,
        university=department.university,
        faculty=department.faculty,
        name=department.name,
        syllabus_year=department.syllabus_year,
        data_version=department.data_version,
        course_count=course_count,
        group_count=len(groups),
    )


def _parse_edge_types(raw: str | None) -> list[EdgeType]:
    if raw is None:
        return list(_EDGE_TYPES)
    values = list(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    unknown = [value for value in values if value not in _EDGE_TYPES]
    if not values or unknown:
        raise HTTPException(
            status_code=422,
            detail=f"edge_types は {','.join(_EDGE_TYPES)} からカンマ区切りで選んでください: {raw!r}",
        )
    return values  # type: ignore[return-value]


def _mapped[T](build: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """写像の失敗（DB の値が壊れている）を、科目の ID 入りの例外のままログに残して 500 にする。"""
    try:
        return build(*args, **kwargs)
    except ValueError:
        logger.exception("DB の行を応答の型に写せませんでした")
        raise


def _group_node(group: neo4j_curriculum_repo.GroupRecord, meta: GroupMeta) -> GroupNode:
    entry = meta.groups.get(group.group_id, _NO_GROUP_META)
    return GroupNode(
        group_id=group.group_id,
        label=group.label,
        name=mapping.group_display_name(group.label, entry.name),
        plain=entry.plain,
        common=entry.common,
        academic_year=group.academic_year,
        semester=group.semester,
        member_count=len(group.members),
    )


# --- D1・D2 学科 ----------------------------------------------------------------------


@router.get("/departments", response_model=list[DepartmentSummary])
async def list_departments(request: Request) -> list[DepartmentSummary]:
    """D1: データのある学科の一覧。"""
    return [await _summary(request, department) for department in load_departments().values()]


@router.get("/departments/{dept_id}", response_model=DepartmentOverview)
async def get_department(dept_id: str, request: Request) -> DepartmentOverview:
    """D2: 学科の概要とデータの状態（区分・卒業要件の有無、類似度の線の本数など）。"""
    department = _department(dept_id)
    summary = await _summary(request, department)
    async with _pool(request).acquire() as conn:
        tables = await postgres_requirements_repo.requirements_tables_exist(conn)
        requirements_status, _ = await _graduation(conn, department, tables)
        kinds = await _kinds(conn, department, tables)
    async with _driver(request).session() as session:
        similar = await neo4j_curriculum_repo.count_similar_edges(session)
        group_edges = await neo4j_curriculum_repo.count_group_edges(
            session, department.neo4j.faculty, department.neo4j.department
        )
    return DepartmentOverview(
        **summary.model_dump(),
        data_status=DepartmentDataStatus(
            requirements=requirements_status,
            kinds=kinds.status,
            classified_courses=sum(kinds.counts.values()),
            similar_to_edges=similar.count,
            similar_models=list(similar.models),
            group_edges=group_edges,
        ),
    )


# --- D3 系統図 -----------------------------------------------------------------------


@router.get("/departments/{dept_id}/graph", response_model=DepartmentGraph)
async def get_department_graph(
    dept_id: str,
    request: Request,
    edge_types: Annotated[str | None, Query(description="カンマ区切り。既定は prerequisite,capstone,english_track")] = None,
) -> DepartmentGraph:
    """D3: まとまり・まとまりどうしの線・興味関心・系統図に載る科目の一覧の項目。"""
    department = _department(dept_id)
    selected_edge_types = _parse_edge_types(edge_types)
    meta = load_group_meta(department.id)

    async with _driver(request).session() as session:
        groups = await neo4j_curriculum_repo.fetch_groups(
            session, department.neo4j.faculty, department.neo4j.department
        )
        edge_rows = await neo4j_curriculum_repo.fetch_group_edges(
            session, department.neo4j.faculty, department.neo4j.department, selected_edge_types
        )
    membership = _membership(groups)
    async with _pool(request).acquire() as conn:
        tables = await postgres_requirements_repo.requirements_tables_exist(conn)
        kinds = await _kinds(conn, department, tables)
        rows = await postgres_courses_repo.fetch_courses_by_ids(
            conn, list(membership), kinds_department_code=kinds.join_code
        )

    summaries = {
        row["syllabus_id"]: _mapped(
            mapping.course_summary_from_row, row, group_id=membership[row["syllabus_id"]]
        )
        for row in rows
    }
    missing = sorted(set(membership) - set(summaries))
    if missing:
        logger.warning(
            "系統図の科目のうち %d 件が courses にありません（学科 %s）: %s",
            len(missing), department.id, ", ".join(missing),
        )
    # 並びは まとまり（学年 → group_id）→ syllabus_id（membership の入れた順）。画面のおすすめの同点は、この並びで決まる。
    members = [summaries[sid] for sid in membership if sid in summaries]

    group_ids = {group.group_id for group in groups}
    for interest in meta.interests:
        unknown = [target for target in interest.targets if target not in group_ids]
        if unknown:
            logger.warning("興味関心 %s の行き先が系統図にありません: %s", interest.id, ", ".join(unknown))

    return DepartmentGraph(
        department_id=department.id,
        edge_types=selected_edge_types,
        groups=[_group_node(group, meta) for group in groups],
        edges=[
            GroupEdge(
                source=row["source"],
                target=row["target"],
                edge_type=row["edge_type"],
                is_major=row["is_major"],
            )
            for row in edge_rows
        ],
        interests=[
            InterestOut(
                id=interest.id,
                label=interest.label,
                targets=list(interest.targets),
                extras=[
                    InterestExtraOut(syllabus_id=extra.syllabus_id, why=extra.why, source=extra.source)
                    for extra in interest.extras
                ],
            )
            for interest in meta.interests
        ],
        members=members,
    )


# --- D4・D5 科目 ----------------------------------------------------------------------


@router.get("/courses", response_model=CoursePage)
async def search_courses(
    request: Request,
    dept: str | None = None,
    q: str | None = None,
    year: Annotated[int | None, Query(ge=1, le=4)] = None,
    term: Term | None = None,
    slot: Annotated[list[str], Query()] = [],
    group: Annotated[list[str], Query()] = [],
    kind: Annotated[list[KindCode], Query()] = [],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CoursePage:
    """D4: 科目の検索。q は空白区切りの語の AND（科目名・概要・到達目標の部分一致）。"""
    department = _department_or_default(dept)
    try:
        words = split_query(q)
    except QueryTooLongError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    bad_slots = [value for value in slot if not _SLOT_RE.match(value)]
    if bad_slots:
        raise HTTPException(status_code=422, detail=f"slot は「月2」の形で指定してください: {bad_slots}")

    async with _pool(request).acquire() as conn:
        tables = await postgres_requirements_repo.requirements_tables_exist(conn)
        kinds = await _kinds(conn, department, tables)
        rows = await postgres_courses_repo.search_courses(
            conn,
            academic_year=department.pg.academic_year,
            patterns=[ilike_pattern(word) for word in words],
            kinds_department_code=kinds.join_code,
        )
    async with _driver(request).session() as session:
        groups = await neo4j_curriculum_repo.fetch_groups(
            session, department.neo4j.faculty, department.neo4j.department
        )
    membership = _membership(groups)

    courses: list[CourseSummary] = [
        _mapped(mapping.course_summary_from_row, row, group_id=membership.get(row["syllabus_id"]))
        for row in rows
    ]
    matched = filter_and_sort(
        courses,
        CourseFilter(
            year=year,
            term=term,
            slots=frozenset(slot),
            groups=frozenset(group),
            kinds=frozenset(kind),
        ),
        words,
    )
    return CoursePage(
        total=len(matched),
        limit=limit,
        offset=offset,
        items=matched[offset : offset + limit],
        kinds_status=kinds.status.status,
    )


@router.get("/courses/{syllabus_id}", response_model=CourseDetail)
async def get_course(syllabus_id: str, request: Request, dept: str | None = None) -> CourseDetail:
    """D5: 科目の詳細（区分の表があれば要覧の行も）。"""
    if not _SYLLABUS_ID_RE.match(syllabus_id):
        raise HTTPException(status_code=404, detail=f"科目が見つかりません: {syllabus_id}")
    department = _department_or_default(dept)
    async with _pool(request).acquire() as conn:
        tables = await postgres_requirements_repo.requirements_tables_exist(conn)
        row = await postgres_courses_repo.fetch_course_detail(
            conn,
            syllabus_id,
            kinds_department_code=department.pg.department_code if tables.course else None,
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"科目が見つかりません: {syllabus_id}")
    async with _driver(request).session() as session:
        group_ids = await neo4j_curriculum_repo.fetch_course_group(
            session, syllabus_id, department.neo4j.faculty, department.neo4j.department
        )
    return _mapped(mapping.course_detail_from_row, row, group_id=group_ids[0] if group_ids else None)


# --- D6 卒業要件と区分 -----------------------------------------------------------------


@router.get("/departments/{dept_id}/requirements", response_model=RequirementsOut)
async def get_requirements(dept_id: str, request: Request) -> RequirementsOut:
    """D6: 卒業要件と区分。DB に問い合わせ、表か学科の行が無いときだけ pending。"""
    department = _department(dept_id)
    async with _pool(request).acquire() as conn:
        tables = await postgres_requirements_repo.requirements_tables_exist(conn)
        requirements_status, row = await _graduation(conn, department, tables)
        kinds = await _kinds(conn, department, tables)
    return RequirementsOut(
        department_id=department.id,
        status=requirements_status.status,
        reason=requirements_status.reason,
        requirements=_mapped(mapping.graduation_requirements_from_row, row) if row is not None else None,
        kinds=kinds.status,
        kinds_count={code: kinds.counts.get(code, 0) for code in _KIND_CODES} | kinds.counts,
    )
