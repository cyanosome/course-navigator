"""
Komazawa University Standard Matrix Curriculum Parser (Style 1).

Applies to 11 faculties/departments including GMS, Economics, Law,
Literature (Geography, History).
Extracts:
  - requirement_type (■ 必修, ◆ 選択必修, ● 選択)
  - course name (normalized)
  - credits (e.g. 2, 4)
  - diploma policy targets (DP e.g. ["2", "3", "4"])
  - 10-digit curriculum code and 3-digit subject area code
  - target year (1 to 4) via dynamic symbol x-coordinate column clustering
"""

import logging
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from pypdf import PdfReader

from src.parsers.komazawa.curriculum_schema import CurriculumSubjectItem

logger = logging.getLogger(__name__)

# Pattern for Style 1 course entry:
# Group 1: Symbol (■, ◆, ●)
# Group 2: Course title
# Group 3: Credits
# Group 4: DP target (optional)
# Group 5: 10-digit code or "なし" (optional)
COURSE_PATTERN = re.compile(
    r"([■◆●])\s*([^\(（\n]+?)[\(（](\d+)[）\)]\s*([0-9・]+)?\s*(\d{10}|なし)?"
)

REQUIREMENT_MAP: Dict[str, str] = {
    "■": "必修",
    "◆": "選択必修",
    "●": "選択",
}


def normalize_title(title: str) -> str:
    """Normalize course title for matching and display."""
    t = unicodedata.normalize("NFKC", title)
    t = t.replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III").replace("Ⅳ", "IV")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def detect_year_boundaries(page) -> List[float]:
    """Detect dynamic column split points (x coordinates) for years 1 to 4."""
    width = float(page.mediabox.width)
    year_positions: Dict[int, List[float]] = {1: [], 2: [], 3: [], 4: []}

    def visitor(text, cm, tm, font_dict, font_size):
        t = text.strip()
        # Look for headers like "1年次", "１年次", "1年次前期", "2年"
        for yr in [1, 2, 3, 4]:
            if re.search(rf"[{yr}{chr(0xFF10 + yr)}]年", t):
                year_positions[yr].append(tm[4])

    page.extract_text(visitor_text=visitor)

    # Pick representative position for each year header
    x_coords = {}
    for yr in [1, 2, 3, 4]:
        if year_positions[yr]:
            x_coords[yr] = min(year_positions[yr])
        else:
            x_coords[yr] = width * (0.15 + (yr - 1) * 0.22)

    # Ensure monotonic order
    for yr in [2, 3, 4]:
        if x_coords[yr] <= x_coords[yr - 1]:
            x_coords[yr] = x_coords[yr - 1] + (width * 0.2)

    # Split boundaries between year columns: [split_1_2, split_2_3, split_3_4]
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


def parse_matrix_pdf(
    pdf_path: Path,
    faculty: str,
    department: str,
    manifest_id: str,
) -> List[CurriculumSubjectItem]:
    """Parse a Style 1 (Standard Matrix) curriculum PDF into CurriculumSubjectItems."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    reader = PdfReader(pdf_path)
    items: List[CurriculumSubjectItem] = []
    seen_keys = set()

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

        # Chunk tokens by course symbol (■, ◆, ●) to accurately associate each course with its symbol's x-coordinate
        chunks: List[Tuple[float, float, str]] = []
        current_chunk: List[str] = []
        current_x: Optional[float] = None
        current_y: Optional[float] = None

        for x, y, t in tokens:
            if t and t[0] in "■◆●":
                if current_chunk and current_x is not None:
                    chunks.append((current_x, current_y, " ".join(current_chunk)))
                current_chunk = [t]
                current_x = x
                current_y = y
            elif current_chunk:
                current_chunk.append(t)

        if current_chunk and current_x is not None:
            chunks.append((current_x, current_y, " ".join(current_chunk)))

        for sym_x, sym_y, chunk_text in chunks:
            norm_chunk = unicodedata.normalize("NFKC", chunk_text)
            match = COURSE_PATTERN.search(norm_chunk)
            if not match:
                continue

            sym = match.group(1)
            raw_name = match.group(2).strip()
            credits_val = float(match.group(3))
            dp_str = match.group(4) or ""
            code_str = match.group(5) or None

            clean_name = normalize_title(raw_name)
            req_type = REQUIREMENT_MAP.get(sym, "選択")
            year = determine_year_from_x(sym_x, boundaries)

            dp_list = [d.strip() for d in dp_str.split("・") if d.strip().isdigit()]
            curriculum_code = code_str if code_str and code_str != "なし" else None
            field_code = curriculum_code[:3] if curriculum_code and len(curriculum_code) == 10 else None

            subject_id = (
                f"{manifest_id}_{curriculum_code}"
                if curriculum_code
                else f"{manifest_id}_{year}_{clean_name}"
            )

            dedup_key = (clean_name, year, curriculum_code)
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            item = CurriculumSubjectItem(
                id=subject_id,
                name=clean_name,
                raw_name=raw_name,
                faculty=faculty,
                department=department,
                year=year,
                requirement_type=req_type,
                credits=credits_val,
                dp_targets=dp_list,
                curriculum_code=curriculum_code,
                field_code=field_code,
                field_name=None,
                source_file=pdf_path.name,
                style="Style1",
            )
            items.append(item)

    logger.info(
        "Parsed %d Style 1 courses from %s (%s %s)",
        len(items),
        pdf_path.name,
        faculty,
        department,
    )
    return items
