"""
Komazawa University Block-Matching Curriculum Parser (Style 2).

Applies to 10 faculties/departments without 10-digit codes:
  - Buddhism (Zen, Buddhist Studies)
  - Literature (Japanese, English, Sociology, Social Welfare, Psychology)
  - Business Administration (Management, Market Strategy)
  - Health Sciences (Radiological Technology)

Extracts:
  - Course names via geometric line-building and longest-match against syllabus index
  - Target year (1 to 4) via dynamic year header x-coordinate clustering
  - Requirement type from context headers or syllabus defaults
  - Links to 6-digit syllabus codes via entity resolution
"""

import logging
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from pypdf import PdfReader

from src.parsers.komazawa.curriculum_schema import CurriculumSubjectItem

logger = logging.getLogger(__name__)


def normalize_string(text: str) -> str:
    """Normalize string for exact and fuzzy matching."""
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III").replace("Ⅳ", "IV")
    t = re.sub(r"\s+", "", t)
    return t


def detect_year_boundaries(page) -> List[float]:
    """Detect dynamic column split points (x coordinates) for years 1 to 4."""
    width = float(page.mediabox.width)
    year_positions: Dict[int, List[float]] = {1: [], 2: [], 3: [], 4: []}

    def visitor(text, cm, tm, font_dict, font_size):
        t = text.strip()
        for yr in [1, 2, 3, 4]:
            if re.search(rf"[{yr}{chr(0xFF10 + yr)}]年", t):
                year_positions[yr].append(tm[4])

    page.extract_text(visitor_text=visitor)

    x_coords = {}
    for yr in [1, 2, 3, 4]:
        if year_positions[yr]:
            x_coords[yr] = min(year_positions[yr])
        else:
            x_coords[yr] = width * (0.20 + (yr - 1) * 0.20)

    # Ensure monotonic order
    for yr in [2, 3, 4]:
        if x_coords[yr] <= x_coords[yr - 1]:
            x_coords[yr] = x_coords[yr - 1] + (width * 0.18)

    b1 = (x_coords[1] + x_coords[2]) / 2.0
    b2 = (x_coords[2] + x_coords[3]) / 2.0
    b3 = (x_coords[3] + x_coords[4]) / 2.0

    return [b1, b2, b3]


def determine_year_from_x(x: float, boundaries: List[float]) -> int:
    """Determine year (1 to 4) given x coordinate and boundaries."""
    if x < boundaries[0]:
        return 1
    elif x < boundaries[1]:
        return 2
    elif x < boundaries[2]:
        return 3
    else:
        return 4


def parse_block_pdf(
    pdf_path: Path,
    faculty: str,
    department: str,
    manifest_id: str,
    syllabus_lookup: Optional[Dict[str, List[str]]] = None,
) -> List[CurriculumSubjectItem]:
    """Parse a Style 2 (Block / Course-name Centered) curriculum PDF."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    syllabus_lookup = syllabus_lookup or {}
    reader = PdfReader(pdf_path)
    items: List[CurriculumSubjectItem] = []
    seen_keys: Set[Tuple[str, int]] = set()

    # Pre-sort syllabus normalized names by length descending for greedy matching
    sorted_syl_names = sorted(
        [name for name in syllabus_lookup.keys() if len(name) >= 2],
        key=len,
        reverse=True,
    )

    for page_idx, page in enumerate(reader.pages):
        boundaries = detect_year_boundaries(page)

        # Collect text tokens with coordinates
        tokens: List[Tuple[float, float, str]] = []

        def visitor(text, cm, tm, font_dict, font_size):
            t = text.strip()
            if t:
                tokens.append((tm[4], tm[5], t))

        page.extract_text(visitor_text=visitor)

        # Sort tokens primarily by y descending (top-to-bottom), then x ascending (left-to-right)
        tokens.sort(key=lambda t: (-round(t[1], 0), round(t[0], 0)))

        # Group tokens into lines by y-coordinate (tolerance: ~4 points)
        lines: List[List[Tuple[float, float, str]]] = []
        current_y = None
        current_line: List[Tuple[float, float, str]] = []

        for x, y, text in tokens:
            if current_y is None or abs(y - current_y) > 4.0:
                if current_line:
                    lines.append(current_line)
                current_y = y
                current_line = [(x, y, text)]
            else:
                current_line.append((x, y, text))

        if current_line:
            lines.append(current_line)

        # Parse courses from line groups
        for line_tokens in lines:
            line_str = " ".join(t[2] for t in line_tokens)
            norm_line = normalize_string(line_str)

            # Look for requirement context in line
            req_type = "選択"
            if "必修" in line_str and "選択必修" not in line_str:
                req_type = "必修"
            elif "選択必修" in line_str:
                req_type = "選択必修"

            # Check for matches against syllabus titles
            for syl_norm in sorted_syl_names:
                if syl_norm in norm_line:
                    # Find corresponding token to get x-coordinate
                    matched_token_x = line_tokens[0][0]
                    for tx, ty, tt in line_tokens:
                        if normalize_string(tt) in syl_norm or syl_norm in normalize_string(tt):
                            matched_token_x = tx
                            break

                    year = determine_year_from_x(matched_token_x, boundaries)
                    clean_name = unicodedata.normalize("NFKC", syl_norm)

                    dedup_key = (clean_name, year)
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)

                    syl_codes = syllabus_lookup.get(syl_norm, [])
                    subject_id = f"{manifest_id}_{year}_{clean_name}"

                    item = CurriculumSubjectItem(
                        id=subject_id,
                        name=clean_name,
                        raw_name=line_str,
                        faculty=faculty,
                        department=department,
                        year=year,
                        requirement_type=req_type,
                        credits=2.0,
                        dp_targets=[],
                        curriculum_code=None,
                        field_code=None,
                        field_name=None,
                        source_file=pdf_path.name,
                        style="Style2",
                        matched_syllabus_codes=syl_codes,
                        match_status="exact" if syl_codes else "unmatched",
                    )
                    items.append(item)

                    # Remove matched substring to prevent sub-string false positives
                    norm_line = norm_line.replace(syl_norm, "")

    logger.info(
        "Parsed %d Style 2 courses from %s (%s %s)",
        len(items),
        pdf_path.name,
        faculty,
        department,
    )
    return items
