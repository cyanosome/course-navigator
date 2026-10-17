"""検索方式比較ハーネスの DB・LLM を使わない部分のテスト。

QuerySpec・埋め込みの書式・RRF・起点の除去・WHERE 句・根拠文に加え、偽の PostgreSQL と
tests/fake_graph.py の traversal 代役で4条件を実際に動かし、クエリ数の数え方と統合の結果を確かめる。
"""

import asyncio
import json
import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

import fake_graph
from course_core.graph import traversal
from eval import retrieval_compare
from eval.corpus import CourseDoc, document_body, merge_seed_metadata
from eval.embeddings import format_document, format_query, l2_normalize, vector_literal
from eval.metrics import GoldenCase
from eval.query_spec import Constraints, build_spec, escape_lucene, parse_constraints
from eval.retrieval_metrics import RankedEntry, RetrievalRecord, score_retrieval
from eval.retrievers import (
    REGISTRY,
    QueryCounter,
    RankedItem,
    RetrievalBackends,
    constraint_clause,
    exclude_anchor,
    rrf_merge,
)

_BACKEND = Path(__file__).resolve().parents[2]
_GOLDEN = {case["id"]: GoldenCase.model_validate(case) for case in json.loads((_BACKEND / "tests" / "golden" / "questions.json").read_text("utf-8"))}
_QUESTIONS = {case_id: case.question for case_id, case in _GOLDEN.items()}


# --- QuerySpec --------------------------------------------------------------------


def test_specs_match_golden_mode_and_anchor_for_all_questions():
    for case_id, case in _GOLDEN.items():
        spec = build_spec(case_id, case.question)
        assert retrieval_compare.spec_matches_golden(spec, case), case_id
        assert spec.embedding_text == case.question


def test_spec_direction_follows_mode():
    assert build_spec("q01", _QUESTIONS["q01"]).direction == "forward"
    assert build_spec("q05", _QUESTIONS["q05"]).direction == "backward"
    assert build_spec("q08", _QUESTIONS["q08"]).direction == "topic"
    assert build_spec("q14", _QUESTIONS["q14"]).direction is None
    assert build_spec("q14", _QUESTIONS["q14"]).alternatives == ["GMS-301", "GMS-401"]


def test_parse_constraints():
    assert parse_constraints(_QUESTIONS["q12"]) == Constraints(day="金", period=3)
    assert parse_constraints("春学期の２単位の授業") == Constraints(term="春学期", credits=2)
    assert parse_constraints(_QUESTIONS["q01"]).is_empty()


def test_escape_lucene():
    assert escape_lucene("GMS-201 の後に進める?") == "GMS\\-201 の後に進める\\?"
    assert escape_lucene("a&&b||(c)") == "a\\&\\&b\\|\\|\\(c\\)"


# --- 埋め込みの書式 ------------------------------------------------------------------


def test_embedding_text_formats_follow_the_official_prefixes():
    assert format_query("機械学習") == "task: search result | query: 機械学習"
    assert format_document("機械学習", "本文") == "title: 機械学習 | text: 本文"
    assert format_document(None, "本文") == "title: none | text: 本文"


def test_document_body_includes_topics_then_syllabus():
    course = CourseDoc(id="x", code="GMS-303", title="機械学習", syllabus_text="本文。", topics=["データ分析", "数学"])
    assert document_body(course) == "トピック: データ分析、数学。本文。"
    assert document_body(course.model_copy(update={"topics": []})) == "本文。"


def test_l2_normalize_and_vector_literal():
    vector, norm = l2_normalize([3.0, 4.0])
    assert norm == 5.0
    assert vector == [0.6, 0.8]
    assert math.isclose(math.fsum(v * v for v in vector), 1.0)
    with pytest.raises(ValueError):
        l2_normalize([0.0, 0.0])
    assert vector_literal([0.5, 1]) == "[0.5,1.0]"


def test_merge_seed_metadata_rejects_mismatched_titles():
    rows = [{"id": "1", "code": "A", "title": "x", "instructor": None, "schedule": None, "credits": 2, "syllabus_text": "t"}]
    seed = [{"code": "A", "title": "x", "topics": ["T"], "prerequisite_codes": []}]
    [course] = merge_seed_metadata(rows, seed)
    assert course.topics == ["T"]
    with pytest.raises(ValueError):
        merge_seed_metadata(rows, [{"code": "A", "title": "y"}])
    with pytest.raises(ValueError):
        merge_seed_metadata(rows, [*seed, {"code": "B", "title": "z"}])


