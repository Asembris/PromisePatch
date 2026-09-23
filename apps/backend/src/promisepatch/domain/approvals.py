"""Asking a customer, waiting durably for their answer, and reading only a literal one.

This is the consent protocol: the one place in PromisePatch where authority comes from outside
the building. Everything here exists to keep two things apart that look alike from a distance --
*a worker confirmed the plan* and *the customer agreed to the change* -- because conflating them
is the failure that would make every other guarantee in the system worthless.

Five transactions, and the boundaries are the design.

``REQUEST_APPROVAL``
    Enqueued by the plan confirmation, run under the case lock. It re-checks that the plan still
    describes the world, refuses outright if the approval window has already closed, writes one
    ``approval_requests`` row and enqueues one outbound message. **The track stays ``PENDING``.**
    A row is not a conversation, and a track that claimed to be waiting on a customer nobody had
    contacted would be the most convincing lie the system could tell.

Outbox dispatch
    The generic dispatcher sends it, with one approval-specific pre-flight
    (:func:`refuse_if_window_closed`): a message whose window has closed while it queued is
    refused rather than delivered. §13.6 forbids sending a request into a window in which no
    valid answer could arrive, and a message delayed past its own deadline is exactly that.

``MARK_APPROVAL_SENT``
    Enqueued by the delivery acknowledgement itself, so it exists only once the provider's
    acceptance is durable. It proves the acceptance from the outbox row, stamps the provider
    reference on the request, arms the deadline as a ``timers`` row, and *now* moves the track
    to ``WAITING_FOR_CUSTOMER``. If that leaves nothing else runnable, the case becomes
    ``WAITING`` and stops doing anything at all.

``EXPIRE_APPROVAL``
    Created by the durable deadline timer. An undecided request expires, its track escalates,
    and no decision is invented on the customer's behalf. A timer that fires for a request
    already answered is a no-op.

``RECEIVE_CUSTOMER_REPLY``
    Created by the inbox from a stored inbound record. It checks the sender against the channel
    the request was sent to, checks the request is still open, checks the deadline against the
    *database's* clock rather than against whether a timer has run yet, and only then hands the
    text to :mod:`promisepatch.domain.consent`. A literal ``YES`` or ``NO`` becomes exactly one
    ``approval_decisions`` row; anything else becomes a stored reply and nothing more.

**What makes the wait durable.** Nothing is held in memory. The request is a row, the deadline is
a row, the customer's reply arrives as a row, and the case sits in ``WAITING`` doing no work at
all. A worker can be killed and restarted for as long as you like; the two things that can wake
the case are an inbox record and a timer, and both survive the process that would have handled
them.

**What makes exactly one decision.** The step transaction takes the case row, then the track row,
then the request row, in that order and no other. A ``YES`` and a ``NO`` racing for one request
therefore serialise, and the loser re-reads ``decided`` under the lock and records that the
request was already answered. Behind that, ``uq_approval_decisions_request_id`` refuses a second
decision outright and ``approval_decisions`` is append-only, so the first valid committed
decision stands for ever whatever any later code believes.

**What this slice deliberately does not do.** It does not revalidate, and an approval does not
apply anything. §14.3's ten checks are the next piece of work, and an approved track therefore
stays ``WAITING_FOR_CUSTOMER`` while the case hands itself to ``REVALIDATING``. Consent is
necessary authority; it is not evidence that the plan is still valid, and treating it as both
would let a stale amendment reach a customer's order carrying a real signature.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.fingerprint import constraint_hash
from promise_graph.model import (
    ApprovalDecisionKind,
    ApprovalRequestState,
    Classification,
    ParserKind,
)
from promise_graph.snapshot import GraphSnapshot
from promisepatch.config import get_settings
from promisepatch.db.clock import database_now
from promisepatch.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    InboundReply,
    InboxEvent,
    Order,
    OutboxMessage,
    Track,
)
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.db.uow import Actor, GovernedWrite, UnitOfWork
from promisepatch.domain import consent, customer_link, messaging
from promisepatch.domain.analysis import NAMESPACE, fresh_snapshot
from promisepatch.domain.cases import (
    CASE_EXECUTING,
    CASE_RECONCILING,
    CASE_RESOLVED,
    CASE_REVALIDATING,
    CASE_WAITING,
    OPEN_APPROVAL_STATES,
    TRACK_WAITING_FOR_CUSTOMER,
    LockedCase,
    case_events,
    case_successors,
    scope_in,
    settled_case_state,
    track_in,
    track_scoped_key,
)
from promisepatch.domain.model import (
    EFFECT_MESSAGE_SEND as _EFFECT_MESSAGE_SEND,
)
from promisepatch.domain.model import (
    EFFECT_TRACK_ID,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_FAILED,
    AppendEvent,
    ArmTimer,
    CaseChange,
    CreateStep,
    DeliveryOutcome,
    DeliveryStatus,
    Disposition,
    EmitEffect,
    InboundOutcome,
    StepOutcome,
)
from promisepatch.domain.recovery import (
    CONTINUATION,
    DELIVERED,
    EVENT_TRACK_ESCALATED,
    FAILED,
    TRACK_ESCALATED,
    TRACK_PENDING,
    chosen_option,
    current_fingerprint,
    hold_tasks,
    lock_track,
    mark_stale,
    set_track,
    skipped,
)
from promisepatch.graph.channel import split_channel
from promisepatch.observability import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------------------- step naming

STEP_REQUEST_APPROVAL: Final = "REQUEST_APPROVAL"
STEP_MARK_APPROVAL_SENT: Final = "MARK_APPROVAL_SENT"
STEP_ABANDON_APPROVAL: Final = "ABANDON_APPROVAL"
STEP_EXPIRE_APPROVAL: Final = "EXPIRE_APPROVAL"
STEP_RECEIVE_CUSTOMER_REPLY: Final = "RECEIVE_CUSTOMER_REPLY"

APPROVAL_STEP_KINDS: Final[frozenset[str]] = frozenset(
    {
        STEP_REQUEST_APPROVAL,
        STEP_MARK_APPROVAL_SENT,
        STEP_ABANDON_APPROVAL,
        STEP_EXPIRE_APPROVAL,
        STEP_RECEIVE_CUSTOMER_REPLY,
    }
)
"""Step kinds the worker routes here. Every one of them reads rows to decide."""

STEP_INTERPRET_CUSTOMER_REPLY: Final = "INTERPRET_CUSTOMER_REPLY"
"""The sixth transaction of the consent protocol: the one question an unreadable reply earns.

Named here, with the rest of the protocol's vocabulary, and *implemented* in
:mod:`promisepatch.domain.customer_intent`, which imports no decision machinery at all. The
split is the boundary: the module that sends the customer a further question cannot reach
:class:`~promisepatch.db.models.ApprovalDecision`, and the module that records consent never
sends a message.

The name is older than the work. A model once read the reply in this step's own window; per
ADR-0008 none does, and the prompt is built from the request the reply is bound to. The kind is
kept because it is a durable identity -- on step rows, on audit rows and in the ledger of every
case ever run -- and renaming it would rewrite history to describe today.

