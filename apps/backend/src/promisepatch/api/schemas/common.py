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
