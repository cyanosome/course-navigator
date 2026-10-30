"""
Kansai University Syllabus Fetcher

Fetches curriculum catalog and syllabus detail HTML files from Kansai University's
official syllabus search system:
  Catalog URL: https://syllabus3.jm.kansai-u.ac.jp/syllabus/search/curri/...
  Detail URL:  https://syllabus3.jm.kansai-u.ac.jp/syllabus/search/ref/...

Extracted files are saved into the local directory hierarchy:
  data/raw/university/kansai/{year}/curri_{catalog_id}.html
  data/raw/university/kansai/{year}/catalog_index.json
  data/raw/university/kansai/{year}/ref/{d1}/{d2}/{d3d4}/{id}.html
"""

import sys
import re
import time
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict
import httpx

from src.fetchers.kansai.schema import CatalogEntry, FetchSummary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Default base URL for Kansai University Syllabus search
BASE_SEARCH_URL = "https://syllabus3.jm.kansai-u.ac.jp/syllabus/search"

# Base directory for raw files
DEFAULT_RAW_BASE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data"
    / "raw"
    / "university"
    / "kansai"
)


class KansaiSyllabusFetcher:
    """Fetcher for Kansai University curriculum and syllabus detail pages."""

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        year: str = "2026",
        bu: str = "10",
        gakubu: str = "320",
        gakka: str = "031",
        delay: float = 0.1,
    ):
        """
        Args:
            base_dir: Root directory for raw downloads (defaults to data/raw/university/kansai/{year}).
            year: Academic year (e.g. '2026').
            bu: Division code (e.g. '10' for undergraduate).
            gakubu: Faculty code (e.g. '320' for Environmental and Urban Engineering).
            gakka: Department code (e.g. '0031' for Energy and Environmental Engineering / Chemical Engineering).
            delay: Polite sleep delay in seconds between detail downloads.
        """
        self.year = year
        self.bu = bu
        self.gakubu = gakubu
        self.gakka = gakka
        self.delay = delay

        root = base_dir or DEFAULT_RAW_BASE_DIR
        self.output_dir = root / year
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36 (CourseNavigator/1.0 Research)"
            )
        }

    def get_curriculum_url(self) -> str:
        """Construct the official URL for the department curriculum table."""
        # e.g., curri/2026/10/320/202610320031ZZZZ_.html
        dest_url = f"{self.year}/{self.bu}/{self.gakubu}"
        dest_file = f"{self.year}{self.bu}{self.gakubu}{self.gakka}ZZZZ_"
        return f"{BASE_SEARCH_URL}/curri/{dest_url}/{dest_file}.html"

    def download_file(
        self,
        url: str,
        dest_path: Path,
        client: httpx.Client,
        force: bool = False,
        chunk_size: int = 64 * 1024,
    ) -> bool:
        """Download a file with streaming and atomic write.

        Returns:
            True if newly downloaded, False if skipped because it already exists.
        """
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if not force and dest_path.exists() and dest_path.stat().st_size > 0:
            return False

        tmp_path = dest_path.with_name(f"{dest_path.name}.tmp")
        try:
            with client.stream("GET", url, headers=self.headers, follow_redirects=True, timeout=30.0) as resp:
                resp.raise_for_status()
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
            tmp_path.replace(dest_path)
            return True
        except Exception as e:
            if tmp_path.exists():
                tmp_path.unlink()
            raise e

    def fetch_curriculum_catalog(
        self,
        client: Optional[httpx.Client] = None,
        force: bool = False,
    ) -> Path:
        """Download the curriculum catalog HTML for the target department.

        Returns:
            Local Path to the downloaded catalog HTML file.
        """
        url = self.get_curriculum_url()
        catalog_filename = f"curri_{self.year}_{self.bu}_{self.gakubu}_{self.gakka}.html"
        dest_path = self.output_dir / catalog_filename

        logger.info("Fetching curriculum catalog: %s -> %s", url, dest_path)
        owns_client = client is None
        http_client = client or httpx.Client()

        try:
            downloaded = self.download_file(url, dest_path, http_client, force=force)
            if downloaded:
                logger.info("Downloaded curriculum catalog (%d bytes)", dest_path.stat().st_size)
            else:
                logger.info("Curriculum catalog already exists, skipping download")
            return dest_path
        finally:
            if owns_client:
                http_client.close()

    @staticmethod
    def extract_catalog_items(catalog_html: str) -> List[CatalogEntry]:
        """Extract course metadata and syllabus detail links from the catalog HTML.

        Args:
            catalog_html: HTML string of the curriculum catalog page.

        Returns:
            List of CatalogEntry objects representing each course.
        """
        entries: List[CatalogEntry] = []

        # Each course item is wrapped in an <ul id='child_li_...'>
        ul_blocks = re.findall(
            r"<ul[^>]*id=[\x22\x27]child_li_[^\x22\x27]+[\x22\x27][^>]*>(.*?)</ul>",
            catalog_html,
            re.S | re.I,
        )

        for block in ul_blocks:
            # 1. Extract detail link and syllabus ID
            link_match = re.search(
                r"openWin\(['\"](?:\.\./)*ref/([^'\"]+?)['\"]\)",
                block,
                re.I,
            )
            if not link_match:
                continue

            rel_ref_path = link_match.group(1).lstrip("/")
            syllabus_id_match = re.search(r"(\d{6})\.html$", rel_ref_path)
            if not syllabus_id_match:
                continue
            syllabus_id = syllabus_id_match.group(1)

            # 2. Extract <p> tags (consistently 6 tags per block)
            p_tags = [
                re.sub(r"&nbsp;", " ", re.sub(r"<[^>]+>", "", p)).strip()
                for p in re.findall(r"<p[^>]*>(.*?)</p>", block, re.S)
            ]

            year_range = p_tags[0] if len(p_tags) > 0 else None
            name_raw = p_tags[1] if len(p_tags) > 1 else ""
            credits_val = p_tags[2] if len(p_tags) > 2 else None
            class_name = p_tags[3] if len(p_tags) > 3 else None
            instructors = p_tags[4] if len(p_tags) > 4 else None
            term_schedule = p_tags[5] if len(p_tags) > 5 else None

            # 3. Extract timetable code from title if present (e.g. '科目名 (00301)')
            code_match = re.search(r"\((\d{5})\)$", name_raw)
            if code_match:
                timetable_code = code_match.group(1)
                subject_name = re.sub(r"\s*\(\d{5}\)$", "", name_raw).strip()
            else:
                timetable_code = None
                subject_name = name_raw.strip()

            detail_url = f"{BASE_SEARCH_URL}/ref/{rel_ref_path}"

            entries.append(
                CatalogEntry(
                    syllabus_id=syllabus_id,
                    timetable_code=timetable_code,
                    subject_name=subject_name,
                    year_range=year_range,
                    credits=credits_val,
                    class_name=class_name,
                    instructors=instructors,
                    term_schedule=term_schedule,
                    detail_url=detail_url,
                    relative_ref_path=rel_ref_path,
                )
            )

        return entries

    def save_catalog_index(self, entries: List[CatalogEntry]) -> Path:
        """Save the extracted list of catalog items to catalog_index.json."""
        index_path = self.output_dir / "catalog_index.json"
        data = [e.model_dump() for e in entries]
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Saved catalog index with %d entries to %s", len(entries), index_path)
        return index_path

    def fetch_details(
        self,
        entries: List[CatalogEntry],
        client: Optional[httpx.Client] = None,
        force: bool = False,
        limit: Optional[int] = None,
    ) -> FetchSummary:
        """Download syllabus detail HTML files for each entry in entries.

        Args:
            entries: List of CatalogEntry objects.
            client: Optional httpx.Client.
            force: If True, re-download existing files.
            limit: Optional maximum number of courses to download.

        Returns:
            FetchSummary with counts of downloaded, skipped, and failed files.
        """
        target_entries = entries[:limit] if limit else entries
        summary = FetchSummary(total_entries=len(target_entries))

        owns_client = client is None
        http_client = client or httpx.Client()

        logger.info(
            "Starting detail fetch for %d courses (delay=%.2fs, force=%s)...",
            len(target_entries),
            self.delay,
            force,
        )

        try:
            for idx, entry in enumerate(target_entries, 1):
                dest_file = self.output_dir / "ref" / entry.relative_ref_path

                try:
                    downloaded = self.download_file(
                        url=entry.detail_url,
                        dest_path=dest_file,
                        client=http_client,
                        force=force,
                    )
                    if downloaded:
                        summary.newly_downloaded += 1
                        time.sleep(self.delay)
                    else:
                        summary.skipped_existing += 1

                    if idx % 50 == 0 or idx == len(target_entries):
                        logger.info(
                            "Progress: %d/%d (new: %d, skipped: %d, failed: %d)",
                            idx,
                            len(target_entries),
                            summary.newly_downloaded,
                            summary.skipped_existing,
                            summary.failed,
                        )
                except Exception as e:
                    logger.warning(
                        "Failed to download %s (%s): %s",
                        entry.syllabus_id,
                        entry.detail_url,
                        e,
                    )
                    summary.failed += 1
                    summary.failed_ids.append(entry.syllabus_id)

            logger.info(
                "Detail fetch completed: %d total, %d newly downloaded, %d skipped, %d failed",
                summary.total_entries,
                summary.newly_downloaded,
                summary.skipped_existing,
                summary.failed,
            )
            return summary
        finally:
            if owns_client:
                http_client.close()

    def fetch_all(
        self,
        force_catalog: bool = False,
        force_details: bool = False,
        limit: Optional[int] = None,
        catalog_only: bool = False,
    ) -> FetchSummary:
        """Full pipeline: fetch catalog, extract index, and fetch detail HTMLs.

        Returns:
            FetchSummary of detail downloads.
        """
        with httpx.Client() as client:
            # 1. Fetch catalog HTML
            catalog_path = self.fetch_curriculum_catalog(client=client, force=force_catalog)

            # 2. Extract catalog items
            content = catalog_path.read_text(encoding="utf-8", errors="replace")
            entries = self.extract_catalog_items(content)
            logger.info("Extracted %d course entries from curriculum catalog", len(entries))

            # 3. Save catalog index JSON
            self.save_catalog_index(entries)

            if catalog_only:
                logger.info("catalog_only=True specified, skipping detail HTML downloads")
                return FetchSummary(
                    total_entries=len(entries),
                    newly_downloaded=0,
                    skipped_existing=len(entries),
                )

            # 4. Fetch detail HTMLs
            return self.fetch_details(
                entries=entries,
                client=client,
                force=force_details,
                limit=limit,
            )


