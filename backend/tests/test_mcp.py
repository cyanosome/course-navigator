"""Neo4j MCP サーバーの接続およびツール実行検証テスト。

ADR-0010 に従い、実 Neo4j インスタンスに依存するため `@pytest.mark.db` を付与する。
CI（GitHub Actions）では `-m 'not db'` によりスキップされる。
"""

import asyncio
import os
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from course_core import config


@pytest.mark.db
def test_neo4j_mcp_server_connection_and_tools():
    """neo4j-mcp-server を stdio で起動し、ツール一覧取得およびクエリ実行ができるかを検証する。"""

    async def _run():
        uri = config.NEO4J_URI
        user = config.NEO4J_USER
        password = config.NEO4J_PASSWORD or os.getenv("NEO4J_PASSWORD", "secure_password_please_change")

        env = os.environ.copy()
        env.update({
            "NEO4J_URI": uri,
            "NEO4J_USERNAME": user,
            "NEO4J_USER": user,
            "NEO4J_PASSWORD": password,
            "NEO4J_READ_ONLY": "true",
            "NEO4J_TELEMETRY": "false",
        })

        server_params = StdioServerParameters(
            command="uv",
            args=["run", "neo4j-mcp-server"],
            env=env,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                init_result = await session.initialize()
                assert init_result is not None

                # 1. ツール一覧の取得
                tool_list = await session.list_tools()
                tools = tool_list.tools
                assert len(tools) > 0, "MCPサーバーからツールが取得できませんでした"

                tool_names = [t.name for t in tools]
                schema_tools = [n for n in tool_names if "schema" in n.lower()]
                cypher_tools = [n for n in tool_names if "cypher" in n.lower() or "query" in n.lower() or "read" in n.lower()]

                assert len(schema_tools) > 0, f"スキーマ取得ツールが見つかりません: {tool_names}"
                assert len(cypher_tools) > 0, f"Cypher実行ツールが見つかりません: {tool_names}"

                # 2. Cypher 読み取りツールの実行テスト (RETURN 1 AS num)
                cypher_tool_name = cypher_tools[0]
                tool_def = next(t for t in tools if t.name == cypher_tool_name)
                properties = tool_def.inputSchema.get("properties", {})
                param_name = "query" if "query" in properties else "cypher" if "cypher" in properties else list(properties.keys())[0]

                result = await session.call_tool(cypher_tool_name, arguments={param_name: "RETURN 1 AS num"})
                assert result is not None
                assert not result.isError, f"Cypher実行でエラーが発生しました: {result}"

                content_texts = [c.text for c in result.content if hasattr(c, "text")]
                combined_text = " ".join(content_texts)
                assert "1" in combined_text, f"クエリ実行結果に '1' が含まれていません: {combined_text}"

    asyncio.run(_run())


@pytest.mark.db
def test_neo4j_mcp_get_schema():
    """neo4j-mcp-server からグラフスキーマが取得できるかを検証する。"""

    async def _run():
        uri = config.NEO4J_URI
        user = config.NEO4J_USER
        password = config.NEO4J_PASSWORD or os.getenv("NEO4J_PASSWORD", "secure_password_please_change")

        env = os.environ.copy()
        env.update({
            "NEO4J_URI": uri,
            "NEO4J_USERNAME": user,
            "NEO4J_USER": user,
            "NEO4J_PASSWORD": password,
            "NEO4J_READ_ONLY": "true",
            "NEO4J_TELEMETRY": "false",
        })

        server_params = StdioServerParameters(
            command="uv",
            args=["run", "neo4j-mcp-server"],
            env=env,
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tool_list = await session.list_tools()
                tools = tool_list.tools
                schema_tools = [t for t in tools if "schema" in t.name.lower()]
                assert len(schema_tools) > 0

                schema_tool = schema_tools[0]
                result = await session.call_tool(schema_tool.name, arguments={})
                assert not result.isError, f"スキーマ取得でエラーが発生しました: {result}"
                content_texts = [c.text for c in result.content if hasattr(c, "text")]
                combined_text = " ".join(content_texts)
                assert len(combined_text) > 0, "スキーマ情報が空です"

    asyncio.run(_run())
