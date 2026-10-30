"""
Kansai University Syllabus Fetchers.
"""

from src.fetchers.kansai.schema import CatalogEntry, FetchSummary
from src.fetchers.kansai.fetch_syllabus import KansaiSyllabusFetcher

__all__ = ["KansaiSyllabusFetcher", "CatalogEntry", "FetchSummary"]
