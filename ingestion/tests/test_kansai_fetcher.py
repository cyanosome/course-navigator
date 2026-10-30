"""
Unit tests for Kansai University Syllabus Fetcher.
"""

import json
from pathlib import Path
import pytest
import httpx

from src.fetchers.kansai import KansaiSyllabusFetcher, CatalogEntry, FetchSummary

MOCK_CATALOG_HTML = """
<!DOCTYPE html>
<html>
<head><title>カリキュラム検索(検索結果)</title></head>
<body>
<ul class='spclearfix single' id='child_li_104919_034454'>
	<li class='name col2 pt01'><p class='heightLine-104919_034454' id='child_li_104919_034454'>１〜４年次</p></li>
	<li class='name col2 pt03'><p class='heightLine-104919_034454'><a href="javascript:void(0);" onClick="javascript:openWin('../../../../ref/0/3/44/034454.html');return false;">日本の近現代史と関西大学－知の群像 (00301)</a></p></li>
	<span class='child_li_104919_034454 tit curri_child_first spnone'>単位</span>
	<li class='child_li_104919_034454 spnone'><p>2</p></li>
	<span class='child_li_104919_034454 tit curri_child spnone'>クラス</span>
	<li class='child_li_104919_034454 spnone pt01'><p></p></li>
	<span class='child_li_104919_034454 tit curri_child spnone'>担任者名</span>
	<li class='child_li_104919_034454 spnone pt01'><p>薮田　貫</p></li>
	<span class='child_li_104919_034454 tit curri_child spnone'>曜限</span>
	<li class='child_li_104919_034454 spnone bdrnone pt01'><p>春学期&nbsp;火2</p></li>
</ul>

<ul class='spclearfix single' id='child_li_028400_160976'>
	<li class='name col2 pt01'><p class='heightLine-028400_160976' id='child_li_028400_160976'>１年次</p></li>
	<li class='name col2 pt03'><p class='heightLine-028400_160976'><a href="javascript:void(0);" onClick="javascript:openWin('../../../../ref/1/6/09/160976.html');return false;">数学解析１ (60075)</a></p></li>
	<span class='child_li_028400_160976 tit curri_child_first spnone'>単位</span>
	<li class='child_li_028400_160976 spnone'><p>2</p></li>
	<span class='child_li_028400_160976 tit curri_child spnone'>クラス</span>
	<li class='child_li_028400_160976 spnone pt01'><p>E</p></li>
	<span class='child_li_028400_160976 tit curri_child spnone'>担任者名</span>
	<li class='child_li_028400_160976 spnone pt01'><p>山田　太郎&nbsp;他</p></li>
	<span class='child_li_028400_160976 tit curri_child spnone'>曜限</span>
	<li class='child_li_028400_160976 spnone bdrnone pt01'><p>秋学期&nbsp;月3</p></li>
</ul>

<ul class='spclearfix single' id='child_li_without_code'>
	<li class='name col2 pt01'><p>２年次</p></li>
	<li class='name col2 pt03'><p><a href="javascript:void(0);" onClick="javascript:openWin('../../../../ref/1/6/22/162242.html');return false;">ユニットオペレーション１</a></p></li>
	<span class='tit'>単位</span>
	<li><p>2</p></li>
	<span class='tit'>クラス</span>
	<li><p></p></li>
	<span class='tit'>担任者名</span>
	<li><p>化学　教授</p></li>
	<span class='tit'>曜限</span>
	<li><p>春学期&nbsp;木1</p></li>
</ul>
</body>
</html>
"""


def test_get_curriculum_url():
    fetcher = KansaiSyllabusFetcher(
        year="2026",
        bu="10",
        gakubu="320",
        gakka="031",
    )
    url = fetcher.get_curriculum_url()
    assert url == "https://syllabus3.jm.kansai-u.ac.jp/syllabus/search/curri/2026/10/320/202610320031ZZZZ_.html"


