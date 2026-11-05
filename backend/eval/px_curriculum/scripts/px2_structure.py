"""PX-2: グループ DAG と科目に展開した DAG の構造の記述（LLM 不要）。

指標（Heileman et al. 2018, arXiv:1811.09676 の式番号）:
  blocking factor  b(v) = Σ_{u∈V} I(v ⇝ u)              (7)(8)  v 自身は数えない（長さ1以上の路）
  curriculum b(G) = Σ_v b(v)                             (9)
  delay factor     d(v) = v を通る最長路の頂点数          (5)    孤立点は 1
  curriculum d(G) = Σ_v d(v)                             (6)
  structural complexity h(G) = d(G) + b(G) = Σ_v (d(v)+b(v))   (14)
そのほか: ノード数・エッジ数・推移簡約後のエッジ数・最長路（辺数と頂点数）・幅（最大反鎖。Dilworth の定理で
n − 推移閉包の二部グラフの最大マッチング、厳密解）・比較可能な順序対の割合（順序が付く非順序対 / C(n,2)）。
"""
import sys
import json
from itertools import combinations
from pathlib import Path

import networkx as nx

PX = Path(__file__).resolve().parent.parent
DATASET = PX / "dataset"
OUT = PX / "px2_metrics.json"


def width_exact(g: nx.DiGraph) -> tuple[int, list[str]]:
    """最大反鎖の大きさと、その一例（König の定理で最小頂点被覆から作る）。"""
    tc = nx.transitive_closure_dag(g)
    b = nx.DiGraph()
    left = [("L", v) for v in g]
    right = [("R", v) for v in g]
    bg = nx.Graph()
    bg.add_nodes_from(left, bipartite=0)
    bg.add_nodes_from(right, bipartite=1)
    for u, v in tc.edges():
        bg.add_edge(("L", u), ("R", v))
    matching = nx.bipartite.hopcroft_karp_matching(bg, top_nodes=left)
    m = sum(1 for k in matching if k[0] == "L")
    cover = nx.bipartite.to_vertex_cover(bg, matching, top_nodes=left)
    antichain = [v for v in g if ("L", v) not in cover and ("R", v) not in cover]
    w = g.number_of_nodes() - m
    assert len(antichain) == w, (len(antichain), w)
    for x, y in combinations(antichain, 2):
        assert not tc.has_edge(x, y) and not tc.has_edge(y, x)
    return w, sorted(antichain)


