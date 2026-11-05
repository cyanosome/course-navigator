"""PX データ取得 第2段: 系統図の科目に当たるシラバス詳細だけを取る（1029件全部は取らない）。

対象 = 系統図70科目の完全一致（normalize_title 後）の全クラス + 「数学を学ぶ（微分積分N・演習N）」に当たる
「数学を学ぶ（微分積分N）」「数学を学ぶ（微分積分演習N）」の全クラス。
リポの KansaiSyllabusFetcher.fetch_details を delay=1.2 秒で使う（取得のたびに 1.2 秒待つ）。
"""
import sys
import json
from pathlib import Path

PX = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PX / "code" / "ingestion"))

import httpx  # noqa: E402
from src.fetchers.kansai.fetch_syllabus import KansaiSyllabusFetcher  # noqa: E402
from src.fetchers.kansai.schema import CatalogEntry  # noqa: E402
from src.transformers.kansai.curriculum_tree_parser import normalize_title  # noqa: E402

DATA_RAW = PX / "data_raw"
CATALOG = DATA_RAW / "2026" / "catalog_index.json"
MATCH = PX / "work" / "catalog_match.json"
MIN_INTERVAL_S = 1.2
EXTRA_NORMS = {normalize_title(s) for s in [
    "数学を学ぶ（微分積分１）", "数学を学ぶ（微分積分演習１）",
    "数学を学ぶ（微分積分２）", "数学を学ぶ（微分積分演習２）",
]}


def main() -> None:
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    match = json.loads(MATCH.read_text(encoding="utf-8"))
    want = {e["syllabus_id"] for r in match for e in r["exact"]}
    want |= {e["syllabus_id"] for e in cat if normalize_title(e["subject_name"]) in EXTRA_NORMS}
    entries = [CatalogEntry(**e) for e in cat if e["syllabus_id"] in want]
    print(f"detail pages to fetch: {len(entries)}", flush=True)
    fetcher = KansaiSyllabusFetcher(base_dir=DATA_RAW, year="2026", delay=MIN_INTERVAL_S)
    with httpx.Client() as client:
        summary = fetcher.fetch_details(entries, client=client)
    print(summary.model_dump_json())


if __name__ == "__main__":
    main()
