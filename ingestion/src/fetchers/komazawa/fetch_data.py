"""
Komazawa University Syllabus Fetcher

Downloads syllabus index data (JavaScript file containing all course records)
from official Komazawa University URL and saves it into local directory hierarchy:
  data/raw/university/komazawa/2026/syllabus_information.js
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
    / "komazawa"
    / "2026"
)

TARGET_FILES: List[Dict[str, str]] = [
    {
        "name": "syllabus_information.js",
        "category": "",
        "url": "https://www.komazawa-u.ac.jp/~kyoumu/syllabus_html2026/js/syllabus_information.js",
    },
]


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

    logger.info("Downloading %s -> %s", url, dest_path)
    tmp_path = dest_path.with_name(f"{dest_path.name}.tmp")

    try:
        with client.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
            response.raise_for_status()
            with open(tmp_path, "wb") as f:
                total_bytes = 0
                for chunk in response.iter_bytes(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        total_bytes += len(chunk)

        # Atomic rename after complete download
        tmp_path.replace(dest_path)
        logger.info(
            "Successfully saved %s (%d bytes)",
            dest_path.name,
            dest_path.stat().st_size,
        )
        return True
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def fetch_all(force: bool = False, base_dir: Optional[Path] = None) -> Dict[str, int]:
    """Fetch all configured Komazawa University syllabus files.

    Args:
        force: If True, overwrite existing files.
        base_dir: Optional root directory override (useful for testing).

    Returns:
        Summary dict containing counts of downloaded, skipped, and failed files.
    """
    target_base = base_dir or RAW_BASE_DIR
    logger.info("Target directory: %s", target_base)

    downloaded_count = 0
    skipped_count = 0
    failed_count = 0

    headers = {
        "User-Agent": "CourseNavigator-Ingestion/0.1.0 (Educational Academic Research; Komazawa University)",
    }

    with httpx.Client(headers=headers) as client:
        for item in TARGET_FILES:
            if item["category"]:
                dest = target_base / item["category"] / item["name"]
            else:
                dest = target_base / item["name"]

            if force and dest.exists():
                logger.info("Force flag enabled. Removing existing file: %s", dest)
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
    """CLI entrypoint."""
    force = "--force" in sys.argv or "--overwrite" in sys.argv or "-f" in sys.argv
    summary = fetch_all(force=force)
    if summary["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
