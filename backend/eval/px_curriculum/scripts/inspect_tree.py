"""tree_env.pdf をリポの Transformer で解析し、辺と PDF の文字列を確かめる（データ準備の点検用）。"""
import sys
import json
from pathlib import Path

PX = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PX / "code" / "ingestion"))

import pdfplumber  # noqa: E402
from src.transformers.kansai.curriculum_tree_parser import (  # noqa: E402
    KansaiCurriculumTreeParser,
    PAGE_6_GROUPS_DEF,
)

PDF = PX / "data_raw" / "2026" / "curriculum" / "tree_env.pdf"
CATALOG = PX / "data_raw" / "2026" / "catalog_index.json"
OUT = PX / "work"
OUT.mkdir(exist_ok=True)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = KansaiCurriculumTreeParser(courses_json_path=CATALOG)
    graph = parser.parse_pdf(pdf_path=PDF, page_number=6)
    parser.save_graph(graph, OUT / "curriculum_group_graph_catalog_lookup.json", OUT / "curriculum_extracted.md")
    print("groups", len(graph.groups), "edges", len(graph.edges))
    for e in graph.edges:
        print("EDGE", e.source_group_id, "->", e.target_group_id, e.edge_type.value, e.is_major_connection)

    with pdfplumber.open(PDF) as pdf:
        print("pages", len(pdf.pages))
        for i, p in enumerate(pdf.pages, 1):
            txt = (p.extract_text() or "")[:80].replace("\n", " | ")
            print("PAGE", i, txt)
        page = pdf.pages[5]
        text = page.extract_text() or ""
        (OUT / "page6_text.txt").write_text(text, encoding="utf-8")
        words = page.extract_words(keep_blank_chars=True, use_text_flow=False)
        (OUT / "page6_words.json").write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
        print("words", len(words))


if __name__ == "__main__":
    main()
