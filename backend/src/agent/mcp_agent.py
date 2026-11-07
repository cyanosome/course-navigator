"""MCP 先行型 Agent（LlmAgent + Neo4j MCP ツール）の定義モジュール。

ADR-0011 に基づき、Google ADK の LlmAgent を構築し、
neo4j-mcp-server を Stdio ツールとして常備して自律的な動的グラフ探索と回答生成を一貫して担う。
"""

import logging
import os
import time
from pathlib import Path
from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import (
    McpToolset,
    StdioConnectionParams,
    StdioServerParameters,
)
from pydantic import BaseModel

from agent import courses_tools
from agent.rdb_tools import get_course_details
from agent.schemas import AnswerPayload, PlanAnswerPayload
from course_core import config

__all__ = [
    "build_grounded_mcp_agent",
    "build_kansai_mcp_agent",
    "build_mcp_agent",
    "build_neo4j_toolset",
    "load_kansai_instruction",
    "open_shared_mcp_toolset",
]

logger = logging.getLogger(__name__)

# RDB ツールを持つ grounded 版だけに連結する追補プロンプト。共有プロンプト（compose_answer.md）に
# 書くと、ツールを持たない adk web の mcp_agent / compose_agent が未宣言ツールを呼んで落ちうる。
_GROUNDED_ADDENDUM_PATH = Path(__file__).resolve().parent / "prompts" / "grounded_addendum.md"
# 関西のデータ（Course{syllabus_id}・CourseGroup・courses）向けの指示文（A1 用）。シードの形の
# compose_answer.md・grounded_addendum.md は /test/agent/mcp と adk web がそのまま使う。
_KANSAI_INSTRUCTION_PATH = Path(__file__).resolve().parent / "prompts" / "kansai_answer.md"
_PROMPT_SEPARATOR = "\n\n"
# MCP セッション確立の待ち時間（秒）。`uv run neo4j-mcp-server` は起動に約6秒かかり、
# ADK 既定の 5.0 秒では接続前にタイムアウトしてツール無しで実行されてしまう。
_MCP_SESSION_TIMEOUT_SECONDS = 30.0


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


def build_neo4j_toolset() -> McpToolset:
    """neo4j-mcp-server を stdio で起動する McpToolset を作る（ADR-0011）。

    作るだけで接続はしない（最初の get_tools() でサブプロセスが起動する）。
    """
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
    connection_params = StdioConnectionParams(
        server_params=server_params, timeout=_MCP_SESSION_TIMEOUT_SECONDS
    )
    return McpToolset(connection_params=connection_params)


def build_mcp_agent(
    model: str | None = None,
    instruction: str | None = None,
    enable_mcp: bool | None = None,
    extra_tools: list[Any] | None = None,
    toolset: McpToolset | None = None,
    output_schema: type[BaseModel] = AnswerPayload,
) -> LlmAgent:
    """MCP 先行型エージェント (LlmAgent) を構築する。

    Args:
        model: 使用する LLM モデル名。未指定時は config.AGENT_MODEL。
        instruction: システムプロンプト。未指定時はプロンプトファイルから読み込み。
        enable_mcp: Neo4j MCP ツールを付与するか。未指定時は config.AGENT_ENABLE_MCP。
        extra_tools: MCP ツールに追加で持たせるツール。未指定時は追加しない。
        toolset: 使い回す Neo4j の McpToolset。未指定時は新しく作る（enable_mcp が偽なら使わない）。
        output_schema: 最終回答の形。未指定時は AnswerPayload。
    """
    active_model = model or config.AGENT_MODEL
    active_instruction = instruction or _load_instruction()
    active_enable_mcp = (
        enable_mcp if enable_mcp is not None else config.AGENT_ENABLE_MCP
    )

    tools: list[Any] = []
    if active_enable_mcp:
        # ADR-0011 に従い、stdio 経由で neo4j-mcp-server を起動する
        tools.append(toolset if toolset is not None else build_neo4j_toolset())
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
        output_schema=output_schema,
    )


def _load_grounded_addendum() -> str:
    if not _GROUNDED_ADDENDUM_PATH.is_file():
        raise FileNotFoundError(f"追補プロンプトが見つかりません: {_GROUNDED_ADDENDUM_PATH}")
    return _GROUNDED_ADDENDUM_PATH.read_text(encoding="utf-8")


def build_grounded_mcp_agent(
    instruction: str | None = None, **agent_kwargs: Any
) -> LlmAgent:
    """test3-2 用の mcp_agent。Neo4j MCP に加えて RDB ツール get_course_details を持つ。

    instruction 未指定時は共有プロンプトに RDB 手順の追補（grounded_addendum.md）を連結する。
    adk web（agent.py）の root_agent が使う build_mcp_agent() の既定構成は変えない。
    """
    active_instruction = (
        instruction
        if instruction is not None
        else _load_instruction() + _PROMPT_SEPARATOR + _load_grounded_addendum()
    )
    return build_mcp_agent(
        instruction=active_instruction,
        extra_tools=[get_course_details],
        **agent_kwargs,
    )


def load_kansai_instruction() -> str:
    if not _KANSAI_INSTRUCTION_PATH.is_file():
        raise FileNotFoundError(f"関西の指示文が見つかりません: {_KANSAI_INSTRUCTION_PATH}")
    return _KANSAI_INSTRUCTION_PATH.read_text(encoding="utf-8")


def build_kansai_mcp_agent(
    instruction: str | None = None,
    toolset: McpToolset | None = None,
    **agent_kwargs: Any,
) -> LlmAgent:
    """A1（POST /api/assist/ask）用の mcp_agent。関西の Neo4j（MCP）と courses を読む get_course_details を持つ。

    instruction 未指定時は kansai_answer.md。最終回答は PlanAnswerPayload（今のプランが渡されたら
    足す・外すの提案も入る）。toolset を渡せばそれを使い（lifespan で作った使い回しの1つ）、無ければ1問ごとに作る。
    """
    return build_mcp_agent(
        instruction=instruction if instruction is not None else load_kansai_instruction(),
        extra_tools=[courses_tools.get_course_details],
        toolset=toolset,
        output_schema=PlanAnswerPayload,
        **agent_kwargs,
    )


async def open_shared_mcp_toolset() -> McpToolset:
    """lifespan で1回だけ作る、A1 で使い回す McpToolset。起動に約6秒かかるので先に繋いでおく。

    繋げなくても起動は止めない（警告を残す）。リクエストごとの事前確認（runner._preflight_toolsets）が
    繋ぎ直しを試み、それでも駄目なら静的経路に倒して理由を notes に残す。
    """
    toolset = build_neo4j_toolset()
    started = time.perf_counter()
    try:
        tools = await toolset.get_tools()
    except Exception as exc:  # 起動は続ける。理由はログに残し、各リクエストの事前確認に任せる
        logger.warning(
            "MCP ツールセットに起動時に繋げませんでした（リクエストのときに繋ぎ直します）: %s: %s",
            type(exc).__name__,
            exc,
        )
        return toolset
    logger.info(
        "MCP ツールセットに繋ぎました（%.1f 秒、ツール %s）",
        time.perf_counter() - started,
        [tool.name for tool in tools],
    )
    return toolset
