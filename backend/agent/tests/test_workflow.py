"""Workflow 通電のテスト（設計書 実験3-2 §8.3 の A4 / A5 / A6）。

A5 / A6 は層A（`course_core.graph.traversal`）を `fake_graph` に差し替えて DB 無しで回す
（CI で走る）。A4 は再現性そのものが検証対象なので実 Neo4j が要る（`-m db`）。

代役に差し替えても検証の意味が消えないのは、A5 が見るのが「trace のエッジが
courses.json の前提関係表に実在するか」「Evidence とエッジが一対一か」という
Workflow 側の性質であり、Cypher の正しさ（A2 / A3 の担当）ではないため。
"""

import asyncio
import json
from pathlib import Path

import pytest
from neo4j import AsyncGraphDatabase

import fake_graph
from agent import deps, runner
from course_core import config

_GOLDEN_RELATIVE = Path("tests") / "golden" / "questions.json"

_PREREQ_ARROW = " <-REQUIRES_PREREQUISITE- "
_TOPIC_HEAD_ARROW = " -COVERS_TOPIC-> "
_TOPIC_TAIL_ARROW = " <-COVERS_TOPIC- "

_EXPECTED_NODE_SEQUENCE = {
    "next_step": ["parse_intent", "route_by_mode", "expand_forward", "rank_candidates", "compose_answer"],
    "prereq": ["parse_intent", "route_by_mode", "expand_backward", "rank_candidates", "compose_answer"],
    "topic": ["parse_intent", "route_by_mode", "search_by_topic", "rank_candidates", "compose_answer"],
    "unclear": ["parse_intent", "route_by_mode", "respond_unclear"],
}
# A6 が出現を要求する unclear_kind（§8.3: 5種のうち4種）。
_REQUIRED_UNCLEAR_KINDS = {"no_mode", "out_of_scope", "decline", "ambiguous"}


def _load_golden() -> list[dict]:
    """golden セットは backend/tests/golden/questions.json の1箇所だけ（§5.3）。"""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _GOLDEN_RELATIVE
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"{_GOLDEN_RELATIVE} が見つかりません。")


GOLDEN = _load_golden()
SEARCH_CASES = [case for case in GOLDEN if case["mode"] != "unclear"]


def _ids(cases: list[dict]) -> list[str]:
    return [case["id"] for case in cases]


@pytest.fixture(scope="module")
def traces(tmp_path_factory) -> dict[str, object]:
    """代役の層A で golden 14問を1回ずつ流し、id → TraceRecord を返す。

    14問を毎テスト流し直すと ADK の起動分だけ無駄に遅くなるので module スコープ。
    monkeypatch は function スコープ固定なので MonkeyPatch.context() を直接使う。
    """
    directory = tmp_path_factory.mktemp("trace")
    with pytest.MonkeyPatch.context() as patch:
        fake_graph.install(patch)
        deps.set_backends(None, fake_graph.FakeDriver())
        records = {
            case["id"]: asyncio.run(
                runner.run_course_navigator(case["question"], trace_dir=directory)
            )[1]
            for case in GOLDEN
        }
        deps.set_backends(None, None)
    return records


@pytest.fixture
def neo4j_backend():
    """A4 用の実 Neo4j ドライバ。`-m db` を外すと収集されないので接続も起きない。"""
    driver = AsyncGraphDatabase.driver(
        config.NEO4J_URI,
        auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
        connection_timeout=5,
    )
    deps.set_backends(None, driver)
    yield driver
    deps.set_backends(None, None)
    asyncio.run(driver.close())


@pytest.mark.parametrize("case", SEARCH_CASES, ids=_ids(SEARCH_CASES))
def test_fake_graph_matches_golden(case: dict) -> None:
    """代役自身の正しさ: 探索結果が golden の期待候補・期待順と一致すること。

    ここが緑でないと A5 / A6 は「代役の間違いを検証している」ことになる。
    """
    finder = {
        "next_step": fake_graph.find_next_courses,
        "prereq": fake_graph.find_prerequisites,
        "topic": fake_graph.find_related_by_topic,
    }[case["mode"]]

    envelope = asyncio.run(finder(None, case["anchor_code"]))
    codes = [candidate.code for candidate in envelope.data]

    assert envelope.ok
    assert sorted(codes) == sorted(case["expected_codes"])
    assert not set(codes) & set(case["forbidden_codes"])
    if case["expected_order"] is not None:
        assert codes == case["expected_order"]


