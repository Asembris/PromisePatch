"""One answer per domain refusal, whichever transport asked the question.

Two surfaces now reach the same application services: the internal intent API the MCP tools call,
and the browser conversation routes a person's own session drives. They authenticate differently
and they attest differently, but they are calling the *same* functions, and a refusal that came
out of :mod:`promisepatch.domain.intake` or :mod:`promisepatch.domain.recovery` is a fact about
the case rather than about who asked.

So the mapping lives here rather than in either router. Two copies of it would drift -- not all at
once and not obviously, but one endpoint at a time, until a stale plan was ``PLAN_SUPERSEDED``
over one transport and ``COMMAND_CONFLICT`` over the other, and a client that had learned the
first would be wrong about the second. A test asserts both routers answer the same code for the
same refusal, and this module is what makes that cheap to keep true.

**The messages are neutral on purpose.** They name what happened to the case, never who was
asking: "this caller may not act on that case" is true for an MCP surface, an observer session and
a baker on somebody else's case alike, and a message that guessed which would be wrong two thirds
of the time. The specific thing each endpoint was trying to do is already in the request.

**Nothing here decides anything.** A refusal reaches this module because a domain function already
raised it; this only chooses the status and code a transport reports it with. An exception with no
entry here is deliberately *not* mapped -- :func:`refusal_for` answers ``None``, the caller
re-raises, and an unexpected failure surfaces as one rather than being flattened into a plausible
``409``.
"""

from __future__ import annotations

from typing import Final

from promisepatch.api.errors import ApiError
from promisepatch.domain import analysis, cases, intake, recovery, withdrawal

CASE_NOT_FOUND: Final = ApiError(
    status_code=404,
    code="CASE_NOT_FOUND",
    message="no case by that id",
)
"""A case id that names nothing.

Distinct from ``CASE_NOT_PERMITTED`` on purpose: case ids are UUIDs and every caller that reaches
here is authenticated, so this is not an enumeration surface, and a conversation that could not
tell "there is no such case" from "that one is not yours" would have to guess which it was.
"""

CASE_NOT_PERMITTED: Final = ApiError(
    status_code=403,
    code="CASE_NOT_PERMITTED",
    message="this caller may not act on that case",
)
"""The domain refused this principal on this case. Whose refusal it is, is the domain's."""

NOT_AWAITING_CLARIFICATION: Final = ApiError(
    status_code=409,
    code="NOT_AWAITING_CLARIFICATION",
    message="that case is not waiting for an answer",
)
"""Not something the caller can fix by rephrasing: the case is not asking anything.

A surface that recorded an answer anyway would be putting words on a case that never questioned
them, which is the invented-evidence failure this boundary exists to stop.
"""

COMMAND_CONFLICT: Final = ApiError(
    status_code=409,
    code="COMMAND_CONFLICT",
    message="this command id was already used for a different request",
)
"""Two different things are claiming one identity, and choosing either would discard the other."""

PLAN_SUPERSEDED: Final = ApiError(
    status_code=409,
    code="PLAN_SUPERSEDED",
    message="that plan is not the one this case is offering",
)
"""A yes that quotes a plan the case has moved past. Never applied to whatever is there now."""

PLAN_NOT_CONFIRMABLE: Final = ApiError(
    status_code=409,
    code="PLAN_NOT_CONFIRMABLE",
    message="that case is not waiting for a confirmation",
)
"""There is no plan on offer, so there is nothing a yes could be about."""

CASE_NOT_WITHDRAWABLE: Final = ApiError(
    status_code=409,
    code="CASE_NOT_WITHDRAWABLE",
    message="that case has already finished, so there is no future work to stop",
)
"""A withdrawal of a case that already ran.

Refused rather than answered as a success. A caller told "withdrawn" about a case that resolved
an hour ago would believe something had been stopped that had already happened, which is the one
thing a withdrawal must never imply.
"""

_MAPPING: Final[tuple[tuple[type[BaseException], ApiError], ...]] = (
    (cases.CaseMissingError, CASE_NOT_FOUND),
    (analysis.CaseNotFoundError, CASE_NOT_FOUND),
    (intake.NotPermittedError, CASE_NOT_PERMITTED),
    (intake.NotAwaitingClarificationError, NOT_AWAITING_CLARIFICATION),
    (intake.IntakeConflictError, COMMAND_CONFLICT),
    (recovery.StalePlanError, PLAN_SUPERSEDED),
    (recovery.PlanNotConfirmableError, PLAN_NOT_CONFIRMABLE),
    (recovery.ConfirmationConflictError, COMMAND_CONFLICT),
    (withdrawal.CaseNotWithdrawableError, CASE_NOT_WITHDRAWABLE),
    (withdrawal.WithdrawalConflictError, COMMAND_CONFLICT),
)
"""Every domain refusal a transport is allowed to translate, and the one answer for each.

Ordered rather than a dict so the first match wins, which matters if two of these ever become
related by inheritance: an answer chosen by dictionary iteration order would be an answer nobody
decided.
"""


def refusal_for(error: BaseException) -> ApiError | None:
    """The answer for this domain refusal, or ``None`` when it is not one of them.

    ``None`` is the important half. An exception this module has never heard of is not turned
    into the nearest plausible ``409``: the caller re-raises it, the request fails as the error it
    actually was, and nobody is told a case is in a state that nothing established.
    """
    for kind, refusal in _MAPPING:
        if isinstance(error, kind):
            return refusal
    return None


__all__ = [
    "CASE_NOT_FOUND",
    "CASE_NOT_PERMITTED",
    "CASE_NOT_WITHDRAWABLE",
    "COMMAND_CONFLICT",
    "NOT_AWAITING_CLARIFICATION",
    "PLAN_NOT_CONFIRMABLE",
    "PLAN_SUPERSEDED",
    "refusal_for",
]
