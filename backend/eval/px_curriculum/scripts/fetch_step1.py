"""PX データ取得 第1段: 学科の履修科目一覧（catalog）と tree_env.pdf を取る。

リポの KansaiSyllabusFetcher（origin/main 14f8d57）をそのまま使い、保存先だけ data_raw に替える。
各リクエストの時刻を request_log.jsonl に残す（間隔 >= 1 秒の確認用）。
"""
import sys
import json
import time
from pathlib import Path

PX = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PX / "code" / "ingestion"))

import httpx  # noqa: E402
from src.fetchers.kansai.fetch_syllabus import KansaiSyllabusFetcher  # noqa: E402

DATA_RAW = PX / "data_raw"
TREE_URL = "https://www.kansai-u.ac.jp/ja/assets/pdf/about/outline/faculty/tree_env.pdf"
MIN_INTERVAL_S = 1.2
LOG = PX / "request_log.jsonl"


def log_request(url: str, ok: bool, note: str = "") -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "url": url, "ok": ok, "note": note}, ensure_ascii=False) + "\n")


def main() -> None:
    fetcher = KansaiSyllabusFetcher(base_dir=DATA_RAW, year="2026", delay=MIN_INTERVAL_S)
    with httpx.Client() as client:
        url = fetcher.get_curriculum_url()
        path = fetcher.fetch_curriculum_catalog(client=client)
        log_request(url, True, "catalog")
        time.sleep(MIN_INTERVAL_S)
        content = path.read_text(encoding="utf-8", errors="replace")
        entries = fetcher.extract_catalog_items(content)
        fetcher.save_catalog_index(entries)
        print(f"catalog entries: {len(entries)}")

        pdf_dest = DATA_RAW / "2026" / "curriculum" / "tree_env.pdf"
        fetcher.download_file(TREE_URL, pdf_dest, client)
        log_request(TREE_URL, True, "tree_env.pdf")
        print(f"pdf bytes: {pdf_dest.stat().st_size}")


if __name__ == "__main__":
    main()