@pytest.mark.parametrize("case", GOLDEN, ids=_ids(GOLDEN))
def test_node_sequence_matches_route(case: dict, traces: dict) -> None:
    """edges が期待どおり通電した証拠（§8.2 の証拠1）。"""
    record = traces[case["id"]]

    assert record.node_sequence == _EXPECTED_NODE_SEQUENCE[case["mode"]]


def _assert_edge_is_real(edge: str) -> None:
    """traversed_edges の1本が courses.json に実在する関係かを確かめる。"""
    if _PREREQ_ARROW in edge:
        prereq, dependent = edge.split(_PREREQ_ARROW)
        assert (dependent, prereq) in fake_graph.prerequisite_pairs(), edge
        return

    head, tail = edge.split(_TOPIC_TAIL_ARROW)
    anchor, topic = head.split(_TOPIC_HEAD_ARROW)
    topics = fake_graph.topics_by_code()
    assert topic in topics[anchor], edge
    assert topic in topics[tail], edge


@pytest.mark.parametrize("case", SEARCH_CASES, ids=_ids(SEARCH_CASES))
def test_edges_and_evidence(case: dict, traces: dict) -> None:
    """A5: 辿ったエッジが実在し、根拠文とエッジが一対一で照合できること。"""
    record = traces[case["id"]]

    assert record.traversed_edges, "traversed_edges が空だと「系統図に沿った」証拠が無い"
    for edge in record.traversed_edges:
        _assert_edge_is_real(edge)

    traversed = set(record.traversed_edges)
    assert record.candidates
    for candidate in record.candidates:
        assert candidate.evidence, candidate.code
        for evidence in candidate.evidence:
            assert evidence.edge_refs, evidence.text
            assert set(evidence.edge_refs) <= traversed, evidence.text

    # 回答が探索結果に接地していること（§8.2 の証拠4）。
    assert set(record.cited_codes) <= {c.code for c in record.candidates}
    # ステップ5 時点では LLM ノードが無い（§9 ステップ5）。
    assert record.llm_calls == 0
    assert record.llm_input_tokens == 0


def test_route_coverage(traces: dict) -> None:
    """A6: 4ルートと unclear_kind 4種すべてが trace に出現すること。"""
    routes = {record.route for record in traces.values()}
    kinds = {
        record.intent.unclear_kind
        for record in traces.values()
        if record.intent.unclear_kind is not None
    }

    assert routes == {"next_step", "prereq", "topic", "unclear"}
    assert _REQUIRED_UNCLEAR_KINDS <= kinds


def test_trace_jsonl_is_appended(tmp_path: Path) -> None:
    """trace は1リクエスト1行で JSONL に追記される（§8.2）。"""
    with pytest.MonkeyPatch.context() as patch:
        fake_graph.install(patch)
        deps.set_backends(None, fake_graph.FakeDriver())
        for question in ("データサイエンス入門の次に取れる科目は?", "何かおすすめの授業ある?"):
            asyncio.run(runner.run_course_navigator(question, trace_dir=tmp_path))
        deps.set_backends(None, None)

    written = list(tmp_path.glob("trace-*.jsonl"))
    assert len(written) == 1
    lines = written[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    # §8.2 が実験の証拠と定める5フィールドが JSONL に残っていること。
    first = json.loads(lines[0])
    assert first["node_sequence"]
    assert first["traversed_edges"]
    assert first["candidates"][0]["evidence"][0]["edge_refs"]
    assert first["cited_codes"]
    assert first["llm_calls"] == 0


@pytest.mark.db
@pytest.mark.parametrize("case", GOLDEN, ids=_ids(GOLDEN))
def test_reproducibility(case: dict, neo4j_backend, tmp_path: Path) -> None:
    """A4: 同じ質問を3回実行して candidates と evidence が完全一致すること。"""
    runs = [
        asyncio.run(runner.run_course_navigator(case["question"], trace_dir=tmp_path))[1]
        for _ in range(3)
    ]

    if case["mode"] != "unclear":
        # 探索が空のまま3回一致しても再現性の検証にならないので、非空を先に見る。
        assert runs[0].candidates, "実 Neo4j にダミーデータが投入されているか確認すること"
    for record in runs[1:]:
        assert record.candidates == runs[0].candidates
        assert record.traversed_edges == runs[0].traversed_edges
