"""
Nagasaki University Syllabus and Curriculum Map Fetcher

Downloads PDF documents from official university URLs and saves them
into the designated local directory hierarchy:
  data/raw/university/nagasaki/2025/data_and_information/...
"""

import sys
import logging
from pathlib import Path
from typing import Optional, List, Dict
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Base directory for raw files
RAW_BASE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data"
    / "raw"
    / "university"
    / "nagasaki"
    / "2025"
    / "data_and_information"
)

TARGET_FILES: List[Dict[str, str]] = [
    # 1. カリキュラム・マップ
    {
        "name": "35.pdf",
        "category": "curriculum_map",
        "url": "https://www.nagasaki-u.ac.jp/ja/campuslife/course/curriculumtrees/file/35.pdf",
    },
    # 2. 情報リテラシー入門 シラバス
    {
        "name": "02.01_25-jouhouliteracynyuumon.pdf",
        "category": "syllabus",
        "url": "https://www.nagasaki-u.ac.jp/ja/campuslife/course/general/syllabus/r07syllabus/PDF/02.01_25-jouhouliteracynyuumon.pdf",
    },
    # 3. 応用情報処理 シラバス
    {
        "name": "02.02_25-ouyoujouhousyori.pdf",
        "category": "syllabus",
        "url": "https://www.nagasaki-u.ac.jp/ja/campuslife/course/general/syllabus/r07syllabus/PDF/02.02_25-ouyoujouhousyori.pdf",
    },
    # 4. データサイエンス概論 シラバス
    {
        "name": "02.03_25-datascience.pdf",
        "category": "syllabus",
        "url": "https://www.nagasaki-u.ac.jp/ja/campuslife/course/general/syllabus/r07syllabus/PDF/02.03_25-datascience.pdf",
    },
    # 5. 統計学概論 シラバス
    {
        "name": "02.04_25-toukeigakugairon.pdf",
        "category": "syllabus",
        "url": "https://www.nagasaki-u.ac.jp/ja/campuslife/course/general/syllabus/r07syllabus/PDF/02.04_25-toukeigakugairon.pdf",
    },
]


def download_file(url: str, dest_path: Path, client: httpx.Client) -> bool:
    """Download a file from url if it does not already exist.

    Returns True if downloaded, False if skipped.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if dest_path.exists() and dest_path.stat().st_size > 0:
        logger.info("File already exists, skipping: %s (%d bytes)", dest_path.name, dest_path.stat().st_size)
        return False

    logger.info("Downloading %s -> %s", url, dest_path)
    response = client.get(url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()

    dest_path.write_bytes(response.content)
    logger.info("Successfully saved %s (%d bytes)", dest_path.name, len(response.content))
    return True


def fetch_all(force: bool = False, base_dir: Optional[Path] = None) -> Dict[str, int]:
    """Fetch all configured Nagasaki University syllabus and curriculum map PDFs."""
    target_base = base_dir or RAW_BASE_DIR
    logger.info("Target directory: %s", target_base)

    downloaded_count = 0
    skipped_count = 0
    failed_count = 0

    headers = {
        "User-Agent": "CourseNavigator-Ingestion/0.1.0 (Educational Academic Research)",
    }

    with httpx.Client(headers=headers) as client:
        for item in TARGET_FILES:
            dest = target_base / item["category"] / item["name"]
            if force and dest.exists():
                dest.unlink()

            try:
                downloaded = download_file(item["url"], dest, client)
                if downloaded:
                    downloaded_count += 1
                else:
                    skipped_count += 1
            except Exception as e:
                logger.error("Failed to download %s: %s", item["name"], e)
                failed_count += 1

    summary = {
        "downloaded": downloaded_count,
        "skipped": skipped_count,
        "failed": failed_count,
    }
    logger.info("Download complete. Summary: %s", summary)
    return summary


def main() -> None:
    force = "--force" in sys.argv or "--overwrite" in sys.argv or "-f" in sys.argv
    summary = fetch_all(force=force)
    if summary["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