It exists only for a reply that reached the literal parser and was not a decision, on a request
that is open, undecided, in date and from the right channel -- which is why no unauthorised
sender, expired window, duplicate delivery or literal ``YES`` ever creates one.
"""

CUSTOMER_INTENT_STEP_KINDS: Final[frozenset[str]] = frozenset({STEP_INTERPRET_CUSTOMER_REPLY})
"""Kinds routed to the module that asks again, which is a different module on purpose."""


def request_step_key(track_id: UUID, plan_id: str | None = None) -> str:
    """One approval request per episode, whatever happens to the process that enqueued it.

    An episode is one track asked under one confirmed plan (ADR-0022). ``plan_id`` is ``None``
    for a track's first ask, which is unique by construction and keeps ``approval:<track>``; a
    re-ask after §14.4's re-plan names the plan whose confirmation asked, so it is a new step
    rather than a replay of the settled one -- and a replayed confirmation of that same plan
    proposes the identical key and is declined.
    """
    return track_scoped_key("approval", track_id, plan_id)


def sent_step_key(track_id: UUID, scope: UUID | None = None) -> str:
    """The step a delivered approval message makes runnable. Scoped as its request is."""
    return track_scoped_key("approval-sent", track_id, scope)


def abandon_step_key(track_id: UUID, scope: UUID | None = None) -> str:
    """The other ending, for a message that will not be attempted again."""
    return track_scoped_key("approval-abandoned", track_id, scope)


def expire_step_key(request_id: UUID) -> str:
    """Derived from the request rather than from the timer, so re-arming cannot double-expire."""
    return f"approval-expired:{request_id}"


def interpret_step_key(reply_id: UUID) -> str:
    """One further question per stored reply, whatever the transport did.

    Keyed on the reply rather than on the request, because a request may legitimately receive
    more than one reply and each of them is its own occasion to ask. Keyed on the *stored*
    reply -- a value derived from the provider's message id -- so a redelivered message that
    somehow reached the protocol twice proposes the identical step key and the unique index on
    ``(case_id, step_key)`` declines the second.
    """
    return f"interpret-reply:{reply_id}"


def request_of(step_key: str) -> UUID:
    """The request an expiry step is about, read back out of its key."""
    return UUID(step_key.partition(":")[2])


def reply_of(step_key: str) -> UUID:
    """The stored reply a confirmation step is about."""
    return UUID(step_key.partition(":")[2])


def inbox_of(step_key: str) -> UUID:
    """The stored inbound record a reply step is about."""
    return UUID(step_key.partition(":")[2])


# ------------------------------------------------------------------------------ derived names


def request_id_for(track_id: UUID, option_id: UUID, plan_id: str | None = None) -> UUID:
    """The identity of one approval episode's request: one track, one option, one plan.

    Derived rather than minted, so the request is unique in the database and not merely unique
    in whichever process happened to create it: a second attempt at the same logical ask
    proposes the same primary key and PostgreSQL declines it. §13.6 allows one request per
    track at a time and one option per request, and this is that rule expressed as a key.

    ``plan_id`` is what makes §14.4's re-ask a *new* request (ADR-0022). A re-plan usually
    re-chooses the very option the customer was first asked about, so a key of track and option
    alone reproduced the superseded request's id -- the insert wrote nothing and the track was
    bound back to a request that was superseded and already answered. A track's first ask passes
    ``None`` and keeps the identity it has always had.
    """
    name = f"approval:{track_id}:{option_id}"
    return uuid5(NAMESPACE, name if plan_id is None else f"{name}:{plan_id}")


def ask_scope(request: Any) -> UUID | None:
    """Which episode a request belongs to, in the terms every later step key is built from.

    ``None`` for a track's first ask -- whose id is the per-track derivation of its own track and
    option -- and the request's own id for every re-ask, whose derivation includes a plan and so
    can never equal it. Read from the row itself, so no step has to be told which it is.
    """
    first = request_id_for(request.track_id, request.option_id)
    return None if request.id == first else request.id


def step_names(step_key: str, request: Any) -> bool:
    """Whether a step keyed for one request is about ``request``, the one the track carries now.

    A per-track key names the track's first ask; a scoped key names the request it carries. A
    step about any other request -- one a re-plan has since superseded -- acts on nothing.
    """
    if request is None:
        return False
    scope = scope_in(step_key)
    return ask_scope(request) == (None if scope is None else UUID(scope))


def reply_id_for(provider_message_id: str) -> UUID:
    """One stored reply per provider message, however many times it is handed to us."""
    return uuid5(NAMESPACE, f"reply:{provider_message_id}")


def link_message_id(request_id: UUID, channel: str) -> str:
    """The provider message id a link-borne answer is stored under. One per request per channel.

    Derived from the request and the channel, and deliberately **not** from the answer. That is
    what makes a second press of either button a no-op rather than a second reply: both propose
    the same id, ``inbox_events`` is unique on ``(source, provider_event_id)``, and the second
    insert writes nothing at all. So a customer who presses Decline and then Approve has
    declined -- a decline can never be edited into an approval by pressing again, and that
    property is a unique index rather than a branch somebody has to remember to write.

    Derived rather than minted for the usual reason as well: a fresh id per press would make
    every double-click, every retried request and every impatient refresh into another reply
    about a question that only has one answer.
    """
    return f"link:{uuid5(NAMESPACE, f'link-reply:{request_id}:{channel}')}"


def option_code_for(option_id: UUID) -> str:
    """The short reference a customer can quote back to the bakery.

    Derived from the option so it is stable across retries and unique per change, short enough
    to read aloud, and meaningless on its own -- it identifies a request, it does not authorise
    one. Only ``YES`` and ``NO`` do that.
    """
    return f"OPT-{option_id.hex[:6].upper()}"


def message_idempotency_key(request_id: UUID) -> str:
    """§12.3's ``pp:approval:{approval_request_id}``, and nothing else in it.

    Not the attempt, not the worker, not the clock, not a fresh UUID. One logical ask has one
    key for its whole life, so every redelivery after every crash presents the identical key and
    a provider that honours keys collapses them into the one message the customer should see.
    """
    return f"pp:approval:{request_id}"


def confirmation_idempotency_key(request_id: UUID, reply_id: UUID) -> str:
    """§12.3's ``pp:confirm:{approval_request_id}:{inbound_reply_id}``, exactly.

    Both halves are server-derived and neither moves: the request id is a ``uuid5`` of the
    track, the option and -- for a re-ask -- the plan that asked, and the reply id is a
    ``uuid5`` of the provider's message id. So every
    retry of one logical confirmation -- after a crash, after a lost acknowledgement, after a
    worker was replaced mid-flight -- presents the identical key, and the outbox's unique index
    turns any number of transport attempts into one message the customer should see.
    """
    return f"pp:confirm:{request_id}:{reply_id}"


# ------------------------------------------------------------------------------ effect naming

EFFECT_MESSAGE_SEND: Final = _EFFECT_MESSAGE_SEND
"""The §13.3 outbox kind for anything said to a customer on their own channel.

Declared in :mod:`promisepatch.domain.model` and re-exported here, so the re-plan that sends
§14.4's supersede notice can name it without importing this module, which would close a cycle.
"""

# ------------------------------------------------------------------------------ timer naming

APPROVAL_SUBJECT: Final = "APPROVAL_REQUEST"
TIMER_APPROVAL_DEADLINE: Final = "APPROVAL_DEADLINE"
"""§11.5's deadline, armed against the request rather than the case.

Per request, because a case may be waiting on more than one customer and a deadline that could
only be armed once per case would silently drop the second one.
"""

# ------------------------------------------------------------------------------ inbound naming

CUSTOMER_REPLY_SOURCE: Final = "customer-reply"
"""The inbound source a customer's own channel arrives on.

One source name for the customer channel, whichever provider is carrying it. Telegram's ingress
is a later slice; what it will change is who fills this row in, never what the consent protocol
does with it, because the protocol reads the *stored* record and never a live request.
"""

# ------------------------------------------------------------------------------- event names

EVENT_APPROVAL_REQUESTED: Final = "approval.requested"
EVENT_APPROVAL_SENT: Final = "approval.sent"
EVENT_APPROVAL_DELIVERY_FAILED: Final = "approval.delivery_failed"
EVENT_APPROVAL_EXPIRED: Final = "approval.expired"
EVENT_APPROVAL_REPLY_RECEIVED: Final = "approval.reply_received"
EVENT_APPROVAL_REPLY_UNRECOGNIZED: Final = "approval.reply_unrecognized"
EVENT_APPROVAL_REPLY_UNAUTHORIZED: Final = "approval.reply_unauthorized"
EVENT_APPROVAL_REPLY_IGNORED: Final = "approval.reply_ignored"
EVENT_APPROVAL_INTERPRETATION_REQUESTED: Final = "approval.semantic_interpretation_requested"
EVENT_APPROVAL_INTERPRETATION_RESOLVED: Final = "approval.semantic_interpretation_resolved"
EVENT_APPROVAL_CONFIRMATION_REQUESTED: Final = "approval.confirmation_requested"
EVENT_APPROVAL_DECIDED: Final = "approval.decided"
"""Envelopes, not content.

