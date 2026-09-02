"""層A（`course_core.graph.traversal`）の DB 非依存な代役。

A5 / A6 を CI（DB 無し）で回すために、`backend/seed/courses.json` だけを読んで
§4.2 の Cypher 3本と同じ結果を決定論的に計算する。単一ソース（§5.3）を守るため
期待値をここに直書きせず、必ず courses.json から導出する。

代役自身の正しさは `test_workflow.py::test_fake_graph_matches_golden` が
golden の期待候補と突き合わせて担保する。
"""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from course_core.schemas.traversal import Candidate, Envelope

_SEED_RELATIVE = Path("seed") / "courses.json"
# §4.2 の Cypher が *1..3 をリテラルで埋めているのに合わせる。
_MAX_DEPTH = 3
_TOPIC_LIMIT = 5

_TRAVERSAL_FUNCTIONS = (
    "find_next_courses",
    "find_prerequisites",
    "find_related_by_topic",
)


def _seed_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _SEED_RELATIVE
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"{_SEED_RELATIVE} が見つかりません。")


def courses() -> list[dict[str, Any]]:
    """courses.json をコード昇順で返す。"""
    raw = json.loads(_seed_path().read_text(encoding="utf-8"))
    return sorted(raw, key=lambda course: course["code"])


def prerequisite_pairs() -> set[tuple[str, str]]:
    """(依存側, 前提側) の全ペア。A5 が traversed_edges の実在確認に使う。"""
    return {
        (course["code"], prereq)
        for course in courses()
        for prereq in course["prerequisite_codes"]
    }


def topics_by_code() -> dict[str, set[str]]:
    return {course["code"]: set(course["topics"]) for course in courses()}


def _titles() -> dict[str, str]:
    return {course["code"]: course["title"] for course in courses()}


def _adjacency(*, forward: bool) -> dict[str, list[str]]:
    """forward=True なら「依存側 → 前提側」、False なら「前提側 → 依存側」。"""
    graph: dict[str, list[str]] = defaultdict(list)
    for dependent, prereq in sorted(prerequisite_pairs()):
        if forward:
            graph[dependent].append(prereq)
        else:
            graph[prereq].append(dependent)
    return graph


def _walk(adjacency: dict[str, list[str]], start: str) -> dict[str, list[str]]:
    """start から3段まで幅優先。各到達ノードの最短経路を1本だけ残す。

    Cypher 側の `collect(...)[0]`（hops ASC で並べた先頭を採用）と同じ意味。
    段ごとに処理するので、先に到達した＝より短い経路が必ず勝つ。
    """
    shortest: dict[str, list[str]] = {}
    frontier = [[start]]
    for _ in range(_MAX_DEPTH):
        following: list[list[str]] = []
        for path in frontier:
            for neighbour in sorted(adjacency.get(path[-1], ())):
                if neighbour == start or neighbour in shortest:
                    continue
                shortest[neighbour] = [*path, neighbour]
                following.append(shortest[neighbour])
        frontier = following
    return shortest


def _path_candidates(code: str, *, forward: bool, reason: str) -> list[Candidate]:
    titles = _titles()
    return [
        Candidate(
            code=target,
            title=titles[target],
            hops=len(path) - 1,
            path_codes=path,
            reason=reason,
        )
        for target, path in _walk(_adjacency(forward=forward), code).items()
    ]


async def find_next_courses(session: Any, code: str) -> Envelope[list[Candidate]]:
    """`ORDER BY best.hops ASC, next.code ASC` 相当。"""
    found = _path_candidates(code, forward=False, reason="prerequisite_of")
    found.sort(key=lambda candidate: (candidate.hops, candidate.code))
    return Envelope(ok=True, data=found)


async def find_prerequisites(session: Any, code: str) -> Envelope[list[Candidate]]:
    """`ORDER BY best.hops DESC, p.code ASC` 相当（先に取るべき科目が先頭）。"""
    found = _path_candidates(code, forward=True, reason="requires")
    found.sort(key=lambda candidate: (-candidate.hops, candidate.code))
    return Envelope(ok=True, data=found)


async def find_related_by_topic(
    session: Any, code: str, limit: int = _TOPIC_LIMIT
) -> Envelope[list[Candidate]]:
    """`ORDER BY shared_count DESC, other.code ASC LIMIT $limit` 相当。"""
    topics = topics_by_code()
    own = topics[code]
    found = [
        Candidate(
            code=other["code"],
            title=other["title"],
            hops=1,  # トピック検索は経路を辿らないので 1 固定
            shared_topics=sorted(own & set(other["topics"])),
            reason="shares_topic",
        )
        for other in courses()
        if other["code"] != code and own & set(other["topics"])
    ]
    found.sort(key=lambda candidate: (-len(candidate.shared_topics), candidate.code))
    return Envelope(ok=True, data=found[:limit])


class _FakeSession:
    """`async with driver.session()` を成立させるだけの器。"""

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class FakeDriver:
    """deps に注入するダミードライバ。

    実際のクエリは monkeypatch した層A の代役が処理するので、セッションは使われない。
    それでも driver を注入するのは、ノードの「ドライバ未設定なら探索しない」分岐を
    本番と同じ経路で通すため。
    """

    def session(self) -> _FakeSession:
        return _FakeSession()


def install(monkeypatch: Any) -> None:
    """層A の3関数を代役に差し替える。ノードは呼び出し時に属性を引くので効く。"""
    from course_core.graph import traversal

    for name in _TRAVERSAL_FUNCTIONS:
        monkeypatch.setattr(traversal, name, globals()[name])
