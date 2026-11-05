"""研究の設定値（環境変数）。

テストで monkeypatch.setenv できるよう、モジュールの読み込み時ではなく呼ぶたびに読む。
"""

import os
from pathlib import Path
from typing import Final

from course_core.research.variants import VARIANTS

__all__ = [
    "DEFAULT_VARIANT_ID",
    "app_commit",
    "default_variant_id",
    "research_data_dir",
    "research_dev",
]

_DATA_DIR_ENV: Final = "RESEARCH_DATA_DIR"
_DEV_ENV: Final = "RESEARCH_DEV"
_DEFAULT_VARIANT_ENV: Final = "NAVI_DEFAULT_VARIANT"
_APP_COMMIT_ENV: Final = "APP_COMMIT"
_TRUE_VALUES: Final = ("true", "1", "yes")
# トークン無しで /navi を開いたときの変種。E1 が通れば V00 に変える（api-contract.md 3.7）。
DEFAULT_VARIANT_ID: Final = "V01"
# backend ルートの目印。agent/trace.py の default_trace_dir と同じ探し方に揃える。
_BACKEND_MARKER: Final = Path("seed") / "courses.json"
_DATA_SUBDIR: Final = Path("logs") / "research"


def research_data_dir() -> Path:
    """研究のログと study のファイルの置き場所。既定は `backend/logs/research`（git の対象外）。"""
    override = os.getenv(_DATA_DIR_ENV)
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        if (parent / _BACKEND_MARKER).is_file():
            return parent / _DATA_SUBDIR
    raise FileNotFoundError(
        f"backend ルートを特定できません。環境変数 {_DATA_DIR_ENV} で指定してください。"
    )


def research_dev() -> bool:
    """開発用の口（変種の直接指定・AI の options）を開けるか。本番では偽。"""
    return os.getenv(_DEV_ENV, "").strip().lower() in _TRUE_VALUES


def default_variant_id() -> str:
    """調査でないときの画面の変種。表に無い値なら設定の誤りとして止める（黙って既定に戻さない）。"""
    variant_id = os.getenv(_DEFAULT_VARIANT_ENV, DEFAULT_VARIANT_ID).strip()
    if variant_id not in VARIANTS:
        raise ValueError(
            f"環境変数 {_DEFAULT_VARIANT_ENV}={variant_id!r} は変種の表にありません"
            f"（{min(VARIANTS)}〜{max(VARIANTS)}）。"
        )
    return variant_id


def app_commit() -> str | None:
    """backend のコミット（ログの app_version.backend）。未設定なら None（扱いは呼ぶ側が決める）。"""
    value = os.getenv(_APP_COMMIT_ENV, "").strip()
    return value or None
