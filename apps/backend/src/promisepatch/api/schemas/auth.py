"""Authentication contracts.

The response type is the interesting one: it is a deliberately narrow projection of the
``workers`` row. ``password_hash`` is not on it, the session id is not on it, and the CSRF
token is not on it -- ``extra="forbid"`` plus an explicit field list means a column added to
the table later cannot start being served by accident.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """Credentials. Bounded lengths so an oversized body is rejected before it is hashed."""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class WorkerIdentity(BaseModel):
    """Everything a client may know about the logged-in worker, and nothing more."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    username: str
    display_name: str
    role: str


class WorkerResponse(BaseModel):
    """The body of ``login`` and of ``me``: one shape for "who am I"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    worker: WorkerIdentity
