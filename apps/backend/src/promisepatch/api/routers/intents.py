"""``/internal/intents/*`` -- the case engine's entrance for the conversational surface.

Two endpoints in this slice, ``report`` and ``status``, and they are the only way a tool call
reaches a case. Everything about them is shaped by one sentence: **the model understands; the
deterministic protocol authorizes.**

**It authenticates a service, not a person.** The caller is the ``mcp`` process. There is no
session cookie and no CSRF token, because a server holds neither and a cookie it did hold would
make every tool call a cross-site request. What it presents is a shared secret compared in
constant time, and with none configured this router answers ``503`` rather than serving an
unauthenticated intent.

**It decides who is speaking, and the wire does not.** The attesting worker comes from
:attr:`~promisepatch.config.Settings.surface_worker_id` -- this server's own configuration --
and there is no request field that could carry an actor, so no orchestrator, model or
compromised intermediary has an actor to choose. The same is true of the clock: "when did this
happen" is read here, because a caller that could set it could backdate a physical claim.

**It authorises nothing that the domain would not authorise anyway.** ``require_worker`` and
``require_permitted`` run inside the domain services exactly as they do for the operator CLI. A
tool that was offered is not a tool that is allowed; this router adds a credential and subtracts
nothing.

**It interprets nothing.** ``report`` stores the words and enqueues the durable work. The
interpreter runs in the worker, under a lease, in a transaction that can be rolled back --
which is the only place a decision that settles a delivery belongs.

**``status`` is rendered here, not paraphrased there.** The answer carries sentences produced
by :mod:`promisepatch.domain.status_view` from the durable case, so a conversational layer
delivers deterministic status rather than restating it. A layer that re-words "planned" is one
word away from "done".
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Header
from sqlalchemy import select
from starlette.requests import Request

from promisepatch.api.dependencies import DatabaseDep, SettingsDep
from promisepatch.api.errors import ApiError
from promisepatch.api.schemas.intents import (
    CaseStatusResponse,
    PromiseStatus,
    ReportAccepted,
    ReportIntent,
    StatusIntent,
)
from promisepatch.db.models import Case
from promisepatch.domain import analysis, intake, status_view
from promisepatch.observability import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/internal/intents", tags=["intents"])

SERVICE_TOKEN_HEADER: Final = "X-Service-Token"

REJECTED = ApiError(
    status_code=401,
    code="SERVICE_TOKEN_INVALID",
    message="this caller does not present the configured service token",
)
"""One rejection for missing, wrong and malformed alike. A caller has no legitimate use for the
difference, and telling them apart would confirm which half they got right."""

UNCONFIGURED = ApiError(
    status_code=503,
    code="INTENTS_NOT_CONFIGURED",
    message="this process has no service token and surface worker configured",
)
"""No credential and no attestor, no intents. Defaulting either one would mean every copy of
this repository shared a secret, or that an intake could arrive with nobody on the record."""


def _authenticate(settings: SettingsDep, presented: str | None) -> str:
    """Check the service credential and return the worker this surface attests as.

    Both halves in one function on purpose: the credential and the identity are decided here,
    together, from configuration, so there is no code path that resolves one without the other.
    """
    if not settings.intents_configured:
        raise UNCONFIGURED
    expected = settings.require_internal_service_token()
    if not presented or not hmac.compare_digest(presented, expected):
        logger.warning("intents.rejected", reason="service_token")
        raise REJECTED
    return settings.require_surface_worker_id()


def _correlation_id(request: Request) -> UUID | None:
    """This request's correlation id, when the caller sent one that is really an identifier.

    The middleware honours any inbound ``X-Correlation-ID`` so a tool call and the case
    transitions it causes stitch into one trace. The audit ledger's column is a UUID, so a
    caller that sent something else gets a fresh one on the row rather than a rejected request:
    a malformed trace header is not a reason to refuse an attestation somebody made.
    """
    value = getattr(request.state, "correlation_id", None)
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


@router.post(
    "/report",
    response_model=ReportAccepted,
    status_code=202,
    summary="Open a case for one spoken physical exception",
)
async def report(
    request: Request,
    intent: ReportIntent,
    settings: SettingsDep,
    database: DatabaseDep,
    service_token: Annotated[str | None, Header(alias=SERVICE_TOKEN_HEADER)] = None,
) -> ReportAccepted:
    """Store what a worker said, verbatim, and enqueue the work that reads it.

    ``202`` rather than ``201``: what is durable when this answers is a statement and a queued
    step, and nothing has yet been concluded about anybody's order. Saying "created" about a
    recovery that has not been planned would be the first of the lies this product exists not
    to tell.
    """
    worker_id = _authenticate(settings, service_token)
    # The clock is this server's, never the caller's -- a caller that could set it could
    # backdate a physical claim. A redelivery of the same command reuses the instant its own
    # statement recorded, because it is that statement arriving twice rather than a second one.
    stored = await intake.observed_at_for(database, command_id=intent.command_id)
    try:
        result = await intake.open_physical_exception(
            database,
            command_id=intent.command_id,
            worker_id=worker_id,
            raw_text=intent.text,
            observed_at=stored or datetime.now(UTC),
            correlation_id=_correlation_id(request),
        )
    except intake.UnknownWorkerError as error:
        # A deployment problem, not a caller problem: this server named an attestor its own
        # database does not have. Answering 4xx would tell the caller to fix something that is
        # not theirs.
        logger.error("intents.surface_worker_unknown", worker=worker_id)
        raise ApiError(
            status_code=503,
            code="SURFACE_WORKER_UNKNOWN",
            message="the configured surface worker does not exist in this deployment",
        ) from error
    except intake.IntakeConflictError as error:
        raise ApiError(
            status_code=409,
            code="COMMAND_CONFLICT",
            message="this command id was already used for a different statement",
        ) from error

    logger.info(
        "intents.report.accepted",
        case_id=str(result.case_id),
        created=result.created,
        worker=worker_id,
    )
    return ReportAccepted(
        case_id=result.case_id,
        statement_id=result.statement_id,
        state=result.state,
        created=result.created,
        attested_by=worker_id,
    )


@router.post(
    "/status",
    response_model=CaseStatusResponse,
    summary="Read one case as it currently stands",
)
async def status(
    intent: StatusIntent,
    settings: SettingsDep,
    database: DatabaseDep,
    service_token: Annotated[str | None, Header(alias=SERVICE_TOKEN_HEADER)] = None,
) -> CaseStatusResponse:
    """Project the durable case into the product's vocabulary and render it. A read, only.

    ``require_permitted`` runs here as well as on the writes. A case id is a value a model can
    put in a tool argument, and the answer to "may I read somebody else's case" has to be the
    domain's answer rather than the transport's convenience.
    """
    worker_id = _authenticate(settings, service_token)
    try:
        async with database.connect() as connection:
            # Existence before permission, so the two refusals stay different answers. The
            # caller here is an authenticated internal service rather than the public, and a
            # conversation that cannot tell "there is no such case" from "that one is not
            # yours" has to guess which it was -- which is exactly how a model ends up saying
            # something untrue about a case it never reached. Case ids are UUIDs, so this is
            # not an enumeration surface, and the permission check itself is unchanged.
            if not await connection.scalar(select(Case.id).where(Case.id == intent.case_id)):
                raise analysis.CaseNotFoundError(f"case {intent.case_id} does not exist")
            await intake.require_permitted(connection, case_id=intent.case_id, worker_id=worker_id)
        current = await analysis.read_case_status(database, case_id=intent.case_id)
    except intake.NotPermittedError as error:
        raise ApiError(
            status_code=403,
            code="CASE_NOT_PERMITTED",
            message="this surface may not read that case",
        ) from error
    except analysis.CaseNotFoundError as error:
        raise ApiError(
            status_code=404,
            code="CASE_NOT_FOUND",
            message="no case by that id",
        ) from error

    view = status_view.project(current)
    return CaseStatusResponse(
        case_id=current.case_id,
        headline=view.headline.value,
        speech=status_view.render(view),
        needs_owner_attention=view.needs_owner_attention,
        exception_category=view.exception_category,
        threatened=tuple(_promise(item) for item in view.threatened),
        untouched=tuple(_promise(item) for item in view.untouched),
        untouched_count=len(view.untouched),
    )


def _promise(item: status_view.PromiseView) -> PromiseStatus:
    return PromiseStatus(
        promise_id=item.promise_id,
        customer_name=item.customer_name,
        order_external_id=item.order_external_id,
        state=item.state.value,
        phrase=item.phrase,
        authority=item.authority.value,
        reason=item.reason,
        deadline_at=item.deadline_at,
        track_id=item.track_id,
        track_state=item.track_state,
        classification=item.classification,
        rule_id=item.rule_id,
    )
