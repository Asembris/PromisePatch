"""``/internal/intents/*`` -- the case engine's entrance for the conversational surface.

Four endpoints, ``report``, ``clarify``, ``confirm`` and ``status``, and they are the only way
a tool call reaches a case. Everything about them is shaped by one sentence: **the model
understands; the deterministic protocol authorizes.**

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

**It interprets nothing.** ``report`` and ``clarify`` store the words and enqueue the durable
work. The interpreter runs in the worker, under a lease, in a transaction that can be rolled
back -- which is the only place a decision that settles a delivery belongs.

**A confirmation is bound to a plan, not to a case.** ``confirm`` carries the identity of the
plan ``status`` presented, and the domain compares it with the plan the case is offering under
the lock it writes with. A yes that quotes a superseded plan is refused; it is never applied to
whatever the case happens to hold when it arrives. Worker plan confirmation is also not
customer consent: it authorises *asking* an approval-required customer and nothing more, and no
endpoint here can record a decision on a customer's behalf.

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
    ClarificationAccepted,
    ClarifyIntent,
    ConfirmationAccepted,
    ConfirmIntent,
    PendingQuestion,
    PromiseStatus,
    QuestionOption,
    ReportAccepted,
    ReportIntent,
    StatusIntent,
)
from promisepatch.db.models import Case
from promisepatch.domain import analysis, cases, intake, recovery, status_view
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

NO_SUCH_CASE = ApiError(status_code=404, code="CASE_NOT_FOUND", message="no case by that id")
"""A case id that names nothing. Case ids are UUIDs and the caller is an authenticated internal
service, so this is not an enumeration surface -- and a conversation that could not tell "no
such case" from "not yours" would have to guess which it was."""

SURFACE_WORKER_MISSING = ApiError(
    status_code=503,
    code="SURFACE_WORKER_UNKNOWN",
    message="the configured surface worker does not exist in this deployment",
)
"""This server named an attestor its own database does not have. A deployment problem, not a
caller problem, so 4xx would tell the caller to fix something that is not theirs."""


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
        logger.error("intents.surface_worker_unknown", worker=worker_id)
        raise SURFACE_WORKER_MISSING from error
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
    "/clarify",
    response_model=ClarificationAccepted,
    status_code=202,
    summary="Answer the one question a case is waiting on",
)
async def clarify(
    request: Request,
    intent: ClarifyIntent,
    settings: SettingsDep,
    database: DatabaseDep,
    service_token: Annotated[str | None, Header(alias=SERVICE_TOKEN_HEADER)] = None,
) -> ClarificationAccepted:
    """Store the worker's answer verbatim and hand the case back to the interpreter.

    ``202``, for the same reason ``report`` is: what is durable when this returns is an answer
    and a queued step. Which physical outcome the answer selects is decided by the worker
    process, against the options that were captured from the delivery's own rows when the
    question was asked -- so an answer can only ever choose among outcomes that were already
    possible, and this endpoint cannot be talked into inventing one.
    """
    worker_id = _authenticate(settings, service_token)
    try:
        result = await intake.answer_clarification(
            database,
            case_id=intent.case_id,
            command_id=intent.command_id,
            worker_id=worker_id,
            raw_text=intent.text,
            correlation_id=_correlation_id(request),
        )
    except intake.UnknownWorkerError as error:
        logger.error("intents.surface_worker_unknown", worker=worker_id)
        raise SURFACE_WORKER_MISSING from error
    except cases.CaseMissingError as error:
        raise NO_SUCH_CASE from error
    except intake.NotPermittedError as error:
        raise ApiError(
            status_code=403,
            code="CASE_NOT_PERMITTED",
            message="this surface may not speak on that case",
        ) from error
    except intake.NotAwaitingClarificationError as error:
        # Not something the caller can fix by rephrasing: the case is not asking anything. A
        # surface that recorded an answer anyway would be putting words on a case that never
        # questioned them, which is the invented-evidence failure this boundary exists to stop.
        raise ApiError(
            status_code=409,
            code="NOT_AWAITING_CLARIFICATION",
            message="that case is not waiting for an answer",
        ) from error
    except intake.IntakeConflictError as error:
        raise ApiError(
            status_code=409,
            code="COMMAND_CONFLICT",
            message="this command id was already used for a different answer",
        ) from error

    logger.info(
        "intents.clarify.accepted",
        case_id=str(result.case_id),
        created=result.created,
        worker=worker_id,
    )
    return ClarificationAccepted(
        case_id=result.case_id,
        statement_id=result.statement_id,
        state=result.state,
        created=result.created,
        attested_by=worker_id,
        speech=status_view.render_clarification_receipt(),
    )