def test_extract_catalog_items():
    entries = KansaiSyllabusFetcher.extract_catalog_items(MOCK_CATALOG_HTML)
    assert len(entries) == 3

    # Entry 1
    e1 = entries[0]
    assert e1.syllabus_id == "034454"
    assert e1.timetable_code == "00301"
    assert e1.subject_name == "日本の近現代史と関西大学－知の群像"
    assert e1.year_range == "１〜４年次"
    assert e1.credits == "2"
    assert e1.class_name == ""
    assert e1.instructors == "薮田　貫"
    assert e1.term_schedule == "春学期 火2"
    assert e1.relative_ref_path == "0/3/44/034454.html"
    assert e1.detail_url == "https://syllabus3.jm.kansai-u.ac.jp/syllabus/search/ref/0/3/44/034454.html"

    # Entry 2
    e2 = entries[1]
    assert e2.syllabus_id == "160976"
    assert e2.timetable_code == "60075"
    assert e2.subject_name == "数学解析１"
    assert e2.year_range == "１年次"
    assert e2.credits == "2"
    assert e2.class_name == "E"
    assert e2.instructors == "山田　太郎 他"
    assert e2.term_schedule == "秋学期 月3"

    # Entry 3 (without timetable code in title)
    e3 = entries[2]
    assert e3.syllabus_id == "162242"
    assert e3.timetable_code is None
    assert e3.subject_name == "ユニットオペレーション１"
    assert e3.year_range == "２年次"


def test_save_catalog_index(tmp_path: Path):
    fetcher = KansaiSyllabusFetcher(base_dir=tmp_path, year="2026")
    entries = KansaiSyllabusFetcher.extract_catalog_items(MOCK_CATALOG_HTML)
    index_file = fetcher.save_catalog_index(entries)

    assert index_file.exists()
    data = json.loads(index_file.read_text(encoding="utf-8"))
    assert len(data) == 3
    assert data[0]["syllabus_id"] == "034454"
    assert data[0]["timetable_code"] == "00301"


def test_download_file_caching(tmp_path: Path):
    fetcher = KansaiSyllabusFetcher(base_dir=tmp_path, year="2026")
    dest_file = tmp_path / "2026" / "test.html"

    # 1. Mock client that returns sample HTML
    def handler(request: httpx.Request):
        return httpx.Response(200, content=b"<html>Test</html>")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    # First download -> Should download
    res1 = fetcher.download_file("https://example.com/test.html", dest_file, client, force=False)
    assert res1 is True
    assert dest_file.exists()
    assert dest_file.read_bytes() == b"<html>Test</html>"

    # Second download without force -> Should skip
    res2 = fetcher.download_file("https://example.com/test.html", dest_file, client, force=False)
    assert res2 is False

    # Third download with force -> Should re-download
    res3 = fetcher.download_file("https://example.com/test.html", dest_file, client, force=True)
    assert res3 is True


def test_fetch_details_with_limit_and_error(tmp_path: Path):
    fetcher = KansaiSyllabusFetcher(base_dir=tmp_path, year="2026", delay=0.0)
    entries = KansaiSyllabusFetcher.extract_catalog_items(MOCK_CATALOG_HTML)

    # Mock handler: return 200 for 034454, 404 for 160976
    def handler(request: httpx.Request):
        if "034454" in str(request.url):
            return httpx.Response(200, content=b"<html>Course 034454</html>")
        elif "160976" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=b"<html>Course other</html>")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    # Limit = 2
    summary = fetcher.fetch_details(entries, client=client, limit=2)

    assert summary.total_entries == 2
    assert summary.newly_downloaded == 1
    assert summary.skipped_existing == 0
    assert summary.failed == 1
    assert "160976" in summary.failed_ids

    # Verify downloaded file path
    downloaded_path = tmp_path / "2026" / "ref" / "0" / "3" / "44" / "034454.html"
    assert downloaded_path.exists()
    assert downloaded_path.read_text(encoding="utf-8") == "<html>Course 034454</html>"
