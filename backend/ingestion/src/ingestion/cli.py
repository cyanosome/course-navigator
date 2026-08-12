"""シラバスデータ取得・精査・DB格納バッチ CLI エントリーポイント。

`course_core` の DBモデル・リポジトリ層を活用してデータ投入を行う。
"""

import argparse
import sys

from course_core.schemas.integrated import IntegratedSyllabusInput


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Syllabus Ingestion CLI (Data Fetch, Parse, and DB Ingestion)"
    )
    parser.add_argument("--source", type=str, help="Target syllabus data source or URL")
    parser.add_argument("--dry-run", action="store_true", help="Parse and validate without DB insert")

    args = parser.parse_args()

    print(f"[Ingestion CLI] Starting pipeline. Source: {args.source or 'default'}, Dry run: {args.dry_run}")
    
    # 動作確認用サンプルモデル検証
    sample = IntegratedSyllabusInput(
        code="CS101",
        title="コンピュータサイエンス入門",
        instructor="山田 太郎",
        schedule="月1",
        credits=2,
        syllabus_text="プログラミングとデータ構造の基礎",
        prerequisite_codes=[],
        topics=["Python", "アルゴリズム"],
    )
    print(f"[Ingestion CLI] Validated sample syllabus model: {sample.title} ({sample.code})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
