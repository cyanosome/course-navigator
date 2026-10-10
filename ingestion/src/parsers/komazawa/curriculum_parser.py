"""
Komazawa University Curriculum Tree Integrated Parser & Dispatcher.

Orchestrates parsing across all 23 documents (Styles 1, 2, 3, 4) using the
appropriate parser strategy based on `manifest.json`.

Outputs:
  - `data/parsed/university/komazawa/2026/curriculum/areacodes.json`
  - `data/parsed/university/komazawa/2026/curriculum/curriculum_subjects.json`
  - `data/parsed/university/komazawa/2026/curriculum/parse_report.json`
"""

import json
import logging
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.parsers.komazawa.areacode_parser import parse_areacode_pdf, save_areacodes
from src.parsers.komazawa.curriculum_block_parser import normalize_string, parse_block_pdf
from src.parsers.komazawa.curriculum_booklet_parser import parse_booklet_pdf
from src.parsers.komazawa.curriculum_matrix_parser import parse_matrix_pdf
from src.parsers.komazawa.curriculum_schema import (
    CurriculumSubjectItem,
    DepartmentParseReport,
    ParseReport,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
RAW_CURRICULUM_DIR = BASE_DIR / "data" / "raw" / "university" / "komazawa" / "2026" / "curriculum"
PARSED_CURRICULUM_DIR = BASE_DIR / "data" / "parsed" / "university" / "komazawa" / "2026" / "curriculum"
SYLLABUS_SUMMARY_FILE = BASE_DIR / "data" / "parsed" / "university" / "komazawa" / "2026" / "courses_summary.json"

STYLE1_IDS = {
    "gms_global_media",
    "economics_economics",
    "economics_commerce",
    "economics_applied",
    "law_law",
    "law_politics",
    "letters_geography_culture",
    "letters_geography_environment",
    "letters_history_japanese",
    "letters_history_foreign",
    "letters_history_archaeology",
}


def load_syllabus_lookup(syllabus_path: Path) -> Dict[str, List[str]]:
    """Build normalized course title to course codes lookup."""
    if not syllabus_path.exists():
        logger.warning("Syllabus summary file not found: %s", syllabus_path)
        return {}

    with open(syllabus_path, encoding="utf-8") as f:
        courses = json.load(f)

    lookup: Dict[str, List[str]] = defaultdict(list)
    for c in courses:
        norm = normalize_string(c["course_name"])
        lookup[norm].append(c["course_code"])
    logger.info("Loaded %d unique course titles from syllabus summary.", len(lookup))
    return dict(lookup)


def parse_all_curriculums(
    raw_dir: Optional[Path] = None,
    parsed_dir: Optional[Path] = None,
    syllabus_path: Optional[Path] = None,
) -> ParseReport:
    """Parse all curriculum PDFs and generate structured JSON outputs."""
    raw_base = raw_dir or RAW_CURRICULUM_DIR
    parsed_base = parsed_dir or PARSED_CURRICULUM_DIR
    syl_path = syllabus_path or SYLLABUS_SUMMARY_FILE

    parsed_base.mkdir(parents=True, exist_ok=True)
    manifest_file = raw_base / "manifest.json"
    if not manifest_file.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_file}")

    with open(manifest_file, encoding="utf-8") as f:
        manifest_items: List[Dict[str, Any]] = json.load(f)

    # 1. Load syllabus lookup for entity resolution
    syllabus_lookup = load_syllabus_lookup(syl_path)

    all_subjects: List[CurriculumSubjectItem] = []
    dept_reports: List[DepartmentParseReport] = []

    # 2. Process each manifest item
    for item in manifest_items:
        manifest_id = item["id"]
        pdf_path = raw_base / item["name"]

        if manifest_id == "areacode":
            # Style 4: Academic Area Code Master
            logger.info("Processing Style 4 Area Codes: %s", item["name"])
            area_codes = parse_areacode_pdf(pdf_path)
            save_areacodes(area_codes, parsed_base / "areacodes.json")
            continue

        item_subjects: List[CurriculumSubjectItem] = []
        style_label: str

        if manifest_id == "common_education":
            # Style 3: Common Education Booklet
            logger.info("Processing Style 3 Booklet: %s", item["name"])
            style_label = "Style3"
            item_subjects = parse_booklet_pdf(
                pdf_path=pdf_path,
                faculty=item["faculty"],
                department=item["department"],
                manifest_id=manifest_id,
                syllabus_lookup=syllabus_lookup,
            )
        elif manifest_id in STYLE1_IDS:
            # Style 1: Standard Matrix
            logger.info("Processing Style 1 Matrix: %s (%s)", item["name"], item["department"])
            style_label = "Style1"
            item_subjects = parse_matrix_pdf(
                pdf_path=pdf_path,
                faculty=item["faculty"],
                department=item["department"],
                manifest_id=manifest_id,
            )
            # Link to syllabus codes
            for sub in item_subjects:
                norm_sub = normalize_string(sub.name)
                matched_codes = syllabus_lookup.get(norm_sub, [])
                if matched_codes:
                    sub.matched_syllabus_codes = matched_codes
                    sub.match_status = "exact"
        else:
            # Style 2: Block / Course-name matching
            logger.info("Processing Style 2 Block: %s (%s)", item["name"], item["department"])
            style_label = "Style2"
            item_subjects = parse_block_pdf(
                pdf_path=pdf_path,
                faculty=item["faculty"],
                department=item["department"],
                manifest_id=manifest_id,
                syllabus_lookup=syllabus_lookup,
            )

        # Audit stats for this department
        matched_cnt = sum(1 for s in item_subjects if s.matched_syllabus_codes)
        unmatched_cnt = len(item_subjects) - matched_cnt
        year_dist = defaultdict(int)
        req_dist = defaultdict(int)
        for s in item_subjects:
            year_dist[s.year] += 1
            req_dist[s.requirement_type] += 1

        dept_reports.append(
            DepartmentParseReport(
                id=manifest_id,
                faculty=item["faculty"],
                department=item["department"],
                filename=item["name"],
                style=style_label,
                extracted_count=len(item_subjects),
                matched_count=matched_cnt,
                unmatched_count=unmatched_cnt,
                year_distribution=dict(year_dist),
                requirement_distribution=dict(req_dist),
            )
        )
        all_subjects.extend(item_subjects)

    # 3. Save curriculum_subjects.json
    subjects_output_path = parsed_base / "curriculum_subjects.json"
    with subjects_output_path.open("w", encoding="utf-8") as f:
        json.dump(
            [s.model_dump() for s in all_subjects],
            f,
            ensure_ascii=False,
            indent=2,
        )
    logger.info("Saved %d total curriculum subjects to: %s", len(all_subjects), subjects_output_path)

    # 4. Generate overall audit report
    total_matched = sum(d.matched_count for d in dept_reports)
    match_rate = (total_matched / len(all_subjects) * 100.0) if all_subjects else 0.0

    report = ParseReport(
        total_files_processed=len(manifest_items),
        total_subjects_extracted=len(all_subjects),
        total_syllabus_matches=total_matched,
        overall_match_rate_pct=round(match_rate, 2),
        departments=dept_reports,
    )

    report_output_path = parsed_base / "parse_report.json"
    with report_output_path.open("w", encoding="utf-8") as f:
        json.dump(report.model_dump(), f, ensure_ascii=False, indent=2)
    logger.info("Saved parsing audit report to: %s", report_output_path)

    return report


def main() -> None:
    """CLI entrypoint for curriculum parser."""
    logger.info("Starting Komazawa University curriculum parser...")
    report = parse_all_curriculums()
    print("\n" + "=" * 60)
    print("=== Komazawa University Curriculum Parsing Summary ===")
    print("=" * 60)
    print(f"Total documents processed: {report.total_files_processed}")
    print(f"Total canonical subjects extracted: {report.total_subjects_extracted}")
    print(f"Total matched with syllabus offerings: {report.total_syllabus_matches} ({report.overall_match_rate_pct:.1f}%)")
    print("-" * 60)
    for d in report.departments:
        print(f"[{d.faculty} {d.department}] ({d.style}): {d.extracted_count} subjects (Matched: {d.matched_count})")
    print("=" * 60)


if __name__ == "__main__":
    main()
