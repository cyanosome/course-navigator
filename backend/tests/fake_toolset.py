"""McpToolset の代役（tests/fake_graph.py と同じく tests の下の部品）。

get_tools() / close() の呼び出し回数を数える。既定ではダミーツールを1件返し、error を渡すと
get_tools() がそれを送出する（MCP サーバーの起動失敗・接続タイムアウトの代役）。
"""

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.function_tool import FunctionTool


def _noop_tool() -> dict[str, str]:
    """ツールセットの代役が返すダミーツール（偽モデルは呼ばない）。"""
    return {}


class RecordingToolset(BaseToolset):
    def __init__(self, tools: list[BaseTool] | None = None, error: Exception | None = None) -> None:
        super().__init__()
        self._tools = tools if tools is not None else [FunctionTool(func=_noop_tool)]
        self._error = error
        self.get_tools_calls = 0
        self.close_calls = 0

    async def get_tools(self, readonly_context: ReadonlyContext | None = None) -> list[BaseTool]:
        self.get_tools_calls += 1
        if self._error is not None:
            raise self._error
        return list(self._tools)

    async def close(self) -> None:
        self.close_calls += 1
