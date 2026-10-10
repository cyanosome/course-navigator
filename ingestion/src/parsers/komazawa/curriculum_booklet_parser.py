"""
Komazawa University Common Education Booklet Parser (Style 3).

Applies to the 8-page common education booklet (2026_22.pdf).
Covers:
  - Page 1-3: General Education (Humanities, Social/Natural Sciences, Data Science & AI)
  - Page 4-5: Foreign Languages (English, German, French, Chinese, Spanish, Russian, Korean)
  - Page 6: Health and Physical Education
  - Page 7-8: Teacher Credential and Librarian programs

Extracts course titles, credits, year availability, and links to syllabus codes.
"""

import logging
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Set
from pypdf import PdfReader

from src.parsers.komazawa.curriculum_schema import CurriculumSubjectItem

logger = logging.getLogger(__name__)


def normalize_title(title: str) -> str:
    """Normalize course title."""
    t = unicodedata.normalize("NFKC", title)
    t = t.replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III").replace("Ⅳ", "IV")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_booklet_pdf(
    pdf_path: Path,
    faculty: str = "全学共通",
    department: str = "全学共通科目教養教育科目",
    manifest_id: str = "common_education",
    syllabus_lookup: Optional[Dict[str, List[str]]] = None,
) -> List[CurriculumSubjectItem]:
    """Parse the 8-page common education booklet PDF."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    syllabus_lookup = syllabus_lookup or {}
    reader = PdfReader(pdf_path)
    items: List[CurriculumSubjectItem] = []
    seen_names: Set[str] = set()

    # Page titles mapping
    page_series_map = {
        1: "教養教育科目（人文・社会・自然）",
        2: "データサイエンス・AI・情報リテラシー",
        3: "教養教育科目（総合・キャリア）",
        4: "外国語科目（英語）",
        5: "外国語科目（初習外国語）",
        6: "保健体育科目",
        7: "教職課程科目",
        8: "司書教諭科目",
    }

    # Pre-sort syllabus normalized names by length descending
    sorted_syl_names = sorted(
        [name for name in syllabus_lookup.keys() if len(name) >= 2],
        key=len,
        reverse=True,
    )

    for page_idx, page in enumerate(reader.pages):
        page_num = page_idx + 1
        series_name = page_series_map.get(page_num, "全学共通科目")
        full_text = page.extract_text() or ""
        norm_text = unicodedata.normalize("NFKC", full_text).replace(" ", "")

        # Detect year from text or default to 1 (available from 1st year)
        # Scan syllabus courses appearing on this page
        for syl_norm in sorted_syl_names:
            if syl_norm in norm_text:
                clean_name = unicodedata.normalize("NFKC", syl_norm)
                if clean_name in seen_names:
                    continue
                seen_names.add(clean_name)

                # Determine credits: default 2.0, check for 4-credit indicators
                credits_val = 2.0
                if f"{clean_name}(4)" in norm_text or f"{clean_name}4単位" in norm_text:
                    credits_val = 4.0

                # Determine available year (defaults to 1st year entry for common education)
                year_val = 1
                if "2年～" in norm_text and clean_name in norm_text:
                    year_val = 2
                elif "3年～" in norm_text and clean_name in norm_text:
                    year_val = 3

                syl_codes = syllabus_lookup.get(syl_norm, [])
                subject_id = f"{manifest_id}_p{page_num}_{clean_name}"

                item = CurriculumSubjectItem(
                    id=subject_id,
                    name=clean_name,
                    raw_name=clean_name,
                    faculty=faculty,
                    department=department,
                    year=year_val,
                    requirement_type="選択",
                    credits=credits_val,
                    dp_targets=[],
                    curriculum_code=None,
                    field_code=None,
                    field_name=series_name,
                    source_file=pdf_path.name,
                    style="Style3",
                    matched_syllabus_codes=syl_codes,
                    match_status="exact" if syl_codes else "unmatched",
                )
                items.append(item)

                # Avoid duplicate matching
                norm_text = norm_text.replace(syl_norm, "")

    logger.info("Parsed %d common education courses from %s", len(items), pdf_path.name)
    return items
