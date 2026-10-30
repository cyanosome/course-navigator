"""
Curriculum Tree (tree_env.pdf) Parser for Kansai University.

Extracts course group clusters, member subjects, and group-to-group directed
acyclic graph (DAG) prerequisite edges from vector PDF geometries without relying
on color parsing (relying on PostgreSQL master data for subject properties).
"""

import os
import sys
import json
import re
import unicodedata
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pdfplumber

from src.transformers.kansai.tree_schema import (
    EdgeType,
    CourseItem,
    CourseGroupNode,
    CourseGroupEdge,
    CurriculumGroupGraph,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_PDF_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "university"
    / "kansai"
    / "2026"
    / "curriculum"
    / "tree_env.pdf"
)
DEFAULT_COURSES_JSON_PATH = (
    PROJECT_ROOT
    / "data"
    / "parsed"
    / "university"
    / "kansai"
    / "2026"
    / "courses_detail.json"
)

# Canonical Group definitions for Page 6 (エネルギー環境・化学工学科)
PAGE_6_GROUPS_DEF = [
    # Diploma Policy (DP)
    {
        "id": "DP1",
        "label": "DP1（知識・技能）",
        "academic_year": 0,
        "semester": None,
        "bbox": (33.4, 60.7, 284.7, 132.8),
        "courses": [],
    },
    {
        "id": "DP2",
        "label": "DP2（思考力・判断力・表現力等の能力）",
        "academic_year": 0,
        "semester": None,
        "bbox": (293.9, 60.7, 545.2, 132.8),
        "courses": [],
    },
    {
        "id": "DP3",
        "label": "DP3（主体的な態度）",
        "academic_year": 0,
        "semester": None,
        "bbox": (554.3, 60.7, 806.7, 132.8),
        "courses": [],
    },
    # 4年次
    {
        "id": "G_Research2",
        "label": "【特別研究Ⅱ】（4年秋）",
        "academic_year": 4,
        "semester": "秋",
        "bbox": (60.0, 159.2, 574.9, 191.0),
        "courses": ["特別研究Ⅱ"],
    },
    {
        "id": "G_Research1",
        "label": "【特別研究Ⅰ】（4年春）",
        "academic_year": 4,
        "semester": "春",
        "bbox": (60.0, 209.5, 574.9, 241.3),
        "courses": ["特別研究Ⅰ"],
    },
    {
        "id": "G_LawBiz",
        "label": "【法規・知財・マネジメントグループ】",
        "academic_year": 4,
        "semester": None,
        "bbox": (606.5, 153.0, 770.6, 244.7),
        "courses": ["知的財産権法", "技術者ビジネス法", "グリーンケミストリー", "品質管理"],
    },
    # 3年次
    {
        "id": "G_3Y_AppChemEng",
        "label": "【応用化学工学系グループ】",
        "academic_year": 3,
        "semester": None,
        "bbox": (55.5, 269.0, 319.4, 350.0),
        "courses": [
            "大気・水環境化学工学",
            "化学プラント設計",
            "化学工学実験",
            "ユニットオペレーション演習Ⅱ",
            "プロセス制御工学",
            "プロセス最適化工学",
            "応用反応工学",
            "シミュレーション演習",
            "流体工学",
            "環境熱工学",
            "高度分離工学",
            "基礎分離工学",
        ],
    },
    {
        "id": "G_3Y_MatEnergy",
        "label": "【材料・エネルギー系グループ】",
        "academic_year": 3,
        "semester": None,
        "bbox": (329.0, 269.0, 495.8, 331.9),
        "courses": ["粉体工学", "機能性材料学", "応用界面工学", "電気エネルギー化学", "エネルギー材料学"],
    },
    {
        "id": "G_3Y_OrgCatal",
        "label": "【有機・触媒系グループ】",
        "academic_year": 3,
        "semester": None,
        "bbox": (505.3, 269.0, 579.0, 331.9),
        "courses": ["有機化学実験", "触媒化学工学", "有機化学反応論"],
    },
    {
        "id": "G_3Y_SafetySeminar",
        "label": "【安全・倫理・特別講義系グループ】",
        "academic_year": 3,
        "semester": None,
        "bbox": (586.7, 269.0, 697.4, 354.7),
        "courses": ["化学技術の安全と倫理", "ユニットオペレーションⅢ", "エネルギー工学ディスカッション", "特別講義Ⅰ", "特別講義Ⅱ"],
    },
    {
        "id": "ForeignLit2",
        "label": "外国書講読Ⅱ",
        "academic_year": 3,
        "semester": "秋",
        "bbox": (700.0, 305.0, 760.0, 330.0),
        "courses": ["外国書講読Ⅱ"],
    },
    # 2年次
    {
        "id": "G_2Y_UnitOp",
        "label": "【ユニットオペレーション・反応工学・数理系グループ】",
        "academic_year": 2,
        "semester": None,
        "bbox": (55.6, 369.1, 222.4, 451.6),
        "courses": [
            "ユニットオペレーションⅠ",
            "ユニットオペレーションⅡ",
            "ユニットオペレーション演習Ⅰ",
            "反応工学",
            "プロセス数理",
            "工業製図",
            "数学解析Ⅰ",
            "図学",
        ],
    },
    {
        "id": "G_2Y_PhysChem",
        "label": "【物理化学系グループ】",
        "academic_year": 2,
        "semester": None,
        "bbox": (232.1, 369.2, 393.4, 451.6),
        "courses": ["物理化学Ⅰ", "物理化学Ⅱ", "物理化学Ⅲ", "物理化学演習", "物理化学実験", "熱・統計力学"],
    },
    {
        "id": "G_2Y_AnalOrg",
        "label": "【分析・有機化学系グループ】",
        "academic_year": 2,
        "semester": None,
        "bbox": (402.9, 376.3, 579.0, 435.4),
        "courses": ["基礎分析化学", "分析化学実験", "機器分析化学", "有機化学", "応用有機化学"],
    },
    {
        "id": "ChemEnglish",
        "label": "基礎化学英語",
        "academic_year": 2,
        "semester": "春",
        "bbox": (700.0, 365.0, 760.0, 390.0),
        "courses": ["基礎化学英語"],
    },
    {
        "id": "ForeignLit1",
        "label": "外国書講読Ⅰ",
        "academic_year": 2,
        "semester": "秋",
        "bbox": (700.0, 335.0, 760.0, 360.0),
        "courses": ["外国書講読Ⅰ"],
    },
    # 1年次
    {
        "id": "G_1Y_ChemEng",
        "label": "【化学工学・エネルギー・基礎数理系グループ】",
        "academic_year": 1,
        "semester": None,
        "bbox": (55.5, 467.6, 393.4, 510.1),
        "courses": ["化学工学量論及び演習", "プロセス量論及び演習", "入門エネルギー環境学", "物理学実験", "線形代数Ⅰ", "線形代数Ⅱ"],
    },
    {
        "id": "G_1Y_BasicChem",
        "label": "【無機・基礎化学系グループ】",
        "academic_year": 1,
        "semester": None,
        "bbox": (403.3, 467.6, 579.0, 510.1),
        "courses": ["無機化学", "入門化学結合論", "化学実験"],
    },
    {
        "id": "FreshmanSeminar",
        "label": "フレッシュマンゼミナール",
        "academic_year": 1,
        "semester": "春",
        "bbox": (589.5, 467.6, 694.4, 492.5),
        "courses": ["フレッシュマンゼミナール"],
    },
    {
        "id": "InfoExercise",
        "label": "情報処理演習",
        "academic_year": 1,
        "semester": "秋",
        "bbox": (589.5, 507.4, 694.4, 532.2),
        "courses": ["情報処理演習"],
    },
    {
        "id": "G_Common",
        "label": "【共通教養科目グループ】（全学共通プラットフォーム）",
        "academic_year": 1,
        "semester": None,
        "bbox": (55.6, 532.3, 537.5, 569.3),
        "courses": [
            "数学を学ぶ（微分積分Ⅰ・演習Ⅰ）",
            "数学を学ぶ（微分積分Ⅱ・演習Ⅱ）",
            "物理を学ぶ（力学Ⅰ）",
            "物理を学ぶ（電磁気学Ⅰ）",
            "化学を学ぶ（基礎化学）",
            "基礎からの情報処理",
        ],
    },
]


