"""The human approval a plan confirmation consumes, and the only two ways one is ever written.

A confirmation is the one authority in the conversational surface that is not the engine's own
bookkeeping: a person said yes, and recoveries execute because of it. That makes "a person said
yes" the claim the whole surface rests on, and it used to be minted by whichever service called
the confirming function.

Over the browser that was true. The caller held a signed, ``HttpOnly`` session cookie naming a
row this server wrote, echoed the CSRF token stored on that row, and the actor was read from the
row rather than from the request -- a person had authenticated, and the audit row saying
``HUMAN_APPROVAL`` said something that had happened.

Over MCP it was not. That caller holds a shared service token, the actor came from
``PP_SURFACE_WORKER_ID`` -- this server's own configuration -- and nothing anywhere in the chain
established that a human was present, let alone that they had been read a plan and agreed to it.
A model reaching the tool could produce durable evidence that a named baker had approved a plan
they had never heard. Host authentication is not human consent, and the record said it was.

So the approval is a **row of its own**, written before and separately from the confirmation
that consumes it.

**Minted only where this system authenticated the person.** :func:`record` is reachable from a
browser session and from the operator console, and :class:`ApprovalChannel` has no member for a
service surface. That is the boundary as a constraint rather than as a convention: the column is
checked against the same closed pair in the database, so the MCP path cannot write an approval
even by calling this function, because there is no channel it could name.

**Consumed, never manufactured, by the service surface.** :func:`require` is a read. It finds
the approval a human already left for exactly this plan, or refuses. The MCP path reaches
nothing else here.

**Bound to one exact plan.** The key is ``(case_id, plan_id)``, and a plan identity covers the
case version and every track including the untouched ones. So an approval cannot survive the
case moving on, cannot be applied to a re-planned set of orders, and cannot be carried to
another case at all -- there is no plan identity of one case that is a plan identity of another.

**Append-only.** An approval is an authored record of what somebody claimed, and nothing edits
it. A plan that should no longer execute is withdrawn, which is its own authority with its own
row. There is deliberately no "consumed" flag: consumption is not a property of the approval, it
is what the confirmation's own durable row records, and a second confirmation of the same plan
fails on the case's state and the plan's identity rather than on a mutable marker here.

Nothing here executes anything. Recording an approval sends no message, amends no order, holds
no task and moves no case: it says a person agreed, and
:func:`promisepatch.domain.recovery.confirm_plan` is what acts on that.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.db.clock import database_now
from promisepatch.db.models import PlanApproval
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.db.uow import UnitOfWork
from promisepatch.domain.cases import CASE_PLANNED, lock_case
from promisepatch.domain.intake import actor_for, require_permitted, require_worker
from promisepatch.domain.recovery import (
    HumanApprovalMissingError,
    PlanNotConfirmableError,
    StalePlanError,
    current_plan_id,
)
from promisepatch.observability import get_logger

logger = get_logger(__name__)

AUDIT_PLAN_APPROVED: Final = "PLAN_APPROVED"
"""The audit type a minted approval writes. Distinct from ``PLAN_CONFIRMED`` on purpose.

Two rows, because two things happened and they can be minutes apart: a person agreed to a plan,
and a surface carried that agreement into execution. A single row would make the second
indistinguishable from the first, which is precisely the conflation this module exists to end.
"""

CONTROL_PRESS: Final = "<explicit confirmation control>"
"""What is stored as evidence when the worker pressed the control rather than saying anything.

A sentinel rather than an empty string. "They pressed the button" and "they said nothing" are
different facts, and a column that could not tell them apart would let the second look like the
first. It is not language and is never read back as language.
"""


class ApprovalChannel(StrEnum):
    """The paths on which PromisePatch itself authenticates the human who approves a plan.

    Closed, and closed is the whole point. There is no member for the MCP surface: its bearer
    token proves which *process* is asking and says nothing about whether anybody was standing
    there. A member added for it would not be a new channel, it would be the defect this module
    was written to remove.
    """

    BROWSER_SESSION = "BROWSER_SESSION"
    """A signed-in session: the cookie, the CSRF token compared against the session row, and an
    actor read from that row rather than from anything the request carried."""

    OPERATOR_CONSOLE = "OPERATOR_CONSOLE"
    """The operator CLI, run on the host by a person who already holds the database. The same
    console that may attest a physical fact; approving a plan is strictly less than that."""


@dataclass(frozen=True, slots=True)
class HumanApproval:
    """One person's yes to one exact plan, as the rest of the system may refer to it."""

    id: UUID
    case_id: UUID
    plan_id: str
    approved_by: str
    channel: str


