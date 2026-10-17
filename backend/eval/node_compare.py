"""ノード設計比較の実行ハーネス（prereg_node_compare.md の実装）。

backend コンテナの /backend_app で実行する（実 DB と実 LLM を使う）:

    uv run --no-sync python -m eval.node_compare run --out eval/results/<name>.jsonl \
        --git-sha <sha> [--budget 400] [--conditions static,...] [--questions q01,...] [--resume]
    uv run --no-sync python -m eval.node_compare summarize --input eval/results/<name>.jsonl

本番コードの挙動は変えない。LLM リクエスト数とトークン数は LlmAgent のコールバックで数える。
M1 の MCP 事前接続・ツールセットの終了・node_sequence の抽出は、M2 の本番経路
（agent.runner）と同じ処理を使うために runner の内部関数をそのまま呼ぶ。
"""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import asyncpg
from google.adk import Event, Runner, Workflow
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.sessions import InMemorySessionService
from google.adk.tools.base_toolset import BaseToolset
from google.genai import errors as genai_errors
from google.genai import types
from neo4j import AsyncDriver, AsyncGraphDatabase
from pydantic import BaseModel, Field

from agent import deps, runner
from agent.grounding import build_grounded_answer, normalize_codes
from agent.mcp_agent import build_grounded_mcp_agent
from agent.runner import ToolCallRecord
from agent.schemas import AnswerPayload
from agent.workflow import build_agent_workflow, build_mcp_first_workflow
from course_core import config
from course_core.repositories import postgres_repo
from eval import report
from eval.metrics import (
    CONDITIONS,
    Condition,
    GoldenCase,
    RunRecord,
    ToolCallSummary,
    score_question,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = BACKEND_ROOT / "tests" / "golden" / "questions.json"
PROMPT_DIR = BACKEND_ROOT / "src" / "agent" / "prompts"
PROMPT_FILES = ("compose_answer.md", "grounded_addendum.md")
LIBRARIES = ("google-adk", "google-genai", "mcp", "neo4j-mcp-server")

# §8 予算と打ち切り
DEFAULT_BUDGET = 400
PER_RUN_LLM_CAP = 25
RUN_TIMEOUT_SECONDS = 300
RETRYABLE_STATUS = (429, 503)
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 30

# シードの件数（golden はこの20科目を前提に作られている）。違えば実行しない。
EXPECTED_COURSES = 20
SET_MODEL_RESPONSE = "set_model_response"  # ADK が構造化出力のために差し込むツール
ERROR_MAX_CHARS = 500
SECRET_ENV_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "DB_PASSWORD", "NEO4J_PASSWORD")
_USER_ID = "node-compare"
_ALL = "all"
_LIST_SEPARATOR = ","

# §2.1 の指示文（事前登録に本文を凍結してある。変えるなら逸脱として記録する）。
STATIC_LLM_INSTRUCTION = """\
あなたは大学の履修選択を支援する「履修アドバイザーAI（Course Navigator）」です。
入力は、静的なグラフ探索が返した候補科目の JSON（CandidateSet）です。あなたはツールを使えません。

1. 回答の根拠にしてよいのは入力 JSON の内容（intent、candidates の code / title / evidence、notes）だけです。入力に無い科目を挙げたり、科目間の関係を推測で補ったりしてはいけません。
2. 「楽単」「単位が取りやすい」「おすすめ」「先生が厳しい」といった主観的・非公式な評価は述べないでください。
3. 回答文中で言及した科目の科目コードは、必ず cited_codes フィールドに漏れなくリストアップしてください。
4. 回答は日本語で、結論を先に書き、各候補を「科目名 [科目コード]」の形で挙げて evidence の内容を根拠として添えてください。
5. candidates が空のときは、該当する科目が見つからなかったことと、notes があればその内容を伝えてください。
"""


class BudgetExhausted(RuntimeError):
    """全体の LLM リクエスト予算に達した（次のリクエストは送っていない）。"""


class RunCapExceeded(RuntimeError):
    """1実行あたりの LLM リクエスト上限に達した。"""