None of these payloads carries a customer's channel address or a word of what they wrote. The
live feed tells a browser that something happened and to which entity; the authoritative detail
stays in rows a reader has to be entitled to look at.
"""

# ------------------------------------------------------------------------------- audit types

AUDIT_APPROVAL_REQUESTED: Final = "APPROVAL_REQUESTED"
AUDIT_APPROVAL_SENT: Final = "APPROVAL_SENT"
AUDIT_APPROVAL_NOT_SENT: Final = "APPROVAL_NOT_SENT"
AUDIT_APPROVAL_EXPIRED: Final = "APPROVAL_EXPIRED"
AUDIT_APPROVAL_DELIVERY_FAILED: Final = "APPROVAL_DELIVERY_FAILED"
AUDIT_APPROVAL_DECISION: Final = "APPROVAL_DECISION_RECORDED"
AUDIT_APPROVAL_REPLY_RECORDED: Final = "APPROVAL_REPLY_RECORDED"
AUDIT_UNAUTHORIZED_APPROVAL: Final = "UNAUTHORIZED_APPROVAL_ATTEMPT"
AUDIT_APPROVAL_REPLY_LATE: Final = "APPROVAL_REPLY_TOO_LATE"
AUDIT_APPROVAL_ALREADY_DECIDED: Final = "APPROVAL_ALREADY_DECIDED"
AUDIT_APPROVAL_CONFIRMATION_REQUESTED: Final = "APPROVAL_CONFIRMATION_REQUESTED"
AUDIT_APPROVAL_CONFIRMATION_UNANSWERED: Final = "APPROVAL_CONFIRMATION_UNANSWERED"

# -------------------------------------------------------------------------- escalation reasons

ESCALATION_NO_APPROVAL_WINDOW: Final = "NO_APPROVAL_WINDOW"
"""§13.6: the deadline had already passed, so no request was sent at all."""

ESCALATION_APPROVAL_EXPIRED: Final = "APPROVAL_EXPIRED"
"""A window that existed and then closed with no answer. Deliberately a different word."""

ESCALATION_APPROVAL_DECLINED: Final = "APPROVAL_DECLINED"
"""The customer said no, literally. The promise is now the owner's to resolve."""

ESCALATION_MESSAGE_UNDELIVERABLE: Final = "MESSAGE_UNDELIVERABLE"
"""The customer was never reached, so there is nobody to be waiting for."""

ESCALATION_NO_CHOSEN_OPTION: Final = "NO_CHOSEN_OPTION"
"""Planning left no option to ask about. Unreachable, and failed closed rather than guessed."""

ESCALATION_CONFIRMATION_UNANSWERED: Final = "CONFIRMATION_UNANSWERED"
"""§13.6's ending for a second reply that is still not one of the two words.

The customer was asked, in the plainest sentence the protocol has, to answer ``YES`` or ``NO``,
and answered something else again. Reading further is not the system's to do, and a second
prompt would be a loop with a person at one end of it. The track goes to the owner with the raw
text attached, which is the one reading of those words anybody is entitled to make.
"""


LIVE_CASE_STATES: Final[tuple[str, ...]] = (
    CASE_EXECUTING,
    CASE_WAITING,
    CASE_REVALIDATING,
    CASE_RECONCILING,
    CASE_RESOLVED,
)
"""Case states in which an inbound reply is still worth reading.

The last two are there because §14.2's duplicate rule outlives the case: "a second distinct
reply to an already-answered request is acknowledged to the customer and audited". A customer
does not know the case has finished, and a reply that arrived one second too late is exactly
the one somebody will later ask about -- so it is stored and the ledger says what was made of
it, rather than being dropped because the workflow had moved on.

Reading one cannot become deciding one. Every path to a decision below requires the request to
be open and undecided, and a case only reaches these states once its requests are settled.
"""
"""Case states in which a customer's reply is still worth reading.

``REVALIDATING`` is in the list deliberately. A second reply to a request that has already been
answered arrives *after* the case has moved on, and §14.2 says it is acknowledged and audited
rather than dropped -- so the transition still has to run in order to record that it changed
nothing. It cannot decide anything: the request is decided, and the check that says so is two
lines below the one that let it in.
"""


class ApprovalStateError(RuntimeError):
    """An approval step describes a shape of the world that cannot be true."""


# --------------------------------------------------------------------------------- executor


async def execute(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    kind: str,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Run one approval step against a case whose row this transaction already holds."""
    if kind == STEP_REQUEST_APPROVAL:
        return await _request(connection, case=case, step_key=step_key, now=now, worker=worker)
    if kind == STEP_MARK_APPROVAL_SENT:
        return await _mark_sent(connection, case=case, step_key=step_key, now=now, worker=worker)
    if kind == STEP_ABANDON_APPROVAL:
        return await _abandon(connection, case=case, step_key=step_key, now=now, worker=worker)
    if kind == STEP_EXPIRE_APPROVAL:
        return await _expire(connection, case=case, step_key=step_key, now=now, worker=worker)
    return await _reply(connection, case=case, step_key=step_key, now=now, worker=worker)


# ------------------------------------------------------------------------- asking the customer


async def _request(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Write the request and queue its message, or refuse to ask at all.

    Nothing is sent from here. What commits is an ``approval_requests`` row, the track bound to
    it, and one outbox row, in a single transaction -- so a crash on either side is recoverable:
    before it there is no request and no message, after it there are both and the dispatcher
    finds the message.

    The track is left ``PENDING`` on purpose. It becomes ``WAITING_FOR_CUSTOMER`` when the
    provider has accepted the message and not one moment earlier.
    """
    if case.state != CASE_EXECUTING:
        return skipped(STEP_REQUEST_APPROVAL, {"case_state": case.state})

    track = await lock_track(connection, track_in(step_key))
    if track.state != TRACK_PENDING:
        return skipped(STEP_REQUEST_APPROVAL, {"track_state": track.state})
    if track.approval_request_id is not None:
        # One live request per track. A track still carrying one is being asked already, and
        # binding it to a second would leave the first open with nothing pointing at it.
        return skipped(
            STEP_REQUEST_APPROVAL, {"approval_request_id": str(track.approval_request_id)}
        )
    if track.classification != Classification.APPROVAL_REQUIRED.value:
        # Unreachable from a confirmation, and refused anyway. Asking a customer to approve a
        # change their own constraints already permitted would be a message nobody needed.
        return skipped(STEP_REQUEST_APPROVAL, {"classification": track.classification})

    option = await chosen_option(connection, track)
    if option is None:
        return await _escalate(
            connection,
            case=case,
            track=track,
            now=now,
            worker=worker,
            reason=ESCALATION_NO_CHOSEN_OPTION,
            audit_type=AUDIT_APPROVAL_NOT_SENT,
            event_type=EVENT_TRACK_ESCALATED,
        )
    if not option.requires_approval:
        return await mark_stale(
            connection,
            case=case,
            track=track,
            now=now,
            worker=worker,
            detail="the chosen option no longer requires approval",
        )

    snapshot = await fresh_snapshot(connection)
    planned = track.fingerprint
    current = await current_fingerprint(connection, track, snapshot=snapshot)
    if planned != current:
        return await mark_stale(
            connection,
            case=case,
            track=track,
            now=now,
            worker=worker,
            detail=f"fingerprint {planned} -> {current}",
        )

    deadline = track.deadline_at
    if deadline is None or deadline <= now:
        # §13.6, and the one branch in this module that decides *not* to contact somebody. A
        # request into a closed window is a message whose only possible answer is too late, so
        # the track goes to the owner with the kitchen work held rather than to the customer.
        return await _escalate(
            connection,
            case=case,
            track=track,
            now=now,
            worker=worker,
            reason=ESCALATION_NO_APPROVAL_WINDOW,
            audit_type=AUDIT_APPROVAL_NOT_SENT,
            event_type=EVENT_TRACK_ESCALATED,
            hold=True,
            detail=None if deadline is None else deadline.isoformat(),
        )

    material = _material(snapshot, track=track, option=option)
    request_id = request_id_for(track.id, option.id, scope_in(step_key))
    code = option_code_for(option.id)
    settings = get_settings()
    # Read once and used for both the wording and the guard, because the two have to agree
    # about the same deployment. Composing the text against one answer and checking it against
    # a second read would be a race nobody could see -- and the message a customer receives is
    # the one artefact of this whole protocol that cannot be corrected afterwards.
    link_available = settings.customer_links_configured
    text = messaging.build_approval_request(
        messaging.ApprovalMessage(
            customer_name=material.customer_name,
            order_reference=material.order_external_id,
            option_code=code,
            due_at=material.due_at,
            timezone=settings.bakery_tz,
            from_product=material.from_product,
            to_product=material.to_product,
            affected_resource=material.affected_resource,
            substitute_resource=material.substitute_resource,
            link_available=link_available,
        )
    )
    if not messaging.carries_required_literals(
        text, option_code=code, link_available=link_available
    ):
        # §13.6's pre-send check. It cannot fail while the text is composed from a template;
        # it exists because the slice that lets a model draft the wording is the one where it
        # can, and a guard added after the drafter is a guard that was once absent.
        raise ApprovalStateError(f"the approval message for {request_id} is missing its literals")

    key = message_idempotency_key(request_id)
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_APPROVAL_REQUESTED,
        # The system is asking, on the authority of the constraint that says this customer must
        # be asked. It is not deciding anything, and the authority that will decide is the
        # customer's own -- which is why nothing here is HUMAN_APPROVAL yet.
        actor=Actor(kind="SYSTEM", id=worker),
        authority="CONSTRAINT" if option.cited_constraint_ids else "POLICY",
        rule_id=option.approval_rule,
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state, "approval_request_id": None},
        after={
            "approval_request_id": str(request_id),
            "option_id": str(option.id),
            "option_code": code,
            "deadline": deadline.isoformat(),
            "idempotency_key": key,
        },
        provenance={
            "step_key": step_key,
            "worker": worker,
            "channel_kind": material.channel_kind,
            "fingerprint": planned,
            "order_external_version": material.order_version,
            "cited_constraint_ids": list(option.cited_constraint_ids),
        },
        occurred_at=now,
    ) as write:
        await _insert_request(
            write,
            request_id=request_id,
            track=track,
            option=option,
            material=material,
            option_code=code,
            deadline=deadline,
            now=now,
        )
        await set_track(write, track=track, approval_request_id=request_id)

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        effects=(
            EmitEffect(
                kind=EFFECT_MESSAGE_SEND,
                payload=_message_payload(
                    track=track,
                    request_id=request_id,
                    scope=None if scope_in(step_key) is None else request_id,
                    material=material,
                    option_code=code,
                    text=text,
                    approval_url=_approval_url(request_id=request_id, channel=material.channel),
                ),
                idempotency_key=key,
            ),
        ),
        events=(
            AppendEvent(
                type=EVENT_APPROVAL_REQUESTED,
                payload={"option_code": code, "deadline": deadline.isoformat()},
                entity_refs=(
                    {"kind": "track", "id": str(track.id)},
                    {"kind": "approval_request", "id": str(request_id)},
                ),
            ),
        ),
        result={
            "outcome": "REQUESTED",
            "track_id": str(track.id),
            "request_id": str(request_id),
            "option_code": code,
            "idempotency_key": key,
            "deadline": deadline.isoformat(),
        },
    )


