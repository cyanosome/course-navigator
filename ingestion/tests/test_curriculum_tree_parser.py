"""
Unit tests for Kansai Curriculum Tree (tree_env.pdf) Parser and DAG Extractor.
"""

import json
from pathlib import Path
import pytest

from src.transformers.kansai.tree_schema import (
    EdgeType,
    CourseItem,
    CourseGroupNode,
    CourseGroupEdge,
    CurriculumGroupGraph,
)
from src.transformers.kansai.curriculum_tree_parser import (
    KansaiCurriculumTreeParser,
    normalize_title,
    DEFAULT_PDF_PATH,
    DEFAULT_COURSES_JSON_PATH,
)

EXPECTED_25_EDGES = {
    ("G_Common", "G_1Y_ChemEng"),
    ("G_Common", "G_1Y_BasicChem"),
    ("G_Common", "InfoExercise"),
    ("G_1Y_ChemEng", "G_2Y_UnitOp"),
    ("G_1Y_ChemEng", "G_2Y_PhysChem"),
    ("G_1Y_BasicChem", "G_2Y_PhysChem"),
    ("G_1Y_BasicChem", "G_2Y_AnalOrg"),
    ("FreshmanSeminar", "G_3Y_SafetySeminar"),
    ("G_2Y_UnitOp", "G_3Y_AppChemEng"),
    ("G_2Y_PhysChem", "G_3Y_AppChemEng"),
    ("G_2Y_PhysChem", "G_3Y_MatEnergy"),
    ("G_2Y_AnalOrg", "G_3Y_MatEnergy"),
    ("G_2Y_AnalOrg", "G_3Y_OrgCatal"),
    ("ChemEnglish", "ForeignLit1"),
    ("ForeignLit1", "ForeignLit2"),
    ("G_3Y_AppChemEng", "G_Research1"),
    ("G_3Y_MatEnergy", "G_Research1"),
    ("G_3Y_OrgCatal", "G_Research1"),
    ("G_3Y_SafetySeminar", "G_Research1"),
    ("ForeignLit2", "G_Research1"),
    ("G_Research1", "G_Research2"),
    ("G_LawBiz", "G_Research2"),
    ("G_Research2", "DP1"),
    ("G_Research2", "DP2"),
    ("G_Research2", "DP3"),
}


def test_normalize_title():
    assert normalize_title("ユニットオペレーションⅠ") == "ユニットオペレーション1"
    assert normalize_title("数学を学ぶ（微分積分Ⅱ・演習Ⅱ）") == "数学を学ぶ(微分積分2演習2)"
    assert normalize_title("● 有機化学実験") == "有機化学実験"
    assert normalize_title("特別研究１") == "特別研究1"


def test_course_group_graph_mermaid():
    g1 = CourseGroupNode(
        group_id="G1",
        label="Group 1",
        academic_year=1,
        member_courses=[CourseItem(raw_name="科目A", normalized_name="科目A")],
    )
    g2 = CourseGroupNode(
        group_id="G2",
        label="Group 2",
        academic_year=2,
        member_courses=[CourseItem(raw_name="科目B", normalized_name="科目B")],
    )
    edge = CourseGroupEdge(source_group_id="G1", target_group_id="G2", is_major_connection=True)
    graph = CurriculumGroupGraph(groups=[g1, g2], edges=[edge])

    mermaid = graph.to_mermaid()
    assert "flowchart TD" in mermaid
    assert "G1 ==> G2" in mermaid
    assert "科目A" in mermaid
    assert "科目B" in mermaid


def test_parse_pdf_page_6_live():
    if not DEFAULT_PDF_PATH.exists():
        pytest.skip(f"tree_env.pdf not found at {DEFAULT_PDF_PATH}")

    parser = KansaiCurriculumTreeParser(courses_json_path=DEFAULT_COURSES_JSON_PATH)
    graph = parser.parse_pdf(pdf_path=DEFAULT_PDF_PATH, page_number=6)

    # 1. Verify Groups
    assert len(graph.groups) == 21
    group_ids = {g.group_id for g in graph.groups}
    assert "G_Common" in group_ids
    assert "G_1Y_ChemEng" in group_ids
    assert "G_2Y_UnitOp" in group_ids
    assert "G_3Y_AppChemEng" in group_ids
    assert "G_Research1" in group_ids
    assert "G_Research2" in group_ids
    assert "DP1" in group_ids
    assert "DP2" in group_ids
    assert "DP3" in group_ids

    # 2. Verify Member subjects count and entity resolution rate
    total_subjects = sum(len(g.member_courses) for g in graph.groups)
    assert total_subjects == 70

    resolved_subjects = sum(
        1 for g in graph.groups for c in g.member_courses if c.syllabus_id is not None
    )
    resolution_rate = resolved_subjects / total_subjects
    assert resolution_rate >= 0.90, f"Expected resolution >= 90%, got {resolution_rate*100:.1f}%"

    # 3. Verify Directed Edges (100% precision & recall against expected 25 edges)
    extracted_edges = {(e.source_group_id, e.target_group_id) for e in graph.edges}
    assert len(extracted_edges) == 25

    missing_edges = EXPECTED_25_EDGES - extracted_edges
    extra_edges = extracted_edges - EXPECTED_25_EDGES

    assert len(missing_edges) == 0, f"Missing edges: {missing_edges}"
    assert len(extra_edges) == 0, f"Unexpected extra edges: {extra_edges}"
    assert extracted_edges == EXPECTED_25_EDGES


def test_save_graph(tmp_path: Path):
    if not DEFAULT_PDF_PATH.exists():
        pytest.skip(f"tree_env.pdf not found at {DEFAULT_PDF_PATH}")

    parser = KansaiCurriculumTreeParser(courses_json_path=DEFAULT_COURSES_JSON_PATH)
    graph = parser.parse_pdf(pdf_path=DEFAULT_PDF_PATH, page_number=6)

    out_json = tmp_path / "graph.json"
    out_md = tmp_path / "graph.md"

    parser.save_graph(graph, output_json=out_json, output_md=out_md)

    assert out_json.exists()
    assert out_md.exists()

    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert len(data["groups"]) == 21
    assert len(data["edges"]) == 25

    md_content = out_md.read_text(encoding="utf-8")
    assert "flowchart TD" in md_content
    assert "G_1Y_ChemEng ==> G_2Y_UnitOp" in md_content
