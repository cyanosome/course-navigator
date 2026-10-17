"""Agent（GraphRAG 静的探索）テスト用ルーター。

ユーザーからの質問文を受け取り、ADK ワークフロー（意図解析、Neo4j グラフ探索、
Evidence 生成、回答文構築）を実行して探索結果およびトレース情報を返却します。
`POST /test/agent/mcp`（test3-2）は MCP Agent の回答を DB 由来の出典付きで返します。
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field

from agent import runner
from agent.schemas import Candidate
from agent.trace import TraceIntent

router = APIRouter(tags=["agent"])


class AgentQueryInput(BaseModel):
    question: str = Field(..., description="ユーザーからの質問文", example="データサイエンス入門の次に取れる科目は?")


class AgentQueryResponse(BaseModel):
    answer: str = Field(..., description="生成された回答文")
    cited_codes: list[str] = Field(default_factory=list, description="引用された科目コード一覧")
    intent: TraceIntent = Field(..., description="意図解析結果")
    candidates: list[Candidate] = Field(default_factory=list, description="探索された講義候補一覧")
    traversed_edges: list[str] = Field(default_factory=list, description="探索で辿ったグラフエッジ一覧")
    node_sequence: list[str] = Field(default_factory=list, description="通過したADKノード順序")


@router.post("/test/agent", response_model=AgentQueryResponse)
async def test_agent_query(data: AgentQueryInput) -> dict[str, Any]:
    question = data.question.strip()
    if not question:
        return AgentQueryResponse(
            answer="質問を入力してください。",
            cited_codes=[],
            intent=TraceIntent(
                mode="unclear",
                anchor_code=None,
                anchor_status="no_anchor",
                unclear_kind="no_mode",
                alternatives=[],
                matched_rule="unclear:no_mode",
            ),
            candidates=[],
            traversed_edges=[],
            node_sequence=[],
        ).model_dump()

    answer_payload, trace_record = await runner.run_course_navigator(question)

    return {
        "answer": answer_payload.answer,
        "cited_codes": answer_payload.cited_codes,
        "intent": trace_record.intent,
        "candidates": trace_record.candidates,
        "traversed_edges": trace_record.traversed_edges,
        "node_sequence": trace_record.node_sequence,
    }


@router.post("/test/agent/mcp", response_model=runner.McpAgentRunResult)
async def test_agent_mcp_query(data: AgentQueryInput) -> runner.McpAgentRunResult:
    """test3-2: MCP Agent（Neo4j MCP + RDB ツール）の回答を DB 由来の出典付きで返す。

    MCP が使えない（AGENT_ENABLE_MCP 無効 / GEMINI_API_KEY 未設定）ときは静的 DAG の回答を
    route="static" で返す。実行中の例外は握りつぶさず、共通例外ハンドラに任せる。
    """
    question = data.question.strip()
    if not question:
        return runner.McpAgentRunResult(
            route="static", answer="質問を入力してください。", latency_ms=0
        )

    return await runner.run_mcp_grounded(question)