async def _insert_request(
    write: GovernedWrite,
    *,
    request_id: UUID,
    track: Any,
    option: Any,
    material: _Material,
    option_code: str,
    deadline: datetime,
    now: datetime,
) -> None:
    """Store what is being asked, and the state of the world it is being asked against.

    ``ON CONFLICT DO NOTHING`` on the derived primary key: a second attempt at one logical ask
    writes nothing rather than opening a second conversation with the same customer about the
    same cake.

    Every captured value is the binding §13.6 requires -- the order version, the pinned recipe
    version, the constraint snapshot and the fingerprint. Revalidation compares against these,
    so an approval given for one state of the world cannot be spent on another.
    """
    await write.execute(
        pg_insert(ApprovalRequest)
        .values(
            id=request_id,
            track_id=track.id,
            promise_id=track.promise_id,
            order_id=material.order_id,
            order_line_id=material.order_line_id,
            option_id=option.id,
            option_code=option_code,
            customer_channel=material.channel,
            sent_at=now,
            deadline=deadline,
            captured_fingerprint=track.fingerprint,
            captured_order_version=material.order_version,
            captured_recipe_version_id=material.pinned_version_id,
            captured_constraint_hash=material.constraint_hash,
            state=ApprovalRequestState.SENT.value,
            decided=False,
        )
        .on_conflict_do_nothing(index_elements=[ApprovalRequest.id])
    )


def _approval_url(*, request_id: UUID, channel: str) -> str | None:
    """Where this customer may answer this request, or ``None`` if this deployment mints none.

    Composed here, in the transaction that creates the request, rather than handed out later on
    demand. That is what makes the link *the message's* -- it goes to the channel the request
    was sent to and to nowhere else, and there is no surface in PromisePatch that will hand a
    link to anybody who did not receive the message, because none is stored for one to read.

    Deterministic in the request and the channel, so the redelivery of a message carries the
    same link rather than a second one.
    """
    settings = get_settings()
    if not settings.customer_links_configured:
        return None
    return customer_link.url_for(
        base_url=settings.require_customer_link_base_url(),
        secret=settings.require_customer_link_secret(),
        request_id=request_id,
        channel=channel,
    )


def _message_payload(
    *,
    track: Any,
    request_id: UUID,
    scope: UUID | None,
    material: _Material,
    option_code: str,
    text: str,
    approval_url: str | None,
) -> Mapping[str, Any]:
    """What the provider is being asked to send, and what its answer makes runnable.

    The continuation is stored on the row rather than held by the dispatcher, which is what
    makes the hand-off crash-safe: the step that turns a delivered message into a waiting track
    is enqueued by the same transaction that records the provider's acceptance.

    ``approval_url`` is the one place a customer is handed a way to answer that is not words on
    a channel, and it travels *beside* the text rather than inside it. The text is §13.6's
    frozen wording and a transport may not edit it; a transport that can render a link renders
    this one, and a transport that cannot sends the words unchanged and loses nothing -- the
    two literal words remain the whole protocol either way.

    It is ``None`` where the deployment configured no signing secret, which is a closed door
    rather than a missing feature: a link nobody signed is a link anybody could write.

    ``scope`` is the request's :func:`ask_scope`, so the steps this message makes runnable are
    this request's own. A re-ask's delivery would otherwise propose ``approval-sent:<track>``,
    already settled by the first ask, and the track would never be marked as waiting.
    """
    return {
        EFFECT_TRACK_ID: str(track.id),
        "request_id": str(request_id),
        "promise_id": track.promise_id,
        "order_id": material.order_id,
        "option_code": option_code,
        "channel_kind": material.channel_kind,
        "channel_address": material.channel_address,
        "approval_url": approval_url,
        "text": text,
        CONTINUATION: {
            DELIVERED: {
                "step_key": sent_step_key(track.id, scope),
                "kind": STEP_MARK_APPROVAL_SENT,
                "track_id": str(track.id),
            },
            FAILED: {
                "step_key": abandon_step_key(track.id, scope),
                "kind": STEP_ABANDON_APPROVAL,
                "track_id": str(track.id),
            },
        },
    }


# ------------------------------------------------------------------------- the message went out


