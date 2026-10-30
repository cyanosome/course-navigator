"""
Kansai University Syllabus Transformer

Parses raw syllabus HTML files and catalog metadata into lossless,
structured KansaiCourseDetail JSON records.
"""

import sys
import os
import re
import html
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from src.transformers.kansai.schema import (
    KansaiCourseDetail,
    InstructorItem,
    ScheduleSession,
    ParseReport,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Default directories
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw" / "university" / "kansai" / "2026"
DEFAULT_PARSED_DIR = PROJECT_ROOT / "data" / "parsed" / "university" / "kansai" / "2026"
BASE_DETAIL_URL = "https://syllabus3.jm.kansai-u.ac.jp/syllabus/search/ref"


class KansaiSyllabusTransformer:
    """Parser and transformer for Kansai University detailed syllabus HTML files."""

    def __init__(
        self,
        raw_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ):
        self.raw_dir = raw_dir or DEFAULT_RAW_DIR
        self.output_dir = output_dir or DEFAULT_PARSED_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def clean_text(raw_html: Optional[str]) -> Optional[str]:
        """Convert HTML tags and entities to clean normalized multiline text."""
        if not raw_html:
            return None

        # Replace <br> variants with newlines
        text = re.sub(r"<br\s*/?>", "\n", raw_html, flags=re.I)
        # Strip other HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Unescape HTML entities (&nbsp;, &amp;, etc.)
        text = html.unescape(text)

        # Normalize whitespace per line while preserving intended newlines
        cleaned_lines = []
        for line in text.split("\n"):
            stripped = " ".join(line.split())
            if stripped:
                cleaned_lines.append(stripped)

        result = "\n".join(cleaned_lines).strip()
        return result if result else None

    @classmethod
    def extract_field_by_id(cls, content: str, dom_id: str) -> Optional[str]:
        """Extract and clean inner text from element with specified id."""
        pattern = r"id=[\x22\x27]" + re.escape(dom_id) + r"[\x22\x27][^>]*>(.*?)</(?:td|span|div|p|dd|li)"
        match = re.search(pattern, content, re.S | re.I)
        if not match:
            return None
        return cls.clean_text(match.group(1))

    @classmethod
    def extract_multi_spans_by_id(cls, content: str, dom_id: str) -> List[str]:
        """Extract multiple occurrences of <span id='...'> (used for textbooks and references)."""
        pattern = r"<span[^>]*id=[\x22\x27]" + re.escape(dom_id) + r"[\x22\x27][^>]*>(.*?)</span>"
        matches = re.findall(pattern, content, re.S | re.I)
        items: List[str] = []
        for m in matches:
            cleaned = cls.clean_text(m)
            if cleaned:
                # Collapse internal newlines into single line per book title
                single_line = " ".join(cleaned.split())
                if single_line and single_line not in items:
                    items.append(single_line)
        return items

    @staticmethod
    def parse_instructors(
        tannin_raw: Optional[str],
        tantou_raw: Optional[str],
        codes_raw: Optional[str],
    ) -> Tuple[List[InstructorItem], List[str], List[str], List[str]]:
        """Pair instructor names with their official codes and primary role flags.

        Args:
            tannin_raw: Slash-separated primary instructor names (担任者).
            tantou_raw: Slash-separated assigned instructor names (担当者).
            codes_raw: Slash-separated official instructor codes (kyoinCdList).

        Returns:
            Tuple of (structured_items, tantou_list, tannin_list, codes_list).
        """
        tannin_list = [x.strip() for x in (tannin_raw or "").split("/") if x.strip()]
        tantou_list = [x.strip() for x in (tantou_raw or "").split("/") if x.strip()]
        codes_list = [x.strip() for x in (codes_raw or "").split("/") if x.strip()]

        # Primary pool: tantou if present, otherwise tannin
        name_pool = tantou_list if tantou_list else tannin_list

        items: List[InstructorItem] = []
        for idx, name in enumerate(name_pool):
            code = codes_list[idx] if idx < len(codes_list) else None
            is_primary = name in tannin_list
            items.append(
                InstructorItem(
                    name=name,
                    code=code,
                    is_primary=is_primary,
                )
            )

        return items, tantou_list, tannin_list, codes_list

    @staticmethod
    def parse_schedule_sessions(schedule_raw: Optional[str]) -> List[ScheduleSession]:
        """Decompose multiline class schedule into structured session objects."""
        if not schedule_raw:
            return []

        sessions: List[ScheduleSession] = []
        lines = [line.strip() for line in schedule_raw.split("\n") if line.strip()]

        # Pattern matches:
        # '第01回 オリエンテーション' or '第1週 微分積分' or '１化学工学' or '1. 導入'
        session_pattern = re.compile(
            r"^(?:第\s*(\d+)\s*[回週講次]|(\d+)[．.　\s]+|(\d+)\s*)(.*)$"
        )

        for line in lines:
            m = session_pattern.match(line)
            if m:
                # Determine which group matched the session number
                num_str = m.group(1) or m.group(2) or m.group(3)
                session_num = int(num_str) if num_str and num_str.isdigit() else None
                topic = m.group(4).strip(" ：:　\t")
                if not topic:
                    topic = line
                sessions.append(
                    ScheduleSession(
                        session_number=session_num,
                        raw_line=line,
                        topic=topic,
                    )
                )
            else:
                sessions.append(
                    ScheduleSession(
                        session_number=None,
                        raw_line=line,
                        topic=line,
                    )
                )

        return sessions

    def parse_single_html(
        self,
        html_path: Path,
        catalog_info: Optional[Dict[str, Any]] = None,
    ) -> KansaiCourseDetail:
        """Parse a single raw syllabus HTML file into a KansaiCourseDetail record.

        Args:
            html_path: Absolute Path to the detailed syllabus HTML file.
            catalog_info: Optional dictionary of metadata from catalog_index.json.

        Returns:
            Validated KansaiCourseDetail instance.
        """
        content = html_path.read_text(encoding="utf-8", errors="replace")
        cat = catalog_info or {}
        syllabus_id = html_path.stem

        # Calculate relative path from raw_dir/ref
        try:
            rel_path = str(html_path.relative_to(self.raw_dir / "ref")).replace("\\", "/")
        except ValueError:
            rel_path = f"{syllabus_id[0]}/{syllabus_id[1]}/{syllabus_id[2:4]}/{syllabus_id}.html"

        # 1. Primary Identifiers & Titles
        nendo_val = self.extract_field_by_id(content, "nendo")
        academic_year = int(nendo_val) if nendo_val and nendo_val.isdigit() else 2026

        course_code = self.extract_field_by_id(content, "kmkCd") or ""
        timetable_code = self.extract_field_by_id(content, "jikanwari") or cat.get("timetable_code")
        subject_name = self.extract_field_by_id(content, "kamoku") or cat.get("subject_name", "")
        subtitle = self.extract_field_by_id(content, "subkamoku")

        # 2. Curriculum, Affiliation & Delivery
        credits_raw = self.extract_field_by_id(content, "tani") or cat.get("credits")
        credits_float = None
        if credits_raw:
            try:
                credits_float = float(credits_raw)
            except ValueError:
                credits_float = None

        year_range = cat.get("year_range")
        class_name = self.extract_field_by_id(content, "class") or cat.get("class_name")
        semester = self.extract_field_by_id(content, "jyugyokeitai")
        term_schedule = self.extract_field_by_id(content, "yougen") or cat.get("term_schedule")

        faculties_str = self.extract_field_by_id(content, "gakubu") or ""
        faculties = [f.strip() for f in faculties_str.split("/") if f.strip()]

        dept_str = self.extract_field_by_id(content, "buGakuguGakka") or ""
        department_codes = [d.strip() for d in dept_str.split(":") if d.strip()]

        subject_type_code = self.extract_field_by_id(content, "jyuKbn")
        category_code = self.extract_field_by_id(content, "gosyu")
        language = self.extract_field_by_id(content, "gengo")

        # 3. Teaching & Instructors
        teaching_type = self.extract_field_by_id(content, "jyugyohouhou")
        methods_raw = self.extract_field_by_id(content, "jyugyosyuhou") or ""
        teaching_methods = [
            re.sub(r"^[・\-\s]+", "", line).strip()
            for line in methods_raw.split("\n")
            if re.sub(r"^[・\-\s]+", "", line).strip()
        ]

        tannin_raw = self.extract_field_by_id(content, "tannin")
        tantou_raw = self.extract_field_by_id(content, "tantou")
        codes_raw = self.extract_field_by_id(content, "kyoinCdList")
        instructors, tantou_list, tannin_list, codes_list = self.parse_instructors(
            tannin_raw=tannin_raw,
            tantou_raw=tantou_raw,
            codes_raw=codes_raw,
        )

        contact_method = self.extract_field_by_id(content, "toiawasehouhou")

        # 4. Content & Pedagogy
        description = self.extract_field_by_id(content, "gaiyo") or ""
        objectives = self.extract_field_by_id(content, "mokuhyo")
        schedule_raw = self.extract_field_by_id(content, "keikaku")
        schedule_sessions = self.parse_schedule_sessions(schedule_raw)
        work_outside_class = self.extract_field_by_id(content, "jikangaigakusyu")

        # 5. Assessment & Policies
        grading_policy = self.extract_field_by_id(content, "hyokahouhou")
        evaluation_criteria = self.extract_field_by_id(content, "hyokakijyun")
        feedback_method = self.extract_field_by_id(content, "feedback")

        # 6. Learning Materials & Comments
        textbooks = self.extract_multi_spans_by_id(content, "kyokasyo")
        textbook_notes = self.extract_field_by_id(content, "kyokasyobikou")
        references = self.extract_multi_spans_by_id(content, "sankousyo")
        reference_notes = self.extract_field_by_id(content, "sankousyobikou")
        notes = self.extract_field_by_id(content, "bikou")

        # 7. Traceability
        detail_url = f"{BASE_DETAIL_URL}/{rel_path}"

        return KansaiCourseDetail(
            syllabus_id=syllabus_id,
            academic_year=academic_year,
            course_code=course_code,
            timetable_code=timetable_code,
            subject_name=subject_name,
            subtitle=subtitle,
            credits=credits_float,
            credits_raw=credits_raw,
            year_range=year_range,
            class_name=class_name,
            semester=semester,
            term_schedule=term_schedule,
            faculties=faculties,
            department_codes=department_codes,
            subject_type_code=subject_type_code,
            category_code=category_code,
            language=language,
            teaching_type=teaching_type,
            teaching_methods=teaching_methods,
            instructors=instructors,
            instructors_tantou_raw=tantou_list,
            instructors_tannin_raw=tannin_list,
            instructor_codes=codes_list,
            contact_method=contact_method,
            description=description,
            objectives=objectives,
            schedule_raw=schedule_raw,
            schedule_sessions=schedule_sessions,
            work_outside_class=work_outside_class,
            grading_policy=grading_policy,
            evaluation_criteria=evaluation_criteria,
            feedback_method=feedback_method,
            textbooks=textbooks,
            textbook_notes=textbook_notes,
            references=references,
            reference_notes=reference_notes,
            notes=notes,
            detail_url=detail_url,
            relative_ref_path=rel_path,
        )

    def load_catalog_map(self) -> Dict[str, Dict[str, Any]]:
        """Load catalog_index.json into a lookup dictionary keyed by syllabus_id."""
        index_file = self.raw_dir / "catalog_index.json"
        catalog_map: Dict[str, Dict[str, Any]] = {}
        if index_file.exists():
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    entries = json.load(f)
                    for e in entries:
                        catalog_map[e["syllabus_id"]] = e
                logger.info("Loaded catalog index with %d entries from %s", len(catalog_map), index_file)
            except Exception as e:
                logger.warning("Could not read catalog index: %s", e)
        return catalog_map

    def parse_all(
        self,
        raw_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
    ) -> Tuple[List[KansaiCourseDetail], ParseReport]:
        """Parse all raw HTML files and save outputs to courses_detail.json and courses_lookup.json."""
        src_raw = raw_dir or self.raw_dir
        dest_out = output_dir or self.output_dir
        dest_out.mkdir(parents=True, exist_ok=True)

        catalog_map = self.load_catalog_map()

        ref_dir = src_raw / "ref"
        html_files = sorted(list(ref_dir.glob("**/*.html")))
        logger.info("Found %d detail HTML files in %s", len(html_files), ref_dir)

        report = ParseReport(total_processed=len(html_files))
        results: List[KansaiCourseDetail] = []
        lookup: Dict[str, Dict[str, Any]] = {}

        for idx, fpath in enumerate(html_files, 1):
            syllabus_id = fpath.stem
            cat_entry = catalog_map.get(syllabus_id)

            try:
                course = self.parse_single_html(fpath, catalog_info=cat_entry)
                results.append(course)
                report.success_count += 1

                course_dict = course.model_dump()
                # Populate lookup keys
                lookup[course.syllabus_id] = course_dict
                if course.timetable_code:
                    lookup[course.timetable_code] = course_dict

                # Record field coverage
                for field_name, field_val in course_dict.items():
                    if field_val not in (None, "", [], {}):
                        report.field_coverage[field_name] = report.field_coverage.get(field_name, 0) + 1

                if idx % 200 == 0 or idx == len(html_files):
                    logger.info("Parsed %d/%d courses (success: %d, errors: %d)", idx, len(html_files), report.success_count, report.error_count)

            except Exception as e:
                logger.error("Failed to parse %s: %s", fpath, e)
                report.error_count += 1
                report.errors.append({"file": fpath.name, "syllabus_id": syllabus_id, "error": str(e)})

        # 1. Save courses_detail.json (array of all courses)
        detail_path = dest_out / "courses_detail.json"
        with open(detail_path, "w", encoding="utf-8") as f:
            json.dump([c.model_dump() for c in results], f, ensure_ascii=False, indent=2)
        logger.info("Saved %d course records to %s (%d bytes)", len(results), detail_path, detail_path.stat().st_size)

        # 2. Save courses_lookup.json (id/code -> record map)
        lookup_path = dest_out / "courses_lookup.json"
        with open(lookup_path, "w", encoding="utf-8") as f:
            json.dump(lookup, f, ensure_ascii=False, indent=2)
        logger.info("Saved courses lookup map with %d keys to %s", len(lookup), lookup_path)

        # 3. Save parse_report.json
        report_path = dest_out / "parse_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report.model_dump(), f, ensure_ascii=False, indent=2)
        logger.info("Saved parse report to %s", report_path)

        return results, report


def main():
    """CLI runner for Kansai University Syllabus Transformer."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Parse raw Kansai University syllabus HTML files into structured JSON."
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help=f"Raw data directory (default: {DEFAULT_RAW_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PARSED_DIR,
        help=f"Parsed output directory (default: {DEFAULT_PARSED_DIR})",
    )

    args = parser.parse_args()

    transformer = KansaiSyllabusTransformer(
        raw_dir=args.raw_dir,
        output_dir=args.output_dir,
    )
    results, report = transformer.parse_all()
    print(f"Transformation complete: {report.success_count}/{report.total_processed} succeeded, {report.error_count} failed.")


if __name__ == "__main__":
    main()
