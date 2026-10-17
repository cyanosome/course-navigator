"""eval.node_compare の I/O を持たない部分のテスト（実 DB・実 LLM は使わない）。

計測の要は「Workflow が複製したグラフ内の LlmAgent にコールバックを付けると、実行時に効く」
ことなので、偽モデルの LlmAgent を1ノードだけの Workflow で実際に動かして確かめる。
"""

import asyncio
from collections.abc import AsyncGenerator

import pytest
from google.adk import Workflow
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import errors as genai_errors
from google.genai import types

from agent.schemas import AnswerPayload
from eval import node_compare
from eval.node_compare import BudgetExhausted, LlmMeter, RunCapExceeded

_ANSWER_JSON = '{"answer": "機械学習 [GMS-303] です", "cited_codes": ["GMS-303"]}'


class _FakeLlm(BaseLlm):
    """構造化出力の JSON を1回返す偽モデル（使用量と model_version も付ける）。"""

    model: str = "fake-llm"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=_ANSWER_JSON)]),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=10, candidates_token_count=5, thoughts_token_count=2
            ),
            model_version="fake-llm-001",
        )


def _single_node_workflow() -> tuple[Workflow, LlmAgent]:
    agent = LlmAgent(
        name="compose_agent", model=_FakeLlm(), instruction="テスト用", output_schema=AnswerPayload
    )
    return Workflow(name="single_node", edges=[("START", agent)]), agent


def test_meter_on_graph_node_counts_requests_and_tokens():
    workflow, original = _single_node_workflow()
    meter = LlmMeter(budget=5, per_run_cap=5)

    node = meter.instrument(node_compare._llm_node(workflow))
    events = asyncio.run(node_compare._run_events(workflow, "質問"))

    assert node is not original  # Workflow が複製したノードに付けている
    assert original.before_model_callback is None
    assert meter.total == meter.run_requests == 1
    assert (meter.input_tokens, meter.output_tokens, meter.thoughts_tokens) == (10, 5, 2)
    assert meter.model_versions == ["fake-llm-001"]
    assert node_compare._final_payload(events) == AnswerPayload(
        answer="機械学習 [GMS-303] です", cited_codes=["GMS-303"]
    )


@pytest.mark.parametrize(
    ("budget", "per_run_cap", "expected"),
    [(0, 5, BudgetExhausted), (5, 0, RunCapExceeded)],
)
def test_meter_stops_before_sending_request(budget: int, per_run_cap: int, expected: type):
    workflow, _ = _single_node_workflow()
    meter = LlmMeter(budget=budget, per_run_cap=per_run_cap)
    meter.instrument(node_compare._llm_node(workflow))

    with pytest.raises(Exception) as info:
        asyncio.run(node_compare._run_events(workflow, "質問"))

    assert node_compare._find_exception(info.value, expected) is not None
    assert meter.total == 0


def test_meter_reset_run_keeps_total():
    meter = LlmMeter(budget=5, per_run_cap=5)
    meter.total, meter.run_requests, meter.input_tokens = 3, 2, 100

    meter.reset_run()

    assert (meter.total, meter.run_requests, meter.input_tokens) == (3, 0, 0)


def _api_error(code: int) -> genai_errors.APIError:
    error_class = genai_errors.ClientError if code < 500 else genai_errors.ServerError
    return error_class(code, {"error": {"code": code, "message": "テスト", "status": "TEST"}})


def test_retryable_status_finds_wrapped_api_errors():
    def chained() -> RuntimeError:
        try:
            raise _api_error(429)
        except genai_errors.APIError as exc:
            try:
                raise RuntimeError("包んだ例外") from exc
            except RuntimeError as wrapped:
                return wrapped

    assert node_compare._retryable_status(_api_error(429)) == 429
    assert node_compare._retryable_status(_api_error(503)) == 503
    assert node_compare._retryable_status(_api_error(400)) is None
    assert node_compare._retryable_status(ExceptionGroup("mcp", [_api_error(503)])) == 503
    assert node_compare._retryable_status(chained()) == 429
    assert node_compare._retryable_status(None) is None


def test_describe_redacts_secrets(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-secret-for-test")

    described = node_compare._describe(RuntimeError("key=dummy-secret-for-test で失敗"))

    assert "dummy-secret-for-test" not in described
    assert "***" in described


def test_describe_timeout():
    assert "300" in node_compare._describe(TimeoutError())


def test_condition_order_alternates_mcp_pair():
    all_conditions = list(node_compare.CONDITIONS)

    assert node_compare.condition_order(all_conditions, 0) == [
        "static",
        "static_llm",
        "mcp_free",
        "mcp_grounded",
    ]
    assert node_compare.condition_order(all_conditions, 1) == [
        "static",
        "static_llm",
        "mcp_grounded",
        "mcp_free",
    ]
    assert node_compare.condition_order(["mcp_grounded", "static"], 1) == [
        "static",
        "mcp_grounded",
    ]


def test_static_llm_workflow_has_one_tool_free_llm_node():
    """S1 の組み立て: 静的 DAG の終端がツール無しの LlmAgent で、指示文がハーネスのもの。"""
    from agent.workflow import build_agent_workflow

    workflow = build_agent_workflow(
        enable_mcp=False, instruction=node_compare.STATIC_LLM_INSTRUCTION
    )
    node = node_compare._llm_node(workflow)

    assert node.name == "compose_agent"
    assert node.tools == []
    assert node.instruction == node_compare.STATIC_LLM_INSTRUCTION