class RouteMismatch(RuntimeError):
    """条件が想定した経路（LLM ノード）を通らなかった。"""


class LlmMeter:
    """LlmAgent の before/after_model_callback として LLM リクエスト数とトークン数を数える。

    リクエストの中身は変えない。予算と1実行の上限は、リクエストを送る前に例外で止める。
    """

    def __init__(self, budget: int, per_run_cap: int) -> None:
        self.budget = budget
        self.per_run_cap = per_run_cap
        self.total = 0
        self.reset_run()

    def reset_run(self) -> None:
        self.run_requests = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.thoughts_tokens = 0
        self.model_versions: list[str] = []

    def before_model(
        self, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> LlmResponse | None:
        if self.total >= self.budget:
            raise BudgetExhausted(f"LLM リクエストの予算 {self.budget} 回に達しました")
        if self.run_requests >= self.per_run_cap:
            raise RunCapExceeded(f"1実行あたりの上限 {self.per_run_cap} 回に達しました")
        self.total += 1
        self.run_requests += 1
        return None

    def after_model(
        self, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> LlmResponse | None:
        usage = llm_response.usage_metadata
        if usage is not None:
            self.input_tokens += usage.prompt_token_count or 0
            self.output_tokens += usage.candidates_token_count or 0
            self.thoughts_tokens += usage.thoughts_token_count or 0
        version = llm_response.model_version
        if version and version not in self.model_versions:
            self.model_versions.append(version)
        return None

    def instrument(self, agent: LlmAgent) -> LlmAgent:
        agent.before_model_callback = self.before_model
        agent.after_model_callback = self.after_model
        return agent


class Outcome(BaseModel):
    """条件の実行関数が返す、採点前の結果。"""

    route: str
    payload: AnswerPayload
    expects_llm: bool  # LLM ノードを通ったはずか（計測漏れの検出に使う）
    model: str | None = None
    node_sequence: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    pipeline_unverified_codes: list[str] | None = None
    pipeline_latency_ms: int | None = None
    mcp_preflight_ms: int | None = None


# --- 条件の組み立てと実行 ---------------------------------------------------------


def _llm_node(workflow: Workflow) -> LlmAgent:
    """Workflow は構築時に LlmAgent を複製するので、実際に動くグラフ内のノードを取り出す。"""
    if workflow.graph is None:
        raise RuntimeError(f"{workflow.name} のグラフが構築されていません")
    agents = [node for node in workflow.graph.nodes if isinstance(node, LlmAgent)]
    if len(agents) != 1:
        raise RuntimeError(f"{workflow.name} の LlmAgent ノードが1つではありません: {len(agents)}")
    return agents[0]


async def _run_events(node: Workflow, question: str) -> list[Event]:
    active = Runner(node=node, session_service=InMemorySessionService(), auto_create_session=True)
    return [
        event
        async for event in active.run_async(
            user_id=_USER_ID,
            session_id=uuid.uuid4().hex,
            new_message=types.Content(role="user", parts=[types.Part(text=question)]),
        )
    ]


def _message_text(event: Event) -> str | None:
    """終端の LlmAgent ノードが出した最終メッセージ（構造化出力の JSON 文字列）を返す。

    LlmAgent ノードの出力は message_as_output の印が付いたモデル発話で、Runner は
    同じ値を二重に出さないよう event.output を None にしてから流す（ADK 2.8 runners.py）。
    """
    is_final_message = (
        not event.partial
        and event.node_info is not None
        and event.node_info.message_as_output
        and event.content is not None
        and event.content.role == "model"
        and not event.get_function_calls()
    )
    if not is_final_message:
        return None
    text = "".join(part.text for part in event.content.parts or [] if part.text and not part.thought)
    return text if text.strip() else None


def _final_payload(events: Sequence[Event]) -> AnswerPayload:
    """終端ノードの出力を取り出す。関数ノードは AnswerPayload、LlmAgent ノードは JSON 文字列。"""
    for event in reversed(events):
        if isinstance(event.output, AnswerPayload):
            return event.output
        if (text := _message_text(event)) is not None:
            return AnswerPayload.model_validate_json(text)
    raise RuntimeError("Workflow が AnswerPayload を返しませんでした")


def _node_sequence(events: Sequence[Event]) -> list[str]:
    return runner._collapse_repeats(
        name for event in events if (name := runner._node_name(event)) is not None
    )


async def run_static(question: str, meter: LlmMeter) -> Outcome:
    """S0: 静的 DAG（agent.workflow.workflow）。LLM を呼んだら失敗にする。"""
    with tempfile.TemporaryDirectory() as trace_dir:
        payload, record = await runner.run_course_navigator(question, trace_dir=Path(trace_dir))
    if record.llm_calls:
        raise RouteMismatch(f"静的 DAG で LLM が {record.llm_calls} 回呼ばれました")
    return Outcome(
        route="static", payload=payload, expects_llm=False, node_sequence=record.node_sequence
    )


async def run_static_llm(question: str, meter: LlmMeter) -> Outcome:
    """S1: 静的 DAG の終端を LlmAgent（ツール無し・ハーネスの指示文）に差し替えたもの。"""
    workflow = build_agent_workflow(enable_mcp=False, instruction=STATIC_LLM_INSTRUCTION)
    agent = meter.instrument(_llm_node(workflow))
    events = await _run_events(workflow, question)
    sequence = _node_sequence(events)
    return Outcome(
        route="static",
        payload=_final_payload(events),
        expects_llm=agent.name in sequence,
        model=runner._model_name(agent),
        node_sequence=sequence,
        tool_calls=runner.extract_tool_calls(events),
    )


async def run_mcp_free(question: str, meter: LlmMeter) -> Outcome:
    """M1: build_mcp_first_workflow（MCP ツールのみ・attach_sources 無し）。

    run_mcp_grounded と同じ事前接続を行い、失敗したら静的経路に倒さず例外にする。
    """
    workflow = build_mcp_first_workflow()
    agent = meter.instrument(_llm_node(workflow))
    if not any(isinstance(tool, BaseToolset) for tool in agent.tools):
        raise RouteMismatch("MCP ツールセットがありません（AGENT_ENABLE_MCP を確認）")
    try:
        started = time.perf_counter()
        failure = await runner._preflight_toolsets(agent)
        preflight_ms = int((time.perf_counter() - started) * 1000)
        if failure is not None:
            raise RouteMismatch(f"MCP 事前接続に失敗しました: {failure}")
        events = await _run_events(workflow, question)
    finally:
        await runner._close_toolsets(agent)
    sequence = _node_sequence(events)
    if agent.name not in sequence:
        raise RouteMismatch(f"{agent.name} を通りませんでした: {sequence}")
    return Outcome(
        route="mcp",
        payload=_final_payload(events),
        expects_llm=True,
        model=runner._model_name(agent),
        node_sequence=sequence,
        tool_calls=runner.extract_tool_calls(events),
        mcp_preflight_ms=preflight_ms,
    )


async def run_mcp_grounded(question: str, meter: LlmMeter) -> Outcome:
    """M2: 本番の run_mcp_grounded（MCP + get_course_details → attach_sources）。"""
    agent = meter.instrument(build_grounded_mcp_agent())
    result = await runner.run_mcp_grounded(question, agent=agent)
    if result.route != "mcp":
        raise RouteMismatch(f"静的経路に倒れました: {result.notes}")
    return Outcome(
        route=result.route,
        payload=AnswerPayload(answer=result.answer, cited_codes=result.cited_codes),
        expects_llm=True,
        model=result.model,
        node_sequence=result.node_sequence,
        tool_calls=result.tool_calls,
        pipeline_unverified_codes=result.unverified_codes,
        pipeline_latency_ms=result.latency_ms,
    )


ConditionRunner = Callable[[str, LlmMeter], Awaitable[Outcome]]
RUNNERS: dict[Condition, ConditionRunner] = {
    "static": run_static,
    "static_llm": run_static_llm,
    "mcp_free": run_mcp_free,
    "mcp_grounded": run_mcp_grounded,
}


# --- 1実行の記録 -----------------------------------------------------------------


def _find_exception[E: BaseException](error: BaseException | None, kind: type[E]) -> E | None:
    """例外グループ（MCP の anyio が包む）と __cause__ をたどって kind の例外を探す。"""
    if error is None:
        return None
    if isinstance(error, kind):
        return error
    if isinstance(error, BaseExceptionGroup):
        for inner in error.exceptions:
            if (found := _find_exception(inner, kind)) is not None:
                return found
    return _find_exception(error.__cause__, kind)


def _redact(text: str) -> str:
    for name in SECRET_ENV_NAMES:
        secret = os.environ.get(name)
        if secret:
            text = text.replace(secret, "***")
    return text


def _describe(error: BaseException) -> str:
    if isinstance(error, TimeoutError):
        return f"TimeoutError: {RUN_TIMEOUT_SECONDS} 秒を超えました"
    return _redact(f"{type(error).__name__}: {error}")[:ERROR_MAX_CHARS]


def _retryable_status(error: BaseException | None) -> int | None:
    api_error = _find_exception(error, genai_errors.APIError)
    if api_error is not None and api_error.code in RETRYABLE_STATUS:
        return api_error.code
    return None


async def _post_hoc_grounding(pool: asyncpg.Pool, payload: AnswerPayload) -> tuple[list[str], int]:
    """全条件共通の事後検証。attach_sources と同じ純関数で DB の行と突き合わせる。"""
    async with pool.acquire() as conn:
        rows = await postgres_repo.get_syllabi_by_codes(conn, normalize_codes(payload.cited_codes))
    grounded = build_grounded_answer(payload, rows)
    return grounded.unverified_codes, len(grounded.sources)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def run_one(
    condition: Condition,
    case: GoldenCase,
    meter: LlmMeter,
    pool: asyncpg.Pool,
    run_id: str,
) -> tuple[RunRecord, bool]:
    """1条件×1質問を実行して記録を返す。2つ目の値は予算切れで全体を止めるべきか。

    429 / 503 は待ってから最初からやり直す（§8）。それ以外の失敗はやり直さずに記録する。
    """
    started_at = _now()
    retry_reasons: list[str] = []
    requests_all_attempts = 0
    attempts = 0
    while True:
        attempts += 1
        meter.reset_run()
        outcome: Outcome | None = None
        error: Exception | None = None
        started = time.perf_counter()
        try:
            outcome = await asyncio.wait_for(
                RUNNERS[condition](case.question, meter), RUN_TIMEOUT_SECONDS
            )
        except Exception as exc:  # 失敗は記録して次へ進む（握りつぶさず error 列に残す）
            error = exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        requests_all_attempts += meter.run_requests
        status = _retryable_status(error)
        if status is None or attempts > MAX_RETRIES:
            break
        retry_reasons.append(f"HTTP {status}（試行 {attempts}）")
        await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempts)

    if outcome is not None and outcome.expects_llm and meter.run_requests == 0:
        error = RouteMismatch("LLM ノードを通ったのに LLM リクエストが数えられていません")

    record = RunRecord(
        run_id=run_id,
        condition=condition,
        question_id=case.id,
        mode=case.mode,
        model=outcome.model if outcome else None,
        model_versions=list(meter.model_versions),
        success=error is None and outcome is not None,
        error=_describe(error) if error is not None else None,
        attempts=attempts,
        retry_reasons=retry_reasons,
        llm_requests=meter.run_requests,
        llm_requests_all_attempts=requests_all_attempts,
        input_tokens=meter.input_tokens,
        output_tokens=meter.output_tokens,
        thoughts_tokens=meter.thoughts_tokens,
        latency_ms=latency_ms,
        started_at=started_at,
    )
    if outcome is not None:
        record = record.model_copy(
            update={
                "route": outcome.route,
                "node_sequence": outcome.node_sequence,
                "answer": outcome.payload.answer,
                "cited_codes": outcome.payload.cited_codes,
                "tool_calls": [
                    ToolCallSummary(name=call.name, args=call.args) for call in outcome.tool_calls
                ],
                "tool_call_count": sum(
                    1 for call in outcome.tool_calls if call.name != SET_MODEL_RESPONSE
                ),
                "pipeline_unverified_codes": outcome.pipeline_unverified_codes,
                "pipeline_latency_ms": outcome.pipeline_latency_ms,
                "mcp_preflight_ms": outcome.mcp_preflight_ms,
            }
        )
    if record.success and outcome is not None:
        unverified, sources_count = await _post_hoc_grounding(pool, outcome.payload)
        record = record.model_copy(
            update={
                "score": score_question(case, outcome.payload.cited_codes, outcome.payload.answer),
                "unverified_codes": unverified,
                "sources_count": sources_count,
            }
        )
    return record, _find_exception(error, BudgetExhausted) is not None


# --- 実験全体 ---------------------------------------------------------------------


def load_golden() -> list[GoldenCase]:
    return [GoldenCase.model_validate(case) for case in json.loads(GOLDEN_PATH.read_text("utf-8"))]


def condition_order(conditions: Sequence[Condition], question_index: int) -> list[Condition]:
    """§8: S0 → S1 → M1/M2。M1 と M2 の順は質問ごとに入れ替える（q01 は M1 が先）。"""
    mcp_pair: list[Condition] = ["mcp_free", "mcp_grounded"]
    if question_index % 2 == 1:
        mcp_pair.reverse()
    ordered: list[Condition] = ["static", "static_llm", *mcp_pair]
    return [condition for condition in ordered if condition in conditions]


def manifest_path(results_path: Path) -> Path:
    return results_path.with_name(f"{results_path.stem}_manifest.json")


def summary_path(results_path: Path) -> Path:
    return results_path.with_name(f"{results_path.stem}_summary.md")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def _db_counts(pool: asyncpg.Pool, driver: AsyncDriver) -> dict[str, int]:
    async with pool.acquire() as conn:
        postgres_rows = await conn.fetchval("SELECT count(*) FROM test_postgres_syllabus")
    async with driver.session() as session:
        result = await session.run("MATCH (c:Course) RETURN count(c) AS n")
        neo4j_nodes = (await result.single())["n"]
    return {"postgres_syllabus": postgres_rows, "neo4j_course": neo4j_nodes}


def _session_manifest(
    run_id: str,
    args: argparse.Namespace,
    counts: dict[str, int],
    conditions: Sequence[Condition],
    questions: Sequence[str],
) -> dict[str, object]:
    prompts = {name: _sha256((PROMPT_DIR / name).read_text("utf-8")) for name in PROMPT_FILES}
    prompts["STATIC_LLM_INSTRUCTION"] = _sha256(STATIC_LLM_INSTRUCTION)
    return {
        "run_id": run_id,
        "started_at": _now(),
        "finished_at": None,
        "git_sha": args.git_sha,
        "model": config.AGENT_MODEL,
        "agent_enable_mcp": config.AGENT_ENABLE_MCP,
        "generation_config": "未指定（API 既定値。本番の組み立て関数が渡していないため）",
        "conditions": list(conditions),
        "questions": list(questions),
        "db_counts": counts,
        "prompt_sha256_16": prompts,
        "budget": args.budget,
        "per_run_llm_cap": PER_RUN_LLM_CAP,
        "run_timeout_seconds": RUN_TIMEOUT_SECONDS,
        "retry": f"HTTP {RETRYABLE_STATUS} で {RETRY_BACKOFF_SECONDS}秒×試行回数待って最大{MAX_RETRIES}回",
        "python": platform.python_version(),
        "libraries": {name: metadata.version(name) for name in LIBRARIES},
        "llm_requests_used": 0,
        "aborted": None,
    }


def _write_manifest(path: Path, sessions: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"sessions": sessions}, ensure_ascii=False, indent=2) + "\n", "utf-8")


