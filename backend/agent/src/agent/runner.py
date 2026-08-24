"""ADK の実行 API に触れる唯一のファイル（設計書 実験3-2 §7.2）。

FastAPI ルーター・pytest・CLI はすべて `run_course_navigator` だけを呼ぶ。
Runner のシグネチャが調査結果と変わっても、修正はこのファイルに閉じる。

実行 API は adk-research の 2026-08-05 smoke で確定した形をそのまま使う:
`Workflow` は `BaseAgent` を継承しないので `Runner(agent=...)` には渡せず `node=` に渡す。
`session_service` はデフォルト値の無い必須キーワード引数。
"""

import time
import uuid
from pathlib import Path

from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent import trace as trace_log
from agent.schemas import AnswerPayload, CandidateSet, SearchIntent
from agent.trace import TraceRecord
from agent.workflow import workflow

__all__ = ["build_runner", "run_course_navigator"]

# セッションを跨いだ状態は持たない設計（マルチターンは実験6 以降）なので固定値でよい。
_USER_ID = "course-navigator"


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
