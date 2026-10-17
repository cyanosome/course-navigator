"""実行したコードの出所を記録・照合する（prereg_retrieval_seed_replication.md §5.1）。

backend コンテナには .git が無いので、HEAD と `git status --porcelain` はホストから渡す。そのうえで、
コンテナから見えた backend のソースを git の blob SHA-1 の一覧にして指紋を取る。ホストでは
`git ls-tree --full-tree -r -z <HEAD> -- backend` から同じ規則で指紋を作り、両者が一致すれば「実行したコード = その commit」と言える。
標準ライブラリだけを使う。
"""

import hashlib
import os
from pathlib import Path, PurePosixPath

__all__ = [
    "FINGERPRINT_RULE",
    "fingerprint_from_ls_tree",
    "git_blob_sha1",
    "is_fingerprinted",
    "require_clean",
    "source_fingerprint",
]

FINGERPRINT_RULE = (
    "backend 配下のファイル。名前が '.' で始まる要素・__pycache__ を含むパス、logs/、eval/results/ を除く。"
    "blob SHA-1 は CRLF を LF にそろえて計算する"
)
GIT_PREFIX = "backend/"
# 実行中に書き換わるもの（ログと結果）。コードではないので指紋に入れない
_EXCLUDED_PREFIXES = ("logs/", "eval/results/")
# git status --porcelain（パスはリポジトリのルートから）で、ハーネス自身が書く結果の置き場
OUTPUT_PREFIX = "backend/eval/results/"
_CACHE_DIR = "__pycache__"


def git_blob_sha1(data: bytes) -> str:
    """git の blob SHA-1。Windows の checkout（core.autocrlf=true）は CRLF なので、git の正規化に合わせて LF にそろえる。"""
    normalized = data.replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(normalized) + normalized).hexdigest()


def is_fingerprinted(relative: str) -> bool:
    """backend からの相対パス（/ 区切り）が指紋の対象か。"""
    parts = PurePosixPath(relative).parts
    if any(part.startswith(".") or part == _CACHE_DIR for part in parts):
        return False
    return not relative.startswith(_EXCLUDED_PREFIXES)


def _digest(entries: dict[str, str]) -> dict[str, object]:
    listing = "".join(f"{sha}  {path}\n" for path, sha in sorted(entries.items()))
    return {
        "rule": FINGERPRINT_RULE,
        "files": len(entries),
        "sha256": hashlib.sha256(listing.encode("utf-8")).hexdigest(),
    }


def source_fingerprint(root: Path) -> dict[str, object]:
    """root（コンテナでは /backend_app）配下の対象ファイルの指紋。隠しディレクトリ（.venv など）は辿らない。"""
    entries: dict[str, str] = {}
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not name.startswith(".") and name != _CACHE_DIR]
        for name in filenames:
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            if is_fingerprinted(relative):
                entries[relative] = git_blob_sha1(path.read_bytes())
    return _digest(entries)


def fingerprint_from_ls_tree(ls_tree: str, prefix: str = GIT_PREFIX) -> dict[str, object]:
    """`git ls-tree --full-tree -r -z <commit> -- backend` の出力から、source_fingerprint と同じ規則で指紋を作る。"""
    entries: dict[str, str] = {}
    for item in ls_tree.split("\0"):
        if not item.strip():
            continue
        meta, path = item.split("\t", 1)
        _, kind, sha = meta.split()
        if kind != "blob" or not path.startswith(prefix):
            continue
        relative = path[len(prefix) :]
        if is_fingerprinted(relative):
            entries[relative] = sha
    return _digest(entries)


def _is_new_output(line: str) -> bool:
    return line.startswith("?? ") and line[3:].startswith(OUTPUT_PREFIX)


def require_clean(git_status: str) -> list[str]:
    """ホストの `git status --porcelain` に未コミットの変更があれば止める（未コミットのコードで結果を記録しない）。

    例外は eval/results/ 配下の未追跡ファイル（前のコマンドが書いた結果と manifest）だけで、それは返り値で返す。
    既存の結果ファイルの変更（M など）は汚れとして止める。
    """
    lines = [line for line in git_status.splitlines() if line.strip()]
    dirty = [line for line in lines if not _is_new_output(line)]
    if dirty:
        raise SystemExit(
            "作業ツリーに未コミットの変更があります。コミットしてから実行してください（git status --porcelain）:\n"
            + "\n".join(dirty)
        )
    return [line[3:] for line in lines if _is_new_output(line)]
