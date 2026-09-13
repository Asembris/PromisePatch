"""Schemas shared across routers."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Liveness only: the process is up and serving. It asserts nothing about readiness."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    service: str
    version: str
    boot_id: str
    image: str | None = None
    """The commit this image was built from, or ``None`` when it was not built from one.

    The one thing about a deployment that cannot be established from outside it. The package
    version moves once a release; the image tag names the commit, so this is what makes "which
    version is deployed" a question a caller can answer rather than one somebody asserts.
    """


class ErrorBody(BaseModel):
    """The inside of an error: a stable code, and a sentence for a person."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str


class ErrorResponse(BaseModel):
    """Every failure this API returns has this shape and no other."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    error: ErrorBody