def _load_records(path: Path) -> list[RunRecord]:
    if not path.exists():
        return []
    return [
        RunRecord.model_validate_json(line)
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
    ]


def _selected(raw: str, allowed: Sequence[str], label: str) -> list[str]:
    if raw == _ALL:
        return list(allowed)
    chosen = [item.strip() for item in raw.split(_LIST_SEPARATOR) if item.strip()]
    unknown = [item for item in chosen if item not in allowed]
    if unknown:
        raise SystemExit(f"不明な{label}: {unknown}（選べるもの: {list(allowed)}）")
    return chosen


async def run_experiment(args: argparse.Namespace) -> None:
    cases = load_golden()
    question_ids = _selected(args.questions, [case.id for case in cases], "質問")
    chosen = set(_selected(args.conditions, CONDITIONS, "条件"))
    conditions = [condition for condition in CONDITIONS if condition in chosen]
    out_path: Path = args.out
    if out_path.exists() and not args.resume:
        raise SystemExit(f"{out_path} は既にあります。続きから流すなら --resume を付けてください")
    done = {(record.condition, record.question_id) for record in _load_records(out_path)}
    out_path.parent.mkdir(parents=True, exist_ok=True)

    config.validate_required_env()
    pool = await asyncpg.create_pool(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
    )
    driver = AsyncGraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    deps.set_backends(pool, driver)
    meter = LlmMeter(args.budget, PER_RUN_LLM_CAP)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    manifest_file = manifest_path(out_path)
    sessions: list[dict[str, object]] = (
        json.loads(manifest_file.read_text("utf-8"))["sessions"] if manifest_file.exists() else []
    )
    aborted = False
    try:
        counts = await _db_counts(pool, driver)
        if set(counts.values()) != {EXPECTED_COURSES}:
            raise SystemExit(f"DB の件数がシードと違います: {counts}")
        session = _session_manifest(run_id, args, counts, conditions, question_ids)
        sessions.append(session)
        _write_manifest(manifest_file, sessions)

        with out_path.open("a", encoding="utf-8") as sink:
            for index, case in enumerate(cases):
                if case.id not in question_ids:
                    continue
                for condition in condition_order(conditions, index):
                    if (condition, case.id) in done:
                        continue
                    record, exhausted = await run_one(condition, case, meter, pool, run_id)
                    sink.write(record.model_dump_json() + "\n")
                    sink.flush()
                    print(_progress_line(record, meter), flush=True)
                    if exhausted:
                        aborted = True
                        break
                if aborted:
                    break
    finally:
        deps.set_backends(None, None)
        await pool.close()
        await driver.close()
        if sessions and sessions[-1].get("run_id") == run_id:
            sessions[-1].update(
                {"finished_at": _now(), "llm_requests_used": meter.total, "aborted": aborted}
            )
            _write_manifest(manifest_file, sessions)


