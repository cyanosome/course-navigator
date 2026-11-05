"""系統図の70科目を、学科の履修科目一覧（catalog_index.json, 1029件）と照合する。

完全一致（リポの normalize_title 後）と、リポの部分一致（norm in k or k in norm）の候補を両方出す。
"""
import sys
import json
from pathlib import Path

PX = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PX / "code" / "ingestion"))

from src.transformers.kansai.curriculum_tree_parser import PAGE_6_GROUPS_DEF, normalize_title  # noqa: E402

CATALOG = PX / "data_raw" / "2026" / "catalog_index.json"
OUT = PX / "work"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_norm = {}
    for e in cat:
        by_norm.setdefault(normalize_title(e["subject_name"]), []).append(e)
    result = []
    for g in PAGE_6_GROUPS_DEF:
        for c in g["courses"]:
            n = normalize_title(c)
            exact = by_norm.get(n, [])
            partial = [] if exact else [e for k, es in by_norm.items() if (n in k or k in n) for e in es]
            result.append({"group": g["id"], "name": c, "norm": n,
                           "exact": [{k: e[k] for k in ("syllabus_id", "subject_name", "year_range", "class_name", "term_schedule", "relative_ref_path")} for e in exact],
                           "partial": [{k: e[k] for k in ("syllabus_id", "subject_name", "year_range", "class_name", "term_schedule")} for e in partial][:8]})
    n_exact = sum(1 for r in result if r["exact"])
    print("subjects", len(result), "exact-matched", n_exact)
    for r in result:
        if len(r["exact"]) != 1:
            print("--", r["group"], r["name"], "exact:", len(r["exact"]))
            for e in r["exact"]:
                print("    E", e["syllabus_id"], e["subject_name"], e["year_range"], e["class_name"], e["term_schedule"])
            for e in r["partial"]:
                print("    P", e["syllabus_id"], e["subject_name"], e["year_range"], e["class_name"], e["term_schedule"])
    (OUT / "catalog_match.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
