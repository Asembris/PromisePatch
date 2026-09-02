"""Liveness.

``/healthz`` must never touch a database, a queue or a provider: it answers "is this process
alive", and a dependency check here would make an unrelated outage look like a dead task and
trigger a pointless restart. Readiness — which does check dependencies — arrives with the
database.

``boot_id`` changes on every process start. It is what makes the on-camera worker restart
verifiable rather than asserted.
"""

from __future__ import annotations

from fastapi import APIRouter
from starlette.requests import Request

from promisepatch import __version__
from promisepatch.api.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="api",
        version=__version__,
        boot_id=request.app.state.boot_id,
    )
