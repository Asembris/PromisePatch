"""Liveness and readiness -- two questions, deliberately answered by two endpoints.

``/healthz`` must never touch a database, a queue or a provider: it answers "is this process
alive", and a dependency check here would make an unrelated outage look like a dead task and
trigger a pointless restart.

``/readyz`` answers "can this process do its job", which means checking the dependencies it
genuinely cannot work without:

* the database is reachable **through the runtime application role** -- checked by asking the
  server who it is, because a probe that authenticated as the migration user would be
  reporting on a connection nobody serves traffic on;
* the schema revision in the database matches the revision this build expects;
* the fixture, if one is loaded, is readable.

The fixture is reported and never fatal. A migrated database with no fixture is what a fresh
deployment looks like before anyone has run ``pp reset-demo-state``, and failing readiness on
it would make a healthy process look broken. The frozen architecture asks readiness to check
the database, not the demo data.

``boot_id`` changes on every process start. It is what makes the on-camera worker restart
verifiable rather than asserted.
"""

from __future__ import annotations

from typing import Final

from fastapi import APIRouter, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.requests import Request

from promisepatch import __version__
from promisepatch.api.schemas.common import HealthResponse
from promisepatch.api.schemas.readiness import (
    DatabaseReadiness,
    FixtureReadiness,
    MigrationReadiness,
    ReadinessResponse,
)
from promisepatch.db import HEAD_REVISION, RuntimeDatabase
from promisepatch.db.boundary import RUNTIME_ROLE
from promisepatch.db.models import FixtureState
from promisepatch.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])

UNREACHABLE: Final = "the database could not be reached over the runtime connection"
"""A fixed sentence. A driver's own connection error routinely quotes the host, the login and
sometimes the whole DSN, none of which belongs in an unauthenticated response body."""

REVISION_QUERY: Final = text("SELECT version_num FROM promisepatch.alembic_version")


def migration_readiness(actual_revision: str | None) -> MigrationReadiness:
    """Compare the revision the database reports with the one this build was written for."""
    at_head = actual_revision == HEAD_REVISION
    return MigrationReadiness(
        at_head=at_head,
        expected_revision=HEAD_REVISION,
        actual_revision=actual_revision,
        detail=None
        if at_head
        else "the database schema revision is not the one this build expects",
    )


async def read_fixture(connection: AsyncConnection) -> FixtureReadiness:
    """What the fixture table says, including the case where it says nothing.

    Separated from the handler so it can be exercised against a database with the row and
    against one without it, rather than against a stand-in for the query.
    """
    row = (await connection.execute(select(FixtureState.__table__))).mappings().first()
    return FixtureReadiness(
        readable=True,
        present=row is not None,
        fixture_name=None if row is None else row["fixture_name"],
        anchor_at=None if row is None else row["anchor_at"],
        loaded_at=None if row is None else row["loaded_at"],
        digest=None if row is None else row["fixture_digest"],
        detail=None if row is not None else "no fixture is loaded",
    )


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="api",
        version=__version__,
        boot_id=request.app.state.boot_id,
    )


@router.get("/readyz", response_model=ReadinessResponse, summary="Readiness probe")
async def readyz(request: Request, response: Response) -> ReadinessResponse:
    database: RuntimeDatabase | None = request.app.state.database
    boot_id: str = request.app.state.boot_id

    if database is None:
        return _not_ready(
            response,
            boot_id,
            database=DatabaseReadiness(
                configured=False,
                reachable=False,
                current_user=None,
                expected_user=RUNTIME_ROLE,
                detail="PP_DATABASE_URL is not configured",
            ),
            migrations=MigrationReadiness(
                at_head=False,
                expected_revision=HEAD_REVISION,
                actual_revision=None,
                detail="not checked: no database connection",
            ),
            fixture=FixtureReadiness(
                readable=False,
                present=False,
                fixture_name=None,
                anchor_at=None,
                loaded_at=None,
                digest=None,
                detail="not checked: no database connection",
            ),
        )

    try:
        async with database.connect() as connection:
            current_user = await database.current_user(connection)
            revision = await connection.scalar(REVISION_QUERY)
            fixture = await read_fixture(connection)
    except Exception:
        # Deliberately every exception, not just ``SQLAlchemyError``. A name that does not
        # resolve raises ``socket.gaierror`` straight through the driver, and a readiness probe
        # that answered 500 with a stack trace for the most ordinary outage there is -- the
        # database host being unreachable -- would be failing at its one job. Anything that
        # stops this check completing means the same thing to a load balancer: not ready.
        #
        # Logged in full for the operator, reduced to one sentence for the caller.
        logger.exception("api.readiness_failed")
        return _not_ready(
            response,
            boot_id,
            database=DatabaseReadiness(
                configured=True,
                reachable=False,
                current_user=None,
                expected_user=RUNTIME_ROLE,
                detail=UNREACHABLE,
            ),
            migrations=MigrationReadiness(
                at_head=False,
                expected_revision=HEAD_REVISION,
                actual_revision=None,
                detail="not checked: the database could not be reached",
            ),
            fixture=FixtureReadiness(
                readable=False,
                present=False,
                fixture_name=None,
                anchor_at=None,
                loaded_at=None,
                digest=None,
                detail="not checked: the database could not be reached",
            ),
        )

    right_role = current_user == RUNTIME_ROLE
    database_status = DatabaseReadiness(
        configured=True,
        reachable=True,
        current_user=current_user,
        expected_user=RUNTIME_ROLE,
        detail=None if right_role else "the runtime connection authenticated as an unexpected role",
    )
    migrations = migration_readiness(None if revision is None else str(revision))

    ready = right_role and migrations.at_head
    if not ready:
        return _not_ready(
            response, boot_id, database=database_status, migrations=migrations, fixture=fixture
        )
    return ReadinessResponse(
        status="ready",
        service="api",
        version=__version__,
        boot_id=boot_id,
        database=database_status,
        migrations=migrations,
        fixture=fixture,
    )


def _not_ready(
    response: Response,
    boot_id: str,
    *,
    database: DatabaseReadiness,
    migrations: MigrationReadiness,
    fixture: FixtureReadiness,
) -> ReadinessResponse:
    """Answer with the evidence and a 503, so a load balancer takes this task out of rotation."""
    response.status_code = 503
    return ReadinessResponse(
        status="not_ready",
        service="api",
        version=__version__,
        boot_id=boot_id,
        database=database,
        migrations=migrations,
        fixture=fixture,
    )