def describe(g: nx.DiGraph, name: str) -> dict:
    assert nx.is_directed_acyclic_graph(g)
    n = g.number_of_nodes()
    tc = nx.transitive_closure_dag(g)
    tr = nx.transitive_reduction(g)
    order = list(nx.topological_sort(g))
    # 頂点数で数えた最長路: v で終わる最長 / v から始まる最長
    end_len = {}
    for v in order:
        end_len[v] = 1 + max((end_len[u] for u in g.predecessors(v)), default=0)
    start_len = {}
    for v in reversed(order):
        start_len[v] = 1 + max((start_len[w] for w in g.successors(v)), default=0)
    delay = {v: end_len[v] + start_len[v] - 1 for v in g}
    blocking = {v: len(nx.descendants(g, v)) for v in g}
    longest_vertices = max(delay.values()) if n else 0
    comparable = sum(1 for x, y in combinations(g.nodes, 2) if tc.has_edge(x, y) or tc.has_edge(y, x))
    total_pairs = n * (n - 1) // 2
    w, antichain = width_exact(g)
    longest_path = nx.dag_longest_path(g)
    return {
        "graph": name,
        "n_nodes": n,
        "n_edges": g.number_of_edges(),
        "n_edges_transitive_reduction": tr.number_of_edges(),
        "n_edges_transitive_closure": tc.number_of_edges(),
        "longest_path_edges": longest_vertices - 1,
        "longest_path_vertices": longest_vertices,
        "longest_path_example": longest_path,
        "width_max_antichain": w,
        "width_method": "exact (Dilworth: n - maximum bipartite matching on transitive closure)",
        "max_antichain_example": antichain,
        "comparable_pairs": comparable,
        "total_pairs": total_pairs,
        "comparable_ratio": comparable / total_pairs if total_pairs else None,
        "blocking_total_bG": sum(blocking.values()),
        "delay_total_dG": sum(delay.values()),
        "structural_complexity_hG": sum(blocking.values()) + sum(delay.values()),
        "blocking_max": max(blocking.values()),
        "delay_max": max(delay.values()),
        "per_node": {v: {"blocking": blocking[v], "delay": delay[v], "complexity": blocking[v] + delay[v]} for v in g},
        "n_sources": sum(1 for v in g if g.in_degree(v) == 0),
        "n_sinks": sum(1 for v in g if g.out_degree(v) == 0),
        "n_isolated": sum(1 for v in g if g.degree(v) == 0),
        "n_weak_components": nx.number_weakly_connected_components(g),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    gd = json.loads((DATASET / "group_dag.json").read_text(encoding="utf-8"))
    courses = json.loads((DATASET / "courses.json").read_text(encoding="utf-8"))

    g_all = nx.DiGraph()
    g_all.add_nodes_from(n["group_id"] for n in gd["nodes"])
    g_all.add_edges_from((e["source"], e["target"]) for e in gd["edges"])
    dp = {n["group_id"] for n in gd["nodes"] if n["is_dp"]}
    g_nodp = g_all.subgraph([v for v in g_all if v not in dp]).copy()

    members: dict[str, list[str]] = {}
    for c in courses:
        members.setdefault(c["group_id"], []).append(c["course_id"])

    def expand(group_graph: nx.DiGraph, keep) -> nx.DiGraph:
        cg = nx.DiGraph()
        for c in courses:
            if keep(c):
                cg.add_node(c["course_id"])
        for a, b in group_graph.edges():
            for x in members.get(a, []):
                for y in members.get(b, []):
                    if x in cg and y in cg:
                        cg.add_edge(x, y)
        return cg

    c_all = expand(g_nodp, lambda c: True)
    c_syl = expand(g_nodp, lambda c: c["has_syllabus"])

    res = {
        "source_dataset": str(DATASET),
        "definitions": {
            "blocking_factor": "b(v) = number of vertices reachable from v by a directed path of length >= 1 (Heileman et al. 2018 Eq.7-8); b(G) = sum_v b(v) (Eq.9)",
            "delay_factor": "d(v) = number of vertices on the longest path through v (Eq.5); d(G) = sum_v d(v) (Eq.6)",
            "structural_complexity": "h(G) = d(G) + b(G) = sum_v (d(v) + b(v)) (Eq.14)",
            "comparable_ratio": "#unordered pairs {u,v} with u~>v or v~>u / C(n,2)",
            "width": "maximum antichain size, exact via Dilworth",
            "course_expansion": "course x -> course y iff group(x) -> group(y) is an edge of the group DAG without DP nodes; courses in the same group are not connected",
        },
        "group_dag_with_dp": describe(g_all, "group DAG (21 nodes incl. DP1-3)"),
        "group_dag_no_dp": describe(g_nodp, "group DAG without DP (18 course groups)"),
        "course_dag_70": describe(c_all, "course DAG, all 70 tree subjects"),
        "course_dag_67_with_syllabus": describe(c_syl, "course DAG, 67 subjects with 2026 syllabus (PX-1 pool)"),
    }
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k in ["group_dag_with_dp", "group_dag_no_dp", "course_dag_70", "course_dag_67_with_syllabus"]:
        r = res[k]
        print(k, {x: r[x] for x in ["n_nodes", "n_edges", "n_edges_transitive_reduction", "longest_path_edges",
                                     "longest_path_vertices", "width_max_antichain", "comparable_pairs", "total_pairs",
                                     "comparable_ratio", "blocking_total_bG", "delay_total_dG", "structural_complexity_hG",
                                     "blocking_max", "delay_max", "n_sources", "n_sinks", "n_isolated", "n_weak_components"]})
        print("   longest:", r["longest_path_example"])
        print("   antichain:", r["max_antichain_example"])


if __name__ == "__main__":
    main()
