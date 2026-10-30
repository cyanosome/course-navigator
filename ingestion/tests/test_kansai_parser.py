"""
Unit tests for Kansai University Syllabus Transformer.
"""

import json
from pathlib import Path
import pytest

from src.transformers.kansai import (
    KansaiSyllabusTransformer,
    KansaiCourseDetail,
    InstructorItem,
    ScheduleSession,
    ParseReport,
)

MOCK_DETAIL_HTML = """
<!DOCTYPE html>
<html>
<head><title>授業科目詳細</title></head>
<body>
<span id="nendo">2026</span>
<span id="kmkCd">055060</span>
<span id="jikanwari">64214</span>
<span id="kamoku">ユニットオペレーション１</span>
<span id="subkamoku">化学工学単位操作の基礎</span>
<span id="tani">2</span>
<span id="class">3</span>
<span id="jyugyokeitai">春</span>
<span id="yougen">火2</span>
<span id="gakubu">環/化</span>
<span id="buGakuguGakka">01320030:01320031</span>
<span id="jyuKbn">01</span>
<span id="gosyu"></span>
<span id="gengo">日本語(Japanese)</span>
<span id="jyugyohouhou">講義（対面型）</span>
<div id="jyugyosyuhou">
・教員による資料等を用いた説明
・学生による課題演習
</div>
<span id="tannin">荒木 貞夫</span>
<span id="tantou">荒木 貞夫/田中 太郎</span>
<span id="kyoinCdList">70726/88888</span>
<span id="toiawasehouhou">関大LMSのメッセージにて</span>
<div id="gaiyo">化学工学の基礎である単位操作を講述する。</div>
<div id="mokuhyo">流動・伝熱の基礎計算を修得する。</div>
<div id="keikaku">
第01回 オリエンテーション
第02回 単位と次元
第03回 質量保存
</div>
<div id="jikangaigakusyu">演習問題を解くこと。</div>
<div id="hyokahouhou">平常点70%と演習30%</div>
<div id="hyokakijyun">60点以上で合格</div>
<span id="kyokasyo">疋田晴夫 『化学工学通論１』 （朝倉書店）</span><br>
<span id="kyokasyo">補助資料プリント</span>
<span id="kyokasyobikou">教科書備考</span>
<span id="sankousyo">化学工学会編 『基礎と実践』 （アグネス承風社）</span>
<span id="sankousyobikou">参考書備考</span>
<div id="feedback">課題は採点後に返却。</div>
<div id="bikou">オンデマンド回があります。</div>
</body>
</html>
"""


def test_clean_text():
    raw = " 第1行 <br> 第2行 &nbsp;テスト <span class='test'>タグ</span> <br/>第3行 "
    cleaned = KansaiSyllabusTransformer.clean_text(raw)
    assert cleaned == "第1行\n第2行 テスト タグ\n第3行"


def test_parse_instructors():
    tannin = "荒木 貞夫"
    tantou = "荒木 貞夫/田中 太郎"
    codes = "70726/88888"

    items, tantou_list, tannin_list, codes_list = KansaiSyllabusTransformer.parse_instructors(
        tannin, tantou, codes
    )

    assert len(items) == 2
    assert items[0].name == "荒木 貞夫"
    assert items[0].code == "70726"
    assert items[0].is_primary is True

    assert items[1].name == "田中 太郎"
    assert items[1].code == "88888"
    assert items[1].is_primary is False

    assert tantou_list == ["荒木 貞夫", "田中 太郎"]
    assert tannin_list == ["荒木 貞夫"]
    assert codes_list == ["70726", "88888"]


def test_parse_schedule_sessions():
    raw = (
        "第01回 オリエンテーション\n"
        "第2週　単位と次元\n"
        "3. 質量保存の法則\n"
        "その他 補講\n"
    )
    sessions = KansaiSyllabusTransformer.parse_schedule_sessions(raw)

    assert len(sessions) == 4
    assert sessions[0].session_number == 1
    assert sessions[0].topic == "オリエンテーション"

    assert sessions[1].session_number == 2
    assert sessions[1].topic == "単位と次元"

    assert sessions[2].session_number == 3
    assert sessions[2].topic == "質量保存の法則"

    assert sessions[3].session_number is None
    assert sessions[3].topic == "その他 補講"


