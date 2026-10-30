"""Workflow のグラフ定義（設計書 実験3-2 §2.2）。

分岐4本・合流1点・終端2箇所という構造そのものが実験3-2 の検証対象なので、
ノードの中身が関数であっても edges からノードを外さない（§10）。
"""

from typing import Any
from google.adk import Workflow
from google.adk.agents.llm_agent import LlmAgent

from agent import nodes

__all__ = [
    "WORKFLOW_NAME",
    "build_agent_workflow",
    "build_mcp_first_workflow",
    "build_mcp_grounded_workflow",
    "build_workflow",
    "workflow",
]

WORKFLOW_NAME = "course_navigator_workflow"


def build_workflow(
    name: str = WORKFLOW_NAME,
    compose_node: Any = nodes.compose_answer,
) -> Workflow:
    """共通の DAG 構造を構築するファクトリ関数。

    edges の先頭には文字列 "START" が必須。
    終端の compose_node には、静的ノード（nodes.compose_answer）または
    LlmAgent ノードを渡すことができる。
    """
    return Workflow(
        name=name,
        edges=[
            ("START", nodes.parse_intent, nodes.route_by_mode),
            (
                nodes.route_by_mode,
                {
                    "next_step": nodes.expand_forward,
                    "prereq": nodes.expand_backward,
                    "topic": nodes.search_by_topic,
                    "unclear": nodes.respond_unclear,
                },
            ),
            # 3経路 → 合流ノード rank_candidates
            (nodes.expand_forward, nodes.rank_candidates),
            (nodes.expand_backward, nodes.rank_candidates),
            (nodes.search_by_topic, nodes.rank_candidates),
            # 合流ノード → 回答生成（静的ノード or Agent ノード）
            (nodes.rank_candidates, compose_node),
        ],
    )


# 静的ワークフロー（CI / test3-1 用の後方互換エクスポート）
workflow = build_workflow()


def build_agent_workflow(
    name: str = "course_navigator_agent_workflow",
    **agent_kwargs: Any,
) -> Workflow:
    """回答生成に LlmAgent (Neo4j MCP ツール装備) を配置した Agent ワークフローを構築する。"""
    from agent.compose_agent import build_compose_agent

    agent_node = build_compose_agent(**agent_kwargs)
    return build_workflow(name=name, compose_node=agent_node)


def build_mcp_first_workflow(
    name: str = "course_navigator_mcp_first_workflow",
    **agent_kwargs: Any,
) -> Workflow:
    """MCP 先行型ワークフロー（ルート完全分離型）を構築する。

    START ➔ route_initial
    route_initial:
        "mcp": mcp_agent (Neo4j MCP ツール装備、自律探索・回答生成)
        "static": parse_intent ➔ route_by_mode ➔ 3経路 ➔ rank_candidates ➔ compose_answer
    """
    from agent.mcp_agent import build_mcp_agent

    mcp_agent_node = build_mcp_agent(**agent_kwargs)

    return Workflow(
        name=name,
        edges=[
            ("START", nodes.route_initial),
            (
                nodes.route_initial,
                {
                    "mcp": mcp_agent_node,
                    "static": nodes.parse_intent,
                },
            ),
            (nodes.parse_intent, nodes.route_by_mode),
            (
                nodes.route_by_mode,
                {
                    "next_step": nodes.expand_forward,
                    "prereq": nodes.expand_backward,
                    "topic": nodes.search_by_topic,
                    "unclear": nodes.respond_unclear,
                },
            ),
            (nodes.expand_forward, nodes.rank_candidates),
            (nodes.expand_backward, nodes.rank_candidates),
            (nodes.search_by_topic, nodes.rank_candidates),
            (nodes.rank_candidates, nodes.compose_answer),
        ],
    )


def build_mcp_grounded_workflow(
    name: str = "course_navigator_mcp_grounded_workflow",
    agent_node: LlmAgent | None = None,
    **agent_kwargs: Any,
) -> Workflow:
    """MCP 先行型 + 出典付与のワークフロー（test3-2）を構築する。

    START ➔ route_initial
    route_initial:
        "mcp": mcp_agent (Neo4j MCP + get_course_details) ➔ attach_sources
        "static": parse_intent ➔ route_by_mode ➔ 3経路 ➔ rank_candidates ➔ compose_answer

    attach_sources は LLM の cited_codes を PostgreSQL で引き直して出典を作る決定論ノード。
    static 側は build_mcp_first_workflow と同じ静的 DAG。
    agent_node はテストで偽モデルの LlmAgent を差し込む口（未指定なら build_grounded_mcp_agent）。
    """
    from agent.mcp_agent import build_grounded_mcp_agent

    mcp_agent_node = (
        agent_node if agent_node is not None else build_grounded_mcp_agent(**agent_kwargs)
    )

    return Workflow(
        name=name,
        edges=[
            ("START", nodes.route_initial),
            (
                nodes.route_initial,
                {
                    "mcp": mcp_agent_node,
                    "static": nodes.parse_intent,
                },
            ),
            # mcp ルート: LLM の回答 → DB 由来の出典付与
            (mcp_agent_node, nodes.attach_sources),
            # static ルート（build_mcp_first_workflow と同じ）
            (nodes.parse_intent, nodes.route_by_mode),
            (
                nodes.route_by_mode,
                {
                    "next_step": nodes.expand_forward,
                    "prereq": nodes.expand_backward,
                    "topic": nodes.search_by_topic,
                    "unclear": nodes.respond_unclear,
                },
            ),
            (nodes.expand_forward, nodes.rank_candidates),
            (nodes.expand_backward, nodes.rank_candidates),
            (nodes.search_by_topic, nodes.rank_candidates),
            (nodes.rank_candidates, nodes.compose_answer),
        ],
    )
