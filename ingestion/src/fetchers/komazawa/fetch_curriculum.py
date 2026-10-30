"""
Komazawa University Curriculum Tree (履修系統図) PDF Fetcher

Downloads curriculum tree PDF documents for all faculties and departments (23 files)
from official Komazawa University URLs and saves them into the local directory hierarchy:
  data/raw/university/komazawa/2026/curriculum/...
Also generates a `manifest.json` catalog containing metadata for all fetched files.
"""

import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    / "komazawa"
    / "2026"
)

TARGET_CURRICULUM_FILES: List[Dict[str, str]] = [
    {
        "id": "areacode",
        "faculty": "全学",
        "department": "科目分野コード",
        "name": "areacode.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/areacode.pdf",
    },
    {
        "id": "common_education",
        "faculty": "全学共通",
        "department": "全学共通科目教養教育科目",
        "name": "2026_22.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/2026_22.pdf",
    },
    {
        "id": "buddhism_zen",
        "faculty": "仏教学部",
        "department": "禅学科",
        "name": "331c2c0cc6cd796b1a229ea3905ac149.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/331c2c0cc6cd796b1a229ea3905ac149.pdf",
    },
    {
        "id": "buddhism_studies",
        "faculty": "仏教学部",
        "department": "仏教学科",
        "name": "4354cd705f360d06dddcdc408ad2843c.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/4354cd705f360d06dddcdc408ad2843c.pdf",
    },
    {
        "id": "letters_japanese",
        "faculty": "文学部",
        "department": "国文学科",
        "name": "2026_03.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_03.pdf",
    },
    {
        "id": "letters_english",
        "faculty": "文学部",
        "department": "英米文学科",
        "name": "2026_04.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_04.pdf",
    },
    {
        "id": "letters_geography_culture",
        "faculty": "文学部",
        "department": "地理学科 地理文化研究専攻",
        "name": "2026_05.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_05.pdf",
    },
    {
        "id": "letters_geography_environment",
        "faculty": "文学部",
        "department": "地理学科 地域環境研究専攻",
        "name": "2026_06.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_06.pdf",
    },
    {
        "id": "letters_history_japanese",
        "faculty": "文学部",
        "department": "歴史学科 日本史学専攻",
        "name": "2026_6.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_6.pdf",
    },
    {
        "id": "letters_history_foreign",
        "faculty": "文学部",
        "department": "歴史学科 外国史学専攻 東洋史 西洋史コース",
        "name": "2026_7.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_7.pdf",
    },
    {
        "id": "letters_history_archaeology",
        "faculty": "文学部",
        "department": "歴史学科 考古学専攻",
        "name": "2026_09.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_09.pdf",
    },
    {
        "id": "letters_sociology",
        "faculty": "文学部",
        "department": "社会学科 社会学専攻",
        "name": "2026_10.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_10.pdf",
    },
    {
        "id": "letters_social_welfare",
        "faculty": "文学部",
        "department": "社会学科 社会福祉学専攻",
        "name": "2026_11.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_11.pdf",
    },
    {
        "id": "letters_psychology",
        "faculty": "文学部",
        "department": "心理学科",
        "name": "2026_12.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_12.pdf",
    },
    {
        "id": "economics_economics",
        "faculty": "経済学部",
        "department": "経済学科",
        "name": "2026_4.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_4.pdf",
    },
    {
        "id": "economics_commerce",
        "faculty": "経済学部",
        "department": "商学科",
        "name": "2026_14.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_14.pdf",
    },
    {
        "id": "economics_applied",
        "faculty": "経済学部",
        "department": "現代応用経済学科",
        "name": "2026_15.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_15.pdf",
    },
    {
        "id": "law_law",
        "faculty": "法学部",
        "department": "法律学科",
        "name": "2026_5.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_5.pdf",
    },
    {
        "id": "law_politics",
        "faculty": "法学部",
        "department": "政治学科",
        "name": "2026_17.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_17.pdf",
    },
    {
        "id": "business_management",
        "faculty": "経営学部",
        "department": "経営学科",
        "name": "2026_18.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_18.pdf",
    },
    {
        "id": "business_market_strategy",
        "faculty": "経営学部",
        "department": "市場戦略学科",
        "name": "2026_19.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_19.pdf",
    },
    {
        "id": "medical_radiological",
        "faculty": "医療健康科学部",
        "department": "診療放射線技術科学科",
        "name": "2026_3.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_3.pdf",
    },
    {
        "id": "gms_global_media",
        "faculty": "グローバル･メディア･スタディーズ学部",
        "department": "グローバル･メディア学科",
        "name": "2026_21.pdf",
        "category": "curriculum",
        "url": "https://www.komazawa-u.ac.jp/campuslife/files/2026_21.pdf",
    },
]


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with file_path.open("rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def download_file(
    url: str,
    dest_path: Path,
    client: httpx.Client,
    chunk_size: int = 64 * 1024,
) -> bool:
    """Download a file from url using streaming if it does not already exist.

    Args:
        url: Source URL to download.
        dest_path: Destination local file path.
        client: httpx Client instance.
        chunk_size: Byte size for streaming chunks.

    Returns:
        True if newly downloaded, False if skipped because it already exists.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if dest_path.exists() and dest_path.stat().st_size > 0:
        logger.info(
            "File already exists, skipping: %s (%d bytes)",
            dest_path.name,
            dest_path.stat().st_size,
        )
        return False

    tmp_path = dest_path.with_name(f"{dest_path.name}.tmp")
    logger.info("Downloading %s -> %s", url, dest_path)

    try:
        with client.stream("GET", url, follow_redirects=True, timeout=30.0) as response:
            response.raise_for_status()
            with tmp_path.open("wb") as f:
                for chunk in response.iter_bytes(chunk_size=chunk_size):
                    f.write(chunk)

        tmp_path.replace(dest_path)
        logger.info(
            "Successfully saved %s (%d bytes)",
            dest_path.name,
            dest_path.stat().st_size,
        )
        return True
    except Exception as e:
        logger.error("Download failed for %s: %s", url, e)
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def fetch_all_curriculums(
    force: bool = False,
    base_dir: Optional[Path] = None,
    interval_sec: float = 0.5,
) -> Dict[str, Any]:
    """Fetch all configured Komazawa University curriculum tree PDF files.

    Args:
        force: If True, re-download existing files.
        base_dir: Override directory for storing downloaded files.
        interval_sec: Sleep interval between successful downloads to avoid overloading the server.

    Returns:
        Summary dict containing counts and manifest items.
    """
    target_base = base_dir or RAW_BASE_DIR
    curriculum_dir = target_base / "curriculum"
    curriculum_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Target curriculum directory: %s", curriculum_dir)

    downloaded_count = 0
    skipped_count = 0
    failed_count = 0
    manifest_records: List[Dict[str, Any]] = []

    headers = {
        "User-Agent": "CourseNavigator-Ingestion/0.1.0 (Academic Research; https://github.com/cyanosome/course-navigator)",
    }

    with httpx.Client(headers=headers) as client:
        for idx, item in enumerate(TARGET_CURRICULUM_FILES):
            dest = target_base / item["category"] / item["name"]
            if force and dest.exists():
                logger.info("Force flag set; removing existing file: %s", dest.name)
                dest.unlink()

            downloaded = False
            try:
                downloaded = download_file(item["url"], dest, client)
                if downloaded:
                    downloaded_count += 1
                    if interval_sec > 0 and idx < len(TARGET_CURRICULUM_FILES) - 1:
                        time.sleep(interval_sec)
                else:
                    skipped_count += 1
            except Exception as e:
                logger.error("Failed to fetch %s (%s): %s", item["name"], item["department"], e)
                failed_count += 1
                continue

            # Record manifest info if file is present
            if dest.exists() and dest.stat().st_size > 0:
                manifest_records.append(
                    {
                        "id": item["id"],
                        "faculty": item["faculty"],
                        "department": item["department"],
                        "name": item["name"],
                        "category": item["category"],
                        "url": item["url"],
                        "size_bytes": dest.stat().st_size,
                        "sha256": calculate_sha256(dest),
                    }
                )

    # Save manifest.json
    manifest_path = curriculum_dir / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest_records, f, ensure_ascii=False, indent=2)
    logger.info("Manifest saved: %s (%d entries)", manifest_path, len(manifest_records))

    summary = {
        "total": len(TARGET_CURRICULUM_FILES),
        "downloaded": downloaded_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "manifest_file": str(manifest_path),
        "records": manifest_records,
    }
    logger.info(
        "Download complete. Total: %d, Downloaded: %d, Skipped: %d, Failed: %d",
        summary["total"],
        summary["downloaded"],
        summary["skipped"],
        summary["failed"],
    )
    return summary


def main() -> None:
    """CLI entrypoint for curriculum fetcher."""
    force = "--force" in sys.argv or "--overwrite" in sys.argv or "-f" in sys.argv
    summary = fetch_all_curriculums(force=force)
    if summary["failed"] > 0:
        logger.error("%d files failed to download.", summary["failed"])
        sys.exit(1)
    logger.info("All curriculum documents fetched successfully.")


if __name__ == "__main__":
    main()
