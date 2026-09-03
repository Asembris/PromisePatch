"""``GET /api/resources`` -- ingredient availability and equipment state.

The numbers come from ``promise_graph.availability`` over a snapshot loaded in one
repeatable-read transaction. This module chooses the horizon and serves the result; it
computes no quantity of its own.

``at`` may be supplied to ask about a different moment, which is how a display offers "by
lunchtime" against "by close". Omitted, it is the last due time in the order book.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from promisepatch.api.dependencies import DatabaseDep, PrincipalDep, now
from promisepatch.api.errors import ApiError
from promisepatch.api.schemas.resources import ResourcesResponse
from promisepatch.api.views import resources as view
from promisepatch.graph import load_snapshot, snapshot_session

router = APIRouter(prefix="/api", tags=["evidence"])

HORIZON_DESCRIPTION = (
    "Horizon to compute availability by, as an ISO-8601 instant with a timezone. "
    "Defaults to the last due time in the order book."
)


@router.get("/resources", response_model=ResourcesResponse, summary="Resource availability")
async def list_resources(
    principal: PrincipalDep,
    database: DatabaseDep,
    at: Annotated[datetime | None, Query(description=HORIZON_DESCRIPTION)] = None,
) -> ResourcesResponse:
    if at is not None and at.tzinfo is None:
        # A naive instant cannot be compared with the stored timestamps at all: every engine
        # record rejects a datetime without a timezone, so this fails here with a sentence
        # rather than deeper down with a TypeError.
        raise ApiError(
            status_code=422,
            code="INVALID_REQUEST",
            message="at must include a timezone offset",
        )

    moment = now()
    async with snapshot_session(database.engine) as session:
        snapshot = await load_snapshot(session)
    horizon = at if at is not None else view.default_horizon(snapshot, now=moment)
    return view.build(snapshot, at=horizon, now=moment, generated_at=moment)
