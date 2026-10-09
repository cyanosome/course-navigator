"""LLM 回答の出典を DB の行から組み立てる純関数群（test3-2）。

出典（Source）は LLM の生成テキストではなく、cited_codes を PostgreSQL で引き直した
行だけから作る。LLM が引用したが DB に存在しないコードは unverified_codes に回し、
出典としては出さない（ハルシネーション検出）。I/O を持たないので DB 無しでテストできる。
"""

import string
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

from agent.schemas import AnswerPayload, GroundedAnswer, Source

__all__ = [
    "EXCERPT_MAX_CHARS",
    "SOURCE_ORIGIN",
    "build_grounded_answer",
    "normalize_codes",
    "source_from_row",
    "truncate_text",
    "ungrounded_answer",
]

SOURCE_ORIGIN = "postgres:test_postgres_syllabus"
EXCERPT_MAX_CHARS = 120
_ELLIPSIS = "…"
# LLM が回答文の書式（例 "[GMS-303]" / "【GMS-303】"）のまま cited_codes に入れてくる括弧。
# NFKC 後に外すので全角の［］や全角空白もここで落ちる。
_CODE_STRIP_CHARS = string.whitespace + "[]【】"


def truncate_text(text: str | None, max_chars: int) -> str:
    """max_chars を超える部分を切り、切ったときだけ省略記号を付ける。"""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + _ELLIPSIS


def _normalize_code(code: str) -> str:
    """NFKC で全角英数・記号を半角に寄せ、前後の空白と括弧を外す。大文字小文字は変えない。"""
    return unicodedata.normalize("NFKC", code).strip(_CODE_STRIP_CHARS)


def normalize_codes(codes: Iterable[str]) -> list[str]:
    """各コードを正規化して空文字を捨て、出現順を保ったまま重複を除く。

    例: "[GMS-303]" / "ＧＭＳ－３０３" / " GMS-303 " はすべて "GMS-303" になる。
    """
    normalized = (_normalize_code(code) for code in codes)
    return list(dict.fromkeys(code for code in normalized if code))


def source_from_row(row: Mapping[str, Any]) -> Source:
    """test_postgres_syllabus の1行（asyncpg.Record / dict）を Source に変換する。"""
    return Source(
        code=row["code"],
        title=row["title"],
        instructor=row["instructor"],
        schedule=row["schedule"],
        credits=row["credits"],
        excerpt=truncate_text(row["syllabus_text"], EXCERPT_MAX_CHARS),
        origin=SOURCE_ORIGIN,
    )


def build_grounded_answer(
    payload: AnswerPayload, rows: Iterable[Mapping[str, Any]]
) -> GroundedAnswer:
    """cited_codes を DB の行と突き合わせ、出典と未検証コードに振り分ける。

    sources / unverified_codes はどちらも cited_codes の出現順に並ぶ。
    """
    cited = normalize_codes(payload.cited_codes)
    rows_by_code = {row["code"]: row for row in rows}
    return GroundedAnswer(
        answer=payload.answer,
        cited_codes=cited,
        sources=[source_from_row(rows_by_code[code]) for code in cited if code in rows_by_code],
        unverified_codes=[code for code in cited if code not in rows_by_code],
    )


def ungrounded_answer(payload: AnswerPayload, note: str) -> GroundedAnswer:
    """DB を引けなかったとき用。全コードを未検証に回し、理由を notes に残す。"""
    cited = normalize_codes(payload.cited_codes)
    return GroundedAnswer(
        answer=payload.answer,
        cited_codes=cited,
        unverified_codes=cited,
        notes=[note],
    )