def main():
    """CLI runner for Kansai University Syllabus Fetcher."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Fetch Kansai University curriculum catalog and syllabus detail HTMLs."
    )
    parser.add_argument("--year", default="2026", help="Academic year (default: 2026)")
    parser.add_argument("--bu", default="10", help="Division code (default: 10)")
    parser.add_argument("--gakubu", default="320", help="Faculty code (default: 320 for Env/Urban Eng)")
    parser.add_argument("--gakka", default="031", help="Department code (default: 031 for Energy/Chem Eng)")
    parser.add_argument("--delay", type=float, default=0.1, help="Delay in seconds between requests (default: 0.1)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of detail HTMLs to fetch")
    parser.add_argument("--catalog-only", action="store_true", help="Only fetch and parse catalog, skip detail HTMLs")
    parser.add_argument("--force", action="store_true", help="Force re-download of existing files")

    args = parser.parse_args()

    fetcher = KansaiSyllabusFetcher(
        year=args.year,
        bu=args.bu,
        gakubu=args.gakubu,
        gakka=args.gakka,
        delay=args.delay,
    )

    fetcher.fetch_all(
        force_catalog=args.force,
        force_details=args.force,
        limit=args.limit,
        catalog_only=args.catalog_only,
    )


if __name__ == "__main__":
    main()
