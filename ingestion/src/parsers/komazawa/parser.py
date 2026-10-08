"""
Komazawa University Syllabus Parser

Parses raw JavaScript syllabus index (data/raw/university/komazawa/2026/syllabus_information.js)
and outputs structured, validated course catalog data:
  data/parsed/university/komazawa/2026/courses_summary.json
"""

import json
import logging
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from src.parsers.komazawa.schema import CourseSummary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Base directory paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_RAW_FILE = (
    BASE_DIR
    / "data"
    / "raw"
    / "university"
    / "komazawa"
    / "2026"
    / "syllabus_information.js"
)
DEFAULT_PARSED_FILE = (
    BASE_DIR
    / "data"
    / "parsed"
    / "university"
    / "komazawa"
    / "2026"
    / "courses_summary.json"
)


def extract_js_data(js_content: str) -> List[Dict[str, Any]]:
    """Extract and parse JavaScript 'var data = [...];' array into Python dicts.

    Args:
        js_content: Raw JavaScript file text content.

    Returns:
        List of course raw dictionary items.

    Raises:
        ValueError: If 'var data = [...]' pattern is not found.
    """
    pattern = re.compile(r"var\s+data\s*=\s*(\[.*?\]);?\s*$", re.DOTALL)
    match = pattern.search(js_content)
    if not match:
        raise ValueError("Could not find 'var data = [...];' in JavaScript content.")

    json_str = match.group(1)
    # Using strict=False is crucial as raw syllabus strings contain unescaped control chars
    return json.loads(json_str, strict=False)


def clean_text(text: str) -> str:
    """Normalize and clean unstructured text.

    Replaces full-width whitespace, collapses consecutive spaces and empty lines,
    and strips leading/trailing blanks.
    """
    if not text:
        return ""
    # Normalize full-width spaces to half-width
    text = text.replace("\u3000", " ")
    # Collapse multiple horizontal whitespaces/tabs
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse multiple consecutive newlines (more than 2 to 2)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_subject_tokens(
    tokens: List[str],
) -> Tuple[
    Optional[str],  # name_kana
    Optional[str],  # term
    Optional[float],  # credits
    Optional[str],  # instructor_kana
    Optional[str],  # day_of_week
    Optional[str],  # period
    str,  # body_text
]:
    """Parse structured metadata from tokens in the raw subject field.

    The Komazawa University 'subject' field embeds:
      Header: [code] [name] [name_kana...] [YYYY年] [開講期] [単位数]
      Body:   [description / objectives / schedule / evaluation...]
      Footer: [instructor_kana...] [曜日] [時限]
    """
    if not tokens:
        return None, None, None, None, None, None, ""

    # 1. Dynamic search for year token (e.g. '2026年') in header
    year_idx = None
    for idx in range(2, min(10, len(tokens))):
        if re.match(r"^\d{4}年$", tokens[idx]):
            year_idx = idx
            break

    name_kana = None
    term = None
    credits = None
    body_start_idx = 0

    if year_idx is not None:
        # tokens[2:year_idx] is name_kana (may consist of multiple tokens)
        kana_parts = tokens[2:year_idx]
        if kana_parts:
            name_kana = " ".join(kana_parts)

        # tokens[year_idx + 1] -> term (e.g. 通年, 前期, 後期)
        if len(tokens) > year_idx + 1:
            term = tokens[year_idx + 1]

        # tokens[year_idx + 2] -> credits (e.g. 4, 2, 2.0)
        if len(tokens) > year_idx + 2:
            credits_str = tokens[year_idx + 2]
            try:
                credits = float(credits_str)
                body_start_idx = year_idx + 3
            except ValueError:
                # If credits cannot be parsed as a float, body starts earlier
                body_start_idx = year_idx + 2
    else:
        # Fallback if year token was not located
        body_start_idx = 0

    # 2. Search for day of week and period in footer
    day_of_week = None
    period = None
    instructor_kana = None
    body_end_idx = len(tokens)

    # Check footer tokens
    if len(tokens) >= 2:
        last_tok = tokens[-1]
        prev_tok = tokens[-2]

        is_period = bool(re.search(r"時限$", last_tok))
        is_day = bool(re.search(r"曜日$", prev_tok))

        if is_period and is_day:
            period = last_tok
            day_of_week = prev_tok
            body_end_idx = len(tokens) - 2

            # Check if tokens right before day_of_week are instructor_kana
            # Usually 1 or 2 katakana tokens (e.g., ['クマモト', 'エイニン'])
            potential_kana: List[str] = []
            for check_idx in range(body_end_idx - 1, max(body_start_idx - 1, body_end_idx - 3), -1):
                tok = tokens[check_idx]
                # Match tokens that are purely Katakana or Katakana-like readings
                if re.match(r"^[\u30A0-\u30FFー]+$", tok):
                    potential_kana.insert(0, tok)
                else:
                    break

            if potential_kana:
                instructor_kana = " ".join(potential_kana)
                body_end_idx -= len(potential_kana)

    # 3. Extract body text tokens
    if body_start_idx < body_end_idx:
        body_tokens = tokens[body_start_idx:body_end_idx]
    else:
        body_tokens = tokens

    body_text = clean_text(" ".join(body_tokens))
    return name_kana, term, credits, instructor_kana, day_of_week, period, body_text


