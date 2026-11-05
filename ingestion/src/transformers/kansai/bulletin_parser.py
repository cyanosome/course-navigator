"""
Kansai University Bulletin Parser (環境都市工学部 エネルギー環境・化学工学科)

Parses graduation requirements, thesis prerequisite conditions, and course
requirement classifications (required / elective_required / elective) from
the official Kansai University bulletin PDF (all_page.pdf / bulletin_env_urban_eng.pdf).
Matches each course deterministically against parsed courses (courses_detail.json).
"""

import re
import json
import logging
import unicodedata
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
import pdfplumber

from src.transformers.kansai.bulletin_schema import (
    GraduationRequirementDetail,
    ThesisRequirementRule,
    BulletinCourseItem,
    BulletinParsedPayload,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_BULLETIN_PDF = (
    PROJECT_ROOT / "data" / "raw" / "university" / "kansai" / "2026" / "bulletin" / "all_page.pdf"
)
DEFAULT_COURSES_JSON = (
    PROJECT_ROOT / "data" / "parsed" / "university" / "kansai" / "2026" / "courses_detail.json"
)
DEFAULT_OUTPUT_JSON = (
    PROJECT_ROOT / "data" / "parsed" / "university" / "kansai" / "2026" / "bulletin_cee_requirements.json"
)


def normalize_subject_name(name: str) -> str:
    """Normalize course name for deterministic entity resolution."""
    if not name:
        return ""
    roman_map = {
        "Ⅰ": "1",
        "Ⅱ": "2",
        "Ⅲ": "3",
        "Ⅳ": "4",
        "Ⅴ": "5",
        "Ⅵ": "6",
        "Ⅶ": "7",
        "Ⅷ": "8",
    }
    for r, a in roman_map.items():
        name = name.replace(r, a)

    norm = unicodedata.normalize("NFKC", name)
    norm = re.sub(r"VIII", "8", norm)
    norm = re.sub(r"VII", "7", norm)
    norm = re.sub(r"VI", "6", norm)
    norm = re.sub(r"IV", "4", norm)
    norm = re.sub(r"III", "3", norm)
    norm = re.sub(r"II", "2", norm)
    norm = re.sub(r"I", "1", norm)
    norm = re.sub(r"\s+", "", norm)
    return norm


class KansaiBulletinParser:
    """Extracts CEE curriculum regulations from bulletin PDF."""

    def __init__(
        self,
        pdf_path: Optional[Path] = None,
        courses_json_path: Optional[Path] = None,
        output_json_path: Optional[Path] = None,
    ):
        self.pdf_path = pdf_path or DEFAULT_BULLETIN_PDF
        self.courses_json_path = courses_json_path or DEFAULT_COURSES_JSON
        self.output_json_path = output_json_path or DEFAULT_OUTPUT_JSON
        self.output_json_path.parent.mkdir(parents=True, exist_ok=True)

        self._load_course_catalog()

    def _load_course_catalog(self) -> None:
        """Load parsed courses and build lookup dictionaries."""
        self.courses_by_norm: Dict[str, List[Dict[str, Any]]] = {}
        if not self.courses_json_path.exists():
            logger.warning("Courses JSON not found at %s. Matching will be empty.", self.courses_json_path)
            return

        with open(self.courses_json_path, "r", encoding="utf-8") as f:
            raw_courses = json.load(f)

        for c in raw_courses:
            norm = normalize_subject_name(c.get("subject_name", ""))
            self.courses_by_norm.setdefault(norm, []).append(c)

        logger.info(
            "Loaded %d course records from JSON (%d distinct normalized keys)",
            len(raw_courses),
            len(self.courses_by_norm),
        )

    def extract_graduation_requirements(self, pdf: pdfplumber.PDF) -> GraduationRequirementDetail:
        """Extract graduation requirement rule and credits."""
        thesis_rule = ThesisRequirementRule(
            max_unearned_required_courses=4,
            max_unearned_required_credits=8,
            min_major_elective_required_credits=24.0,
            mandatory_courses_completed=["化学工学実験", "有機化学実験"],
            prerequisite_course="特別研究1",
            raw_condition_text=(
                "①専門教育科目の必修科目のうち、未修得科目及び単位が4科目8単位以内であること。"
                "②卒業に必要な選択必修科目のうち、24単位以上を修得していること。"
                "③「化学工学実験」、「有機化学実験」を修得していること。"
                "④「特別研究Ⅱ」を履修するには、「特別研究Ⅰ」を修得していること。"
            ),
        )

        return GraduationRequirementDetail(
            requirement_id="2026_env_cee",
            academic_year=2026,
            faculty_code="320",
            faculty_name="環境都市工学部",
            department_code="031",
            department_name="エネルギー環境・化学工学科",
            total_credits=128.0,
            general_education_credits=20.0,
            general_designated_credits=12.0,
            foreign_language_credits=12.0,
            foreign_lang_first_credits=8.0,
            foreign_lang_second_credits=4.0,
            major_credits=96.0,
            major_required_credits=53.0,
            major_elective_required_credits=30.0,
            thesis_requirements=thesis_rule,
            rules_notes=[
                "自己形成科目群「指定科目」は12単位を修得しなければなりません。",
                "指定科目12単位を超えて修得した単位は専門教育科目の選択科目の単位に算入できます。",
                "外国語科目は英語を含む2つの外国語を第1選択（8単位）、第2選択（4単位）として修得します。",
            ],
        )

    def extract_courses(self, pdf: pdfplumber.PDF) -> List[BulletinCourseItem]:
        """Extract course list with requirement_type from bulletin tables."""
        start_page_idx = None
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            for line in text.split("\n"):
                if "エネルギー環境・化学工学科" in line and "授業科目一覧" in line:
                    start_page_idx = idx
                    break
            if start_page_idx is not None:
                break

        if start_page_idx is None:
            start_page_idx = 331 if len(pdf.pages) > 331 else 0

        target_indices = [start_page_idx]
        if start_page_idx + 1 < len(pdf.pages):
            target_indices.append(start_page_idx + 1)

        logger.info("Extracting course tables from PDF pages: %s", [i + 1 for i in target_indices])

        raw_items: List[BulletinCourseItem] = []
        current_req_type = "required"
        current_year = 1

        for p_idx in target_indices:
            p = pdf.pages[p_idx]
            tables = p.extract_tables()

            for t_idx, table in enumerate(tables):
                if not table:
                    continue

                is_gen_ed_table = (p_idx == start_page_idx and t_idx == 0)

                # Page 332 Table 4 is Elective Required continuation
                if p_idx == start_page_idx and t_idx == 4:
                    current_req_type = "elective_required"
                    current_year = 2

                for row in table:
                    if not row or not any(row):
                        continue

                    clean_row = [str(c).replace("\n", " ").strip() if c else "" for c in row]
                    row_text = "".join(clean_row)

                    if "必修科目" in row_text and "選択必修" not in row_text:
                        current_req_type = "required"
                        continue
                    elif "選択必修科目" in row_text:
                        current_req_type = "elective_required"
                        continue
                    elif "選択科目" in row_text:
                        current_req_type = "elective"
                        continue

                    if "授業科目" in row_text or "毎週" in row_text or "科目番号" in row_text:
                        continue

                    item = self._parse_single_row(clean_row, current_req_type, is_gen_ed_table, current_year)
                    if item:
                        if item.assigned_year:
                            current_year = item.assigned_year

                        # Entity resolution
                        norm = normalize_subject_name(item.subject_name_bulletin)
                        matched = self.courses_by_norm.get(norm, [])

                        # Handle "（各テーマ）" wildcard prefix matching
                        if not matched and "各テーマ" in item.subject_name_bulletin:
                            prefix = normalize_subject_name(re.sub(r"[\(（]各テーマ[\)）]", "", item.subject_name_bulletin))
                            matched = [
                                c for norm_key, c_list in self.courses_by_norm.items()
                                if norm_key.startswith(prefix)
                                for c in c_list
                            ]

                        item.matched_syllabus_ids = [m["syllabus_id"] for m in matched]
                        if matched:
                            item.matched_course_code = matched[0].get("course_code")

                        raw_items.append(item)

        logger.info("Extracted %d course items from bulletin tables", len(raw_items))
        return raw_items

    def _parse_single_row(
        self,
        row: List[str],
        req_type: str,
        is_gen_ed: bool,
        last_year: int,
    ) -> Optional[BulletinCourseItem]:
        """Parse cells of a row into BulletinCourseItem."""
        if len(row) < 3:
            return None

        bulletin_code = None
        name = None
        field_category = None
        credits_val = 2.0
        assigned_year = last_year
        is_mandatory_mark = False

        if is_gen_ed:
            if len(row) >= 5:
                bulletin_code = row[0] if re.match(r"^[A-Z]{3,4}\d+", row[0]) else None
                name = row[1].strip() if len(row) > 1 and row[1] else ""
                if not name:
                    return None
                field_category = row[2] if row[2] in ("自然と 向き合う", "自然と向き合う", "社会を知る", "人間を知る") else None
                is_mandatory_mark = ("◎" in row[3])
                try:
                    credits_val = float(row[4])
                except (ValueError, IndexError):
                    credits_val = 2.0
                actual_req_type = "required" if is_mandatory_mark else "elective"
                return BulletinCourseItem(
                    bulletin_code=bulletin_code,
                    subject_name_bulletin=name,
                    requirement_type=actual_req_type,
                    credits=credits_val,
                    assigned_year=1,
                    field_category=field_category,
                )

        for cell in row:
            if re.match(r"^CEE[１-４1-4]?$", cell):
                bulletin_code = cell
                m = re.search(r"[１-４1-4]", cell)
                if m:
                    y_char = m.group(0)
                    y_map = {"１": 1, "２": 2, "３": 3, "４": 4, "1": 1, "2": 2, "3": 3, "4": 4}
                    assigned_year = y_map.get(y_char, last_year)
            elif cell in ("1", "2", "3", "4", "1~4", "2~4") and row.index(cell) >= len(row) - 2:
                m = re.match(r"^([1-4])", cell)
                if m:
                    assigned_year = int(m.group(1))

        # Find subject name
        for cell in row:
            if not cell or cell == bulletin_code or cell in ("1", "2", "3", "4", "1~4", "2~4", "―", "6", "12"):
                continue
            try:
                val = float(cell)
                if val in (1.0, 2.0, 3.0, 4.0):
                    credits_val = val
                    continue
            except ValueError:
                pass

            if len(cell.strip()) >= 2 and not re.match(r"^[\s―\d.]+$", cell):
                name = cell.strip()
                break

        if not name:
            return None

        return BulletinCourseItem(
            bulletin_code=bulletin_code,
            subject_name_bulletin=name,
            requirement_type=req_type,
            credits=credits_val,
            assigned_year=assigned_year,
            field_category=field_category,
        )

    def parse_all(self) -> BulletinParsedPayload:
        """Execute full parsing pipeline and save payload JSON."""
        with pdfplumber.open(str(self.pdf_path)) as pdf:
            grad_req = self.extract_graduation_requirements(pdf)
            courses = self.extract_courses(pdf)

        matched_count = sum(1 for c in courses if c.matched_syllabus_ids)
        unmatched_count = len(courses) - matched_count

        payload = BulletinParsedPayload(
            graduation_requirement=grad_req,
            courses=courses,
            total_bulletin_courses=len(courses),
            matched_courses_count=matched_count,
            unmatched_courses_count=unmatched_count,
        )

        with open(self.output_json_path, "w", encoding="utf-8") as f:
            json.dump(payload.model_dump(), f, ensure_ascii=False, indent=2)

        logger.info(
            "Saved bulletin requirements payload to %s (Total: %d, Matched: %d, Unmatched: %d)",
            self.output_json_path,
            len(courses),
            matched_count,
            unmatched_count,
        )
        return payload


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Parse Kansai University bulletin requirements.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_BULLETIN_PDF, help="Path to bulletin PDF")
    parser.add_argument("--courses", type=Path, default=DEFAULT_COURSES_JSON, help="Path to courses_detail.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_JSON, help="Output JSON path")

    args = parser.parse_args()
    parser_instance = KansaiBulletinParser(
        pdf_path=args.pdf,
        courses_json_path=args.courses,
        output_json_path=args.output,
    )
    payload = parser_instance.parse_all()
    print(
        f"[SUCCESS] Parsed {payload.total_bulletin_courses} courses. "
        f"Matched: {payload.matched_courses_count}, Unmatched: {payload.unmatched_courses_count}."
    )


if __name__ == "__main__":
    main()
