"""
Komazawa University Subject Field Code Master Parser (Style 4).

Parses `areacode.pdf` and extracts 3-digit subject area codes (分野コード)
along with broad categories and specific fields into structured JSON.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional
from pypdf import PdfReader

from src.parsers.komazawa.curriculum_schema import SubjectFieldItem

logger = logging.getLogger(__name__)

# Base category mapping based on the first digit
FIRST_DIGIT_CATEGORY_MAP: Dict[str, str] = {
    "0": "全学共通科目",
    "1": "総合系",
    "2": "人文学系",
    "3": "社会科学系",
    "4": "理工系",
    "5": "生物学系",
}


def parse_areacode_pdf(pdf_path: Path) -> List[SubjectFieldItem]:
    """Parse areacode.pdf and return a list of SubjectFieldItem objects."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"areacode.pdf not found at: {pdf_path}")

    reader = PdfReader(pdf_path)
    full_text = "\n".join(p.extract_text() or "" for p in reader.pages)

    # Pattern: text preceding three separated digits at end of line
    # e.g. "宗教教育 宗教 0 1 1" -> field="宗教教育 宗教", d1="0", d2="1", d3="1"
    line_pattern = re.compile(r"^(.*?)\s+(\d)\s+(\d)\s+(\d)$")

    results: List[SubjectFieldItem] = []
    seen_codes = set()

    for line in full_text.splitlines():
        line = line.strip()
        match = line_pattern.match(line)
        if not match:
            continue

        raw_title = match.group(1).strip()
        code = f"{match.group(2)}{match.group(3)}{match.group(4)}"

        if code in seen_codes:
            logger.debug("Skipping duplicate area code: %s", code)
            continue
        seen_codes.add(code)

        # Split title tokens (e.g. "宗教教育 宗教", "情報学基礎", "哲学・倫理学")
        tokens = [t for t in raw_title.split() if t]
        broad_cat = FIRST_DIGIT_CATEGORY_MAP.get(code[0], "その他")

        if len(tokens) >= 2:
            field = tokens[0]
            subfield = tokens[1]
        elif len(tokens) == 1:
            field = tokens[0]
            subfield = None
        else:
            field = raw_title
            subfield = None

        results.append(
            SubjectFieldItem(
                code=code,
                category=broad_cat,
                field=field,
                subfield=subfield,
            )
        )

    # Sort by code
    results.sort(key=lambda item: item.code)
    logger.info("Parsed %d subject field codes from %s", len(results), pdf_path.name)
    return results


def save_areacodes(
    items: List[SubjectFieldItem],
    output_path: Path,
) -> None:
    """Save parsed subject field codes to JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump([item.model_dump() for item in items], f, ensure_ascii=False, indent=2)
    logger.info("Saved %d area codes to: %s", len(items), output_path)