async def _mark_sent(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Turn a delivered message into a real wait, against durable proof that it was delivered.

    The proof is the outbox row, read back by the key the request step recorded. An adapter that
    returned successfully in memory proves nothing: the process could have died before that
    answer was written down, and a track marked ``WAITING_FOR_CUSTOMER`` on the strength of it
    would be waiting for a message nobody could show had been sent.
    """
    if case.state != CASE_EXECUTING:
        return skipped(STEP_MARK_APPROVAL_SENT, {"case_state": case.state})

    track = await lock_track(connection, track_in(step_key))
    if track.state != TRACK_PENDING:
        return skipped(STEP_MARK_APPROVAL_SENT, {"track_state": track.state})

    request = await _lock_request(connection, track.approval_request_id)
    if request is None:
        raise ApprovalStateError(f"track {track.id} has no approval request to mark sent")
    if not step_names(step_key, request):
        # The delivery this step reports was for a request the track no longer carries. A later
        # ask is marked sent by its own delivery, never by an earlier one's.
        return skipped(STEP_MARK_APPROVAL_SENT, {"request_id": str(request.id)})
    if request.decided or request.state not in OPEN_APPROVAL_STATES:
        return skipped(STEP_MARK_APPROVAL_SENT, {"request_state": request.state})

    key = message_idempotency_key(request.id)
    effect = await _effect_for(connection, key)
    if effect is None or effect.state != "DELIVERED" or effect.provider_ref is None:
        # Fail closed rather than claim a wait. The step was enqueued by a delivery
        # acknowledgement, so this should be unreachable; retrying and eventually escalating is
        # the only answer that does not invent a conversation.
        return StepOutcome(
            disposition=Disposition.RETRYING,
            event_type=EVENT_STEP_FAILED,
            error=f"approval message {key} is not durably delivered",
        )

    if request.deadline <= now:
        # The window closed between the provider accepting the message and this transaction.
        # There is no valid answer left, so the track does not pretend to be waiting for one.
        return await _close_request(
            connection,
            case=case,
            track=track,
            request=request,
            now=now,
            worker=worker,
            reason=ESCALATION_APPROVAL_EXPIRED,
            audit_type=AUDIT_APPROVAL_EXPIRED,
            event_type=EVENT_APPROVAL_EXPIRED,
            hold=True,
        )

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_APPROVAL_SENT,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state, "provider_ref": request.provider_ref},
        after={
            "track_state": TRACK_WAITING_FOR_CUSTOMER,
            "provider_ref": effect.provider_ref,
            "sent_at": now.isoformat(),
            "deadline": request.deadline.isoformat(),
        },
        provenance={
            "step_key": step_key,
            "worker": worker,
            "request_id": str(request.id),
            "idempotency_key": key,
            "attempts": effect.attempts,
        },
        occurred_at=now,
    ) as write:
        # ``sent_at`` becomes the instant the provider accepted it, which is what makes the
        # ``deadline > sent_at`` check on this table the database's own record that no request
        # was ever *sent* into a closed window.
        await write.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.id == request.id)
            .values(provider_ref=effect.provider_ref, sent_at=now)
        )
        await set_track(write, track=track, state=TRACK_WAITING_FOR_CUSTOMER)
        moved_to = await settled_case_state(connection, case=case, except_step_key=step_key)
    successors = await case_successors(connection, moved_to, case_id=case.id)

    logger.info(
        "approval.sent",
        request_id=str(request.id),
        track_id=str(track.id),
        attempts=effect.attempts,
        case_state=moved_to or case.state,
    )
    events = [
        AppendEvent(
            type=EVENT_APPROVAL_SENT,
            payload={"attempts": effect.attempts, "deadline": request.deadline.isoformat()},
            entity_refs=(
                {"kind": "track", "id": str(track.id)},
                {"kind": "approval_request", "id": str(request.id)},
            ),
        ),
        *case_events(moved_to, case_id=case.id),
    ]
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=moved_to),
        successors=successors,
        timers=(_deadline_timer(request_id=request.id, deadline=request.deadline, now=now),),
        events=tuple(events),
        result={
            "outcome": "WAITING_FOR_CUSTOMER",
            "track_id": str(track.id),
            "request_id": str(request.id),
            "provider_ref": effect.provider_ref,
            "case_state": moved_to or case.state,
        },
    )


async def _abandon(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """The message will not be attempted again, so nobody is waiting on this customer.

    §11.6 escalates rather than leaving a track that looks busy while nothing is happening. The
    reason distinguishes the two ways a message can end up undeliverable, because they are
    different problems: a provider that refused it, and a window that closed while it queued.
    """
    track = await lock_track(connection, track_in(step_key))
    if track.state != TRACK_PENDING:
        return skipped(STEP_ABANDON_APPROVAL, {"track_state": track.state})

    request = await _lock_request(connection, track.approval_request_id)
    if request is None:
        raise ApprovalStateError(f"track {track.id} has no approval request to abandon")
    if not step_names(step_key, request):
        # An earlier ask's failed delivery says nothing about the request the track carries now.
        return skipped(STEP_ABANDON_APPROVAL, {"request_id": str(request.id)})

    expired = request.deadline <= now
    return await _close_request(
        connection,
        case=case,
        track=track,
        request=request,
        now=now,
        worker=worker,
        reason=ESCALATION_APPROVAL_EXPIRED if expired else ESCALATION_MESSAGE_UNDELIVERABLE,
        audit_type=AUDIT_APPROVAL_DELIVERY_FAILED,
        event_type=EVENT_APPROVAL_DELIVERY_FAILED,
        # The same discriminant the reason above uses, so the two can never drift apart: a
        # deadline that has passed is §23's expiry row and holds, while a message that failed
        # to send inside a window still open is not a row §23 answers with a hold.
        hold=expired,
        detail=request.provider_ref,
    )


# -------------------------------------------------------------------------- the window closes


async def _expire(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """The deadline passed with no literal answer. Nothing is decided on the customer's behalf.

    Created by a ``timers`` row, so downtime delays it and never loses it: a worker that starts
    an hour after the deadline finds it overdue and fires it immediately, which is what should
    happen, because the window closed whether or not anybody was running.
    """
    request = await _read_request(connection, request_of(step_key))
    if request is None:
        raise ApprovalStateError(f"approval request {request_of(step_key)} does not exist")

    track = await lock_track(connection, request.track_id)
    locked = await _lock_request(connection, request.id)
    if locked is None:  # pragma: no cover - the row cannot vanish under a held track lock
        raise ApprovalStateError(f"approval request {request.id} vanished under its track lock")
    if locked.decided or locked.state not in OPEN_APPROVAL_STATES:
        # §11.5's ``TIMER_NOOP``: a deadline for a question already answered changes nothing.
        return skipped(STEP_EXPIRE_APPROVAL, {"request_state": locked.state})
    if now < locked.deadline:  # pragma: no cover - the timer is armed at the deadline itself
        return skipped(STEP_EXPIRE_APPROVAL, {"deadline": locked.deadline.isoformat()})

    return await _close_request(
        connection,
        case=case,
        track=track,
        request=locked,
        now=now,
        worker=worker,
        reason=ESCALATION_APPROVAL_EXPIRED,
        audit_type=AUDIT_APPROVAL_EXPIRED,
        event_type=EVENT_APPROVAL_EXPIRED,
        hold=True,
    )


async def approval_timer_case(connection: AsyncConnection, request_id: UUID) -> UUID | None:
    """Which case a deadline belongs to, for the timer sweep that has only the request id.

    A deadline is armed against the request rather than the case (a case may be waiting on more
    than one customer), so firing it has to find its way back to a case before it can become a
    step. Returns ``None`` for a request whose rows have gone, which the sweep treats as a timer
    with nothing to wake.
    """
    case_id: UUID | None = await connection.scalar(
        select(Track.case_id)
        .join(ApprovalRequest, ApprovalRequest.track_id == Track.id)
        .where(ApprovalRequest.id == request_id)
    )
    return case_id


# ---------------------------------------------------------------------- the customer replies


async def _reply(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Read one stored reply, and let it decide only what a literal reply is allowed to decide.

    The order of the checks is the protocol (§18.5), and each one fails to a *no-op that is
    recorded* rather than to an exception: a wrong sender, a closed request and a late answer
    are all things that really happen, and the honest response to each is to keep the raw text,
    say in the ledger what was done with it, and leave the request exactly as it was.
    """
    if case.state not in LIVE_CASE_STATES:
        return skipped(STEP_RECEIVE_CUSTOMER_REPLY, {"case_state": case.state})

    reply = await _stored_reply(connection, inbox_of(step_key))
    request = await _read_request(connection, reply.request_id)
    if request is None:
        raise ApprovalStateError(f"reply {reply.provider_message_id} names no approval request")

    track = await lock_track(connection, request.track_id)
    locked = await _lock_request(connection, request.id)
    if locked is None:  # pragma: no cover - the row cannot vanish under a held track lock
        raise ApprovalStateError(f"approval request {request.id} vanished under its track lock")

    customer_id = await _customer_of(connection, locked.order_id)
    context = _ReplyContext(
        connection=connection,
        case=case,
        track=track,
        request=locked,
        reply=reply,
        customer_id=customer_id,
        now=now,
        worker=worker,
        step_key=step_key,
    )

    if reply.sender != locked.customer_channel:
        # §14.3 check 8, and the only place in the system where an approval is refused because
        # of *who* sent it. There is no worker or owner path that could substitute for this.
        return await _record_reply(
            context,
            audit_type=AUDIT_UNAUTHORIZED_APPROVAL,
            event_type=EVENT_APPROVAL_REPLY_UNAUTHORIZED,
            actor=Actor(kind="SYSTEM", id=worker),
            outcome="UNAUTHORIZED",
            needs_owner_attention=True,
        )
    if locked.decided or locked.state not in OPEN_APPROVAL_STATES:
        return await _record_reply(
            context,
            audit_type=AUDIT_APPROVAL_ALREADY_DECIDED,
            event_type=EVENT_APPROVAL_REPLY_IGNORED,
            actor=Actor(kind="CUSTOMER", id=customer_id),
            outcome="ALREADY_SETTLED",
        )
    if now > locked.deadline:
        # Compared against the database's clock, under the request lock, rather than against
        # whether the deadline timer has been processed yet. A worker running late must not
        # extend a customer's authority by the length of its own backlog.
        return await _record_reply(
            context,
            audit_type=AUDIT_APPROVAL_REPLY_LATE,
            event_type=EVENT_APPROVAL_REPLY_IGNORED,
            actor=Actor(kind="CUSTOMER", id=customer_id),
            outcome="TOO_LATE",
        )

    decision = consent.read_literal(reply.text)
    if decision is None:
        # The one branch the whole authority model turns on. "Strawberries work" is a sentence
        # about strawberries; it is stored, and it decides nothing here or anywhere after here.
        return await _unrecognized(context)
    # Literal, and therefore authoritative -- whatever else the customer wrote on this request
    # before it. An earlier reply is provenance; it is not an input to this line.
    return await _record_decision(context, decision=decision)


async def _unrecognized(context: _ReplyContext) -> StepOutcome:
    """What §13.6 does with words that are not one of the two: ask once, then hand over.

    The rule is the request's own state, and it is deliberately a counter of one:

    * **First** non-literal reply, request ``SENT``: store it, and enqueue the durable work that
      asks the customer to answer in words that count. Nothing is decided, nothing is mutated,
      and the track keeps waiting.
    * **Second** non-literal reply, request ``CONFIRMATION_PENDING``: the plainest sentence the
      protocol has was already sent and was answered with something else. The track escalates
      with the raw text attached, for a person to read.

    That is also the whole of the duplicate-confirmation defence, and it is deterministic: the
    condition that permits a prompt is a state the prompt itself removes, so there is exactly
    one outstanding confirmation per request and no number of further replies produces a second.
    """
    if context.request.state == ApprovalRequestState.CONFIRMATION_PENDING.value:
        return await _escalate_unconfirmed(context)

    reply_id = reply_id_for(context.reply.provider_message_id)
    return await _record_reply(
        context,
        audit_type=AUDIT_APPROVAL_REPLY_RECORDED,
        event_type=EVENT_APPROVAL_REPLY_UNRECOGNIZED,
        actor=Actor(kind="CUSTOMER", id=context.customer_id),
        outcome="NOT_LITERAL",
        # Enqueued in the same transaction that stores the reply, so a crash between the two is
        # not a shape the database can hold: either there is no reply and no work, or there is
        # a reply and the durable work that reads it.
        successors=(
            CreateStep(
                step_key=interpret_step_key(reply_id),
                kind=STEP_INTERPRET_CUSTOMER_REPLY,
            ),
        ),
        events=(
            AppendEvent(
                type=EVENT_APPROVAL_INTERPRETATION_REQUESTED,
                payload={"reason": "NOT_LITERAL"},
                entity_refs=({"kind": "approval_request", "id": str(context.request.id)},),
            ),
        ),
    )


async def _escalate_unconfirmed(context: _ReplyContext) -> StepOutcome:
    """§13.6's "a second non-literal reply -> ESCALATED with the raw text attached".

    The same ending as an expired window, reached for a different reason and named differently
    so the ledger says which: the customer was reachable and answered twice, and neither answer
    was consent. No decision is written and none is implied -- a person picks this up holding
    exactly what the customer wrote.
    """
    case, track, request = context.case, context.track, context.request
    unit_of_work = UnitOfWork(context.connection)
    async with unit_of_work.governed(
        event_type=AUDIT_APPROVAL_CONFIRMATION_UNANSWERED,
        actor=Actor(kind="SYSTEM", id=context.worker),
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state, "request_state": request.state},
        after={
            "track_state": TRACK_ESCALATED,
            "request_state": ApprovalRequestState.EXPIRED.value,
            "reason": ESCALATION_CONFIRMATION_UNANSWERED,
        },
        provenance={
            "request_id": str(request.id),
            "provider_message_id": context.reply.provider_message_id,
            "inbound_reply_id": str(reply_id_for(context.reply.provider_message_id)),
            "inbox_event_id": str(context.reply.inbox_id),
            "sender_identity": context.reply.sender,
            "executed_by": context.worker,
            "step_key": context.step_key,
        },
        occurred_at=context.now,
    ) as write:
        await _insert_reply(write, context)
        await write.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.id == request.id, ApprovalRequest.decided.is_(False))
            .values(state=ApprovalRequestState.EXPIRED.value)
        )
        await set_track(write, track=track, state=TRACK_ESCALATED)
        moved_to = await settled_case_state(
            context.connection, case=case, except_step_key=context.step_key
        )
    successors = await case_successors(context.connection, moved_to, case_id=case.id)

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=moved_to, needs_owner_attention=True),
        successors=successors,
        events=(
            AppendEvent(
                type=EVENT_APPROVAL_REPLY_UNRECOGNIZED,
                payload={"outcome": "SECOND_NOT_LITERAL"},
                entity_refs=({"kind": "approval_request", "id": str(request.id)},),
            ),
            AppendEvent(
                type=EVENT_TRACK_ESCALATED,
                payload={"reason": ESCALATION_CONFIRMATION_UNANSWERED},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
            *case_events(moved_to, case_id=case.id),
        ),
        result={
            "outcome": "ESCALATED",
            "track_id": str(track.id),
            "request_id": str(request.id),
            "reason": ESCALATION_CONFIRMATION_UNANSWERED,
        },
    )


