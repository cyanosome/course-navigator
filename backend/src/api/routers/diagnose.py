"""診断の API（navi-v1）: 質問に答えると履修プランを返す。LLM は使わない。

- GET /diagnose/config?department_id= … いま有効な設定（JSON のまま）と version
- POST /diagnose/plan … 答えからプラン。版が違えば 409、答えの誤り（知らない質問・選択肢、数の違い）は 422
外から見えるパスは `/api` の後ろ（Traefik が `/api` を剥がす）。成功の応答に X-Navi-Contract を付ける。
設定とデータの読み方は依存（get_config_loader・get_catalog_loader）で差し替えられる（テストは偽物を渡す）。
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.contract import set_contract_header
from course_core.catalog.registry import DepartmentEntry, load_departments
from course_core.diagnose.answers import validate_answers
from course_core.diagnose.config import ConfigError, ConfigNotFoundError, LoadedConfig, load_config, validate_config
from course_core.diagnose.engine import build_plan
from course_core.diagnose.model import Catalog
from course_core.diagnose.source import load_catalog
from course_core.schemas.diagnose import DiagnoseConfigOut, DiagnosePlanIn, DiagnosePlanOut

__all__ = ["CatalogLoader", "ConfigLoader", "get_catalog_loader", "get_config_loader", "router"]

router = APIRouter(prefix="/diagnose", tags=["diagnose"], dependencies=[Depends(set_contract_header)])

logger = logging.getLogger(__name__)

ConfigLoader = Callable[[str], LoadedConfig]
CatalogLoader = Callable[[Request, DepartmentEntry], Awaitable[Catalog]]


async def _catalog_from_db(request: Request, department: DepartmentEntry) -> Catalog:
    state: Any = request.app.state  # app.state は型を持たない（境界）
    async with state.db_pool.acquire() as conn, state.neo4j_driver.session() as session:
        return await load_catalog(conn, session, department)


def get_config_loader() -> ConfigLoader:
    return load_config


def get_catalog_loader() -> CatalogLoader:
    return _catalog_from_db


def _department(department_id: str) -> DepartmentEntry:
    department = load_departments().get(department_id)
    if department is None:
        raise HTTPException(status_code=404, detail=f"学科が見つかりません: {department_id}")
    return department


def _loaded(loader: ConfigLoader, department_id: str) -> LoadedConfig:
    try:
        return loader(department_id)
    except ConfigNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConfigError:
        logger.exception("診断の設定が読めません（学科 %s）", department_id)
        raise HTTPException(status_code=500, detail="診断の設定に誤りがあります。") from None


@router.get("/config", response_model=DiagnoseConfigOut)
def get_config(
    department_id: Annotated[str, Query()],
    config_loader: Annotated[ConfigLoader, Depends(get_config_loader)],
) -> DiagnoseConfigOut:
    """いま有効な設定（質問・選択肢・重み・理由の文）と version。"""
    department = _department(department_id)
    loaded = _loaded(config_loader, department.id)
    return DiagnoseConfigOut(department_id=department.id, version=loaded.config.version, config=loaded.raw)


@router.post("/plan", response_model=DiagnosePlanOut)
async def make_plan(
    body: DiagnosePlanIn,
    request: Request,
    config_loader: Annotated[ConfigLoader, Depends(get_config_loader)],
    catalog_loader: Annotated[CatalogLoader, Depends(get_catalog_loader)],
) -> DiagnosePlanOut:
    """答えから、埋める学期ごとの科目と理由を返す。同じ設定・同じデータ・同じ答えなら同じプラン。"""
    department = _department(body.department_id)
    loaded = _loaded(config_loader, department.id)
    if body.config_version != loaded.config.version:
        raise HTTPException(
            status_code=409,
            detail=f"診断の設定の版が違います（送られた版 {body.config_version}、いまの版 {loaded.config.version}）。",
        )
    answers, errors = validate_answers(loaded.config, body.answers)
    if errors:
        raise HTTPException(status_code=422, detail="答えに誤りがあります: " + "; ".join(errors))

    catalog = await catalog_loader(request, department)
    issues = validate_config(loaded.raw, department_id=department.id, known_groups=catalog.group_ids)
    if issues:
        logger.error(
            "診断の設定が系統図と合いません（学科 %s）: %s",
            department.id,
            "; ".join(f"{issue.path}: {issue.message}" for issue in issues),
        )
        raise HTTPException(status_code=500, detail="診断の設定に誤りがあります。")
    return build_plan(loaded.config, catalog, answers)
