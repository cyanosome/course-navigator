"""Evidence の決定論生成（設計書 実験3-2 §4.4）。DB にも LLM にも触らない純関数。

`rank_candidates`（層B の合流ノード）の中身をここに切り出してあるので、ADK 抜きで
pytest できる。根拠文をコードが断定することで、LLM が根拠を捏造する余地が構造的に消える
（compose_answer の役割は Evidence の言い換えと接続だけに制約される）。

候補の並び順は Cypher（§4.2）が `ORDER BY ... code ASC` まで決定論的にソート済みなので、
ここでは並べ替えない。順序の正しさは層A の責務。
"""

from agent.schemas import Candidate, CandidateSet, Evidence, SearchIntent

EVIDENCE_TEMPLATES = {
    # path_arrow は常に「前提 → 後続」の向きに固定する（向きが文から一意に読める）
    "prereq_path": "{target_code} {target_title} は {anchor_code} {anchor_title} と"
    "前提関係で {hops} 段つながっています（{path_arrow}）",
    "topic_share": "{target_code} {target_title} は {anchor_code} {anchor_title} と"
    "トピック「{topics}」を共有します",
}

# traversed_edges の表記。矢印の向きが実際のリレーション方向で、
# 「A <-REQUIRES_PREREQUISITE- B」は「B が A を前提として要求する」と読む（§8.2）。
_PREREQ_EDGE = "{prereq_code} <-REQUIRES_PREREQUISITE- {dependent_code}"
# NOTE(設計書の補完): topic モードのエッジ表記は §8.2 に例が無いため、
# 共有トピック1件につき1本を次の形式で固定する。
_TOPIC_EDGE = "{anchor_code} -COVERS_TOPIC-> {topic} <-COVERS_TOPIC- {candidate_code}"

_TOPIC_SEPARATOR = "、"
_PATH_SEPARATOR = " → "

_UNCLEAR_NOTE = "mode=unclear のため候補探索を行いません。"


def _prereq_edges(mode: str, path_codes: list[str]) -> list[str]:
    """経路の隣接ペアを traversed_edges の表記に変換する（アンカーから辿った順）。

    next_step の path_codes は [アンカー → 後続]、prereq の path_codes は
    [依存側 → 前提側] で返ってくる（§4.2 の nodes(path)）。リレーションの向きは
    どちらも「前提 <- 依存側」なので、prereq のときだけ隣接ペアを入れ替える。
    """
    edges = []
    for first, second in zip(path_codes, path_codes[1:]):
        if mode == "next_step":
            edges.append(
                _PREREQ_EDGE.format(prereq_code=first, dependent_code=second)
            )
        else:
            edges.append(
                _PREREQ_EDGE.format(prereq_code=second, dependent_code=first)
            )
    return edges


def _path_arrow(mode: str, path_codes: list[str]) -> str:
    """Evidence 本文の矢印。常に「前提 → 後続」の向きに揃える。"""
    ordered = path_codes if mode == "next_step" else list(reversed(path_codes))
    return _PATH_SEPARATOR.join(ordered)


def _topic_edges(anchor_code: str, candidate: Candidate) -> list[str]:
    """共有トピックごとに1本。shared_topics はソートしてから使う。

    Cypher の collect 順序に依存させないことで、同じ質問を3回投げても
    traversed_edges が完全一致する（A4 の再現性）。
    """
    return [
        _TOPIC_EDGE.format(
            anchor_code=anchor_code, topic=topic, candidate_code=candidate.code
        )
        for topic in sorted(candidate.shared_topics)
    ]


def _build_evidence(
    intent: SearchIntent, candidate: Candidate, edges: list[str]
) -> Evidence:
    """候補1件につき Evidence を1件生成する（不変条件: 最低1件）。"""
    if intent.mode == "topic":
        text = EVIDENCE_TEMPLATES["topic_share"].format(
            target_code=candidate.code,
            target_title=candidate.title,
            anchor_code=intent.anchor_code,
            anchor_title=intent.anchor_title,
            topics=_TOPIC_SEPARATOR.join(sorted(candidate.shared_topics)),
        )
        return Evidence(kind="topic_share", text=text, edge_refs=edges)

    text = EVIDENCE_TEMPLATES["prereq_path"].format(
        target_code=candidate.code,
        target_title=candidate.title,
        anchor_code=intent.anchor_code,
        anchor_title=intent.anchor_title,
        hops=candidate.hops,
        path_arrow=_path_arrow(intent.mode, candidate.path_codes),
    )
    return Evidence(kind="prereq_path", text=text, edge_refs=edges)


def build_candidate_set(
    intent: SearchIntent, candidates: list[Candidate]
) -> CandidateSet:
    """層A の探索結果に Evidence と traversed_edges を載せて CandidateSet にする。

    不変条件（A5 で機械検証する）:
    - すべての候補が Evidence を最低1件持つ
    - 各 Evidence の edge_refs は traversed_edges の要素である（一対一で照合できる）
    """
    if intent.mode == "unclear" or intent.anchor_code is None:
        # unclear は respond_unclear へ流れるので、ここに来たら候補を作らずに通す。
        return CandidateSet(intent=intent, notes=[_UNCLEAR_NOTE])

    traversed_edges: list[str] = []
    ranked: list[Candidate] = []
    for candidate in candidates:
        if intent.mode == "topic":
            edges = _topic_edges(intent.anchor_code, candidate)
        else:
            edges = _prereq_edges(intent.mode, candidate.path_codes)
        for edge in edges:
            if edge not in traversed_edges:  # 先頭から重複排除（決定論的順序）
                traversed_edges.append(edge)
        ranked.append(
            candidate.model_copy(
                update={
                    "shared_topics": sorted(candidate.shared_topics),
                    "evidence": [_build_evidence(intent, candidate, edges)],
                }
            )
        )

    return CandidateSet(
        intent=intent, candidates=ranked, traversed_edges=traversed_edges
    )