async def _record_decision(
    context: _ReplyContext, *, decision: ApprovalDecisionKind
) -> StepOutcome:
    """Persist exactly one authoritative decision, and hand the case on without spending it.

    The decision row is append-only and unique per request, so what commits here is final: no
    later reply, timer, worker or owner can overwrite it, and there is no code path that could.

    An approval does not apply anything. §14.3's ten checks have not run, so the track stays
    ``WAITING_FOR_CUSTOMER`` and the case moves to ``REVALIDATING`` once nothing is outstanding.
    A decline is different only in that there is nothing left to revalidate: the track escalates
    to the owner, and the customer is never told the original will arrive, because it may not.
    """
    case, track, request = context.case, context.track, context.request
    approved = decision is ApprovalDecisionKind.APPROVE
    unit_of_work = UnitOfWork(context.connection)
    async with unit_of_work.governed(
        event_type=AUDIT_APPROVAL_DECISION,
        # The customer, and nobody else. The worker's identity is on the provenance because it
        # executed the transition; it did not supply the consent, and the ledger must never
        # read as though a process could.
        actor=Actor(kind="CUSTOMER", id=context.customer_id),
        authority="HUMAN_APPROVAL",
        case_id=case.id,
        track_id=track.id,
        before={"request_state": request.state, "decided": request.decided},
        after={
            "request_state": ApprovalRequestState.ANSWERED.value,
            "decided": True,
            "decision": decision.value,
            "parser": ParserKind.LITERAL.value,
            "track_state": track.state if approved else TRACK_ESCALATED,
        },
        provenance={
            "request_id": str(request.id),
            "provider_message_id": context.reply.provider_message_id,
            "inbound_reply_id": str(reply_id_for(context.reply.provider_message_id)),
            "inbox_event_id": str(context.reply.inbox_id),
            "sender_identity": context.reply.sender,
            "parser": ParserKind.LITERAL.value,
            "executed_by": context.worker,
            "step_key": context.step_key,
        },
        occurred_at=context.now,
    ) as write:
        await _insert_reply(write, context)
        await write.execute(
            pg_insert(ApprovalDecision).values(
                id=uuid4(),
                request_id=request.id,
                decision=decision.value,
                parser=ParserKind.LITERAL.value,
                sender_identity=context.reply.sender,
                provider_message_id=context.reply.provider_message_id,
                raw_text=context.reply.text,
                received_at=context.now,
            )
        )
        await write.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.id == request.id, ApprovalRequest.decided.is_(False))
            .values(state=ApprovalRequestState.ANSWERED.value, decided=True)
        )
        if not approved:
            await set_track(write, track=track, state=TRACK_ESCALATED)
        moved_to = await settled_case_state(
            context.connection, case=case, except_step_key=context.step_key
        )
    # The revalidation this decision has earned, or the reconciliation a decline has: either
    # way the case must leave the boundary it has just arrived at under its own power.
    successors = await case_successors(context.connection, moved_to, case_id=case.id)

    # No channel address and no reply text: §26 keeps both in the database, where a reader has
    # to be entitled to look, and out of a log that is shipped, sampled and searchable.
    logger.info(
        "approval.decided",
        request_id=str(request.id),
        track_id=str(track.id),
        decision=decision.value,
        parser=ParserKind.LITERAL.value,
        case_state=moved_to or case.state,
    )
    events = [
        AppendEvent(
            type=EVENT_APPROVAL_REPLY_RECEIVED,
            payload={"literal": True},
            entity_refs=({"kind": "approval_request", "id": str(request.id)},),
        ),
        AppendEvent(
            type=EVENT_APPROVAL_DECIDED,
            payload={"decision": decision.value, "parser": ParserKind.LITERAL.value},
            entity_refs=(
                {"kind": "track", "id": str(track.id)},
                {"kind": "approval_request", "id": str(request.id)},
            ),
        ),
        *case_events(moved_to, case_id=case.id),
    ]
    if not approved:
        events.append(
            AppendEvent(
                type=EVENT_TRACK_ESCALATED,
                payload={"reason": ESCALATION_APPROVAL_DECLINED},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            )
        )
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=moved_to, needs_owner_attention=None if approved else True),
        successors=successors,
        events=tuple(events),
        result={
            "outcome": decision.value,
            "track_id": str(track.id),
            "request_id": str(request.id),
            "parser": ParserKind.LITERAL.value,
            "case_state": moved_to or case.state,
        },
    )


