"""研究（調査のセッション・同意・ブロック・イベントの記録・変種の旗）の API（navi-v1）。

約束は api-contract.md 3 章（R1〜R9）。外から見えるパスは /api/research/…（Traefik が /api を剥がす）。
- セッションはトークン（カード）からだけ始まる。トークン・セッションの無い要求は何も書かない（計画 4.2）。
- pid・系列・条件・ブロック・旗はサーバーが付け、クライアントの申告を使わない。
- 氏名・学籍番号・IP・User-Agent は受け取らず、書かない。
"""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any, Final

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from course_core.repositories import research_repo
from course_core.research.settings import default_variant_id, research_dev
from course_core.research.sink import SESSION_COOKIE, session_id_from_request
from course_core.research.store import (
    ResearchConflict,
    ResearchStore,
    SessionNotFound,
    SessionState,
    default_store,
    to_session_out,
)
from course_core.research.study import start_violations
from course_core.research.variants import FLAGS_VERSION, VARIANTS
from course_core.schemas.research import (
    BlockStartOut,
    ConsentIn,
    EventBatchIn,
    EventBatchOut,
    SessionOut,
    SessionStartIn,
    VariantOut,
)

CONTRACT_HEADER: Final = "X-Navi-Contract"
CONTRACT_VERSION: Final = "navi-v1"
FRONTEND_HEADER: Final = "X-Navi-Frontend"
_FRONTEND_VERSION_MAX: Final = 64
MAX_EVENT_BODY_BYTES: Final = 256 * 1024
_NO_SESSION: Final = "調査のセッションがありません。カードの URL から開いてください。"

DataStatusProbe = Callable[[Request], Awaitable[dict[str, Any]]]


async def _contract_header(response: Response) -> None:
    response.headers[CONTRACT_HEADER] = CONTRACT_VERSION


router = APIRouter(prefix="/research", tags=["research"], dependencies=[Depends(_contract_header)])


def get_research_store() -> ResearchStore:
    """FastAPI の依存。テストは環境変数 RESEARCH_DATA_DIR で置き場所を変える。"""
    return default_store()


async def neo4j_data_status(request: Request) -> dict[str, Any]:
    """セッションの開始で数えるデータの状態（session_start の data_status）。Neo4j の不通は共通ハンドラが 503。"""
    driver = getattr(request.app.state, "neo4j_driver", None)
    if driver is None:
        raise RuntimeError("Neo4j のドライバがありません。SIMILAR_TO を数えられないので開始しません。")
    async with driver.session() as session:
        edges, models = await research_repo.count_similar_to(session)
    return {"similar_to_edges": edges, "similar_models": models}


def get_data_status_probe() -> DataStatusProbe:
    """FastAPI の依存。テストは dependency_overrides で決まった数を返す偽物を差し込む。"""
    return neo4j_data_status


@contextmanager
def _as_http_errors() -> Iterator[None]:
    try:
        yield
    except ResearchConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except SessionNotFound as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _NO_SESSION) from exc


def _frontend_version(request: Request) -> str | None:
    value = request.headers.get(FRONTEND_HEADER, "").strip()
    return value[:_FRONTEND_VERSION_MAX] or None


def _require_session(request: Request, store: ResearchStore) -> SessionState:
    session_id = session_id_from_request(request)
    state = store.session(session_id) if session_id else None
    if state is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _NO_SESSION)
    return state


def _is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip().lower() == "https"


def _session_out(store: ResearchStore, state: SessionState) -> SessionOut:
    return to_session_out(store.load_study(state.study_id), state)


# --- R1〜R7 調査のセッション ---------------------------------------------------------


@router.post("/sessions", response_model=SessionOut)
async def start_session(
    body: SessionStartIn,
    request: Request,
    response: Response,
    store: ResearchStore = Depends(get_research_store),
    probe: DataStatusProbe = Depends(get_data_status_probe),
) -> SessionOut:
    """R1: カードのトークンでセッションを始める。同じトークンの2回目は前のセッションを返す（タブの開き直し）。"""
    found = store.find_by_token(body.token)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "カードのトークンが見つかりません。")
    study, participant = found
    state = store.session_for_pid(study.study_id, participant.pid)
    if state is None:
        if participant.withdrawn:
            raise HTTPException(status.HTTP_409_CONFLICT, "このカードは撤回済みです。")
        if study.active_arm is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "study の腕が未決定です。")
        data_status = await probe(request)
        violations = start_violations(
            study,
            similar_to_edges=data_status["similar_to_edges"],
            similar_models=data_status["similar_models"],
        )
        if violations:
            raise HTTPException(status.HTTP_409_CONFLICT, "開始できません: " + " / ".join(violations))
        with _as_http_errors():
            state = store.start_session(
                study.study_id,
                participant.pid,
                data_status=data_status,
                frontend_version=_frontend_version(request),
            )
    if state.ended_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "このカードのセッションは終了しています。")
    response.set_cookie(
        SESSION_COOKIE,
        state.session_id,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
        path="/",
    )
    return _session_out(store, state)


