"""取得したシラバス詳細 HTML（127件）をリポの KansaiSyllabusTransformer で JSON にする。"""
import sys
from pathlib import Path

PX = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PX / "code" / "ingestion"))

from src.transformers.kansai.syllabus_parser import KansaiSyllabusTransformer  # noqa: E402


def main() -> None:
    t = KansaiSyllabusTransformer(raw_dir=PX / "data_raw" / "2026", output_dir=PX / "work" / "parsed")
    results, report = t.parse_all()
    print(f"parsed {report.success_count}/{report.total_processed}, errors {report.error_count}")


if __name__ == "__main__":
    main()
