"""実験ログ（trace JSONL）— 「系統図に沿った」ことの証拠（設計書 実験3-2 §8.2）。

1リクエスト1行を `backend/logs/trace-YYYYMMDD.jsonl` に追記する。§8.2 が実験の証拠と
定める5フィールド（node_sequence / traversed_edges / evidence[].edge_refs /
cited_codes / llm_calls）を落とさないことがこのモジュールの唯一の責務。
"""

import os
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from agent.schemas import AnswerPayload, Candidate, CandidateSet, SearchIntent

__all__ = [
    "TraceIntent",
    "TraceRecord",
    "append_trace",
    "build_trace_record",
    "default_trace_dir",
]

_TRACE_DIR_ENV = "COURSE_TRACE_DIR"
_TRACE_SUBDIR = "logs"
# backend ルートの目印。intent_rules._seed_path と同じ探し方に揃えてある。
_BACKEND_MARKER = Path("seed") / "courses.json"


class TraceIntent(BaseModel):
    """§8.2 の intent 欄。unclear_kind / alternatives は A6 の判定に要る。"""

    mode: str
    anchor_code: str | None = None
    anchor_status: str
    unclear_kind: str | None = None
    alternatives: list[str] = Field(default_factory=list)
    matched_rule: str


class TraceRecord(BaseModel):
    """1リクエスト分の実験ログ（§8.2）。`POST /api/chat?debug=1` にも同じ物を載せる。"""

    trace_id: str
    ts: str
    question: str
    intent: TraceIntent
    route: str
    node_sequence: list[str] = Field(default_factory=list)
    traversed_edges: list[str] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    # notes は §8.2 の例には無いが、層A の障害（GRAPH_UNAVAILABLE 等）が
    # 「候補0件」としか見えなくなるのを防ぐために残す（サイレント失敗の禁止）。
    notes: list[str] = Field(default_factory=list)
    llm_calls: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    answer: str = ""
    cited_codes: list[str] = Field(default_factory=list)
    latency_ms: int = 0


def default_trace_dir() -> Path:
    """既定の書き込み先 `backend/logs`。テストは環境変数か引数で差し替える。"""
    override = os.getenv(_TRACE_DIR_ENV)
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        if (parent / _BACKEND_MARKER).is_file():
            return parent / _TRACE_SUBDIR
    raise FileNotFoundError(
        f"backend ルートを特定できません。環境変数 {_TRACE_DIR_ENV} で指定してください。"
    )


def build_trace_record(
    *,
    question: str,
    intent: SearchIntent,
    candidate_set: CandidateSet | None,
    payload: AnswerPayload,
    node_sequence: list[str],
    llm_calls: int = 0,
    llm_input_tokens: int = 0,
    llm_output_tokens: int = 0,
    latency_ms: int = 0,
) -> TraceRecord:
    """実行結果から TraceRecord を組み立てる（I/O を伴わない純関数）。

    candidate_set は unclear ルートでは None になる（rank_candidates を通らないため）。
    """
    return TraceRecord(
        trace_id=uuid.uuid4().hex,
        ts=datetime.now().astimezone().isoformat(),
        question=question,
        intent=TraceIntent(
            mode=intent.mode,
            anchor_code=intent.anchor_code,
            anchor_status=intent.anchor_status,
            unclear_kind=intent.unclear_kind,
            alternatives=list(intent.alternatives),
            matched_rule=intent.matched_rule,
        ),
        route=intent.mode,
        node_sequence=list(node_sequence),
        traversed_edges=list(candidate_set.traversed_edges) if candidate_set else [],
        candidates=list(candidate_set.candidates) if candidate_set else [],
        notes=list(candidate_set.notes) if candidate_set else [],
        llm_calls=llm_calls,
        llm_input_tokens=llm_input_tokens,
        llm_output_tokens=llm_output_tokens,
        answer=payload.answer,
        cited_codes=list(payload.cited_codes),
        latency_ms=latency_ms,
    )


def append_trace(record: TraceRecord, directory: Path | None = None) -> Path:
    """JSONL に1行追記して書き込み先を返す。"""
    target = directory if directory is not None else default_trace_dir()
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"trace-{datetime.now().astimezone():%Y%m%d}.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(record.model_dump_json() + "\n")
    return path
