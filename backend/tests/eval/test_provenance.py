"""出所の記録（eval.provenance）と、ハーネスが汚れた作業ツリーで記録を残さないことのテスト（DB・LLM 無し）。"""

from pathlib import Path

import pytest

from eval import provenance, retrieval_compare

# printf 'hello\n' | git hash-object --stdin
_HELLO_BLOB = "ce013625030ba8dba906f756967f9e9ca394464a"


def test_git_blob_sha1_matches_git_and_normalizes_crlf():
    assert provenance.git_blob_sha1(b"hello\n") == _HELLO_BLOB
    assert provenance.git_blob_sha1(b"hello\r\n") == _HELLO_BLOB


def test_is_fingerprinted_skips_hidden_caches_logs_and_results():
    assert provenance.is_fingerprinted("eval/retrieval_compare.py")
    assert provenance.is_fingerprinted("uv.lock")
    for path in (
        ".venv/lib/site.py",
        ".env",
        ".gitignore",
        "eval/__pycache__/x.cpython-314.pyc",
        "agent/.pytest_cache/README.md",
        "logs/trace-20261013.jsonl",
        "eval/results/2026-10-13_retrieval_seed.jsonl",
    ):
        assert not provenance.is_fingerprinted(path), path


def _write(root: Path, files: dict[str, bytes]) -> None:
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _ls_tree(files: dict[str, bytes]) -> str:
    """git ls-tree -r -z の形（<mode> <type> <sha>\\t<path>\\0）。"""
    return "".join(
        f"100644 blob {provenance.git_blob_sha1(data)}\tbackend/{path}\0" for path, data in sorted(files.items())
    )


def test_source_fingerprint_matches_the_git_tree_built_by_the_same_rule(tmp_path):
    tracked = {"eval/a.py": b"x = 1\r\n", "pyproject.toml": b"[project]\n"}
    _write(tmp_path, tracked)
    _write(tmp_path, {".venv/lib.py": b"ignored", "eval/results/r.jsonl": b"{}", "eval/__pycache__/a.pyc": b"\0"})
    git = provenance.fingerprint_from_ls_tree(
        _ls_tree(tracked) + "160000 commit 0123\tbackend/vendor\0" + "100644 blob 4567\tfrontend/x.ts\0"
    )
    container = provenance.source_fingerprint(tmp_path)
    assert container == git
    assert container["files"] == 2


def test_source_fingerprint_detects_modified_and_untracked_files(tmp_path):
    tracked = {"eval/a.py": b"x = 1\n"}
    git = provenance.fingerprint_from_ls_tree(_ls_tree(tracked))
    _write(tmp_path, {"eval/a.py": b"x = 2\n"})
    assert provenance.source_fingerprint(tmp_path)["sha256"] != git["sha256"]
    _write(tmp_path, {"eval/a.py": b"x = 1\n", "eval/new.py": b""})
    assert provenance.source_fingerprint(tmp_path)["files"] == 2 != git["files"]


def test_require_clean_allows_only_new_result_files():
    assert provenance.require_clean("") == []
    assert provenance.require_clean("\n") == []
    # 前のコマンドが書いた未追跡の結果と manifest は許す
    status = "?? backend/eval/results/r_manifest.json\n?? backend/eval/results/r.jsonl\n"
    assert provenance.require_clean(status) == ["backend/eval/results/r_manifest.json", "backend/eval/results/r.jsonl"]
    for dirty in (
        " M backend/eval/retrieval_compare.py\n",
        "?? backend/eval/new.py\n",
        " M backend/eval/results/2026-10-13_retrieval_seed.jsonl\n",  # 既存の結果の書き換え
        "?? backend/eval/results/r.jsonl\n?? docs/x.md\n",
    ):
        with pytest.raises(SystemExit):
            provenance.require_clean(dirty)


def test_session_refuses_a_dirty_working_tree(tmp_path):
    manifest = tmp_path / "m.json"
    with pytest.raises(SystemExit):
        retrieval_compare.Session(manifest, "retrieve", "abc", git_status="?? backend/eval/new.py\n")
    assert not manifest.exists()


def test_session_records_provenance_and_counts_the_given_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_DB_HOST", "cn-eval-pgvector")
    monkeypatch.setenv("EVAL_DB_NAME", "coursenavigator_eval_replication")
    manifest = tmp_path / "m.json"
    session = retrieval_compare.Session(
        manifest, "generate", "abc", git_status="?? backend/eval/results/r.jsonl\n", llm_budget=50, embedding_budget=60
    )
    assert session.data["git_status_clean"] is True
    assert session.data["untracked_outputs"] == ["backend/eval/results/r.jsonl"]
    assert session.data["source_tree"] == provenance.source_fingerprint(retrieval_compare.BACKEND_ROOT)
    assert session.data["eval_db"] == {"host": "cn-eval-pgvector", "name": "coursenavigator_eval_replication"}
    assert session.data["budget"] == {"llm": 50, "embedding": 60}
    session.data.update({"llm_requests": 40, "embedding_requests": 15, "aborted": False})
    session.save()
    assert session.remaining() == (10, 45)


def test_run_commands_require_git_status_and_accept_budgets():
    parser = retrieval_compare.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["retrieve", "--out", "r.jsonl", "--git-sha", "abc"])
    args = parser.parse_args(
        ["generate", "--input", "r.jsonl", "--git-sha", "abc", "--git-status", "", "--llm-budget", "50"]
    )
    assert (args.git_status, args.llm_budget, args.embedding_budget) == (
        "",
        50,
        retrieval_compare.EMBEDDING_BUDGET_TOTAL,
    )
    summary = parser.parse_args(["summarize", "--input", "r.jsonl"])
    assert not hasattr(summary, "git_status")
