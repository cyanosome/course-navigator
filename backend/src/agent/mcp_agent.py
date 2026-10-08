"""MCP 先行型 Agent（LlmAgent + Neo4j MCP ツール）の定義モジュール。

ADR-0011 に基づき、Google ADK の LlmAgent を構築し、
neo4j-mcp-server を Stdio ツールとして常備して自律的な動的グラフ探索と回答生成を一貫して担う。
"""

import os
from pathlib import Path
from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import (
    McpToolset,
    StdioConnectionParams,
    StdioServerParameters,
)

from agent.rdb_tools import get_course_details
from agent.schemas import AnswerPayload
from course_core import config

__all__ = ["build_grounded_mcp_agent", "build_mcp_agent"]


def _load_instruction() -> str:
    """プロンプトファイルを読み込む。"""
    path = Path(config.AGENT_INSTRUCTION_PATH)
    if path.is_file():
        return path.read_text(encoding="utf-8")

    # モジュールからの相対パスを試行
    base_dir = Path(__file__).resolve().parent
    candidate = base_dir / "prompts" / "compose_answer.md"
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8")

    # backend ルート基準を試行
    for parent in Path(__file__).resolve().parents:
        cand = parent / config.AGENT_INSTRUCTION_PATH
        if cand.is_file():
            return cand.read_text(encoding="utf-8")

    raise FileNotFoundError(
        f"プロンプトファイルが見つかりません: {config.AGENT_INSTRUCTION_PATH}"
    )


def build_mcp_agent(
    model: str | None = None,
    instruction: str | None = None,
    enable_mcp: bool | None = None,
    extra_tools: list[Any] | None = None,
) -> LlmAgent:
    """MCP 先行型エージェント (LlmAgent) を構築する。

    Args:
        model: 使用する LLM モデル名。未指定時は config.AGENT_MODEL。
        instruction: システムプロンプト。未指定時はプロンプトファイルから読み込み。
        enable_mcp: Neo4j MCP ツールを付与するか。未指定時は config.AGENT_ENABLE_MCP。
        extra_tools: MCP ツールに追加で持たせるツール。未指定時は追加しない。
    """
    active_model = model or config.AGENT_MODEL
    active_instruction = instruction or _load_instruction()
    active_enable_mcp = (
        enable_mcp if enable_mcp is not None else config.AGENT_ENABLE_MCP
    )

    tools: list[Any] = []
    if active_enable_mcp:
        # ADR-0011 に従い、stdio 経由で neo4j-mcp-server を起動する
        env = os.environ.copy()
        env.update({
            "NEO4J_URI": config.NEO4J_URI,
            "NEO4J_USERNAME": config.NEO4J_USER,
            "NEO4J_USER": config.NEO4J_USER,
            "NEO4J_PASSWORD": config.NEO4J_PASSWORD or "secure_password_please_change",
            "NEO4J_READ_ONLY": "true",
            "NEO4J_TELEMETRY": "false",
        })
        server_params = StdioServerParameters(
            command="uv",
            args=["run", "neo4j-mcp-server"],
            env=env,
        )
        connection_params = StdioConnectionParams(server_params=server_params)
        tools.append(McpToolset(connection_params=connection_params))
    if extra_tools:
        tools.extend(extra_tools)

    # GEMINI_API_KEY が config にあれば環境変数へ伝播（Google GenAI SDK 連携用）
    if config.GEMINI_API_KEY and not os.environ.get("GEMINI_API_KEY"):
        os.environ["GEMINI_API_KEY"] = config.GEMINI_API_KEY

    return LlmAgent(
        name="mcp_agent",
        model=active_model,
        instruction=active_instruction,
        tools=tools,
        output_schema=AnswerPayload,
    )


def build_grounded_mcp_agent(**agent_kwargs: Any) -> LlmAgent:
    """test3-2 用の mcp_agent。Neo4j MCP に加えて RDB ツール get_course_details を持つ。

    adk web（agent.py）の root_agent が使う build_mcp_agent() の既定構成は変えない。
    """
    return build_mcp_agent(extra_tools=[get_course_details], **agent_kwargs)
