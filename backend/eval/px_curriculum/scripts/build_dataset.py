"""PX のデータセットを作る: グループ DAG・科目→グループ・各科目のシラバス項目を JSON に出す。

入力:
  data_raw/2026/curriculum/tree_env.pdf  … リポの KansaiCurriculumTreeParser（page 6）で辺を抽出
  data_raw/2026/catalog_index.json       … 学科の履修科目一覧（1029件）
  work/parsed/courses_detail.json        … 取得した127件のシラバス詳細（リポの KansaiSyllabusTransformer）
出力:
  dataset/group_dag.json, dataset/courses.json, dataset/dataset_summary.json

科目の対応の規則（事前に決めたもの。報告に書く）:
  1. 系統図の科目名と catalog の科目名を、リポの normalize_title で正規化して完全一致させる。
  2. 「数学を学ぶ（微分積分N・演習N）」は catalog では講義「数学を学ぶ（微分積分N）」と演習「数学を学ぶ（微分積分演習N）」の
     2科目に分かれている。系統図の1科目として扱い、代表は講義のほう（演習の科目コードも記録する）。
  3. 同名で複数クラスあるときの代表は syllabus_id が最小のクラス。授業概要・到達目標はその代表から取る。
  4. 配当年次 = year_range の最小の年次（全クラスで同じか確かめる）。
     学期 = 全クラスの学期（詳細ページの jyugyokeitai）の最頻値。同数で割れたら「春学期または秋学期（クラスにより異なる）」。
     「秋（隔・ク）」は秋、「夏集」は夏期集中として扱う（B-year の順序は 春 < 夏期集中 < 秋）。
  5. 2026年度の catalog に無い科目は「シラバス無し」として残し、PX-1 の標本から外す。
"""
import sys
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

PX = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PX / "code" / "ingestion"))

import networkx as nx  # noqa: E402
from src.transformers.kansai.curriculum_tree_parser import (  # noqa: E402
    KansaiCurriculumTreeParser,
    PAGE_6_GROUPS_DEF,
    normalize_title,
)

RAW = PX / "data_raw" / "2026"
PDF = RAW / "curriculum" / "tree_env.pdf"
CATALOG = RAW / "catalog_index.json"
DETAIL = PX / "work" / "parsed" / "courses_detail.json"
OUT = PX / "dataset"
TEXT_LIMIT = 300
MATH_SPLIT = {
    "数学を学ぶ（微分積分Ⅰ・演習Ⅰ）": ("数学を学ぶ（微分積分１）", "数学を学ぶ（微分積分演習１）"),
    "数学を学ぶ（微分積分Ⅱ・演習Ⅱ）": ("数学を学ぶ（微分積分２）", "数学を学ぶ（微分積分演習２）"),
}
SEM_LABEL = {"春": "春学期", "夏集": "夏期集中", "秋": "秋学期"}


def first_year(year_range: str) -> int | None:
    s = unicodedata.normalize("NFKC", year_range or "")
    m = re.search(r"(\d)", s)
    return int(m.group(1)) if m else None


def clip(text: str | None) -> str:
    t = " ".join((text or "").split())
    return t[:TEXT_LIMIT]


