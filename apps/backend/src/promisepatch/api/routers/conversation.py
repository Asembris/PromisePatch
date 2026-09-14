"""``/api/conversation/*`` -- the four things a person can say to a case from their browser.

The same four application services the MCP tools reach, called over a different credential. Every
sentence below is about that difference, because the difference is exactly one thing: **who the
server decides is speaking.**

**A session, not a service token.** The caller holds the signed, ``HttpOnly`` cookie naming a
server-side session row -- the same one the workspace reads use. The internal intent API's shared
secret is never sent to a browser and is not accepted here: a page that presented one would be
presenting a credential it should never have been able to obtain, and it would still arrive at
this router with no session and be refused as unauthenticated.

**CSRF is load-bearing here for the first time.** Until now the only browser mutation in this
product was logging out. These four change a case, so each one runs through
``CsrfPrincipalDep``: the token is minted with the session, stored on its row, echoed by the
client in a header, and compared against **the row** rather than against the cookie. ``SameSite``
removes most of the surface before that check runs; the check is what remains correct when it
does not.

**The actor is the session and nothing else.** ``worker_id = principal.worker_id``, read from the
row this server wrote. The request models have no actor field and forbid extras, so there is
nothing to set and an attempt to set one is a ``422`` rather than a value quietly ignored. The
clock is this server's for the same reason: a caller who could set it could backdate a physical
claim.

**No permission is decided here.** ``require_worker`` and ``require_permitted`` run inside the
domain services exactly as they do for the CLI and for the intent API, so an observer session --
which the domain admits to reads and to nothing else -- is refused *by the domain*, with the
domain's own error, on a route that contains no check for it. That is why the read widening in
:func:`promisepatch.domain.intake.require_readable` cannot leak into a write: these endpoints do
not consult it.

**Nothing is interpreted here.** ``report`` and ``clarify`` store the words and enqueue the
durable work; the interpreter runs in the worker, under a lease, in a transaction that can be
rolled back. And a confirmation is bound to a plan: ``plan_id`` is the identity the case response
presented, compared under the lock the confirmation is written with, so a yes authorises the plan
that was read and never whatever the case happens to hold when it arrives.

**A withdrawal stops future work and is never an undo.** ``withdraw`` answers with two lists the
domain composed: what it stood down, and what had already reached a customer or the order system
and is therefore *not* reversed. No physical fact moves -- facts and recovery authorisation are
separate authorities, and no field on this route could name one.

**Every answer is a permission, never an outcome.** ``202`` throughout, counts that say what may
now happen, and speech rendered by :mod:`promisepatch.domain.status_view` and delivered unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter

from promisepatch.api.dependencies import CsrfPrincipalDep, DatabaseDep
from promisepatch.api.errors import ApiError
from promisepatch.api.refusals import refusal_for
from promisepatch.api.schemas.conversation import (
    ClarifyTurn,
    ConfirmTurn,
    ReportTurn,
    TurnAccepted,
    WithdrawalAccepted,
    WithdrawTurn,
)
from promisepatch.domain import cases, intake, recovery, status_view, withdrawal
from promisepatch.observability import get_logger
from promisepatch.orchestrator.policy import reads_as_worker_confirmation

logger = get_logger(__name__)

router = APIRouter(prefix="/api/conversation", tags=["conversation"])

ATTESTOR_MISSING = ApiError(
    status_code=503,
    code="ATTESTOR_UNKNOWN",
    message="the worker this session names no longer exists in this deployment",
)
"""A live session naming a worker row that has since gone.

A deployment problem rather than a caller problem -- they signed in perfectly well -- so ``4xx``
would be telling somebody to fix something that is not theirs. It is also the one condition here
that is not a refusal *about the case*, which is why it is stated in this module rather than in
the shared mapping.
"""


NOT_A_PLAIN_YES = ApiError(
    status_code=409,
    code="NOT_A_PLAIN_YES",
    message="that was not a plain yes, so nothing was confirmed",
)
"""A spoken confirmation whose words do not read as an agreement (ADR-0015).

Raised *before* the domain is called, so no command is written and the case is exactly as it was.
It is deliberately not re-routed anywhere: a sentence this cannot read as a yes is not stored as a
clarification, not treated as a withdrawal and not answered with a question. Doing something else
with words nobody could read as agreement would be the surface guessing at what a worker meant,
and the whole reason the check exists is that nothing may guess here.

