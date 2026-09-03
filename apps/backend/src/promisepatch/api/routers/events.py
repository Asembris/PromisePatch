"""``GET /events`` -- the live feed the evidence UI keeps open.

The endpoint is thin on purpose: it authenticates the caller, reads the resume cursor off the
request, and hands back a stream. What that stream contains, and why a dropped notification
cannot cost a subscriber any state, is :mod:`promisepatch.api.stream`.

Three things about the HTTP shape are worth stating:

* **It is a session endpoint like every other read.** No token, no query-string credential, no
  separate authentication path -- the same cookie that admits a caller to ``/api/promises``
  admits it here, and a revoked session is refused on the next connection attempt like anything
  else. A browser's ``EventSource`` sends cookies for a same-origin stream, which is what the
  UI opens.
* **Buffering is switched off explicitly.** An intermediary that helpfully accumulates a
  response until it looks worth forwarding turns a live feed into a slow one, so the response
  says not to cache and not to buffer. ``X-Accel-Buffering`` is the nginx spelling of it and is
  ignored harmlessly elsewhere.
* **The frames are notifications, not state.** A client reacts to one by refetching the read
  API the event concerns. Nothing here streams a reconstructed view of the application.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter
from starlette.requests import Request
from starlette.responses import StreamingResponse

from promisepatch.api.dependencies import BroadcasterDep, DatabaseDep, StreamPrincipalDep
from promisepatch.api.errors import ApiError
from promisepatch.api.stream import (
    LAST_EVENT_ID_HEADER,
    DatabaseEventReader,
    InvalidCursorError,
    event_stream,
    parse_cursor,
)
from promisepatch.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["events"])

MEDIA_TYPE: Final = "text/event-stream"

STREAM_HEADERS: Final = {
    "Cache-Control": "no-cache, no-store, no-transform",
    "X-Accel-Buffering": "no",
}


@router.get(
    "/events",
    summary="Domain event stream",
    response_class=StreamingResponse,
    responses={200: {"content": {MEDIA_TYPE: {}}, "description": "An open event stream"}},
)
async def events(
    request: Request,
    principal: StreamPrincipalDep,
    database: DatabaseDep,
    broadcaster: BroadcasterDep,
) -> StreamingResponse:
    """Open a live feed of domain events, resuming from ``Last-Event-ID`` when one is given."""
    try:
        cursor = parse_cursor(request.headers.get(LAST_EVENT_ID_HEADER))
    except InvalidCursorError as error:
        raise ApiError(
            status_code=400,
            code="INVALID_LAST_EVENT_ID",
            message=str(error),
        ) from error

    logger.info("events.stream_opened", worker_id=principal.worker_id, cursor=cursor)
    return StreamingResponse(
        event_stream(
            reader=DatabaseEventReader(database),
            broadcaster=broadcaster,
            cursor=cursor,
        ),
        media_type=MEDIA_TYPE,
        headers=dict(STREAM_HEADERS),
    )
