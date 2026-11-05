"""Navi integration router for /api/navi/departments/{id}."""

import re
from typing import Any, List
from fastapi import APIRouter, HTTPException, Request

from course_core.schemas.navi import (
    Department,
    Frame,
    FrameEdge,
    GradNeed,
    Interest,
    NaviCourse,
    Requirements,
    TeacherKnown,
    TeacherNotInSyllabus,
)

router = APIRouter(prefix="/navi", tags=["navi"])

_QUERY_REQUIREMENT = """
MATCH (r:GraduationRequirement)
WHERE r.requirement_id = $id OR $id IN ['kansai-system-eng', 'default', 'latest']
RETURN r
LIMIT 1;
"""

_QUERY_FALLBACK_REQ = """
MATCH (r:GraduationRequirement)
RETURN r
LIMIT 1;
"""

_QUERY_FRAMES = """
MATCH (cg:CourseGroup)
RETURN cg.group_id AS id,
       cg.academic_year AS year,
       cg.label AS name
ORDER BY year ASC, id ASC;
"""

_QUERY_FRAME_EDGES = """
MATCH (c1:Course)-[:BELONGS_TO_GROUP]->(cg1:CourseGroup)
MATCH (c2:Course)-[:BELONGS_TO_GROUP]->(cg2:CourseGroup)
MATCH (c1)-[:REQUIRES_PREREQUISITE]->(c2)
WHERE cg1.group_id <> cg2.group_id
RETURN DISTINCT cg2.group_id AS from_id, cg1.group_id AS to_id;
"""

_QUERY_COURSES = """
MATCH (c:Course)
OPTIONAL MATCH (c)-[:BELONGS_TO_GROUP]->(cg:CourseGroup)
OPTIONAL MATCH (c)-[:TAUGHT_BY]->(p:Professor)
OPTIONAL MATCH (c)-[:CLASSIFIED_AS]->(req:RequirementCategory)
OPTIONAL MATCH (c)-[:OFFERED_BY]->(f:Faculty)
WITH c, cg, head(collect(DISTINCT p.name)) AS prof_name,
     head(collect(DISTINCT req.requirement_type)) AS req_type,
     head(collect(DISTINCT f.name)) AS faculty_name
RETURN coalesce(c.course_code, c.code, '') AS code,
       coalesce(c.title, c.name, '') AS name,
       cg.group_id AS frame_id,
       c.credits AS credits,
       c.semester AS semester,
       c.year_range AS year_range,
       c.detail_url AS detail_url,
       c.teaching_type AS teaching_type,
       faculty_name,
       prof_name,
       req_type
ORDER BY code ASC;
"""


def _parse_term(semester: str | None) -> str:
    if not semester:
        return "春"
    if "春" in semester:
        return "春"
    if "秋" in semester:
        return "秋"
    return "通年"


def _parse_year(year_range: str | None) -> int:
    if not year_range:
        return 1
    m = re.search(r"(\d+)", year_range)
    if m:
        return int(m.group(1))
    return 1


@router.get("/departments/{department_id}", response_model=Department)
async def get_department(department_id: str, request: Request) -> Department:
    """Retrieve full department syllabus, cluster frames, prerequisite edges, and graduation requirements."""
    driver = getattr(request.app.state, "neo4j_driver", None)
    if not driver:
        raise HTTPException(status_code=503, detail="Neo4j driver is not initialized")

    async with driver.session() as session:
        # 1. Graduation Requirement
        res_req = await session.run(_QUERY_REQUIREMENT, id=department_id)
        rec_req = await res_req.single()
        if not rec_req:
            res_fallback = await session.run(_QUERY_FALLBACK_REQ)
            rec_req = await res_fallback.single()

        req_node = rec_req["r"] if rec_req else None
        dept_name = req_node.get("department_name", "エネルギー環境・化学工学科") if req_node else "システム理工学部"
        fac_name = req_node.get("faculty_name", "環境都市工学部") if req_node else "環境都市工学部"
        acad_year = int(req_node.get("academic_year", 2026)) if req_node else 2026
        total_creds = float(req_node.get("total_credits", 128.0)) if req_node else 128.0
        req_creds = float(req_node.get("major_required_credits", 53.0)) if req_node else 53.0
        elec_creds = float(req_node.get("major_elective_required_credits", 30.0)) if req_node else 30.0

        requirements = Requirements(
            total=total_creds,
            termCap=24.0,
            needs=[
                GradNeed(category="必修", need=req_creds),
                GradNeed(category="選択", need=elec_creds),
            ],
        )

        # 2. Frames
        res_frames = await session.run(_QUERY_FRAMES)
        frame_records = await res_frames.data()
        frames: list[Frame] = []
        for fr in frame_records:
            name = fr.get("name") or fr.get("id") or ""
            plain = name.replace("【", "").replace("】", "").replace("グループ", "")
            frames.append(
                Frame(
                    id=fr["id"],
                    year=int(fr.get("year") or 1),
                    name=name,
                    plain=plain,
                    common="Common" in fr["id"],
                )
            )

        # 3. Frame Edges
        res_edges = await session.run(_QUERY_FRAME_EDGES)
        edge_records = await res_edges.data()
        edges = [
            FrameEdge(from_=er["from_id"], to=er["to_id"])
            for er in edge_records
            if er.get("from_id") and er.get("to_id")
        ]

        # 4. Courses
        res_courses = await session.run(_QUERY_COURSES)
        course_records = await res_courses.data()
        courses: list[NaviCourse] = []
        for cr in course_records:
            if not cr.get("code") or not cr.get("name"):
                continue

            prof_name = cr.get("prof_name")
            teacher = (
                TeacherKnown(name=prof_name)
                if prof_name
                else TeacherNotInSyllabus()
            )

            req_type = cr.get("req_type")
            kind_val = "必修" if req_type == "required" else ("選択" if req_type in ("elective", "elective_required") else None)
            grad_val = "必修" if req_type == "required" else ("選択" if req_type in ("elective", "elective_required") else None)

            courses.append(
                NaviCourse(
                    code=cr["code"],
                    name=cr["name"],
                    short=None,
                    frameId=cr.get("frame_id"),
                    faculty=cr.get("faculty_name"),
                    year=_parse_year(cr.get("year_range")),
                    yearRange=cr.get("year_range"),
                    term=_parse_term(cr.get("semester")),
                    slots=[],
                    slotNote=None,
                    credits=cr.get("credits"),
                    kind=kind_val,
                    grad=grad_val,
                    teacher=teacher,
                    learn="",
                    summary=cr.get("name", ""),
                    plan=[],
                    syllabusUrl=cr.get("detail_url"),
                )
            )

        return Department(
            id=department_id,
            university="関西大学",
            faculty=fac_name,
            name=dept_name,
            dataVersion="2026.1",
            syllabusYear=acad_year,
            frames=frames,
            edges=edges,
            courses=courses,
            interests=[],
            requirements=requirements,
        )