@router.post(
    "/confirm",
    response_model=ConfirmationAccepted,
    status_code=202,
    summary="Confirm one specific plan, so the recoveries it already authorises may execute",
)
async def confirm(
    request: Request,
    intent: ConfirmIntent,
    settings: SettingsDep,
    database: DatabaseDep,
    service_token: Annotated[str | None, Header(alias=SERVICE_TOKEN_HEADER)] = None,
) -> ConfirmationAccepted:
    """Record the worker's yes to the plan they were shown, and enqueue only what it permits.

    ``202``, and the counts in the answer are permissions rather than outcomes. Nothing has
    been sent, no order has been amended and no customer has been asked when this returns: the
    worker process is what executes against the confirmation, and until one runs the case sits
    exactly where this left it.
    """
    worker_id = _authenticate(settings, service_token)
    try:
        result = await recovery.confirm_plan(
            database,
            case_id=intent.case_id,
            command_id=intent.command_id,
            worker_id=worker_id,
            plan_id=intent.plan_id,
            correlation_id=_correlation_id(request),
        )
    except intake.UnknownWorkerError as error:
        logger.error("intents.surface_worker_unknown", worker=worker_id)
        raise SURFACE_WORKER_MISSING from error
    except cases.CaseMissingError as error:
        raise NO_SUCH_CASE from error
    except intake.NotPermittedError as error:
        raise ApiError(
            status_code=403,
            code="CASE_NOT_PERMITTED",
            message="this surface may not confirm that case",
        ) from error
    except recovery.StalePlanError as error:
        raise ApiError(
            status_code=409,
            code="PLAN_SUPERSEDED",
            message="that plan is not the one this case is offering",
        ) from error
    except recovery.PlanNotConfirmableError as error:
        raise ApiError(
            status_code=409,
            code="PLAN_NOT_CONFIRMABLE",
            message="that case is not waiting for a confirmation",
        ) from error
    except recovery.ConfirmationConflictError as error:
        raise ApiError(
            status_code=409,
            code="COMMAND_CONFLICT",
            message="this command id was already used for a different confirmation",
        ) from error

    logger.info(
        "intents.confirm.accepted",
        case_id=str(result.case_id),
        created=result.created,
        worker=worker_id,
    )
    return ConfirmationAccepted(
        case_id=result.case_id,
        command_id=result.command_id,
        state=result.state,
        created=result.created,
        confirmed_by=worker_id,
        applying=len(result.applying),
        awaiting_approval=len(result.awaiting_approval),
        escalated=len(result.escalated),
        speech=status_view.render_confirmation(
            applying=len(result.applying),
            awaiting_approval=len(result.awaiting_approval),
            escalated=len(result.escalated),
            already_confirmed=not result.created,
        ),
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
        raise NO_SUCH_CASE from error

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
        question=_question(view),
        plan_id=view.plan_id,
        awaiting_confirmation=view.awaiting_confirmation,
    )


def _question(view: status_view.CaseView) -> PendingQuestion | None:
    if view.question is None:
        return None
    return PendingQuestion(
        clarification_id=UUID(view.question.clarification_id),
        question=view.question.question,
        options=tuple(
            QuestionOption(code=option.code, label=option.label) for option in view.question.options
        ),
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
