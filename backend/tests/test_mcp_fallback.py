"""MCP 先行型ワークフローおよび静的フォールバックの動作検証テスト。

ADR-0010 に従い、CI では実 LLM や実 Neo4j を呼ばずに高速実行できるよう、
fake_graph と route_initial の判定ロジックを中心に検証する。
"""

import asyncio
import pytest
from google.adk import Context, Runner, Workflow
from google.adk.sessions import InMemorySessionService
from google.genai import types

import fake_graph
from agent import deps, nodes
from agent.schemas import AnswerPayload
from agent.workflow import build_mcp_first_workflow
from course_core import config


def test_build_mcp_first_workflow_structure():
    """MCP 先行型ワークフローが正常な DAG 構造として構築できることを検証する。"""
    wf = build_mcp_first_workflow(enable_mcp=False)
    assert isinstance(wf, Workflow)
    assert wf.name == "course_navigator_mcp_first_workflow"
    # エッジ数: START->route_initial(1), route_initial->mcp/static(1),
    # parse_intent->route_by_mode(1), route_by_mode->4(1), 3->rank(3), rank->compose(1) = 8
    assert len(wf.edges) == 8


def test_route_initial_fallback_when_mcp_disabled(monkeypatch):
    """AGENT_ENABLE_MCP が False の場合、static ルートが選択されることを検証する。"""
    monkeypatch.setattr(config, "AGENT_ENABLE_MCP", False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-api-key")

    event = nodes.route_initial("データサイエンス入門の次に取れる科目は?", None)
    assert event.actions.route == ["static"]


def test_route_initial_fallback_when_api_key_missing(monkeypatch):
    """GEMINI_API_KEY が未設定の場合、static ルートが選択されることを検証する。"""
    monkeypatch.setattr(config, "AGENT_ENABLE_MCP", True)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    event = nodes.route_initial("データサイエンス入門の次に取れる科目は?", None)
    assert event.actions.route == ["static"]


def test_route_initial_selects_mcp_when_available(monkeypatch):
    """MCP 有効かつ API キーがある場合、mcp ルートが選択されることを検証する。"""
    monkeypatch.setattr(config, "AGENT_ENABLE_MCP", True)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "valid-gemini-api-key")

    event = nodes.route_initial("データサイエンス入門の次に取れる科目は?", None)
    assert event.actions.route == ["mcp"]


def test_mcp_first_workflow_static_fallback_execution(monkeypatch):
    """CI 環境下で MCP 先行ワークフローが static 側にフォールバックして正常終了することを検証する。"""
    # MCP を無効化して static 側にフォールバックさせる
    monkeypatch.setattr(config, "AGENT_ENABLE_MCP", False)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    fake_graph.install(monkeypatch)
    deps.set_backends(None, fake_graph.FakeDriver())

    try:
        wf = build_mcp_first_workflow(enable_mcp=False)
        runner = Runner(
            node=wf,
            session_service=InMemorySessionService(),
            auto_create_session=True,
        )

        async def _run():
            final_payload: AnswerPayload | None = None
            async for event in runner.run_async(
                user_id="test-user",
                session_id="test-session",
                new_message=types.Content(
                    role="user",
                    parts=[types.Part(text="データサイエンス入門の次に取れる科目は?")],
                ),
            ):
                if isinstance(event.output, AnswerPayload):
                    final_payload = event.output
            return final_payload

        payload = asyncio.run(_run())
        assert payload is not None, "AnswerPayload が返されませんでした"
        assert len(payload.cited_codes) > 0
        assert "GMS-303" in payload.cited_codes  # データサイエンス入門の後続（機械学習 GMS-303）
    finally:
        deps.set_backends(None, None)
