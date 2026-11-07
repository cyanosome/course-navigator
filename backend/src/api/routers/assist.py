"""画面の AI の口（navi-v1、api-contract.md 4.2 の A1 `POST /api/assist/ask`）。

既存の `/test/agent`・`/test/agent/mcp` は変えない。違いは次の3つ:
1. 変種の因子（route・style・verify・citations）をリクエストごとに当てる。決め方は上から順に
   調査のセッションの今のブロックの旗 → 開発（RESEARCH_DEV）なら本文の options → 既定の変種の旗。
2. 調査のセッションがあれば、成功でも失敗でも chat_response を研究のログに1行書く。
3. サーバー側の時間切れ（170 秒で 504。画面の上限 180 秒より短く）。
関西のデータで答え、出典は syllabus_id と courses で照合する（E1）。本文に plan_context（今のプラン）があれば、
足す・外すの提案を照合して plan_suggestions で返す。
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Mapping
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Request

from agent import deps, route_options
from agent.route_options import AssistIn, AssistOptions, AssistOut, UnverifiedItem
from api.contract import set_contract_header
from course_core.research import settings
from course_core.research.sink import ResearchSink, get_research_sink, session_id_from_request
from course_core.research.variants import VARIANTS, VariantFlags

router = APIRouter(tags=["assist"], dependencies=[Depends(set_contract_header)])

logger = logging.getLogger(__name__)

# 画面の待ちの上限（frontend/src/navi/state.ts の 180 秒）より短くし、画面より先にサーバーが打ち切る。
ASSIST_TIMEOUT_SECONDS: Final = 170.0
_ERROR_DETAIL_MAX_CHARS: Final = 300

ErrorKind = Literal["timeout", "mcp_unavailable", "db", "llm", "other"]

# 例外の型の置き場所（モジュール）で失敗の種類を分ける。asyncpg は手元の環境に無いことがあるので
# import せず名前で見る（記録のための分類で、HTTP の状態は共通ハンドラが決める）。
_DB_MODULES: Final = ("asyncpg", "neo4j")
_LLM_MODULES: Final = ("google.genai", "google.api_core", "google.adk.models")


def classify_error(exc: BaseException) -> ErrorKind:
    module = type(exc).__module__
    if module.startswith(_DB_MODULES):
        return "db"
    if module.startswith(_LLM_MODULES):
        return "llm"
    return "other"


def options_from_flags(flags: VariantFlags) -> AssistOptions:
    """変種の旗から AI の因子を作る。AI の無い変種や、この口で出さない経路は断る。"""
    if flags.assistant != "on":
        raise HTTPException(status_code=409, detail="この条件では AI を使えません（assistant=off）。")
    if flags.ai_route not in ("mcp_grounded", "static"):
        raise HTTPException(
            status_code=501, detail=f"未実装の水準です（ai_route={flags.ai_route} はこの口では使えません）。"
        )
    return AssistOptions(route=flags.ai_route, style=flags.style, verify=flags.verify, citations=flags.citations)


def _unverified_items(codes: list[str]) -> list[UnverifiedItem]:
    reason = "lookup_failed" if deps.db_pool() is None else "not_in_db"
    return [UnverifiedItem(code=code, reason=reason) for code in codes]


def _chat_response_payload(
    *,
    request_id: str,
    data: AssistIn,
    options: AssistOptions,
    options_ignored: bool,
    latency_ms: int,
    run: route_options.AssistRun | None,
    error: ErrorKind | None,
    error_detail: str | None,
) -> Mapping[str, Any]:
    """chat_response の payload（ab-variants.md 7.2）。トークン数は今の runner から取れないので null。

    7.2 に足した項目（E1）: plan_context_sha256（plan_context の指紋。診断のまとめの本文は書かない）、
    plan_suggestions（照合の後の足す・外すの syllabus_id と外した理由）、toolset（McpToolset を使い回したか）。
    """
    result = run.result if run is not None else None
    suggestions = run.plan_suggestions if run is not None else None
    return {
        "request_id": request_id,
        "client_event_id": str(data.client_event_id) if data.client_event_id else None,
        "route_requested": options.route,
        "route_actual": result.route if result is not None else None,
        "options": options.model_dump(),
        "options_ignored": options_ignored,
        "latency_ms": latency_ms,
        "workflow_latency_ms": result.latency_ms if result is not None else None,
        "model": result.model if result is not None else None,
        "prompt_sha256": run.prompt_sha256 if run is not None else None,
        "tool_calls": [call.model_dump(exclude={"result_summary"}) for call in result.tool_calls]
        if result is not None
        else [],
        "cited_codes": result.cited_codes if result is not None else [],
        "source_codes": [source.code for source in result.sources] if result is not None else [],
        "unverified_codes": result.unverified_codes if result is not None else [],
        "plan_context_sha256": route_options.plan_context_sha256(data.plan_context)
        if data.plan_context is not None
        else None,
        "plan_suggestions": {
            "add": [item.syllabus_id for item in suggestions.add],
            "remove": [item.syllabus_id for item in suggestions.remove],
            "dropped": [item.model_dump() for item in suggestions.dropped],
        }
        if suggestions is not None
        else None,
        "toolset": ("reused" if run.toolset_reused else "per_request") if run is not None else None,
        "tokens": None,
        "error": error,
        "error_detail": error_detail,
    }


@router.post("/assist/ask", response_model=AssistOut)
async def ask(
    data: AssistIn,
    request: Request,
    sink: Annotated[ResearchSink, Depends(get_research_sink)],
) -> AssistOut:
    """A1: AI に聞く。調査のセッションでは本文の options を使わず、今のブロックの旗で決める。"""
    question = data.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="質問を入力してください。")

    session_id = session_id_from_request(request)
    if session_id is not None:
        current = await sink.current_variant(session_id)
        if current is None:
            raise HTTPException(status_code=401, detail="調査のセッションが見つかりません。カードの URL から開き直してください。")
        if current.flags is None:
            raise HTTPException(status_code=409, detail="課題のブロックの外では AI を使えません。")
        options = options_from_flags(current.flags)
        variant_id = current.variant_id
        options_ignored = data.options is not None
    elif settings.research_dev():
        options = data.options if data.options is not None else AssistOptions()
        variant_id = None
        options_ignored = False
    else:
        variant_id = settings.default_variant_id()
        options = options_from_flags(VARIANTS[variant_id])
        options_ignored = data.options is not None

    request_id = uuid.uuid4().hex
    started = time.perf_counter()

    async def record(run: route_options.AssistRun | None, error: ErrorKind | None, detail: str | None) -> None:
        if session_id is None:
            return
        payload = _chat_response_payload(
            request_id=request_id,
            data=data,
            options=options,
            options_ignored=options_ignored,
            latency_ms=int((time.perf_counter() - started) * 1000),
            run=run,
            error=error,
            error_detail=detail[:_ERROR_DETAIL_MAX_CHARS] if detail else None,
        )
        await sink.append_server_event(session_id, "chat_response", payload)

    deadline = asyncio.timeout(ASSIST_TIMEOUT_SECONDS)
    try:
        async with deadline:
            run = await route_options.run_with_options(question, options, plan_context=data.plan_context)
    except route_options.UnsupportedLevelError as exc:
        await record(None, "other", str(exc))
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except Exception as exc:
        if deadline.expired():
            await record(None, "timeout", f"{ASSIST_TIMEOUT_SECONDS:.0f} 秒で打ち切りました")
            raise HTTPException(status_code=504, detail="AI の回答が時間内に返りませんでした。") from exc
        await record(None, classify_error(exc), f"{type(exc).__name__}: {exc}")
        raise

    result = run.result
    fell_back = options.route == "mcp_grounded" and result.route != "mcp"
    if fell_back:
        logger.warning("AI が MCP を使えず静的探索で答えました（request_id=%s）: %s", request_id, result.notes)
    await record(run, "mcp_unavailable" if fell_back else None, "; ".join(result.notes) if fell_back else None)

    return AssistOut(
        **result.model_dump(),
        request_id=request_id,
        variant_id=variant_id,
        options_applied=options,
        options_ignored=options_ignored,
        route_requested=options.route,
        unverified_items=_unverified_items(result.unverified_codes) if options.verify == "off" else [],
        plan_suggestions=run.plan_suggestions,
    )
