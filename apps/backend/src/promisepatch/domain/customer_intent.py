"""Asking a customer again, in the two words that count.

A reply that reached the literal parser and was not one of the two words is not an answer. It
is stored verbatim, it decides nothing, and §13.6 gives it exactly one response: a message
asking the customer to reply ``YES`` or ``NO``. This module is that response, and nothing else.

It lives in its own module because of what it must not be able to do. The rule from §15 is that
the model "can never produce a decision", and a rule enforced by remembering it is not enforced.
So:

* Nothing here imports :mod:`promisepatch.domain.consent`, and nothing here can read a literal
  ``YES``. Deciding is somebody else's job and this module cannot do it by accident.
* Nothing here imports :class:`~promisepatch.db.models.ApprovalDecision`, mentions
  ``approval_decisions``, or writes :class:`~promise_graph.model.ParserKind`. There is no line
  to delete to make this module safe, because there is no line that makes it unsafe.
* Nothing here imports :mod:`promisepatch.semantic`. Per ADR-0008 the prompt this sends is
  built from the request the reply is bound to and from nothing a model said, so the consent
  path holds no provider call at all -- neither one whose answer is used, nor one whose answer
  is ignored. An import-linter contract keeps it that way.

**What it decides is nothing.** It sends one message and moves the request to
``CONFIRMATION_PENDING``; the track stays where it was, the case stays ``WAITING``, and the only
thing that can settle either is a literal reply arriving afterwards. Which is also why a
prompt-injected reply buys nothing here: whatever it demands, what goes out is the frozen
sentence asking for a word that counts.

**One transaction**, taken by the ordinary step sweep::

    worker claims the INTERPRET_CUSTOMER_REPLY step   (the ordinary claim sweep)
            │
            └── transaction: case, track and request locked; deadline, sender and binding
                re-checked; one confirmation enqueued, or nothing at all

The step kind still carries the name it was given when a model read the reply between those
two moments. It is a durable identity -- it is on step rows, on audit rows and in the ledger of
every case ever run -- so it is left alone, and the work it names is the work described above.

**The step is never created for a reply that could not use one.** An unauthorised sender, a
closed window, a settled request, a duplicate delivery and a literal ``YES`` are all refused by
the reply step before this work exists. The re-checks in :func:`execute` cover the window
between the enqueue and the commit -- which is where a customer's literal ``YES``, racing this
transaction, wins absolutely and this work no-ops.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.model import ApprovalRequestState
from promisepatch.config import get_settings
from promisepatch.db.models import (
    ApprovalRequest,
    Customer,
    InboundReply,
    Order,
)
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.domain import approvals, messaging
from promisepatch.domain.cases import (
    OPEN_APPROVAL_STATES,
    LockedCase,
    case_events,
    case_successors,
    settled_case_state,
)
from promisepatch.domain.model import (
    EFFECT_TRACK_ID,
    EVENT_STEP_COMPLETED,
    AppendEvent,
    CaseChange,
    Disposition,
    EmitEffect,
    StepOutcome,
)
from promisepatch.domain.recovery import lock_track
from promisepatch.graph.channel import split_channel
from promisepatch.observability import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------------------- outcomes

OUTCOME_CONFIRMATION_REQUESTED: Final = "CONFIRMATION_REQUESTED"
"""One confirmation prompt enqueued, and nothing else touched."""

OUTCOME_ALREADY_SETTLED: Final = "ALREADY_SETTLED"
"""The request was answered or closed while the model was being asked. The reading is dropped.

This is the literal-``YES``-races-the-model case, and dropping is the whole of the handling: a
decision already stands, it is append-only and unique per request, and a confirmation prompt
about a change the customer has already approved would be a message contradicting the ledger.
"""

OUTCOME_CONFIRMATION_OUTSTANDING: Final = "CONFIRMATION_OUTSTANDING"
"""A prompt is already out for this request. §13.6 allows exactly one, so this one is not sent."""

OUTCOME_TOO_LATE: Final = "TOO_LATE"
"""The window closed between the reply arriving and the reading returning.

