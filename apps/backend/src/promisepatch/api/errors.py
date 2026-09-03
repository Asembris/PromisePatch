"""One error shape, and the handlers that guarantee it.

Every failure a client sees is ``{"error": {"code", "message"}}``. The code is a stable
identifier a caller may branch on; the message is a sentence a human may read. Neither ever
carries a stack trace, a SQL fragment, a driver message, a connection string, a password hash
or a session id -- an error is the easiest place in a system to leak the thing it was
protecting, so the redaction is structural rather than remembered case by case.

Unexpected exceptions are the important case. The traceback is logged with the request's
correlation id and the client is told only that something failed and which correlation id to
quote. That keeps the operator's copy complete and the attacker's copy empty.
"""

from __future__ import annotations

from typing import Final

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from promisepatch.api.middleware import CORRELATION_HEADER
from promisepatch.api.schemas.common import ErrorBody, ErrorResponse
from promisepatch.observability import get_logger

logger = get_logger(__name__)

INTERNAL_ERROR: Final = "INTERNAL_ERROR"
INVALID_REQUEST: Final = "INVALID_REQUEST"

STATUS_CODES: Final[dict[int, str]] = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    422: INVALID_REQUEST,
    429: "TOO_MANY_REQUESTS",
    503: "UNAVAILABLE",
}
"""Fallback codes for failures raised as a bare status, so no response is left uncoded."""


class ApiError(HTTPException):
    """A failure with a code chosen deliberately rather than derived from a status.

    A subclass of :class:`~fastapi.HTTPException` so that raising one from a dependency works
    the way FastAPI already expects, and so a route that raises the framework's own exception
    still produces the same envelope.
    """

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code
        self.message = message


def envelope(status_code: int, code: str, message: str, correlation_id: str | None) -> JSONResponse:
    """Render the one error shape, echoing the correlation id back to the caller."""
    body = ErrorResponse(error=ErrorBody(code=code, message=message))
    headers = {CORRELATION_HEADER: correlation_id} if correlation_id else None
    return JSONResponse(status_code=status_code, content=body.model_dump(), headers=headers)


def _correlation_id(request: Request) -> str | None:
    value = getattr(request.state, "correlation_id", None)
    return str(value) if value else None


def register_error_handlers(app: FastAPI) -> None:
    """Install the handlers. Every route in the application is covered by them."""

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, ApiError)
        return envelope(error.status_code, error.code, error.message, _correlation_id(request))

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, error: Exception) -> JSONResponse:
        assert isinstance(error, HTTPException)
        code = STATUS_CODES.get(error.status_code, INTERNAL_ERROR)
        message = error.detail if isinstance(error.detail, str) else code.replace("_", " ").lower()
        return envelope(error.status_code, code, message, _correlation_id(request))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, error: Exception) -> JSONResponse:
        # The framework's own detail names the offending fields, which is useful to a
        # developer and is also a description of our internals. The fields are logged and the
        # client is told the shape was wrong.
        logger.info("api.request_invalid", errors=str(error))
        return envelope(
            422,
            INVALID_REQUEST,
            "the request body or parameters did not match the expected shape",
            _correlation_id(request),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, error: Exception) -> JSONResponse:
        correlation_id = _correlation_id(request)
        logger.exception(
            "api.unhandled_error",
            path=request.url.path,
            method=request.method,
            correlation_id=correlation_id,
        )
        return envelope(
            500,
            INTERNAL_ERROR,
            "the request could not be completed; quote the correlation id when reporting it",
            correlation_id,
        )
