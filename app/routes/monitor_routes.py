"""Painel operacional local, somente com metadados sem conteúdo do chat."""

import ipaddress
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.observability import storage
from app.observability.metrics import snapshot

router = APIRouter(tags=["Observabilidade"])
STATIC = Path(__file__).resolve().parents[1] / "observability" / "static"
ASSETS = {
    "monitor.css": "text/css",
    "monitor.js": "text/javascript",
    "brand.css": "text/css",
    "icon/logo-quimia-symbol.svg": "image/svg+xml",
    "icon/logo-quimia.svg": "image/svg+xml",
    "icon/geral.svg": "image/svg+xml",
    "icon/history.svg": "image/svg+xml",
    "icon/puzzle.svg": "image/svg+xml",
    "icon/calendar-fold.svg": "image/svg+xml",
    "icon/chevron-right.svg": "image/svg+xml",
    "icon/chevron-left.svg": "image/svg+xml",
}


def require_local_access(request: Request):
    try:
        local = ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        local = False
    if not local:
        raise HTTPException(403, "O painel de observabilidade é restrito ao computador local.")


@router.get("/monitor", dependencies=[Depends(require_local_access)])
def monitor(days: int = Query(7, ge=1, le=30), turns_per_user: float = Query(5, gt=0, le=10000),
            minutes_saved: float | None = Query(None, ge=0, le=10000),
            hourly_cost: float | None = Query(None, ge=0, le=100000),
            fixed_weekly_cost: float = Query(0, ge=0, le=10000000),
            assumed_resolution_rate: float = Query(.7, ge=0, le=1),
            planned_input_tokens: int = Query(10000, ge=0, le=10000000),
            planned_output_tokens: int = Query(2000, ge=0, le=10000000)):
    try:
        rows, truncated = storage.records(days)
    except storage.StorageUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    return snapshot(rows, days=days, turns_per_user=turns_per_user, minutes_saved=minutes_saved,
                    hourly_cost=hourly_cost, fixed_weekly_cost=fixed_weekly_cost,
                    assumed_resolution_rate=assumed_resolution_rate,
                    planned_input_tokens=planned_input_tokens, planned_output_tokens=planned_output_tokens,
                    truncated=truncated)


class ResolutionFeedback(BaseModel):
    resolved: bool


@router.post("/monitor/feedback/{trace_id}", dependencies=[Depends(require_local_access)])
def resolution(trace_id: UUID, body: ResolutionFeedback):
    try:
        storage.feedback(str(trace_id), body.resolved)
    except KeyError:
        raise HTTPException(404, "Turno não encontrado.") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    except storage.StorageUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    return {"trace_id": str(trace_id), "resolved": body.resolved}


@router.get("/monitor.html", include_in_schema=False)
def page():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/monitor-assets/{filename:path}", include_in_schema=False)
def asset(filename: str):
    if filename not in ASSETS:
        raise HTTPException(404)
    return FileResponse(STATIC / filename, media_type=ASSETS[filename],
                        headers={"X-Content-Type-Options": "nosniff"})