# --- 統合・後処理 -------------------------------------------------------------------


def test_rrf_merge_sums_reciprocal_ranks_and_breaks_ties_by_code():
    fused = rrf_merge([["A", "B", "C"], ["B", "D"]], k=60)
    scores = dict(fused)
    assert scores["B"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["A"] == pytest.approx(1 / 61)
    assert [code for code, _ in fused][:2] == ["B", "A"]
    assert rrf_merge([["B"], ["A"]]) == [("A", 1 / 61), ("B", 1 / 61)]
    assert rrf_merge([["A", "A"]]) == [("A", 1 / 61)]  # 同じリスト内の重複は1回だけ数える


def test_exclude_anchor():
    items = [RankedItem(code=c, title=c, score=0.0) for c in ("GMS-301", "GMS-303")]
    assert [i.code for i in exclude_anchor(items, "GMS-301")] == ["GMS-303"]
    assert len(exclude_anchor(items, None)) == 2


def test_constraint_clause():
    assert constraint_clause(Constraints(), 3) == ("", [])
    where, params = constraint_clause(Constraints(day="金", period=3, credits=2), 3)
    assert where == "WHERE s.schedule LIKE '%' || $3 || '%' AND s.credits = $4"
    assert params == ["金曜3限", 2]
    _, params = constraint_clause(Constraints(term="秋学期", day="水"), 3)
    assert params == ["秋学期", "水曜"]


def test_rotated_condition_order():
    assert retrieval_compare.rotated(0) == ["pure_vector", "vector_metadata", "pure_graph", "hybrid"]
    assert retrieval_compare.rotated(1) == ["vector_metadata", "pure_graph", "hybrid", "pure_vector"]
    assert retrieval_compare.rotated(4) == retrieval_compare.rotated(0)


def test_generation_input_carries_question_intent_and_candidates():
    spec = build_spec("q01", _QUESTIONS["q01"])
    entries = [RankedEntry(code="GMS-303", title="機械学習", score=0.5, evidence=["根拠"])]
    payload = json.loads(retrieval_compare.generation_input(spec, entries))
    assert payload["intent"] == {"mode": "next_step", "anchor_code": "GMS-301", "anchor_title": "データサイエンス入門"}
    assert payload["candidates"] == [{"rank": 1, "code": "GMS-303", "title": "機械学習", "evidence": ["根拠"]}]


def test_h0_holds_requires_graph_recall_at_ten():
    specs = [build_spec(case_id, case.question) for case_id, case in _GOLDEN.items()]
    prereqs = fake_graph.courses()
    prerequisites = {c["code"]: c["prerequisite_codes"] for c in prereqs}

    def record(case: GoldenCase, codes: list[str]) -> RetrievalRecord:
        return RetrievalRecord(
            run_id="t", condition="pure_graph", question_id=case.id, mode=case.mode,
            ranked=[RankedEntry(code=c, title=c, score=0.0) for c in codes],
            scores={str(k): score_retrieval(case, codes, prerequisites, k) for k in (5, 10)},
            started_at="t",
        )

    perfect = [record(case, case.expected_codes) for case in _GOLDEN.values() if case.is_search]
    assert retrieval_compare.h0_holds(perfect, _GOLDEN, specs)
    assert not retrieval_compare.h0_holds(perfect[:-1], _GOLDEN, specs)


# --- 偽の DB で4条件を動かす ----------------------------------------------------------


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append((query, args))
        limit = args[1]
        return self.rows[:limit]


class _FakePool:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.connection = _FakeConnection(rows)

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


class _FakeSession:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def run(self, query: str, parameters: Any = None, **kwargs: Any) -> Any:
        self.queries.append(query)
        return None

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class _FakeDriver:
    def __init__(self) -> None:
        self.sessions: list[_FakeSession] = []

    def session(self) -> _FakeSession:
        session = _FakeSession()
        self.sessions.append(session)
        return session


@pytest.fixture
def counted_traversal(monkeypatch):
    """traversal の3関数を、session.run を1回呼んでから fake_graph の結果を返す代役にする。"""
    for name in ("find_next_courses", "find_prerequisites", "find_related_by_topic"):
        fake = getattr(fake_graph, name)

        async def wrapper(session: Any, code: str, *args: Any, _fake=fake, **kwargs: Any):
            await session.run("MATCH (fake)")
            return await _fake(session, code, *args, **kwargs)

        monkeypatch.setattr(traversal, name, wrapper)


def _vector_rows(codes: list[str]) -> list[dict[str, Any]]:
    titles = {c["code"]: c["title"] for c in fake_graph.courses()}
    return [{"code": code, "title": titles[code], "score": 1.0 - i / 100} for i, code in enumerate(codes)]


def _backends(vector_codes: list[str]) -> tuple[RetrievalBackends, _FakePool, _FakeDriver]:
    pool = _FakePool(_vector_rows(vector_codes))
    driver = _FakeDriver()
    vectors = {case_id: [0.0, 1.0] for case_id in _GOLDEN}
    return RetrievalBackends(pool=pool, driver=driver, query_vectors=vectors), pool, driver


def _run(condition: str, question_id: str, backends: RetrievalBackends) -> tuple[list[RankedItem], QueryCounter]:
    spec = build_spec(question_id, _QUESTIONS[question_id])
    counter = QueryCounter()
    items = asyncio.run(REGISTRY[condition](spec, 11, backends, counter))
    return items, counter


def test_registry_has_the_four_preregistered_conditions():
    assert sorted(REGISTRY) == sorted(["pure_vector", "vector_metadata", "pure_graph", "hybrid"])


def test_pure_graph_uses_anchor_traversal_with_static_evidence(counted_traversal):
    backends, _, driver = _backends([])
    items, counter = _run("pure_graph", "q01", backends)
    assert [item.code for item in items] == ["GMS-303", "GMS-401"]
    assert counter.cypher == 1 and counter.sql == 0
    assert "前提関係で 1 段つながっています" in items[0].evidence[0]


def test_vector_conditions_count_one_sql_and_add_where_only_with_constraints(counted_traversal):
    backends, pool, _ = _backends(["GMS-301", "GMS-303", "GMS-401"])
    items, counter = _run("pure_vector", "q01", backends)
    assert [i.code for i in items] == ["GMS-301", "GMS-303", "GMS-401"]
    assert counter.sql == 1 and counter.cypher == 0
    _run("vector_metadata", "q01", backends)
    assert "WHERE" not in pool.connection.calls[-1][0]
    items, _ = _run("vector_metadata", "q12", backends)
    query, args = pool.connection.calls[-1]
    assert "WHERE" in query and args[2:] == ("金曜3限",)
    assert items[0].evidence[-1] == "条件（金曜・3限）に合致"


def test_hybrid_expands_from_vector_entries_and_fuses_by_rrf(counted_traversal):
    # 入口: 301（後続 303, 401）、401（後続なし）、203（後続 301, 303, 401）
    backends, _, _ = _backends(["GMS-301", "GMS-401", "GMS-203", "GMS-102"])
    items, counter = _run("hybrid", "q01", backends)
    assert counter.sql == 1 and counter.cypher == 3
    codes = [item.code for item in items]
    expected = [code for code, _ in rrf_merge([
        ["GMS-301", "GMS-401", "GMS-203", "GMS-102"],
        ["GMS-303", "GMS-401"],
        [],
        ["GMS-301", "GMS-303", "GMS-401"],
    ])]
    assert codes == expected
    assert codes[0] == "GMS-401"
    entry_401 = next(item for item in items if item.code == "GMS-401")
    assert any("ベクトル検索" in text for text in entry_401.evidence)
    assert any("前提関係" in text for text in entry_401.evidence)


def test_hybrid_without_direction_is_the_vector_ranking(counted_traversal):
    backends, _, _ = _backends(["GMS-301", "GMS-401"])
    items, counter = _run("hybrid", "q14", backends)
    assert [i.code for i in items] == ["GMS-301", "GMS-401"]
    assert counter.cypher == 0
