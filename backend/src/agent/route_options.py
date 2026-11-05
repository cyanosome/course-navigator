"""画面の AI の口（POST /api/assist/ask）の型と、変種の因子に合わせた振り分け（api-contract.md 4.2）。

既存の runner（run_mcp_grounded）と mcp_agent（build_grounded_mcp_agent）は書き換えず、呼ぶだけにする。
- route: mcp_grounded は run_mcp_grounded。static は関西の静的経路が入るまで未実装（UnsupportedLevelError）。
- style: standard は今と同じ文（instruction を渡さない）。brief・detailed は同じ文に追補ファイルを足して渡す。
- verify・citations: 生成は変えない（照合は常にかかる）。画面の出し方と記録のために options に残すだけ。
型を course_core でなくここに置くのは、AssistOut が runner.McpAgentRunResult を継ぐため
（course_core から agent を import すると向きが逆になる）。
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from uuid import UUID

from google.adk.agents.llm_agent import LlmAgent
from pydantic import BaseModel, Field

from agent import runner

__all__ = [
    "AssistIn",
    "AssistOptions",
    "AssistOut",
    "AssistRun",
    "UnsupportedLevelError",
    "UnverifiedItem",
    "build_agent",
    "instruction_for",
    "run_with_options",
]

_PROMPTS_DIR: Final = Path(__file__).resolve().parent / "prompts"
_STYLE_ADDENDUM_FILES: Final = {
    "brief": _PROMPTS_DIR / "style_brief.md",
    "detailed": _PROMPTS_DIR / "style_detailed.md",
}
_PROMPT_SEPARATOR: Final = "\n\n"


class AssistOptions(BaseModel):
    route: Literal["mcp_grounded", "static"] = "mcp_grounded"
    style: Literal["standard", "brief", "detailed"] = "standard"
    verify: Literal["on", "off"] = "on"
    citations: Literal["cards", "text"] = "cards"


class AssistIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)  # composeQuestion の後の文
    raw_input: str | None = Field(None, max_length=2000)  # 利用者が打った文（記録用）
    client_event_id: UUID | None = None  # 対応する chat_send の event_id
    options: AssistOptions | None = None  # 開発のときだけ効く


class UnverifiedItem(BaseModel):
    code: str
    reason: Literal["not_in_db", "lookup_failed"]


class AssistOut(runner.McpAgentRunResult):
    """既存の応答（McpAgentRunResult）の全項目に、因子の当て方と照合の結果を足したもの。"""

    request_id: str
    variant_id: str | None
    options_applied: AssistOptions
    options_ignored: bool  # 送られた options を使わなかったか（調査中・開発でないとき）
    route_requested: Literal["mcp_grounded", "static"]
    unverified_items: list[UnverifiedItem]  # verify=off のときだけ埋める


class UnsupportedLevelError(Exception):
    """この口でまだ動かせない水準（例 route=static は関西の静的経路が入るまで）。501 にする。"""


@dataclass(frozen=True)
class AssistRun:
    result: runner.McpAgentRunResult
    prompt_sha256: str | None  # 使った指示文の SHA-256（指示文が文字列でなければ None）


def _style_addendum(style: str) -> str:
    path = _STYLE_ADDENDUM_FILES[style]
    if not path.is_file():
        raise FileNotFoundError(f"文体の追補プロンプトが見つかりません: {path}")
    return path.read_text(encoding="utf-8")


def instruction_for(style: str) -> str | None:
    """style ごとの指示文。standard は None（build_grounded_mcp_agent の既定の文をそのまま使う）。"""
    if style == "standard":
        return None
    # 既定の文の組み立て（共有プロンプト＋RDB の追補）は mcp_agent の読み込み関数をそのまま使う。
    from agent.mcp_agent import _load_grounded_addendum, _load_instruction

    return _PROMPT_SEPARATOR.join(
        (_load_instruction(), _load_grounded_addendum(), _style_addendum(style))
    )


def build_agent(options: AssistOptions) -> LlmAgent:
    """options の style に合わせた grounded 版の mcp_agent。テストはここを偽モデルの LlmAgent に差し替える。"""
    # mcp_agent は mcp パッケージを読み込むので遅延 import にする（runner と同じ方針）。
    from agent.mcp_agent import build_grounded_mcp_agent

    return build_grounded_mcp_agent(instruction=instruction_for(options.style))


def _prompt_sha256(agent: LlmAgent) -> str | None:
    instruction = agent.instruction
    if not isinstance(instruction, str):
        return None
    return hashlib.sha256(instruction.encode("utf-8")).hexdigest()


async def run_with_options(question: str, options: AssistOptions) -> AssistRun:
    """options に合わせて AI を1回動かす。例外は握りつぶさない（呼ぶ側が記録してから共通ハンドラへ）。"""
    if options.route == "static":
        raise UnsupportedLevelError("route=static は未実装の水準です（関西の静的経路が入るまで使えません）。")
    agent = build_agent(options)
    result = await runner.run_mcp_grounded(question, agent=agent)
    return AssistRun(result=result, prompt_sha256=_prompt_sha256(agent))
