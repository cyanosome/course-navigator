"""
Data schema for Kansai University Curriculum Tree (tree_env.pdf) Parser.
Represents course groups (clusters), their member subjects, and group-to-group directed edges.
"""

from enum import Enum
from typing import List, Optional, Tuple, Dict, Any
from pydantic import BaseModel, Field


class EdgeType(str, Enum):
    """Types of edges in curriculum DAG."""
    PREREQUISITE = "prerequisite"           # Standard group prerequisite connection
    ENGLISH_TRACK = "english_track"         # Foreign language progression
    CAPSTONE_RESEARCH = "capstone"          # 3rd year groups -> Special Research 1
    DP_CONTRIBUTION = "dp_contribution"     # Special Research 2 -> DP到達目標


class CourseItem(BaseModel):
    """Individual subject inside a course group."""
    raw_name: str                           # Subject name as written in PDF (e.g., "ユニットオペレーションⅠ")
    normalized_name: str                    # NFKC normalized with arabic numbers (e.g., "ユニットオペレーション1")
    syllabus_id: Optional[str] = None       # Resolved from PostgreSQL courses table
    course_code: Optional[str] = None       # Resolved from PostgreSQL courses table


class CourseGroupNode(BaseModel):
    """Course group / cluster container node in curriculum tree."""
    group_id: str                           # Unique ID (e.g., "G_1Y_ChemEng", "FreshmanSeminar", "DP1")
    label: str                              # Display header label (e.g., "【化学工学・エネルギー・基礎数理系グループ】")
    academic_year: int                      # 1, 2, 3, 4, or 0 (for DP)
    semester: Optional[str] = None          # "春", "秋", "通年", or None
    member_courses: List[CourseItem] = []   # List of subjects contained in this group
    bbox: Optional[Tuple[float, float, float, float]] = None # (x0, top, x1, bottom)


class CourseGroupEdge(BaseModel):
    """Directed edge between two course groups in the curriculum tree."""
    source_group_id: str                    # Source group ID
    target_group_id: str                    # Target group ID
    edge_type: EdgeType = EdgeType.PREREQUISITE
    is_major_connection: bool = True        # True for thick arrows (==>), False for thin (-->)
    source_point: Optional[Tuple[float, float]] = None # Origin coordinate
    target_point: Optional[Tuple[float, float]] = None # Arrowhead apex coordinate


class CurriculumGroupGraph(BaseModel):
    """Complete directed graph representation of curriculum tree."""
    university: str = "関西大学"
    faculty: str = "環境都市工学部"
    department: str = "エネルギー環境・化学工学科"
    academic_year: int = 2026
    groups: List[CourseGroupNode] = []
    edges: List[CourseGroupEdge] = []

    def get_group(self, group_id: str) -> Optional[CourseGroupNode]:
        """Find group by ID."""
        for g in self.groups:
            if g.group_id == group_id:
                return g
        return None

    def to_mermaid(self) -> str:
        """Export graph to Mermaid flowchart TD format."""
        lines = [
            "flowchart TD",
            "    %% Diploma Policy",
            "    subgraph DP[\"ディプロマ・ポリシー (DP)\"]",
        ]
        for g in self.groups:
            if g.academic_year == 0:
                lines.append(f'        {g.group_id}["{g.label}"]')
        lines.append("    end\n")

        for year in [4, 3, 2, 1]:
            year_groups = [g for g in self.groups if g.academic_year == year]
            if not year_groups:
                continue
            lines.append(f"    subgraph Y{year}[\"【{year}年次】\"]")
            for g in year_groups:
                if g.member_courses:
                    course_lines = "<br/>".join([f"・{c.raw_name}" for c in g.member_courses])
                    label = f"<b>{g.label}</b><br/>{course_lines}"
                else:
                    label = g.label
                lines.append(f'        {g.group_id}["{label}"]')
            lines.append("    end\n")

        lines.append("    %% Directed Edges")
        for e in self.edges:
            arrow = "==>" if e.is_major_connection else "-->"
            lines.append(f"    {e.source_group_id} {arrow} {e.target_group_id}")

        return "\n".join(lines)