``409`` rather than ``400`` because every ``409`` this router returns means one thing to a reader
and to a listener alike -- the case is exactly as it was -- which is precisely what this leaves
behind.
"""


def _refused(error: Exception) -> ApiError:
    """Translate a domain refusal, or re-raise what was never one.

    The mapping is :mod:`promisepatch.api.refusals`, shared with the internal intent API so the
    two transports cannot answer the same refusal differently. An exception with no entry there
    leaves this function by being raised again: flattening an unknown failure into the nearest
    plausible ``409`` would tell a person their case is in a state nothing established.
    """
    refusal = refusal_for(error)
    if refusal is None:
        raise error
    return refusal


@router.post(
    "/report",
    response_model=TurnAccepted,
    status_code=202,
    summary="Open a case for one spoken physical exception",
)
async def report(
    turn: ReportTurn,
    principal: CsrfPrincipalDep,
    database: DatabaseDep,
) -> TurnAccepted:
    """Store what this worker said, verbatim, under their own name, and enqueue the reading.

    ``202`` rather than ``201``: what is durable when this answers is a statement and a queued
    step, and nothing has been concluded about anybody's order. Saying "created" about a recovery
    nobody has planned would be the first of the lies this product exists not to tell.
    """
    # The clock is this server's, never the caller's. A redelivery of the same command reuses the
    # instant its own statement recorded, because it is that statement arriving twice rather than
    # a second one -- a fresh `now()` would change the request hash and turn an idempotent
    # redelivery into a conflict.
    stored = await intake.observed_at_for(database, command_id=turn.command_id)
    try:
        result = await intake.open_physical_exception(
            database,
            command_id=turn.command_id,
            worker_id=principal.worker_id,
            raw_text=turn.text,
            observed_at=stored or datetime.now(UTC),
        )
    except intake.UnknownWorkerError as error:
        logger.error("conversation.attestor_unknown", worker=principal.worker_id)
        raise ATTESTOR_MISSING from error
    except (intake.NotPermittedError, intake.IntakeConflictError) as error:
        # `NotPermittedError` reaches here from `require_attestor`: this principal is not somebody
        # whose word about the kitchen counts, which is how an observer is refused a case of its
        # own. Refused before the case row exists, so the id derived from the command names
        # nothing afterwards.
        raise _refused(error) from error

    logger.info(
        "conversation.report.accepted",
        case_id=str(result.case_id),
        created=result.created,
        worker=principal.worker_id,
    )
    return _accepted(
        case_id=result.case_id,
        statement_id=result.statement_id,
        state=result.state,
        created=result.created,
        worker_id=principal.worker_id,
        speech=status_view.render_report_receipt(),
        spoken=status_view.render_report_receipt(),
    )


@router.post(
    "/clarify",
    response_model=TurnAccepted,
    status_code=202,
    summary="Answer the one question a case is waiting on",
)
async def clarify(
    turn: ClarifyTurn,
    principal: CsrfPrincipalDep,
    database: DatabaseDep,
) -> TurnAccepted:
    """Store this worker's answer verbatim and hand the case back to the interpreter.

    Which physical outcome the answer selects is decided by the worker process, against the
    options captured from the delivery's own rows when the question was asked -- so an answer can
    only ever choose among outcomes that were already possible, and this endpoint cannot be talked
    into inventing one.
    """
    try:
        result = await intake.answer_clarification(
            database,
            case_id=turn.case_id,
            command_id=turn.command_id,
            worker_id=principal.worker_id,
            raw_text=turn.text,
        )
    except intake.UnknownWorkerError as error:
        logger.error("conversation.attestor_unknown", worker=principal.worker_id)
        raise ATTESTOR_MISSING from error
    except (
        cases.CaseMissingError,
        intake.NotPermittedError,
        intake.NotAwaitingClarificationError,
        intake.IntakeConflictError,
    ) as error:
        raise _refused(error) from error

    logger.info(
        "conversation.clarify.accepted",
        case_id=str(result.case_id),
        created=result.created,
        worker=principal.worker_id,
    )
    return _accepted(
        case_id=result.case_id,
        statement_id=result.statement_id,
        state=result.state,
        created=result.created,
        worker_id=principal.worker_id,
        speech=status_view.render_clarification_receipt(),
        spoken=status_view.render_clarification_receipt(),
    )


@router.post(
    "/confirm",
    response_model=TurnAccepted,
    status_code=202,
    summary="Confirm one specific plan, so the recoveries it already authorises may execute",
)
async def confirm(
    turn: ConfirmTurn,
    principal: CsrfPrincipalDep,
    database: DatabaseDep,
) -> TurnAccepted:
    """Record this worker's yes to the plan they were shown, and enqueue only what it permits.

    Nothing has been sent, no order has been amended and no customer has been asked when this
    returns: the worker process is what executes against the confirmation, and until one runs the
    case sits exactly where this left it. A worker's yes is also not a customer's consent -- it
    authorises *asking* an approval-required customer, and no endpoint here can record a decision
    on somebody else's behalf.

    A spoken confirmation carries the worker's own words, and they are read **here** rather than
    by the browser that captured them (ADR-0015). The rule is
    :func:`promisepatch.orchestrator.policy.reads_as_worker_confirmation`, imported rather than
    rewritten: the same closed opening affirmations and the same disqualifying words the
    conversational orchestrator has always applied, so the two surfaces cannot drift into
    disagreeing about what a yes is. A press of the explicit control carries no words at all and
    is unchanged -- the press is the yes.

    Neither reading widens what a yes is *about*. ``plan_id`` still decides that, still compared
    under the confirming lock by the domain, so this check can only ever refuse a confirmation
    the control could have made and never permit one it could not.
    """
    if turn.text is not None and not reads_as_worker_confirmation(turn.text):
        logger.info("conversation.confirm.not_a_yes", case_id=str(turn.case_id))
        raise NOT_A_PLAIN_YES

    try:
        result = await recovery.confirm_plan(
            database,
            case_id=turn.case_id,
            command_id=turn.command_id,
            worker_id=principal.worker_id,
            plan_id=turn.plan_id,
        )
    except intake.UnknownWorkerError as error:
        logger.error("conversation.attestor_unknown", worker=principal.worker_id)
        raise ATTESTOR_MISSING from error
    except (
        cases.CaseMissingError,
        intake.NotPermittedError,
        recovery.StalePlanError,
        recovery.PlanNotConfirmableError,
        recovery.ConfirmationConflictError,
    ) as error:
        raise _refused(error) from error

    logger.info(
        "conversation.confirm.accepted",
        case_id=str(result.case_id),
        created=result.created,
        worker=principal.worker_id,
    )
    return _accepted(
        case_id=result.case_id,
        statement_id=result.command_id,
        state=result.state,
        created=result.created,
        worker_id=principal.worker_id,
        speech=status_view.render_confirmation(
            applying=len(result.applying),
            awaiting_approval=len(result.awaiting_approval),
            escalated=len(result.escalated),
            already_confirmed=not result.created,
        ),
        spoken=status_view.render_confirmation_spoken(
            applying=len(result.applying),
            awaiting_approval=len(result.awaiting_approval),
            escalated=len(result.escalated),
            already_confirmed=not result.created,
        ),
    )


@router.post(
    "/withdraw",
    response_model=WithdrawalAccepted,
    status_code=202,
    summary="Withdraw an exception, stopping the work that has not happened yet",
)
async def withdraw(
    turn: WithdrawTurn,
    principal: CsrfPrincipalDep,
    database: DatabaseDep,
) -> WithdrawalAccepted:
    """Stop what this case had not done yet, and say plainly what it had already done.

    The honest half of this answer is ``applied``, and it is never empty when something had gone
    out. Anything the order system has accepted or a customer has received is left exactly where
    it is: there is no branch here that recalls a message or reverses an amendment, because
    neither is a thing this product can do. Nor does a withdrawal touch a physical fact -- the
    ingredient that did not arrive still did not arrive, and only a correcting attestation, which
    this route cannot reach, changes that.
    """
    try:
        result = await withdrawal.withdraw_exception(
            database,
            case_id=turn.case_id,
            command_id=turn.command_id,
            worker_id=principal.worker_id,
        )
    except intake.UnknownWorkerError as error:
        logger.error("conversation.attestor_unknown", worker=principal.worker_id)
        raise ATTESTOR_MISSING from error
    except (
        cases.CaseMissingError,
        intake.NotPermittedError,
        withdrawal.CaseNotWithdrawableError,
        withdrawal.WithdrawalConflictError,
    ) as error:
        raise _refused(error) from error

    logger.info(
        "conversation.withdraw.accepted",
        case_id=str(result.case_id),
        created=result.created,
        worker=principal.worker_id,
    )
    reversals = [(kind.value, count) for kind, count in result.reversals]
    applied = [(kind.value, count) for kind, count in result.applied]
    withdrawal_speech = status_view.render_withdrawal(
        withdrawn=len(result.withdrawn),
        escalated=len(result.escalated),
        reversals=reversals,
        applied=applied,
        already_withdrawn=not result.created,
    )
    return WithdrawalAccepted(
        case_id=result.case_id,
        command_id=result.command_id,
        state=result.state,
        created=result.created,
        withdrawn_by=principal.worker_id,
        withdrawn=len(result.withdrawn),
        escalated=len(result.escalated),
        reversed_writes=status_view.render_reversals(reversals),
        applied=status_view.render_applied(applied),
        speech=withdrawal_speech,
        # Deliberately the same sentence. Every clause names a distinct consequence class with
        # its own count, and `docs/bounded-withdrawal.md` fixes that the applied half is never
        # dropped -- counting four reversal kinds as one number would lose the distinction that
        # document exists to protect. It is long, and staying long is the correct answer here.
        spoken=withdrawal_speech,
    )


def _accepted(
    *,
    case_id: UUID,
    statement_id: UUID,
    state: str,
    created: bool,
    worker_id: str,
    speech: str,
    spoken: str,
) -> TurnAccepted:
    """One answer shape for all three turns, so no endpoint grows a different idea of success."""
    return TurnAccepted(
        case_id=case_id,
        statement_id=statement_id,
        state=state,
        created=created,
        attested_by=worker_id,
        speech=speech,
        spoken=spoken,
    )
