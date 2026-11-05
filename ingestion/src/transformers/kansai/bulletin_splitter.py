"""
Kansai University Bulletin PDF Splitter

Splits the full 371-page bulletin (all_page.pdf) into faculty-specific PDF slices.
"""

import re
import logging
from pathlib import Path
from typing import Dict, Tuple, Optional
import pypdf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_BULLETIN_PATH = PROJECT_ROOT / "data" / "raw" / "university" / "kansai" / "2026" / "bulletin" / "all_page.pdf"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "raw" / "university" / "kansai" / "2026" / "bulletin" / "splitted"


class BulletinSplitter:
    """Detects faculty page ranges and slices the full bulletin PDF."""

    FACULTY_SLUGS = {
        "法学部": "law",
        "文学部": "letters",
        "経済学部": "economics",
        "商学部": "commerce",
        "社会学部": "sociology",
        "政策創造学部": "policy",
        "外国語学部": "foreign_languages",
        "人間健康学部": "health",
        "総合情報学部": "informatics",
        "社会安全学部": "safety",
        "ビジネスデータサイエンス学部": "bds",
        "システム理工学部": "science_eng",
        "環境都市工学部": "env_urban_eng",
        "環境都市理工学部": "env_urban_eng",  # handle slight header variation
        "化学生命工学部": "chem_bio_eng",
    }

    def __init__(self, pdf_path: Optional[Path] = None, output_dir: Optional[Path] = None):
        self.pdf_path = pdf_path or DEFAULT_BULLETIN_PATH
        self.output_dir = output_dir or DEFAULT_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def detect_ranges(self) -> Dict[str, Tuple[int, int]]:
        """Scan all pages and detect 0-indexed page ranges for each faculty."""
        reader = pypdf.PdfReader(str(self.pdf_path))
        raw_ranges: Dict[str, Tuple[int, int]] = {}

        for idx, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            # Search for header line e.g., '環境都市工学部 2026' or '法学部 2026'
            m = re.search(r"([^\s\d]{2,10}学部)\s*2026", text)
            if m:
                faculty = m.group(1)
                # Normalize slight OCR/header variations
                if faculty == "環境都市理工学部":
                    faculty = "環境都市工学部"
                elif faculty == "ネスデータサイエンス学部" or faculty == "サイエンス学部":
                    faculty = "ビジネスデータサイエンス学部"

                if faculty not in raw_ranges:
                    raw_ranges[faculty] = (idx, idx)
                else:
                    raw_ranges[faculty] = (raw_ranges[faculty][0], idx)

        logger.info("Detected %d faculties across %d pages", len(raw_ranges), len(reader.pages))
        return raw_ranges

    def split_faculty(self, faculty_name: str, start_page: int, end_page: int) -> Path:
        """Slice a given page range (0-indexed, inclusive) into a faculty PDF."""
        reader = pypdf.PdfReader(str(self.pdf_path))
        writer = pypdf.PdfWriter()

        for p_num in range(start_page, end_page + 1):
            writer.add_page(reader.pages[p_num])

        slug = self.FACULTY_SLUGS.get(faculty_name, "faculty")
        out_path = self.output_dir / f"bulletin_{slug}.pdf"
        with open(out_path, "wb") as f:
            writer.write(f)

        logger.info(
            "Saved %s (Pages %d - %d, count: %d) -> %s",
            faculty_name,
            start_page + 1,
            end_page + 1,
            end_page - start_page + 1,
            out_path,
        )
        return out_path

    def split_all(self) -> Dict[str, Path]:
        """Detect and split all faculties."""
        ranges = self.detect_ranges()
        results: Dict[str, Path] = {}
        for fac, (s, e) in sorted(ranges.items(), key=lambda x: x[1][0]):
            out = self.split_faculty(fac, s, e)
            results[fac] = out
        return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Split Kansai University bulletin PDF by faculty.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_BULLETIN_PATH, help="Path to all_page.pdf")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    parser.add_argument("--faculty", type=str, default=None, help="Target faculty (e.g. '環境都市工学部')")

    args = parser.parse_args()
    splitter = BulletinSplitter(pdf_path=args.pdf, output_dir=args.output_dir)

    if args.faculty:
        ranges = splitter.detect_ranges()
        if args.faculty not in ranges:
            print(f"Faculty '{args.faculty}' not found. Available: {list(ranges.keys())}")
            return
        s, e = ranges[args.faculty]
        splitter.split_faculty(args.faculty, s, e)
    else:
        splitter.split_all()


if __name__ == "__main__":
    main()
