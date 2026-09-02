"""Request-scoped context.

One middleware, one job: give every request a correlation id, bind it for the duration of the
request so structlog carries it onto every line, and echo it back so a caller can quote it.
An inbound ``X-Correlation-ID`` is honoured, which is how a later phase will stitch an Alexa
turn, an MCP tool call and the case transitions it causes into one trace.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from promisepatch.observability.logging import bind_correlation_id, clear_context

CORRELATION_HEADER = "X-Correlation-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = request.headers.get(CORRELATION_HEADER) or str(uuid4())
        request.state.correlation_id = correlation_id
        bind_correlation_id(correlation_id)
        try:
            response = await call_next(request)
        finally:
            clear_context()
        response.headers[CORRELATION_HEADER] = correlation_id
        return response