async def record(
    database: RuntimeDatabase,
    *,
    case_id: UUID,
    plan_id: str,
    worker_id: str,
    channel: ApprovalChannel,
    evidence: str,
    correlation_id: UUID | None = None,
) -> HumanApproval:
    """Write a human's approval of the plan they were shown. Authorises nothing by itself.

    Every check the confirmation would make is made here too, under the case lock: the worker
    exists, the case is offering a plan, this worker may act on this case, and the plan quoted is
    the plan the case is currently offering. A person cannot approve a plan they were not shown,
    and an observer cannot approve at all -- the refusal is
    :func:`promisepatch.domain.intake.require_permitted`'s, on the same function every other
    write in this system passes through.

    Idempotent on the plan. A second yes to a plan somebody already approved returns the first
    approval rather than writing a second one: two rows would be two authorities for one
    agreement, and the unique constraint refuses them anyway.
    """
    if not evidence.strip():
        raise ValueError("an approval must record what the human did")

    async with database.begin() as connection:
        await require_worker(connection, worker_id)
        case = await lock_case(connection, case_id)
        if case.state != CASE_PLANNED:
            raise PlanNotConfirmableError(f"case {case_id} is {case.state}, not {CASE_PLANNED}")
        await require_permitted(connection, case_id=case_id, worker_id=worker_id)

        current = await current_plan_id(connection, case_id=case_id, case_version=case.version)
        if current != plan_id:
            raise StalePlanError(f"case {case_id} is offering a different plan than the approved")

        existing = await _approval_for(connection, case_id=case_id, plan_id=plan_id)
        if existing is not None:
            return existing

        approval_id = uuid4()
        now = await database_now(connection)
        unit_of_work = UnitOfWork(connection)
        async with unit_of_work.governed(
            event_type=AUDIT_PLAN_APPROVED,
            actor=await actor_for(connection, worker_id),
            # A human said yes, and this row is the only place that is established. The
            # confirmation that consumes it audits ``HUMAN_APPROVAL`` too, and now that word is
            # true on both rows rather than asserted on one.
            authority="HUMAN_APPROVAL",
            case_id=case_id,
            after={"plan_id": plan_id, "approved_by": worker_id, "channel": channel.value},
            provenance={"approval_id": str(approval_id), "channel": channel.value},
            correlation_id=correlation_id,
            occurred_at=now,
        ) as write:
            await write.execute(
                insert(PlanApproval).values(
                    id=approval_id,
                    case_id=case_id,
                    plan_id=plan_id,
                    approved_by=worker_id,
                    channel=channel.value,
                    evidence=evidence,
                    approved_at=now,
                )
            )

    logger.info(
        "plan.approval.recorded",
        case_id=str(case_id),
        worker=worker_id,
        channel=channel.value,
    )
    return HumanApproval(
        id=approval_id,
        case_id=case_id,
        plan_id=plan_id,
        approved_by=worker_id,
        channel=channel.value,
    )


async def find(database: RuntimeDatabase, *, case_id: UUID, plan_id: str) -> HumanApproval | None:
    """The approval a human left for exactly this plan, or ``None``. A read, and only a read."""
    async with database.begin() as connection:
        return await _approval_for(connection, case_id=case_id, plan_id=plan_id)


async def require(database: RuntimeDatabase, *, case_id: UUID, plan_id: str) -> HumanApproval:
    """The approval this plan already carries, or a refusal. **The service surface's only door.**

    This is what makes an MCP ``confirm`` a consumption rather than a mint. It writes nothing, it
    takes no worker argument and it has nothing to offer a caller who wants to become somebody:
    either a person already approved this exact plan through a channel that authenticated them,
    or the call is refused and the conversation has to go and ask them.
    """
    approval = await find(database, case_id=case_id, plan_id=plan_id)
    if approval is None:
        raise HumanApprovalMissingError(
            f"no human has approved the plan this case {case_id} is offering"
        )
    return approval


async def _approval_for(
    connection: AsyncConnection, *, case_id: UUID, plan_id: str
) -> HumanApproval | None:
    row = (
        await connection.execute(
            select(
                PlanApproval.id,
                PlanApproval.case_id,
                PlanApproval.plan_id,
                PlanApproval.approved_by,
                PlanApproval.channel,
            ).where(PlanApproval.case_id == case_id, PlanApproval.plan_id == plan_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return HumanApproval(
        id=row.id,
        case_id=row.case_id,
        plan_id=row.plan_id,
        approved_by=row.approved_by,
        channel=row.channel,
    )


__all__ = [
    "AUDIT_PLAN_APPROVED",
    "CONTROL_PRESS",
    "ApprovalChannel",
    "HumanApproval",
    "find",
    "record",
    "require",
]
