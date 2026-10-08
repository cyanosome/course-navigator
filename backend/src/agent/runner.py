"""ADK の実行 API に触れる唯一のファイル（設計書 実験3-2 §7.2）。

FastAPI ルーター・pytest・CLI はすべて `run_course_navigator` だけを呼ぶ。
test3-2 の MCP + 出典付与ワークフローだけは `run_mcp_grounded` を呼ぶ（契約が別）。
Runner のシグネチャが調査結果と変わっても、修正はこのファイルに閉じる。

実行 API は adk-research の 2026-08-05 smoke で確定した形をそのまま使う:
`Workflow` は `BaseAgent` を継承しないので `Runner(agent=...)` には渡せず `node=` に渡す。
`session_service` はデフォルト値の無い必須キーワード引数。
"""

import json
import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

from google.adk import Event, Runner
from google.adk.agents.llm_agent import LlmAgent
from google.adk.sessions import InMemorySessionService
from google.adk.tools.base_toolset import BaseToolset
from google.genai import types
from pydantic import BaseModel, Field

from agent import trace as trace_log
from agent.grounding import truncate_text
from agent.mcp_agent import build_grounded_mcp_agent
from agent.schemas import AnswerPayload, CandidateSet, GroundedAnswer, SearchIntent, Source
from agent.trace import TraceRecord
from agent.workflow import build_mcp_grounded_workflow, workflow

__all__ = [
    "McpAgentRunResult",
    "ToolCallRecord",
    "build_runner",
    "extract_tool_calls",
    "run_course_navigator",
    "run_mcp_grounded",
]

# セッションを跨いだ状態は持たない設計（マルチターンは実験6 以降）なので固定値でよい。
_USER_ID = "course-navigator"
# tool_calls の result_summary に載せる応答 JSON の上限文字数（画面表示用）。
_RESULT_SUMMARY_MAX_CHARS = 600


def build_runner() -> Runner:
    """Runner は lifespan で1回だけ構築して app.state に置く（§7.3）。"""
    return Runner(
        node=workflow,
        session_service=InMemorySessionService(),
        auto_create_session=True,
    )


def _node_name(event: object) -> str | None:
    """`Event.node_info.path`（例 'course_navigator_workflow@1/parse_intent@1'）から
    ノード名を取り出す（§8.2 の node_sequence）。

    `Event.author` はワークフロー名になるので trace には使えない（smoke 結果）。
    '/' を含まないパスは Workflow 自身のイベントなのでノード列には数えない。
    """
    path = getattr(getattr(event, "node_info", None), "path", None)
    if not path or "/" not in path:
        return None
    return path.rsplit("/", 1)[-1].split("@", 1)[0]