No prompt is sent. Asking somebody to answer inside a window that has shut is a message whose
only possible reply is too late, which §13.6 forbids for the request and which would be no more
honest here. The deadline timer escalates the track on its own.
"""

OUTCOME_UNAUTHORIZED: Final = "UNAUTHORIZED"
"""The channel moved under the reply. Unreachable from the reply step, and refused anyway."""

OUTCOME_UNBOUND: Final = "UNBOUND"
"""The reply no longer names a request. Nothing to confirm and nothing to conclude."""


class CustomerIntentStateError(RuntimeError):
    """A confirmation step describes a shape of the world that cannot be true."""


# -------------------------------------------------------------------------------- binding


@dataclass(frozen=True, slots=True)
class ReplyBinding:
    """Everything a reading of one reply is an answer *about*.

    §13.6 binds an approval to the request, the option and the state of the world it was asked
    against. A reading of a reply is bound at least as tightly: it is an answer about one
    message, from one sender, on one request, with one deadline and one chosen option. If any
    of that has moved by the time the answer comes back, the answer is about something else.
    """

    reply_id: UUID
    provider_message_id: str
    sender: str
    text: str
    request_id: UUID
    track_id: UUID
    option_id: UUID
    option_code: str
    order_id: str
    customer_channel: str
    deadline: datetime
    state: str
    decided: bool


# ------------------------------------------------------------------------------ consumption


async def execute(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    kind: str,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Decide whether this reply still earns the one question §13.6 allows. Usually: yes.

    The lock order is the system's -- case, then track, then request -- so a customer's literal
    ``YES`` arriving at the same moment serialises against this rather than racing it, and
    whichever of the two commits second re-reads a row the first has already settled.

    Every check below is a reason to send nothing. None of them is a reason to decide anything,
    because there is no code path from here that could.
    """
    if case.state not in approvals.LIVE_CASE_STATES:
        return _noop(
            outcome=OUTCOME_ALREADY_SETTLED,
            detail=f"the case is {case.state}",
            request_id=None,
        )

    reply_id = approvals.reply_of(step_key)
    probe = await _binding(connection, reply_id)
    if probe is None:
        return _noop(outcome=OUTCOME_UNBOUND, detail="the reply names no request", request_id=None)

    track = await lock_track(connection, probe.track_id)
    locked = await _lock_request(connection, probe.request_id)
    if locked is None:  # pragma: no cover - the row cannot vanish under a held track lock
        raise CustomerIntentStateError(f"approval request {probe.request_id} vanished under lock")
    binding = _bound(probe, locked)

    if binding.decided or binding.state not in OPEN_APPROVAL_STATES:
        # The literal answer won. It always does, and it does not matter which of them the
        # customer sent, how confident the model was, or which arrived first in wall-clock time.
        return _noop(
            outcome=OUTCOME_ALREADY_SETTLED,
            detail=f"the request is {binding.state}",
            request_id=binding.request_id,
        )
    if binding.state != ApprovalRequestState.SENT.value:
        return _noop(
            outcome=OUTCOME_CONFIRMATION_OUTSTANDING,
            detail="one confirmation prompt is already outstanding",
            request_id=binding.request_id,
        )
    if now > binding.deadline:
        # Against the database's clock, under the request lock. A model that took its time must
        # not extend a customer's window, and a prompt sent into a closed one is not a courtesy.
        return _noop(
            outcome=OUTCOME_TOO_LATE,
            detail="the approval window closed while the reply was being read",
            request_id=binding.request_id,
        )
    if binding.sender != binding.customer_channel:
        return _noop(
            outcome=OUTCOME_UNAUTHORIZED,
            detail="the reply did not arrive on the customer's own channel",
            request_id=binding.request_id,
        )

    return await _request_confirmation(
        connection,
        case=case,
        track=track,
        binding=binding,
        now=now,
        worker=worker,
        step_key=step_key,
    )