def parse_record(item: Dict[str, Any]) -> CourseSummary:
    """Parse a single raw dictionary item into a validated CourseSummary."""
    raw_subject = str(item.get("subject", "") or "")
    tokens = raw_subject.split()

    name_kana, term, credits, instructor_kana, day, period, body_text = parse_subject_tokens(tokens)

    return CourseSummary(
        course_code=str(item.get("rishu_code", "")).strip(),
        course_name=str(item.get("kamoku_name", "")).strip(),
        course_name_kana=name_kana,
        instructor=str(item.get("kyoin_shimei", "")).strip(),
        instructor_kana=instructor_kana,
        department=str(item.get("gakka_srnm", "")).strip(),
        year=int(item.get("syllabus_nendo", 2026)),
        term=term,
        credits=credits,
        day_of_week=day,
        period=period,
        text=body_text if body_text else clean_text(raw_subject),
        raw_subject=raw_subject,
    )


def parse_file(
    input_path: Path,
    output_path: Path,
) -> Dict[str, Any]:
    """Parse raw JS syllabus file and save output as structured JSON.

    Args:
        input_path: Path to raw syllabus_information.js file.
        output_path: Path to destination courses_summary.json.

    Returns:
        Summary dict containing parsing statistics.
    """
    logger.info("Reading raw file: %s", input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    raw_content = input_path.read_text(encoding="utf-8")
    raw_items = extract_js_data(raw_content)
    total_count = len(raw_items)
    logger.info("Found %d raw course records.", total_count)

    courses: List[Dict[str, Any]] = []
    success_count = 0
    error_count = 0
    with_term = 0
    with_credits = 0
    with_schedule = 0

    for idx, item in enumerate(raw_items):
        try:
            summary = parse_record(item)
            courses.append(summary.model_dump())
            success_count += 1
            if summary.term:
                with_term += 1
            if summary.credits is not None:
                with_credits += 1
            if summary.day_of_week and summary.period:
                with_schedule += 1
        except (ValidationError, Exception) as e:
            logger.error("Error parsing record at index %d (%s): %s", idx, item.get("rishu_code"), e)
            error_count += 1

    # Atomic write to destination file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f"{output_path.name}.tmp")

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(courses, f, ensure_ascii=False, indent=2)

    tmp_path.replace(output_path)
    logger.info("Successfully wrote %d courses to %s", len(courses), output_path)

    stats = {
        "total": total_count,
        "success": success_count,
        "error": error_count,
        "with_term": with_term,
        "with_credits": with_credits,
        "with_schedule": with_schedule,
    }
    logger.info("Parsing statistics: %s", stats)
    return stats


def main() -> None:
    """CLI entrypoint."""
    input_file = DEFAULT_RAW_FILE
    output_file = DEFAULT_PARSED_FILE

    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        input_file = Path(sys.argv[1])
    if len(sys.argv) > 2 and not sys.argv[2].startswith("-"):
        output_file = Path(sys.argv[2])

    stats = parse_file(input_file, output_file)
    if stats["error"] > 0:
        logger.warning("%d records failed to parse.", stats["error"])


if __name__ == "__main__":
    main()
