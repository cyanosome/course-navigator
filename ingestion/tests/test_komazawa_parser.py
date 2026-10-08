"""Unit tests for Komazawa University syllabus parser."""

import json
from pathlib import Path
import pytest

from src.parsers.komazawa.parser import (
    extract_js_data,
    clean_text,
    parse_subject_tokens,
    parse_record,
    parse_file,
)
from src.parsers.komazawa.schema import CourseSummary


def test_extract_js_data_normal():
    """Should correctly extract JSON list from JavaScript variable assignment."""
    js = """
    var nendo = "2026";
    var data = [
        {"syllabus_nendo": 2026, "rishu_code": "500101", "kamoku_name": "Test Course"}
    ];
    """
    result = extract_js_data(js)
    assert len(result) == 1
    assert result[0]["rishu_code"] == "500101"


def test_extract_js_data_with_control_chars():
    """Should successfully parse JS strings containing raw unescaped newlines and tabs."""
    # Embedding raw newlines within JSON string literal
    js = 'var data = [{"rishu_code": "500101", "subject": "line1\nline2\tline3"}];'
    result = extract_js_data(js)
    assert len(result) == 1
    assert "line1\nline2\tline3" == result[0]["subject"]


def test_extract_js_data_not_found():
    """Should raise ValueError when 'var data = [...]' pattern is missing."""
    with pytest.raises(ValueError):
        extract_js_data("var other = 123;")


def test_clean_text():
    """Should replace full-width spaces and collapse redundant whitespaces."""
    raw = "　テスト　科目\n\n\n\n説明文   詳細　"
    cleaned = clean_text(raw)
    assert cleaned == "テスト 科目\n\n説明文 詳細"


def test_parse_subject_tokens_standard():
    """Should correctly parse header, body, and footer tokens."""
    subject = (
        "500101 仏教と人間 ﾌﾞﾂｷﾖｳﾄﾆﾝｹﾞﾝ 2026年 通年 4 "
        "建学の理念に基づく授業です。到達目標を達成すること。 "
        "クマモト エイニン 金曜日 3時限"
    )
    tokens = subject.split()
    kana, term, credits, inst_kana, day, period, body = parse_subject_tokens(tokens)

    assert kana == "ﾌﾞﾂｷﾖｳﾄﾆﾝｹﾞﾝ"
    assert term == "通年"
    assert credits == 4.0
    assert inst_kana == "クマモト エイニン"
    assert day == "金曜日"
    assert period == "3時限"
    assert "建学の理念に基づく授業です。到達目標を達成すること。" in body


def test_parse_subject_tokens_multi_token_kana():
    """Should locate year token dynamically even if kana consists of multiple tokens."""
    subject = (
        "542431 日本の位相 ﾃｰﾏﾃﾞﾏﾅﾌﾞﾆﾎﾝﾉｲｿｳ (3) 2026年 前期 2 "
        "日本の文化を多角的に考察します。 "
        "ヤマダ タロウ 月曜日 1時限"
    )
    tokens = subject.split()
    kana, term, credits, inst_kana, day, period, body = parse_subject_tokens(tokens)

    assert kana == "ﾃｰﾏﾃﾞﾏﾅﾌﾞﾆﾎﾝﾉｲｿｳ (3)"
    assert term == "前期"
    assert credits == 2.0
    assert inst_kana == "ヤマダ タロウ"
    assert day == "月曜日"
    assert period == "1時限"
    assert "日本の文化を多角的に考察します。" in body


def test_parse_subject_tokens_fallback():
    """Should safely fallback without crashing when text format is irregular."""
    subject = "集中講義のため不規則なテキスト形式です。"
    tokens = subject.split()
    kana, term, credits, inst_kana, day, period, body = parse_subject_tokens(tokens)

    assert kana is None
    assert term is None
    assert credits is None
    assert day is None
    assert period == "不規則なテキスト形式です。" or period is None
    assert body != ""


def test_parse_record():
    """Should validate record using Pydantic CourseSummary model."""
    raw_item = {
        "syllabus_nendo": 2026,
        "rishu_code": "500101",
        "kamoku_name": "仏教と人間",
        "kyoin_shimei": "熊本　英人",
        "gakka_srnm": "禅仏/禅/仏",
        "subject": "500101 仏教と人間 ﾌﾞﾂｷﾖｳﾄﾆﾝｹﾞﾝ 2026年 通年 4 授業概要 クマモト エイニン 金曜日 3時限",
    }
    course = parse_record(raw_item)
    assert isinstance(course, CourseSummary)
    assert course.course_code == "500101"
    assert course.course_name == "仏教と人間"
    assert course.instructor == "熊本　英人"
    assert course.department == "禅仏/禅/仏"
    assert course.term == "通年"
    assert course.credits == 4.0
    assert course.day_of_week == "金曜日"
    assert course.period == "3時限"
    assert course.text == "授業概要"


def test_parse_file_end_to_end(tmp_path: Path):
    """Should read raw JS file and write valid courses_summary.json atomically."""
    input_file = tmp_path / "raw.js"
    output_file = tmp_path / "out" / "courses_summary.json"

    js_content = """
    var nendo = "2026";
    var data = [
        {
            "syllabus_nendo": 2026,
            "rishu_code": "500101",
            "kamoku_name": "仏教と人間",
            "kyoin_shimei": "熊本　英人",
            "gakka_srnm": "禅仏/禅/仏",
            "subject": "500101 仏教と人間 ﾌﾞﾂｷﾖｳﾄﾆﾝｹﾞﾝ 2026年 通年 4 講義概要本文 クマモト エイニン 金曜日 3時限"
        },
        {
            "syllabus_nendo": 2026,
            "rishu_code": "500201",
            "kamoku_name": "哲学入門",
            "kyoin_shimei": "佐藤　次郎",
            "gakka_srnm": "哲学科",
            "subject": "500201 哲学入門 ﾃﾂｶﾞｸﾆｭｳﾓﾝ 2026年 前期 2 哲学の基礎 サトウ ジロウ 月曜日 2時限"
        }
    ];
    """
    input_file.write_text(js_content, encoding="utf-8")

    stats = parse_file(input_file, output_file)

    assert stats["total"] == 2
    assert stats["success"] == 2
    assert stats["error"] == 0
    assert stats["with_term"] == 2
    assert stats["with_credits"] == 2
    assert stats["with_schedule"] == 2

    assert output_file.exists()
    # Temporary file should not exist
    assert not output_file.with_name(f"{output_file.name}.tmp").exists()

    saved_data = json.loads(output_file.read_text(encoding="utf-8"))
    assert len(saved_data) == 2
    assert saved_data[0]["course_code"] == "500101"
    assert saved_data[1]["course_code"] == "500201"
