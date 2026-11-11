"""Study 1 の道具が共通に使うファイルの扱い（書き先の検査・SHA-256・JSON の書き出し）。

人のデータ（研究のイベントの JSONL、質問票）とそこから作った表は公開リポに入れない（事前登録 6.3）。
書き先の検査は course_core.research.cli の _private_output と同じ考え方: 既にあるファイルは上書きせず、
git の作業ツリーの中には書かない。コンテナの中ではホストの .git が見えないので、/tmp に書いて
docker compose cp でリポの外へ出す（手順書 1章）。
"""

import hashlib
import json
from pathlib import Path
from typing import Any

__all__ = ["OutputError", "check_private_output", "sha256_file", "write_private_json", "write_private_text"]


class OutputError(ValueError):
    """書き先が使えない（既にある・git の作業ツリーの中）。"""


def _inside_git_worktree(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in path.resolve().parents)


def check_private_output(path: Path, what: str) -> None:
    """研究者の手元にだけ置くファイルの書き先を検査する。使えなければ OutputError。"""
    if path.exists():
        raise OutputError(f"{what} の書き先 {path} は既にあります（上書きしません）。")
    if _inside_git_worktree(path):
        raise OutputError(f"{what} を git の作業ツリーの中（{path}）には書きません。リポの外を指定してください。")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_private_text(path: Path, text: str, what: str) -> str:
    """検査してから新しく書く（"x" で開くので、検査と書き込みの間にできたファイルも上書きしない）。SHA-256 を返す。"""
    check_private_output(path, what)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    return sha256_file(path)


def write_private_json(path: Path, data: Any, what: str) -> str:
    return write_private_text(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n", what)
