"""``GET /api/promises`` -- the order book Live Operations reads.

The whole graph is read in one repeatable-read, read-only transaction through the snapshot
loader, which also locks its read set first so a concurrent fixture reset cannot be observed
half-applied. That matters more here than it looks: a partially truncated read would show an
order book with no promises at all, and "nothing is affected" is precisely the wrong answer to
arrive at silently.

There is no write route in this module, and there will not be one. The external order system
is the system of record; PromisePatch has no order editor, and the only way it ever changes an
order is a governed recovery amendment raised by a case.
"""

from __future__ import annotations

from fastapi import APIRouter

from promisepatch.api.dependencies import DatabaseDep, PrincipalDep, now
from promisepatch.api.schemas.promises import PromisesResponse
from promisepatch.api.views import promises as view
from promisepatch.graph import load_snapshot, snapshot_session

router = APIRouter(prefix="/api", tags=["evidence"])


@router.get("/promises", response_model=PromisesResponse, summary="The customer order book")
async def list_promises(principal: PrincipalDep, database: DatabaseDep) -> PromisesResponse:
    """Every customer promise, in due order, with the state needed to display it."""
    async with snapshot_session(database.engine) as session:
        snapshot = await load_snapshot(session)
        pointers = await view.track_pointers(session)
    return view.build(snapshot, pointers=pointers, generated_at=now())