def _progress_line(record: RunRecord, meter: LlmMeter) -> str:
    status = "ok" if record.success else f"NG {record.error}"
    return (
        f"{record.question_id} {record.condition:<12} {status} llm={record.llm_requests} "
        f"tools={record.tool_call_count} {record.latency_ms / 1000:.1f}s "
        f"cited={record.cited_codes} total_llm={meter.total}"
    )


def summarize(args: argparse.Namespace) -> None:
    records = _load_records(args.input)
    if not records:
        raise SystemExit(f"{args.input} に記録がありません")
    sessions = json.loads(manifest_path(args.input).read_text("utf-8"))["sessions"]
    cases = {case.id: case for case in load_golden()}
    out = args.out or summary_path(args.input)
    out.write_text(report.render_summary(records, cases, sessions), "utf-8")
    print(f"wrote {out}")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m eval.node_compare", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="条件×質問を実行して JSONL に追記する")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--git-sha", required=True, help="コンテナ内に .git が無いので外から渡す")
    run.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    run.add_argument("--conditions", default=_ALL)
    run.add_argument("--questions", default=_ALL)
    run.add_argument("--resume", action="store_true")
    summary = commands.add_parser("summarize", help="JSONL から集計表と仮説の判定を書く")
    summary.add_argument("--input", type=Path, required=True)
    summary.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.command == "run":
        asyncio.run(run_experiment(args))
    else:
        summarize(args)


if __name__ == "__main__":
    main(sys.argv[1:])