def test_extract_multi_spans():
    html_content = (
        "<span id='kyokasyo'>書籍 A</span><br>"
        "<span id='kyokasyo'>書籍 B (著者)</span>"
    )
    books = KansaiSyllabusTransformer.extract_multi_spans_by_id(html_content, "kyokasyo")
    assert books == ["書籍 A", "書籍 B (著者)"]


def test_parse_single_html(tmp_path: Path):
    html_file = tmp_path / "1" / "6" / "22" / "162242.html"
    html_file.parent.mkdir(parents=True, exist_ok=True)
    html_file.write_text(MOCK_DETAIL_HTML, encoding="utf-8")

    catalog_entry = {
        "syllabus_id": "162242",
        "timetable_code": "64214",
        "subject_name": "ユニットオペレーション１",
        "year_range": "２年次",
        "credits": "2",
        "term_schedule": "火2",
    }

    transformer = KansaiSyllabusTransformer(raw_dir=tmp_path, output_dir=tmp_path / "parsed")
    course = transformer.parse_single_html(html_file, catalog_info=catalog_entry)

    assert isinstance(course, KansaiCourseDetail)
    assert course.syllabus_id == "162242"
    assert course.course_code == "055060"
    assert course.timetable_code == "64214"
    assert course.subject_name == "ユニットオペレーション１"
    assert course.subtitle == "化学工学単位操作の基礎"
    assert course.credits == 2.0
    assert course.year_range == "２年次"
    assert course.class_name == "3"
    assert course.semester == "春"
    assert course.term_schedule == "火2"
    assert course.faculties == ["環", "化"]
    assert course.department_codes == ["01320030", "01320031"]
    assert course.language == "日本語(Japanese)"
    assert course.teaching_type == "講義（対面型）"
    assert course.teaching_methods == ["教員による資料等を用いた説明", "学生による課題演習"]
    assert len(course.instructors) == 2
    assert course.instructors[0].name == "荒木 貞夫"
    assert course.instructors[0].code == "70726"
    assert course.instructors[0].is_primary is True
    assert course.contact_method == "関大LMSのメッセージにて"
    assert course.description == "化学工学の基礎である単位操作を講述する。"
    assert course.objectives == "流動・伝熱の基礎計算を修得する。"
    assert len(course.schedule_sessions) == 3
    assert course.schedule_sessions[0].session_number == 1
    assert course.textbooks == ["疋田晴夫 『化学工学通論１』 （朝倉書店）", "補助資料プリント"]
    assert course.textbook_notes == "教科書備考"
    assert course.references == ["化学工学会編 『基礎と実践』 （アグネス承風社）"]
    assert course.feedback_method == "課題は採点後に返却。"
    assert course.notes == "オンデマンド回があります。"


def test_parse_all_batch(tmp_path: Path):
    raw_dir = tmp_path / "raw"
    ref_dir = raw_dir / "ref" / "1" / "6" / "22"
    ref_dir.mkdir(parents=True, exist_ok=True)

    file1 = ref_dir / "162242.html"
    file1.write_text(MOCK_DETAIL_HTML, encoding="utf-8")

    catalog_index = [
        {
            "syllabus_id": "162242",
            "timetable_code": "64214",
            "subject_name": "ユニットオペレーション１",
            "year_range": "２年次",
        }
    ]
    (raw_dir / "catalog_index.json").write_text(json.dumps(catalog_index), encoding="utf-8")

    out_dir = tmp_path / "parsed"
    transformer = KansaiSyllabusTransformer(raw_dir=raw_dir, output_dir=out_dir)
    results, report = transformer.parse_all()

    assert report.total_processed == 1
    assert report.success_count == 1
    assert report.error_count == 0
    assert len(results) == 1

    detail_json = out_dir / "courses_detail.json"
    lookup_json = out_dir / "courses_lookup.json"
    report_json = out_dir / "parse_report.json"

    assert detail_json.exists()
    assert lookup_json.exists()
    assert report_json.exists()

    lookup_data = json.loads(lookup_json.read_text(encoding="utf-8"))
    assert "162242" in lookup_data
    assert "64214" in lookup_data
