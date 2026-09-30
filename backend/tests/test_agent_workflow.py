"""Agent ワークフローおよび compose_agent の構築検証テスト。

ADR-0010 に従い、CI では実 LLM や実 Neo4j を呼ばずに高速実行できるよう、
モックやビルド検証（Pure Unit Test）として実装する。
"""

from google.adk import Workflow
from google.adk.agents.llm_agent import LlmAgent

from agent.compose_agent import build_compose_agent
from agent.workflow import build_agent_workflow, build_workflow, workflow


def test_build_workflow_static():
    """静的ワークフローが正常に構築され、エッジが正しく配線されていることを検証する。"""
    wf = build_workflow()
    assert isinstance(wf, Workflow)
    assert wf.name == "course_navigator_workflow"
    assert len(wf.edges) == 6


def test_static_workflow_backward_compatibility():
    """既存の workflow エクスポートが後方互換性を保っていることを検証する。"""
    assert isinstance(workflow, Workflow)
    assert workflow.name == "course_navigator_workflow"


def test_build_compose_agent_without_mcp():
    """MCP 無効で LlmAgent が構築できることを検証する。"""
    agent = build_compose_agent(
        model="gemini-2.5-flash",
        enable_mcp=False,
    )
    assert isinstance(agent, LlmAgent)
    assert agent.name == "compose_agent"
    assert agent.model == "gemini-2.5-flash"
    assert len(agent.tools) == 0
    assert "履修アドバイザー" in agent.instruction


def test_build_compose_agent_with_mcp():
    """MCP 有効で McpToolset がツールに追加されることを検証する。"""
    agent = build_compose_agent(
        model="gemini-2.5-flash",
        enable_mcp=True,
    )
    assert isinstance(agent, LlmAgent)
    assert len(agent.tools) == 1


def test_build_agent_workflow():
    """Agent ワークフローが構築できることを検証する。"""
    agent_wf = build_agent_workflow(
        name="test_agent_workflow",
        enable_mcp=False,
    )
    assert isinstance(agent_wf, Workflow)
    assert agent_wf.name == "test_agent_workflow"
    assert len(agent_wf.edges) == 6