async def _record_reply(
    context: _ReplyContext,
    *,
    audit_type: str,
    event_type: str,
    actor: Actor,
    outcome: str,
    needs_owner_attention: bool | None = None,
    successors: tuple[CreateStep, ...] = (),
    events: tuple[AppendEvent, ...] = (),
) -> StepOutcome:
    """Store a reply that decided nothing, and say in the ledger why it decided nothing.

    Every one of these leaves the request exactly as it was: still open if it was open, still
    settled if it was settled, and never carrying a decision it did not receive.
    """
    case, track, request = context.case, context.track, context.request
    unit_of_work = UnitOfWork(context.connection)
    async with unit_of_work.governed(
        event_type=audit_type,
        actor=actor,
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"request_state": request.state, "decided": request.decided},
        after={"request_state": request.state, "decided": request.decided, "outcome": outcome},
        provenance={
            "request_id": str(request.id),
            "provider_message_id": context.reply.provider_message_id,
            "inbox_event_id": str(context.reply.inbox_id),
            "sender_identity": context.reply.sender,
            "expected_channel": request.customer_channel,
            "executed_by": context.worker,
            "step_key": context.step_key,
        },
        occurred_at=context.now,
    ) as write:
        await _insert_reply(write, context)

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(needs_owner_attention=needs_owner_attention),
        successors=successors,
        events=(
            AppendEvent(
                type=event_type,
                payload={"outcome": outcome},
                entity_refs=({"kind": "approval_request", "id": str(request.id)},),
            ),
            *events,
        ),
        result={
            "outcome": outcome,
            "track_id": str(track.id),
            "request_id": str(request.id),
            "decided": request.decided,
        },
    )


async def _insert_reply(write: GovernedWrite, context: _ReplyContext) -> None:
    """Keep the customer's words, exactly as they wrote them, whatever we made of them.

    Keyed on the provider's message id so one message is one stored reply however many times it
    is handed to us. ``apparent_intent`` stays null: this slice has nothing that reads free text,
    and a column filled in by guesswork would be indistinguishable later from one filled in by a
    classifier that had actually run.
    """
    await write.execute(
        pg_insert(InboundReply)
        .values(
            id=reply_id_for(context.reply.provider_message_id),
            request_id=context.request.id,
            provider_message_id=context.reply.provider_message_id,
            sender_identity=context.reply.sender,
            raw_text=context.reply.text,
            received_at=context.reply.received_at or context.now,
        )
        .on_conflict_do_nothing(index_elements=[InboundReply.provider_message_id])
    )


# ------------------------------------------------------------------------------ inbound intake


async def bind_customer_reply(
    connection: AsyncConnection, outcome: InboundOutcome
) -> InboundOutcome:
    """Attach a stored customer reply to the case that will decide what to do with it.

    Binding is *not* authorisation, and the distinction matters: this resolves which request the
    transport says the reply is about, and the step that follows is what checks whether the
    sender was entitled to answer it. A reply naming a request that does not exist is understood
    and produces no work, rather than being retried forever against a row that will never arrive.
    """
    normalized = dict(outcome.normalized or {})
    raw_request = normalized.get("request_id")
    try:
        request_id = UUID(str(raw_request))
    except (TypeError, ValueError):
        return InboundOutcome(
            state="IGNORED", normalized=normalized, error="the reply names no approval request"
        )

    case_id = await approval_timer_case(connection, request_id)
    if case_id is None:
        return InboundOutcome(
            state="IGNORED",
            normalized=normalized,
            error=f"no approval request {request_id} is on any case",
        )
    return InboundOutcome(
        state="PROCESSED",
        normalized=normalized,
        case_id=case_id,
        step_kind=STEP_RECEIVE_CUSTOMER_REPLY,
    )


# -------------------------------------------------------------------- refusing a late message


async def refuse_if_window_closed(
    database: RuntimeDatabase, *, kind: str, payload: Mapping[str, Any]
) -> DeliveryOutcome | None:
    """Refuse an approval message whose window closed while it waited to be sent.

    The one piece of business knowledge the dispatcher is allowed to consult, and it is narrow
    on purpose: it answers "may this still be sent at all", never "what should happen next".
    §13.6 forbids sending a request into a window in which no valid answer could arrive, and a
    message that queued past its own deadline is precisely that -- so it is refused terminally,
    which routes it to the failure continuation the request step already stored on the row.

    Returns ``None`` for every effect that is not an approval message, and for every approval
    message that is still valid.
    """
    if kind != EFFECT_MESSAGE_SEND:
        return None
    raw_request = payload.get("request_id")
    if raw_request is None:
        return None

    async with database.connect() as connection:
        now = await database_now(connection)
        request = await _read_request(connection, UUID(str(raw_request)))

    if request is None:
        return DeliveryOutcome(
            status=DeliveryStatus.TERMINAL, error="the approval request no longer exists"
        )
    if request.decided or request.state not in OPEN_APPROVAL_STATES:
        return DeliveryOutcome(
            status=DeliveryStatus.TERMINAL,
            error=f"the approval request is {request.state}, not open",
        )
    if request.deadline <= now:
        return DeliveryOutcome(
            status=DeliveryStatus.TERMINAL,
            error="the approval window closed before the message could be delivered",
        )
    return None


# ------------------------------------------------------------------------------ shared endings


async def _close_request(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    track: Any,
    request: Any,
    now: datetime,
    worker: str,
    reason: str,
    audit_type: str,
    event_type: str,
    hold: bool,
    detail: str | None = None,
) -> StepOutcome:
    """Shut a request that can no longer be answered, and hand its track to the owner.

    One ending for expiry and for undeliverable transport, because the customer's position is
    identical in both: they were never going to be able to answer, so nothing they might say
    later could authorise anything, and the promise belongs on somebody's desk rather than in a
    queue. No decision is written, and none is implied.

    ``hold`` is the other half of §23's answer. Its failure-semantics table meets "customer does
    not reply" with "EXPIRED -> ESCALATED; task HELD", so an escalation this path reaches after
    the deadline stops the kitchen too: nobody should bake a cake the case has just concluded it
    can no longer ask about. Escalating without it leaves the promise on a desk and the oven on.

    It has no default on purpose. The two endings are not the same fact -- a deadline that has
    passed is the spec's row, transport that failed inside a window still open is not -- and §23
    states the hold for one of them only, so each caller says which it is rather than inheriting
    an answer from the function they happen to share.
    """
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=audit_type,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state, "request_state": request.state},
        after={
            "track_state": TRACK_ESCALATED,
            "request_state": ApprovalRequestState.EXPIRED.value,
            "reason": reason,
        },
        provenance={
            "worker": worker,
            "request_id": str(request.id),
            "deadline": request.deadline.isoformat(),
            "detail": detail,
        },
        occurred_at=now,
    ) as write:
        await write.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.id == request.id, ApprovalRequest.decided.is_(False))
            .values(state=ApprovalRequestState.EXPIRED.value)
        )
        await set_track(write, track=track, state=TRACK_ESCALATED)
        held = await hold_tasks(write, track=track, case_id=case.id) if hold else ()
        moved_to = await settled_case_state(connection, case=case)
    successors = await case_successors(connection, moved_to, case_id=case.id)

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=moved_to, needs_owner_attention=True),
        successors=successors,
        events=(
            AppendEvent(
                type=event_type,
                payload={"reason": reason, "tasks_held": len(held)},
                entity_refs=(
                    {"kind": "track", "id": str(track.id)},
                    {"kind": "approval_request", "id": str(request.id)},
                ),
            ),
            *case_events(moved_to, case_id=case.id),
        ),
        result={
            "outcome": "ESCALATED",
            "track_id": str(track.id),
            "request_id": str(request.id),
            "reason": reason,
            "tasks_held": len(held),
        },
    )


