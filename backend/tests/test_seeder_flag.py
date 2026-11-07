"""起動時シード自動投入の旗 `AUTO_SEED_DATA` のテスト（ADR-0013）。

ADR-0010 に従い実 DB には接続しない。PostgreSQL は `acquire()` / `fetchrow()` / `execute()` /
`transaction()` だけを持つ偽プール、Neo4j は `session().run()` だけを持つ偽ドライバで代役させ、
seeder が投げた SQL / Cypher を記録して「入ったか・入らなかったか」を見る。
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from course_core import seeder

_ENV = "AUTO_SEED_DATA"
_SEED_CODES = [course["code"].strip() for course in seeder.load_seed_courses()]


# --- PostgreSQL の代役 ---------------------------------------------------------


class _FakeConnection:
    def __init__(self, pg_count: int) -> None:
        self._pg_count = pg_count
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "COUNT(*)" in query:
            return {"count": self._pg_count}
        return None  # get_syllabus_id_by_code: 既存の行は無い扱い

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        return "OK"

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None, None]:
        yield

    def inserted_codes(self) -> list[str]:
        # insert_syllabus の引数は (id, code, title, ...) の順
        return [args[1] for query, args in self.executed if query.startswith("INSERT")]


class _FakePool:
    def __init__(self, pg_count: int) -> None:
        self.connection = _FakeConnection(pg_count)
        self.acquire_calls = 0

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[_FakeConnection, None]:
        self.acquire_calls += 1
        yield self.connection


# --- Neo4j の代役 --------------------------------------------------------------


class _FakeResult:
    def __init__(self, neo4j_count: int) -> None:
        self._neo4j_count = neo4j_count

    async def single(self) -> dict[str, Any]:
        return {"count": self._neo4j_count}

    async def consume(self) -> None:
        return None


class _FakeSession:
    def __init__(self, driver: "_FakeDriver") -> None:
        self._driver = driver

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def run(self, query: str, **params: Any) -> _FakeResult:
        self._driver.runs.append((query, params))
        return _FakeResult(self._driver.neo4j_count)


class _FakeDriver:
    def __init__(self, neo4j_count: int) -> None:
        self.neo4j_count = neo4j_count
        self.runs: list[tuple[str, dict[str, Any]]] = []
        self.session_calls = 0

    def session(self) -> _FakeSession:
        self.session_calls += 1
        return _FakeSession(self)

    def merged_codes(self) -> list[str]:
        # merge_main_course だけが code を引数に渡す
        return [params["code"] for _, params in self.runs if "code" in params]


def _run(pool: _FakePool, driver: _FakeDriver, *, force: bool = False) -> None:
    asyncio.run(seeder.seed_initial_data_if_empty(pool, driver, force=force))


# --- テスト --------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "false", "0", "no"])
def test_auto_seed_is_off_unless_opted_in(monkeypatch, value: str | None) -> None:
    """未設定（既定）や true 以外では、空の DB でも何も入れず、DB に触れもしない。"""
    if value is None:
        monkeypatch.delenv(_ENV, raising=False)
    else:
        monkeypatch.setenv(_ENV, value)
    pool, driver = _FakePool(pg_count=0), _FakeDriver(neo4j_count=0)

    _run(pool, driver)

    assert pool.acquire_calls == 0
    assert pool.connection.executed == []
    assert driver.session_calls == 0


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes"])
def test_auto_seed_on_fills_empty_db_as_before(monkeypatch, value: str) -> None:
    """`AUTO_SEED_DATA=true` なら従来どおり、空の DB に seed の20科目を両方の DB へ入れる。"""
    monkeypatch.setenv(_ENV, value)
    pool, driver = _FakePool(pg_count=0), _FakeDriver(neo4j_count=0)

    _run(pool, driver)

    assert len(_SEED_CODES) == 20
    assert pool.connection.inserted_codes() == _SEED_CODES
    assert driver.merged_codes() == _SEED_CODES


def test_auto_seed_on_skips_when_db_has_data(monkeypatch) -> None:
    """`AUTO_SEED_DATA=true` でも、両方の DB に科目があれば従来どおり投入しない。"""
    monkeypatch.setenv(_ENV, "true")
    pool, driver = _FakePool(pg_count=5), _FakeDriver(neo4j_count=5)

    _run(pool, driver)

    assert pool.connection.executed == []
    assert driver.merged_codes() == []


def test_force_seeds_without_flag(monkeypatch) -> None:
    """手動 CLI（force=True）は旗を見ずに投入する（ADR-0013 で残す経路）。"""
    monkeypatch.delenv(_ENV, raising=False)
    pool, driver = _FakePool(pg_count=5), _FakeDriver(neo4j_count=5)

    _run(pool, driver, force=True)

    assert pool.connection.inserted_codes() == _SEED_CODES
    assert driver.merged_codes() == _SEED_CODES