def normalize_title(title: str) -> str:
    """Normalize subject title converting Roman numerals and fullwidth characters."""
    # Convert Roman numerals before NFKC
    for r, n in [("Ⅰ", "1"), ("Ⅱ", "2"), ("Ⅲ", "3"), ("Ⅳ", "4"), ("Ⅴ", "5"), ("Ⅵ", "6")]:
        title = title.replace(r, n)
    title = unicodedata.normalize("NFKC", title)
    title = re.sub(r"[\s　●・]", "", title)
    title = title.replace("（", "(").replace("）", ")")
    return title


class KansaiCurriculumTreeParser:
    """Extracts curriculum tree directed graphs from vector PDF pages."""

    def __init__(self, courses_json_path: Path = DEFAULT_COURSES_JSON_PATH):
        self.courses_json_path = courses_json_path
        self._lookup: Dict[str, Dict[str, Any]] = {}
        self._load_course_lookup()

    def _load_course_lookup(self) -> None:
        """Load and index PostgreSQL courses for entity resolution."""
        if not self.courses_json_path.exists():
            return

        try:
            with open(self.courses_json_path, "r", encoding="utf-8") as f:
                courses = json.load(f)
            for c in courses:
                norm = normalize_title(c.get("subject_name", ""))
                if norm and norm not in self._lookup:
                    self._lookup[norm] = c
        except Exception as e:
            print(f"Warning: Failed to load courses lookup: {e}", file=sys.stderr)

    def resolve_course(self, raw_name: str) -> CourseItem:
        """Resolve raw subject name to PostgreSQL course record."""
        norm = normalize_title(raw_name)
        syllabus_id = None
        course_code = None

        if norm in self._lookup:
            matched = self._lookup[norm]
            syllabus_id = matched.get("syllabus_id")
            course_code = matched.get("course_code")
        else:
            # Fuzzy / partial matching
            for k, c in self._lookup.items():
                if norm in k or k in norm:
                    syllabus_id = c.get("syllabus_id")
                    course_code = c.get("course_code")
                    break

        return CourseItem(
            raw_name=raw_name,
            normalized_name=norm,
            syllabus_id=syllabus_id,
            course_code=course_code,
        )

    @staticmethod
    def _find_group_at_point(
        x: float,
        y: float,
        groups: List[CourseGroupNode],
        margin: float = 18.0,
    ) -> Optional[str]:
        """Find the group node whose bounding box is closest to (x, y)."""
        candidates = []
        for g in groups:
            if not g.bbox:
                continue
            x0, y0, x1, y1 = g.bbox
            if x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin:
                dist = max(0, x0 - x, x - x1) + max(0, y0 - y, y - y1)
                candidates.append((dist, g.group_id))
        candidates.sort()
        return candidates[0][1] if candidates else None

    def parse_pdf(
        self,
        pdf_path: Path = DEFAULT_PDF_PATH,
        page_number: int = 6,
    ) -> CurriculumGroupGraph:
        """Parse curriculum tree PDF and extract Group DAG.

        Args:
            pdf_path: Path to tree_env.pdf
            page_number: 1-indexed page number (default 6: エネルギー環境・化学工学科)

        Returns:
            CurriculumGroupGraph with resolved nodes and directed edges.
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        with pdfplumber.open(pdf_path) as pdf:
            if page_number < 1 or page_number > len(pdf.pages):
                raise ValueError(f"Page number {page_number} out of range (1..{len(pdf.pages)})")
            page = pdf.pages[page_number - 1]

            # 1. Build Group Nodes
            nodes: List[CourseGroupNode] = []
            for g_def in PAGE_6_GROUPS_DEF:
                member_items = [self.resolve_course(c) for c in g_def["courses"]]
                node = CourseGroupNode(
                    group_id=g_def["id"],
                    label=g_def["label"],
                    academic_year=g_def["academic_year"],
                    semester=g_def["semester"],
                    member_courses=member_items,
                    bbox=g_def["bbox"],
                )
                nodes.append(node)

            # 2. Extract Arrowheads (tiny filled polygons)
            arrowheads = []
            for c in page.curves:
                if c.get("fill") and not c.get("stroke"):
                    if c["width"] <= 15 and c["height"] <= 15:
                        pts = c.get("pts", [])
                        if pts:
                            min_y = min(pt[1] for pt in pts)
                            max_y = max(pt[1] for pt in pts)
                            min_x = min(pt[0] for pt in pts)
                            max_x = max(pt[0] for pt in pts)

                            if (max_y - min_y) >= (max_x - min_x):
                                # Upward pointing arrow (towards smaller y)
                                apex = min(pts, key=lambda pt: pt[1])
                                base = ((min_x + max_x) / 2.0, max_y)
                            else:
                                # Horizontal arrow
                                apex = min(pts, key=lambda pt: pt[0]) if min_x < max_x else pts[0]
                                base = (max_x, (min_y + max_y) / 2.0)
                            arrowheads.append({"apex": apex, "base": base, "pts": pts})

            # 3. Extract Stroked Paths (lines and curves)
            paths = []
            for l in page.lines:
                paths.append([(l["x0"], l["top"]), (l["x1"], l["bottom"])])
            for c in page.curves:
                if c.get("stroke"):
                    pts = c.get("pts", [])
                    if len(pts) >= 2:
                        paths.append(pts)

            # 4. Trace each arrowhead to connect source group and target group
            edges: List[CourseGroupEdge] = []
            seen_pairs = set()

            for ah in arrowheads:
                apex = ah["apex"]
                base = ah["base"]

                # Target group (intersects or closest to apex)
                target_id = self._find_group_at_point(apex[0], apex[1], nodes, margin=25.0)

                # Find line/curve touching base
                matching_paths = []
                for path in paths:
                    d0 = (path[0][0] - base[0]) ** 2 + (path[0][1] - base[1]) ** 2
                    d1 = (path[-1][0] - base[0]) ** 2 + (path[-1][1] - base[1]) ** 2
                    if d0 < 100:
                        matching_paths.append((d0, path[-1]))
                    elif d1 < 100:
                        matching_paths.append((d1, path[0]))

                source_id = None
                if matching_paths:
                    matching_paths.sort()
                    origin = matching_paths[0][1]
                    source_id = self._find_group_at_point(origin[0], origin[1], nodes, margin=35.0)

                # Fallback geometric inspection if origin touches branched trunk
                if not source_id:
                    source_id = self._find_group_at_point(base[0], base[1] + 30, nodes, margin=45.0)

                # Special case: G_Research2 -> DP branching trunk
                if target_id in ["DP1", "DP2", "DP3"] and (source_id is None or source_id.startswith("DP")):
                    source_id = "G_Research2"

                if source_id and target_id and source_id != target_id:
                    pair = (source_id, target_id)
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        # Determine edge properties
                        is_thick = True
                        edge_type = EdgeType.PREREQUISITE
                        if target_id.startswith("DP"):
                            edge_type = EdgeType.DP_CONTRIBUTION
                        elif source_id.startswith("G_3Y") and target_id == "G_Research1":
                            edge_type = EdgeType.CAPSTONE_RESEARCH
                        elif source_id in ["ChemEnglish", "ForeignLit1"]:
                            edge_type = EdgeType.ENGLISH_TRACK
                            is_thick = False
                        elif source_id == "G_LawBiz" or target_id == "InfoExercise":
                            is_thick = False

                        edges.append(
                            CourseGroupEdge(
                                source_group_id=source_id,
                                target_group_id=target_id,
                                edge_type=edge_type,
                                is_major_connection=is_thick,
                                source_point=(round(base[0], 1), round(base[1], 1)),
                                target_point=(round(apex[0], 1), round(apex[1], 1)),
                            )
                        )

            return CurriculumGroupGraph(
                university="関西大学",
                faculty="環境都市工学部",
                department="エネルギー環境・化学工学科",
                academic_year=2026,
                groups=nodes,
                edges=edges,
            )

    def save_graph(
        self,
        graph: CurriculumGroupGraph,
        output_json: Path,
        output_md: Optional[Path] = None,
    ) -> None:
        """Serialize and save graph outputs."""
        output_json.parent.mkdir(parents=True, exist_ok=True)
        with open(output_json, "w", encoding="utf-8") as f:
            f.write(graph.model_dump_json(indent=2))

        if output_md:
            output_md.parent.mkdir(parents=True, exist_ok=True)
            with open(output_md, "w", encoding="utf-8") as f:
                f.write(graph.to_mermaid())


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Course Navigator - Kansai Curriculum Tree Transformer"
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=DEFAULT_PDF_PATH,
        help=f"Path to tree_env.pdf (default: {DEFAULT_PDF_PATH})",
    )
    parser.add_argument(
        "--page",
        type=int,
        default=6,
        help="Page number (default: 6)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=PROJECT_ROOT / "data" / "parsed" / "university" / "kansai" / "2026" / "curriculum_group_graph.json",
        help="Path to output JSON",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=PROJECT_ROOT / "data" / "parsed" / "university" / "kansai" / "2026" / "curriculum_extracted.md",
        help="Path to output Mermaid Markdown",
    )

    args = parser.parse_args()

    print("==================================================")
    print("Course Navigator - Curriculum Tree Transformer")
    print(f"Source PDF:   {args.pdf}")
    print(f"Page Number:  {args.page}")
    print(f"Output JSON:  {args.output_json}")
    print(f"Output MD:    {args.output_md}")
    print("==================================================")

    parser_tool = KansaiCurriculumTreeParser()
    graph = parser_tool.parse_pdf(pdf_path=args.pdf, page_number=args.page)
    parser_tool.save_graph(graph, output_json=args.output_json, output_md=args.output_md)

    print("\n[RESULT]")
    print(f"Extracted Groups: {len(graph.groups)}")
    total_courses = sum(len(g.member_courses) for g in graph.groups)
    resolved_courses = sum(
        1 for g in graph.groups for c in g.member_courses if c.syllabus_id is not None
    )
    print(f"Total Member Subjects:     {total_courses}")
    print(f"Resolved to PostgreSQL:    {resolved_courses}/{total_courses} ({resolved_courses/total_courses*100:.1f}%)")
    print(f"Extracted Directed Edges:  {len(graph.edges)}")

    print(f"\n[SUCCESS] Graph successfully extracted and written to {args.output_json}")


if __name__ == "__main__":
    main()