async def run_course_navigator(
    question: str,
    *,
    runner: Runner | None = None,
    trace_dir: Path | None = None,
) -> tuple[AnswerPayload, TraceRecord]:
    """Workflow を1回実行し、回答と実験ログを返す。

    ステップ5 時点では LLM ノードが無いので llm_calls は常に 0 になる。
    集計方法（usage_metadata を持つ Event を数える）はステップ6 で Agent に
    差し替えてもそのまま効く。
    """
    active = runner if runner is not None else build_runner()
    started = time.perf_counter()

    intent: SearchIntent | None = None
    candidate_set: CandidateSet | None = None
    payload: AnswerPayload | None = None
    node_sequence: list[str] = []
    llm_calls = 0
    llm_input_tokens = 0
    llm_output_tokens = 0

    async for event in active.run_async(
        user_id=_USER_ID,
        session_id=uuid.uuid4().hex,
        new_message=types.Content(role="user", parts=[types.Part(text=question)]),
    ):
        name = _node_name(event)
        if name is not None:
            node_sequence.append(name)

        output = event.output
        if isinstance(output, SearchIntent):
            intent = output
        elif isinstance(output, CandidateSet):
            candidate_set = output
        elif isinstance(output, AnswerPayload):
            payload = output

        usage = event.usage_metadata
        if usage is not None:
            llm_calls += 1
            llm_input_tokens += usage.prompt_token_count or 0
            llm_output_tokens += usage.candidates_token_count or 0

    if intent is None or payload is None:
        raise RuntimeError(
            "Workflow が SearchIntent / AnswerPayload を返しませんでした: "
            f"node_sequence={node_sequence}"
        )

    record = trace_log.build_trace_record(
        question=question,
        intent=intent,
        candidate_set=candidate_set,
        payload=payload,
        node_sequence=node_sequence,
        llm_calls=llm_calls,
        llm_input_tokens=llm_input_tokens,
        llm_output_tokens=llm_output_tokens,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    trace_log.append_trace(record, trace_dir)
    return payload, record


Route = Literal["mcp", "static"]


class ToolCallRecord(BaseModel):
    """LlmAgent のツール呼び出し1件（adk web の Events 表示に相当）。"""

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    # 応答を JSON 化して切り詰めたもの。対応する応答イベントが無ければ None。
    result_summary: str | None = None


class McpAgentRunResult(BaseModel):
    """run_mcp_grounded の戻り値（POST /test/agent/mcp のレスポンスと同形）。"""

    route: Route = Field(..., description="実際に通ったルート（mcp: LLM + MCP / static: 静的 DAG）")
    answer: str = Field(..., description="回答文")
    cited_codes: list[str] = Field(default_factory=list, description="回答で引用された科目コード")
    sources: list[Source] = Field(default_factory=list, description="DB の行から組み立てた出典")
    unverified_codes: list[str] = Field(
        default_factory=list, description="引用されたが DB で確認できなかった科目コード"
    )
    notes: list[str] = Field(default_factory=list, description="検証できなかった理由など")
    tool_calls: list[ToolCallRecord] = Field(
        default_factory=list, description="LlmAgent のツール呼び出し履歴（呼び出し順）"
    )
    node_sequence: list[str] = Field(default_factory=list, description="通過した ADK ノード順序")
    model: str | None = Field(None, description="使用した LLM モデル名（static ルートでは None）")
    latency_ms: int = Field(..., description="ワークフロー実行の所要時間（ミリ秒）")


def _summarize_response(response: dict[str, Any] | None) -> str:
    return truncate_text(
        json.dumps(response, ensure_ascii=False, default=str), _RESULT_SUMMARY_MAX_CHARS
    )


def extract_tool_calls(events: Iterable[Event]) -> list[ToolCallRecord]:
    """Event 列から function_call / function_response を拾い、呼び出し順に並べる。

    応答は function_call.id で呼び出しに対応付ける（ADK が id を必ず振る）。
    ストリーミングの途中断片（partial）は数えない。対応する呼び出しが見つからない応答も
    落とさずに1件として残す（サイレント失敗の禁止）。
    """
    records: list[ToolCallRecord] = []
    index_by_call_id: dict[str, int] = {}
    for event in events:
        if event.partial:
            continue
        for call in event.get_function_calls():
            if call.id:
                index_by_call_id[call.id] = len(records)
            records.append(ToolCallRecord(name=call.name or "", args=dict(call.args or {})))
        for response in event.get_function_responses():
            summary = _summarize_response(response.response)
            index = index_by_call_id.get(response.id or "")
            if index is None:
                records.append(ToolCallRecord(name=response.name or "", result_summary=summary))
                continue
            records[index] = records[index].model_copy(update={"result_summary": summary})
    return records


def _collapse_repeats(names: Iterable[str]) -> list[str]:
    """LlmAgent は1ノードで複数 Event を出すので、連続する同名をまとめる。"""
    collapsed: list[str] = []
    for name in names:
        if not collapsed or collapsed[-1] != name:
            collapsed.append(name)
    return collapsed


def _model_name(agent: LlmAgent) -> str:
    model = agent.model
    return model if isinstance(model, str) else model.model


async def _close_toolsets(agent: LlmAgent) -> None:
    """McpToolset（stdio サブプロセス）を閉じる。

    Runner.close() が閉じるのは root が BaseAgent のときだけで、Workflow を node= で
    渡した場合は閉じてくれないため、ここで明示的に閉じる。
    """
    for tool in agent.tools:
        if isinstance(tool, BaseToolset):
            await tool.close()


async def run_mcp_grounded(
    question: str,
    *,
    agent: LlmAgent | None = None,
) -> McpAgentRunResult:
    """test3-2 の MCP + 出典付与ワークフローを1回実行する。

    MCP が使えない（AGENT_ENABLE_MCP 無効 / GEMINI_API_KEY 未設定）ときは route_initial が
    static に振るので、静的 DAG の回答を route="static" で返す。
    agent はテストで偽モデルの LlmAgent を差し込む口（未指定なら build_grounded_mcp_agent）。
    trace JSONL は §8.2 の静的探索用の形式なので、この経路では書かない。
    """
    active_agent = agent if agent is not None else build_grounded_mcp_agent()
    active = Runner(
        node=build_mcp_grounded_workflow(agent_node=active_agent),
        session_service=InMemorySessionService(),
        auto_create_session=True,
    )
    started = time.perf_counter()

    events: list[Event] = []
    try:
        async for event in active.run_async(
            user_id=_USER_ID,
            session_id=uuid.uuid4().hex,
            new_message=types.Content(role="user", parts=[types.Part(text=question)]),
        ):
            events.append(event)
        # ツールセットの終了処理（MCP サブプロセスの停止）は latency に含めない。
        latency_ms = int((time.perf_counter() - started) * 1000)
    finally:
        await _close_toolsets(active_agent)

    node_sequence = _collapse_repeats(
        name for event in events if (name := _node_name(event)) is not None
    )
    grounded = next(
        (event.output for event in reversed(events) if isinstance(event.output, GroundedAnswer)),
        None,
    )
    if grounded is not None:
        return McpAgentRunResult(
            route="mcp",
            answer=grounded.answer,
            cited_codes=grounded.cited_codes,
            sources=grounded.sources,
            unverified_codes=grounded.unverified_codes,
            notes=grounded.notes,
            tool_calls=extract_tool_calls(events),
            node_sequence=node_sequence,
            model=_model_name(active_agent),
            latency_ms=latency_ms,
        )

    payload = next(
        (event.output for event in reversed(events) if isinstance(event.output, AnswerPayload)),
        None,
    )
    if payload is None:
        raise RuntimeError(
            "Workflow が GroundedAnswer / AnswerPayload を返しませんでした: "
            f"node_sequence={node_sequence}"
        )
    return McpAgentRunResult(
        route="static",
        answer=payload.answer,
        cited_codes=payload.cited_codes,
        node_sequence=node_sequence,
        latency_ms=latency_ms,
    )