async def _request_confirmation(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    track: Any,
    binding: ReplyBinding,
    now: datetime,
    worker: str,
    step_key: str,
) -> StepOutcome:
    """Ask the customer for one of the two words, and change nothing else in the world.

    Reached identically for every reply that was not one of the two words, whatever it said.
    §13.6 says a decline must be literal too, "because it escalates" -- so an agreeable sentence
    is no more authoritative here than a reluctant one, and neither is authority.

    The prompt is built from the request the reply is bound to: the customer's own name, their
    own order reference and the option code this request offered. Not from the reply, and not
    from any reading of it -- which is what makes the sentence the customer receives a property
    of the conversation they are already in rather than of anything they just typed.

    What this writes: the request to ``CONFIRMATION_PENDING``, and one outbox message. What it
    does not write: the reply row, which keeps the words exactly as they arrived; the track,
    which stays ``WAITING_FOR_CUSTOMER``; the case, which stays ``WAITING`` because a
    ``CONFIRMATION_PENDING`` request is still an open one; and any decision, ever.
    """
    addressee = await _addressee(connection, binding.order_id)
    # The same single read the request itself is composed against, for the same reason: the
    # prompt names the way this deployment can be answered, and a prompt that named a different
    # one from the message it follows would be two sets of instructions in one conversation.
    link_available = get_settings().customer_links_configured
    text = messaging.build_confirmation_prompt(
        messaging.ApprovalMessage(
            customer_name=addressee.customer_name,
            order_reference=addressee.order_external_id,
            option_code=binding.option_code,
            link_available=link_available,
        )
    )
    if not messaging.carries_confirmation_literals(
        text, option_code=binding.option_code, link_available=link_available
    ):
        # §13.6's pre-send check, applied to this message as well as to the request. The words
        # a customer is told to reply with are a fixed string in the builder and are never
        # drafted, so this cannot fail today -- and the guard predates any drafter on purpose.
        raise CustomerIntentStateError(
            f"the confirmation prompt for {binding.request_id} is missing its literals"
        )

    key = approvals.confirmation_idempotency_key(binding.request_id, binding.reply_id)
    kind, address = split_channel(binding.customer_channel)

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=approvals.AUDIT_APPROVAL_CONFIRMATION_REQUESTED,
        # The system is asking again, on nobody's authority, having been given none. The
        # customer is the actor of a *decision*; they are not the actor of this, and a ledger
        # that said otherwise would read as though a model had spoken for them.
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"request_state": binding.state, "decided": binding.decided},
        after={
            "request_state": ApprovalRequestState.CONFIRMATION_PENDING.value,
            "decided": False,
            "track_state": track.state,
            "idempotency_key": key,
        },
        provenance={
            "request_id": str(binding.request_id),
            "inbound_reply_id": str(binding.reply_id),
            "provider_message_id": binding.provider_message_id,
            "inbox_event_id": None,
            "sender_identity": binding.sender,
            # Both named explicitly, and both null. A confirmation is not a reading of consent
            # by any parser, and per ADR-0008 no model read the reply that earned it. The
            # fields being present and empty say so louder than their absence would.
            "parser": None,
            "semantic": None,
            "executed_by": worker,
            "step_key": step_key,
        },
        occurred_at=now,
    ) as write:
        moved = (
            await write.execute(
                update(ApprovalRequest)
                .where(
                    ApprovalRequest.id == binding.request_id,
                    ApprovalRequest.decided.is_(False),
                    ApprovalRequest.state == ApprovalRequestState.SENT.value,
                )
                .values(state=ApprovalRequestState.CONFIRMATION_PENDING.value)
            )
        ).rowcount
        if moved != 1:  # pragma: no cover - unreachable while the request lock is held
            raise CustomerIntentStateError(
                f"approval request {binding.request_id} changed under a held lock"
            )
        state_now = await settled_case_state(connection, case=case, except_step_key=step_key)
    successors = await case_successors(connection, state_now, case_id=case.id)

    logger.info(
        "approval.confirmation_requested",
        request_id=str(binding.request_id),
        track_id=str(track.id),
        # The request and the track, never the words. §26 keeps a customer's message in the
        # table a reader has to be entitled to open, and out of a log that is shipped,
        # sampled and searchable.
        reply_id=str(binding.reply_id),
    )
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=state_now),
        successors=successors,
        effects=(
            EmitEffect(
                kind=approvals.EFFECT_MESSAGE_SEND,
                payload={
                    EFFECT_TRACK_ID: str(track.id),
                    # Carried so the dispatcher's one pre-flight -- may this still be sent at
                    # all -- covers this message too. A confirmation whose request was decided
                    # or whose window closed while it queued is refused unsent, by the same
                    # guard and the same rule as the request that preceded it.
                    "request_id": str(binding.request_id),
                    "inbound_reply_id": str(binding.reply_id),
                    "promise_id": track.promise_id,
                    "order_id": binding.order_id,
                    "option_code": binding.option_code,
                    "channel_kind": kind,
                    "channel_address": address,
                    "text": text,
                },
                # No continuation, deliberately. There is no state this message's delivery
                # earns: the track is already waiting and the request is already pending. A
                # terminal failure puts the case on the owner's desk through the outbox's own
                # failure path and leaves the wait exactly where it was, which is the honest
                # outcome -- the customer was not reached, and the deadline still governs.
                idempotency_key=key,
            ),
        ),
        events=(
            AppendEvent(
                type=approvals.EVENT_APPROVAL_INTERPRETATION_RESOLVED,
                payload={"outcome": OUTCOME_CONFIRMATION_REQUESTED},
                entity_refs=({"kind": "approval_request", "id": str(binding.request_id)},),
            ),
            AppendEvent(
                type=approvals.EVENT_APPROVAL_CONFIRMATION_REQUESTED,
                payload={"option_code": binding.option_code},
                entity_refs=(
                    {"kind": "track", "id": str(track.id)},
                    {"kind": "approval_request", "id": str(binding.request_id)},
                ),
            ),
            *case_events(state_now, case_id=case.id),
        ),
        result={
            "outcome": OUTCOME_CONFIRMATION_REQUESTED,
            "track_id": str(track.id),
            "request_id": str(binding.request_id),
            "idempotency_key": key,
        },
    )