@router.get("/sessions/current", response_model=SessionOut)
async def current_session(request: Request, store: ResearchStore = Depends(get_research_store)) -> SessionOut:
    """R2: 開き直したときの再開。セッションが無いか終わっていれば 404。"""
    session_id = session_id_from_request(request)
    state = store.session(session_id) if session_id else None
    if state is None or state.ended_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_SESSION)
    return _session_out(store, state)


@router.post("/consent", response_model=SessionOut)
async def record_consent(
    body: ConsentIn, request: Request, store: ResearchStore = Depends(get_research_store)
) -> SessionOut:
    """R3: 同意の記録。版が study と違えば 409。同意しないときも記録して 200（画面は先へ進めない）。"""
    state = _require_session(request, store)
    with _as_http_errors():
        state = store.record_consent(
            state.session_id,
            consent_version=body.consent_version,
            form_serial=body.form_serial,
            agreed=body.agreed,
            frontend_version=_frontend_version(request),
        )
    return _session_out(store, state)


@router.post("/blocks/{block}/start", response_model=BlockStartOut)
async def start_block(
    request: Request,
    block: int = Path(..., ge=0),
    store: ResearchStore = Depends(get_research_store),
) -> BlockStartOut:
    """R4: ブロックの開始。同意の前・前のブロックが終わっていない・次の番号でないときは 409。"""
    state = _require_session(request, store)
    with _as_http_errors():
        state = store.start_block(state.session_id, block, frontend_version=_frontend_version(request))
    study = store.load_study(state.study_id)
    return BlockStartOut(
        plan=study.block_plan(state.sequence_id, state.arm, block),
        variant=study.variant_out(state.sequence_id, state.arm, block),
    )


@router.post("/blocks/{block}/end", response_model=SessionOut)
async def end_block(
    request: Request,
    block: int = Path(..., ge=0),
    store: ResearchStore = Depends(get_research_store),
) -> SessionOut:
    """R5: ブロックの終了。開いていないブロックは 409。"""
    state = _require_session(request, store)
    with _as_http_errors():
        state = store.end_block(state.session_id, block, frontend_version=_frontend_version(request))
    return _session_out(store, state)


@router.post("/events", response_model=EventBatchOut)
async def post_events(request: Request, store: ResearchStore = Depends(get_research_store)) -> EventBatchOut:
    """R6: イベントの一括送信（本文は EventBatchIn。1回 100 件・256 KB まで）。

    セッションが無ければ本文を読まずに 401（何も書かない）。sendBeacon の text/plain でも受けるよう、
    本文は自分で読んで検査する。種類が一覧に無いイベントを含めば 422。
    """
    state = _require_session(request, store)
    body = await request.body()
    if len(body) > MAX_EVENT_BODY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "本文が 256 KB を超えています。")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "本文が UTF-8 ではありません。") from exc
    try:
        batch = EventBatchIn.model_validate_json(text)
    except ValidationError as exc:
        # 送られた値は返さない（本文が大きく、自由記述を含みうるため）
        raise RequestValidationError(exc.errors(include_url=False, include_input=False)) from exc
    with _as_http_errors():
        result = store.append_client_events(
            state.session_id, batch.events, frontend_version=_frontend_version(request)
        )
    return EventBatchOut(
        accepted=result.accepted,
        duplicates=result.duplicates,
        last_seq=result.last_seq,
        warnings=result.warnings,
    )


@router.post("/sessions/current/end", status_code=status.HTTP_204_NO_CONTENT)
async def end_session(
    request: Request, response: Response, store: ResearchStore = Depends(get_research_store)
) -> None:
    """R7: セッションの終了。クッキーを消す。終わったセッションの2回目は何も書かずに 204。"""
    state = _require_session(request, store)
    with _as_http_errors():
        store.end_session(state.session_id, frontend_version=_frontend_version(request))
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=_is_https(request))


# --- R8・R9 変種の旗（記録しない） -------------------------------------------------------


def _variant_out(variant_id: str) -> VariantOut:
    return VariantOut(
        variant_id=variant_id, condition_id=None, flags=VARIANTS[variant_id], flags_version=FLAGS_VERSION
    )


@router.get("/variants/default", response_model=VariantOut)
async def default_variant() -> VariantOut:
    """R8: 調査でないとき（トークン無し）の画面の旗。環境変数 NAVI_DEFAULT_VARIANT（既定 V01）。"""
    return _variant_out(default_variant_id())


@router.get("/variants/{variant_id}", response_model=VariantOut)
async def variant_by_id(variant_id: str) -> VariantOut:
    """R9: 変種の旗（開発用）。RESEARCH_DEV=true のときだけ。それ以外は 404。"""
    if not research_dev() or variant_id not in VARIANTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return _variant_out(variant_id)