async def _escalate(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    track: Any,
    now: datetime,
    worker: str,
    reason: str,
    audit_type: str,
    event_type: str,
    hold: bool = False,
    detail: str | None = None,
) -> StepOutcome:
    """Hand a track to the owner before any request exists, and send nothing to anybody.

    ``hold`` is §13.6's one write for a closed window: the kitchen work stops, so nobody starts
    a cake whose change nobody can be asked about in time. It is reversible by the owner, and it
    is the only consequence a refusal to ask has.
    """
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=audit_type,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        track_id=track.id,
        before={"track_state": track.state},
        after={"track_state": TRACK_ESCALATED, "reason": reason},
        provenance={"worker": worker, "deadline": detail},
        occurred_at=now,
    ) as write:
        await set_track(write, track=track, state=TRACK_ESCALATED)
        held = await hold_tasks(write, track=track, case_id=case.id) if hold else ()
        moved_to = await settled_case_state(connection, case=case)
    successors = await case_successors(connection, moved_to, case_id=case.id)

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=moved_to, needs_owner_attention=True),
        successors=successors,
        events=(
            AppendEvent(
                type=event_type,
                payload={"reason": reason, "tasks_held": len(held)},
                entity_refs=({"kind": "track", "id": str(track.id)},),
            ),
            *case_events(moved_to, case_id=case.id),
        ),
        result={
            "outcome": "ESCALATED",
            "track_id": str(track.id),
            "reason": reason,
            "tasks_held": len(held),
        },
    )


def _deadline_timer(*, request_id: UUID, deadline: datetime, now: datetime) -> ArmTimer:
    """The deadline, as a row that outlives every process that could have watched it."""
    return ArmTimer(
        kind=TIMER_APPROVAL_DEADLINE,
        subject_type=APPROVAL_SUBJECT,
        subject_id=str(request_id),
        delay=deadline - now,
    )


# ---------------------------------------------------------------------------------- reading


@dataclass(frozen=True, slots=True)
class _Material:
    """Everything an approval request needs about the world, read once from one snapshot."""

    order_id: str
    order_line_id: str
    order_external_id: str
    order_version: int
    due_at: datetime | None
    customer_name: str
    channel: str
    channel_kind: str
    channel_address: str
    pinned_version_id: str
    constraint_hash: str
    from_product: str | None
    to_product: str | None
    affected_resource: str | None
    substitute_resource: str | None


@dataclass(frozen=True, slots=True)
class _StoredReply:
    """One inbound record, as the consent protocol reads it back out of the inbox."""

    inbox_id: UUID
    request_id: UUID | None
    sender: str
    text: str
    provider_message_id: str
    received_at: datetime | None


@dataclass(frozen=True, slots=True)
class _ReplyContext:
    """The rows one reply transaction is holding, passed once instead of eight times over."""

    connection: AsyncConnection
    case: LockedCase
    track: Any
    request: Any
    reply: _StoredReply
    customer_id: str | None
    now: datetime
    worker: str
    step_key: str


def _material(snapshot: GraphSnapshot, *, track: Any, option: Any) -> _Material:
    """Read the request's whole world out of one graph snapshot.

    One snapshot rather than six queries, because every value here has to describe the *same*
    instant: a customer name from one moment and an order version from another would produce a
    request bound to a world that never existed.
    """
    promise = snapshot.promises[track.promise_id]
    order = snapshot.orders[promise.order_id]
    customer = snapshot.customers[order.customer_id]
    line_id = option.order_line_id
    if line_id is None or line_id not in snapshot.order_lines:
        raise ApprovalStateError(f"option {option.id} names no order line to change")
    kind, address = split_channel(customer.approval_channel)

    return _Material(
        order_id=order.id,
        order_line_id=line_id,
        order_external_id=order.external_id,
        order_version=order.external_version,
        due_at=promise.due_at,
        customer_name=customer.name,
        channel=customer.approval_channel,
        channel_kind=kind,
        channel_address=address,
        pinned_version_id=snapshot.order_lines[line_id].recipe_version_id,
        constraint_hash=constraint_hash(snapshot, order.id),
        from_product=_product(snapshot, option.from_version_id),
        to_product=_product(snapshot, option.to_version_id),
        affected_resource=_resource(snapshot, option.affected_resource_id),
        substitute_resource=_resource(snapshot, option.substitute_resource_id),
    )


def _product(snapshot: GraphSnapshot, version_id: str | None) -> str | None:
    """A recipe version as a customer would recognise it: the product name and its version."""
    if version_id is None or version_id not in snapshot.versions:
        return None
    version = snapshot.versions[version_id]
    recipe = snapshot.recipes.get(version.recipe_id)
    return None if recipe is None else f"{recipe.name} (v{version.version_no})"


def _resource(snapshot: GraphSnapshot, resource_id: str | None) -> str | None:
    if resource_id is None or resource_id not in snapshot.resources:
        return None
    return snapshot.resources[resource_id].name


async def _read_request(connection: AsyncConnection, request_id: UUID | None) -> Any:
    if request_id is None:
        return None
    return (
        await connection.execute(select(ApprovalRequest).where(ApprovalRequest.id == request_id))
    ).one_or_none()


async def _lock_request(connection: AsyncConnection, request_id: UUID | None) -> Any:
    """Take the request row for update. After the case row and after the track row, never before.

    One lock order everywhere -- case, track, request -- is what makes a ``YES`` and a ``NO``
    racing for the same request queue instead of deadlock, and what makes the loser re-read a
    row the winner has already settled.
    """
    if request_id is None:
        return None
    return (
        await connection.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == request_id).with_for_update()
        )
    ).one_or_none()


async def _effect_for(connection: AsyncConnection, idempotency_key: str) -> Any:
    return (
        await connection.execute(
            select(OutboxMessage).where(OutboxMessage.idempotency_key == idempotency_key)
        )
    ).one_or_none()


async def _customer_of(connection: AsyncConnection, order_id: str) -> str | None:
    customer_id: str | None = await connection.scalar(
        select(Order.customer_id).where(Order.id == order_id)
    )
    return customer_id


async def _stored_reply(connection: AsyncConnection, inbox_id: UUID) -> _StoredReply:
    """The inbound record, read from the row rather than from whatever delivered it.

    Replaying an inbox row a year later reads the same material it read at the time, which is
    what makes the consent protocol replayable and what stops a decision from ever depending on
    a connection that has since closed.
    """
    row = (
        await connection.execute(
            select(InboxEvent.id, InboxEvent.normalized, InboxEvent.received_at).where(
                InboxEvent.id == inbox_id
            )
        )
    ).one_or_none()
    if row is None or not row.normalized:
        raise ApprovalStateError(f"inbox record {inbox_id} carries no normalised reply")

    normalized = dict(row.normalized)
    raw_request = normalized.get("request_id")
    return _StoredReply(
        inbox_id=row.id,
        request_id=None if raw_request is None else UUID(str(raw_request)),
        sender=str(normalized.get("sender", "")),
        text=str(normalized.get("text", "")),
        provider_message_id=str(normalized.get("provider_message_id", "")),
        received_at=row.received_at,
    )