def semester_label(sems: list[str]) -> tuple[str, str | None]:
    """(表示用の学期, 正規化した学期キー 春/秋/None) を返す。"""
    norm = []
    for s in sems:
        if s.startswith("春"):
            norm.append("春")
        elif s.startswith("秋"):
            norm.append("秋")
        else:
            norm.append(s)
    cnt = Counter(norm).most_common()
    if len(cnt) > 1 and cnt[0][1] == cnt[1][1]:
        return "春学期または秋学期（クラスにより異なる）", None
    top = cnt[0][0]
    return SEM_LABEL.get(top, top), (top if top in SEM_LABEL else None)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    details = {d["syllabus_id"]: d for d in json.loads(DETAIL.read_text(encoding="utf-8"))}
    cat_by_norm: dict[str, list[dict]] = {}
    for e in catalog:
        cat_by_norm.setdefault(normalize_title(e["subject_name"]), []).append(e)

    # --- グループ DAG（リポの Transformer の出力をそのまま使う）---
    parser = KansaiCurriculumTreeParser(courses_json_path=CATALOG)
    graph = parser.parse_pdf(pdf_path=PDF, page_number=6)
    g = nx.DiGraph()
    for node in graph.groups:
        g.add_node(node.group_id)
    for e in graph.edges:
        g.add_edge(e.source_group_id, e.target_group_id)
    is_dag = nx.is_directed_acyclic_graph(g)
    group_dag = {
        "source": "KansaiCurriculumTreeParser.parse_pdf(tree_env.pdf, page_number=6) @ origin/main 14f8d57",
        "is_dag": is_dag,
        "n_nodes": g.number_of_nodes(),
        "n_edges": g.number_of_edges(),
        "nodes": [{"group_id": n.group_id, "label": n.label, "academic_year": n.academic_year,
                   "semester": n.semester, "n_members": len(n.member_courses),
                   "is_dp": n.group_id.startswith("DP")} for n in graph.groups],
        "edges": [{"source": e.source_group_id, "target": e.target_group_id, "edge_type": e.edge_type.value,
                   "is_major": e.is_major_connection} for e in graph.edges],
    }
    (OUT / "group_dag.json").write_text(json.dumps(group_dag, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- 科目 ---
    repo_resolved = {(n.group_id, c.raw_name): c.syllabus_id for n in graph.groups for c in n.member_courses}
    courses = []
    for gd in PAGE_6_GROUPS_DEF:
        for name in gd["courses"]:
            rec = {"course_id": None, "name": name, "group_id": gd["id"], "group_label": gd["label"],
                   "group_year": gd["academic_year"], "repo_parser_syllabus_id": repo_resolved.get((gd["id"], name))}
            if name in MATH_SPLIT:
                lec, ex = MATH_SPLIT[name]
                sections = cat_by_norm.get(normalize_title(lec), [])
                ex_sections = cat_by_norm.get(normalize_title(ex), [])
                rec["match_rule"] = "split: 講義+演習の2科目。代表は講義"
                rec["exercise_course_codes"] = sorted({details[s["syllabus_id"]]["course_code"] for s in ex_sections if s["syllabus_id"] in details})
            else:
                sections = cat_by_norm.get(normalize_title(name), [])
                rec["match_rule"] = "exact" if sections else "none"
            if not sections:
                rec.update({"has_syllabus": False})
                courses.append(rec)
                continue
            sections = sorted(sections, key=lambda s: s["syllabus_id"])
            rep = details[sections[0]["syllabus_id"]]
            sec_details = [details[s["syllabus_id"]] for s in sections]
            years = sorted({first_year(s["year_range"]) for s in sections})
            sem_disp, sem_key = semester_label([d["semester"] or "" for d in sec_details])
            rec.update({
                "has_syllabus": True,
                "n_sections": len(sections),
                "syllabus_id": rep["syllabus_id"],
                "course_code": rep["course_code"],
                "course_codes_all_sections": sorted({d["course_code"] for d in sec_details}),
                "subject_name_syllabus": rep["subject_name"],
                "year": years[0],
                "years_all_sections": years,
                "year_range_raw": sections[0]["year_range"],
                "semester_display": sem_disp,
                "semester_key": sem_key,
                "semesters_all_sections": [d["semester"] for d in sec_details],
                "description_300": clip(rep["description"]),
                "objectives_300": clip(rep["objectives"]),
                "description_len": len(" ".join((rep["description"] or "").split())),
                "objectives_len": len(" ".join((rep["objectives"] or "").split())),
                "detail_url": rep["detail_url"],
            })
            courses.append(rec)
    for i, c in enumerate(courses, 1):
        c["course_id"] = f"c{i:02d}"
    (OUT / "courses.json").write_text(json.dumps(courses, ensure_ascii=False, indent=1), encoding="utf-8")

    n_with = sum(1 for c in courses if c["has_syllabus"])
    summary = {
        "group_dag": {"is_dag": is_dag, "n_nodes": g.number_of_nodes(), "n_edges": g.number_of_edges(),
                      "n_dp_nodes": sum(1 for n in g if n.startswith("DP"))},
        "n_tree_courses": len(courses),
        "n_with_syllabus": n_with,
        "n_without_syllabus": len(courses) - n_with,
        "without_syllabus": [c["name"] for c in courses if not c["has_syllabus"]],
        "match_rule_counts": Counter(c["match_rule"] for c in courses),
        "repo_parser_resolved": sum(1 for c in courses if c["repo_parser_syllabus_id"]),
        "repo_vs_mine_syllabus_id_differs": [
            {"name": c["name"], "repo": c["repo_parser_syllabus_id"], "mine": c.get("syllabus_id")}
            for c in courses if c["repo_parser_syllabus_id"] != c.get("syllabus_id")],
        "multi_year_sections": [c["name"] for c in courses if c.get("years_all_sections") and len(c["years_all_sections"]) > 1],
        "year_differs_from_group_year": [
            {"name": c["name"], "group": c["group_id"], "group_year": c["group_year"], "syllabus_year": c.get("year")}
            for c in courses if c["has_syllabus"] and c["group_year"] != c.get("year")],
        "semester_ambiguous": [c["name"] for c in courses if c["has_syllabus"] and c["semester_key"] is None],
        "empty_objectives": [c["name"] for c in courses if c["has_syllabus"] and not c["objectives_300"]],
        "empty_description": [c["name"] for c in courses if c["has_syllabus"] and not c["description_300"]],
    }
    (OUT / "dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for c in courses:
        if c["has_syllabus"]:
            print(c["course_id"], c["group_id"], c["name"], c["year"], c["semester_display"], c["semesters_all_sections"], c["n_sections"], len(c["description_300"]), len(c["objectives_300"]))


if __name__ == "__main__":
    main()