def _noop(*, outcome: str, detail: str, request_id: UUID | None) -> StepOutcome:
    """A reading that arrived too late, or about something else. Nothing is written.

    ``DONE`` rather than a retry: none of the conditions that reach here is one that asking
    again would change. The step settles carrying what it found, which is the evidence somebody
    reconstructing the conversation needs -- "a reading came back and this is why it was worth
    nothing" is a different fact from "no reading was ever requested".
    """
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        events=(
            AppendEvent(
                type=approvals.EVENT_APPROVAL_INTERPRETATION_RESOLVED,
                payload={"outcome": outcome},
                entity_refs=(
                    ()
                    if request_id is None
                    else ({"kind": "approval_request", "id": str(request_id)},)
                ),
            ),
        ),
        result={"outcome": outcome, "detail": detail},
    )


@dataclass(frozen=True, slots=True)
class _Addressee:
    """Who the confirmation is going to, and which order it is about."""

    customer_name: str
    order_external_id: str


async def _addressee(connection: AsyncConnection, order_id: str) -> _Addressee:
    row = (
        await connection.execute(
            select(Customer.name, Order.external_id)
            .join(Order, Order.customer_id == Customer.id)
            .where(Order.id == order_id)
        )
    ).one_or_none()
    if row is None:  # pragma: no cover - an approval request cannot name an absent order
        raise CustomerIntentStateError(f"order {order_id} has no customer to write to")
    return _Addressee(customer_name=row.name, order_external_id=row.external_id)


async def _binding(connection: AsyncConnection, reply_id: UUID) -> ReplyBinding | None:
    """The reply and the request it names, read together and without a lock.

    Used to find out *which* rows to lock. The authoritative reading is :func:`_bound`, against
    the request row this transaction holds once it has them.
    """
    row = (
        await connection.execute(
            select(
                InboundReply.id,
                InboundReply.provider_message_id,
                InboundReply.sender_identity,
                InboundReply.raw_text,
                ApprovalRequest.id.label("request_id"),
                ApprovalRequest.track_id,
                ApprovalRequest.option_id,
                ApprovalRequest.option_code,
                ApprovalRequest.order_id,
                ApprovalRequest.customer_channel,
                ApprovalRequest.deadline,
                ApprovalRequest.state,
                ApprovalRequest.decided,
            )
            .join(ApprovalRequest, ApprovalRequest.id == InboundReply.request_id)
            .where(InboundReply.id == reply_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return ReplyBinding(
        reply_id=row.id,
        provider_message_id=row.provider_message_id,
        sender=row.sender_identity,
        text=row.raw_text,
        request_id=row.request_id,
        track_id=row.track_id,
        option_id=row.option_id,
        option_code=row.option_code,
        order_id=row.order_id,
        customer_channel=row.customer_channel,
        deadline=row.deadline,
        state=row.state,
        decided=row.decided,
    )


def _bound(probe: ReplyBinding, request: Any) -> ReplyBinding:
    """The same binding, with every request-owned field taken from the locked row.

    The reply's half cannot move -- ``inbound_replies`` is written once and never updated by
    anything at all -- so only the request's half is re-read. That is the half a decision, an
    expiry or a supersession changes.
    """
    return ReplyBinding(
        reply_id=probe.reply_id,
        provider_message_id=probe.provider_message_id,
        sender=probe.sender,
        text=probe.text,
        request_id=request.id,
        track_id=request.track_id,
        option_id=request.option_id,
        option_code=request.option_code,
        order_id=request.order_id,
        customer_channel=request.customer_channel,
        deadline=request.deadline,
        state=request.state,
        decided=request.decided,
    )


async def _lock_request(connection: AsyncConnection, request_id: UUID) -> Any:
    """Take the request row for update. After the case row and after the track row, never before.

    One lock order everywhere -- case, track, request -- is what makes a customer's ``YES`` and
    this transaction queue instead of deadlock, and what makes the loser re-read a row the
    winner has already settled.
    """
    return (
        await connection.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == request_id).with_for_update()
        )
    ).one_or_none()


__all__: Sequence[str] = [
    "OUTCOME_ALREADY_SETTLED",
    "OUTCOME_CONFIRMATION_OUTSTANDING",
    "OUTCOME_CONFIRMATION_REQUESTED",
    "OUTCOME_TOO_LATE",
    "OUTCOME_UNAUTHORIZED",
    "OUTCOME_UNBOUND",
    "CustomerIntentStateError",
    "ReplyBinding",
    "execute",
]
