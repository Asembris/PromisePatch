"""The readiness contract.

Readiness answers a different question from liveness, so it is a different shape. ``/healthz``
says "this process is up"; ``/readyz`` says "this process can do its job", which means naming
the dependencies it checked and what each one said. A bare ``{"status": "not_ready"}`` would
tell an operator to go and look at logs, which is the thing a readiness probe exists to avoid.

Nothing here can carry a credential. The database section reports the role it authenticated as
and whether the connection worked; a failure is a short, fixed sentence, never the driver's
message, because a connection error commonly quotes the host, the user and occasionally the
whole DSN.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ReadinessStatus = Literal["ready", "not_ready"]


class DatabaseReadiness(BaseModel):
    """Whether the runtime connection works, and who it turned out to be.

    ``current_user`` is asked of the server rather than parsed out of the URL: on a pooled
    endpoint the login can be rewritten in transit, and only the server's answer governs what
    the database will actually permit.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    configured: bool
    reachable: bool
    current_user: str | None
    expected_user: str
    detail: str | None = None


class MigrationReadiness(BaseModel):
    """Whether the schema in the database is the schema this build expects."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    at_head: bool
    expected_revision: str
    actual_revision: str | None
    detail: str | None = None


class FixtureReadiness(BaseModel):
    """Whether a demo fixture is loaded.

    Absence is reported, not punished. A migrated database with no fixture is a perfectly
    valid state -- it is exactly what a fresh deployment looks like before anyone has run
    ``pp reset-demo-state`` -- and failing readiness on it would make a healthy process look
    broken. The frozen architecture asks readiness to check the database, not the demo data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    readable: bool
    present: bool
    fixture_name: str | None
    anchor_at: datetime | None
    loaded_at: datetime | None
    digest: str | None
    detail: str | None = None


class ReadinessResponse(BaseModel):
    """The whole answer: a verdict, and the evidence for it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ReadinessStatus
    service: str
    version: str
    boot_id: str
    database: DatabaseReadiness
    migrations: MigrationReadiness
    fixture: FixtureReadiness
