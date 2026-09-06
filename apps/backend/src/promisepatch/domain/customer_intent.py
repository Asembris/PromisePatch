"""Reading a customer's free text, and asking them again in the two words that count.

This is the semantic half of the consent protocol, and it lives in its own module because of
what it must not be able to do. The rule from §15 is that the model "can never produce a
decision", and a rule enforced by remembering it is not enforced. So:

* Nothing here imports :mod:`promisepatch.domain.consent`, and nothing here can read a literal
  ``YES``. Deciding is somebody else's job and this module cannot do it by accident.
* Nothing here imports :class:`~promisepatch.db.models.ApprovalDecision`, mentions
  ``approval_decisions``, or writes :class:`~promise_graph.model.ParserKind`. There is no line
  to delete to make this module safe, because there is no line that makes it unsafe.
* The strongest word the vocabulary it consumes contains is ``APPARENT_APPROVE``, which is not
  a member of :class:`~promise_graph.model.ApprovalDecisionKind` and cannot be handed anywhere
  a decision is expected. A test asserts all of this against the source of this file.

**What it actually decides is nothing.** §13.6 gives all three labels -- ``APPARENT_APPROVE``,
``APPARENT_DECLINE`` and ``UNCLEAR`` -- the same response: one confirmation prompt, the request
to ``CONFIRMATION_PENDING``, the track left exactly where it was. So does the deterministic
fallback for the job, which §14.3 fixes as ``UNCLEAR``. That is worth stating plainly, because
it is the property the whole slice rests on:

    The label changes what the ledger records. It changes nothing about what happens.

A model that answered ``APPARENT_APPROVE``, a model that answered ``APPARENT_DECLINE``, a model
that returned malformed JSON and a model that could not be reached at all produce the identical
message and the identical state. There is no branch here for a model to influence, which is why
a prompt-injected reply cannot buy anything: complying with it perfectly still sends the
customer the sentence asking them to type ``YES`` or ``NO``.

**Two transactions and a call between them**, the same shape as every other provider call in
PromisePatch::

    worker claims the INTERPRET_CUSTOMER_REPLY step   (the ordinary claim sweep)
            │
            ├── transaction: read the reply and its request, decide whether to ask at all,
            │   fingerprint the binding ... commit, hold nothing ...
            ├── the provider call                     (no transaction, no lock, no connection)
            └── transaction: write the reading onto the step row, fenced by the claim
            │
    worker executes the step                          (the ordinary execution transaction)
            case, track and request locked; deadline, sender and binding re-checked;
            one confirmation enqueued, or nothing at all

**The step is never created for a reply that could not use one.** An unauthorised sender, a
closed window, a settled request, a duplicate delivery and a literal ``YES`` are all refused by
the reply step before this work exists, so none of them costs a model call. The re-checks in
:func:`prepare` cover only the window between the enqueue and the claim, and the re-checks in
:func:`execute` cover the window between the call and the commit -- which is where a customer's
literal ``YES``, racing a model that is still thinking, wins absolutely and this work no-ops.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.model import ApprovalRequestState
from promisepatch.db.clock import database_now
from promisepatch.db.models import (
    ApprovalRequest,
    Case,
    CaseStep,
    Customer,
    InboundReply,
    Order,
)
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.db.uow import Actor, UnitOfWork
from promisepatch.domain import approvals, crash, messaging, retry, semantic_intake
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
    EVENT_STEP_FAILED,
    AppendEvent,
    CaseChange,
    Disposition,
    EmitEffect,
    StepOutcome,
)
from promisepatch.domain.recovery import lock_track
from promisepatch.domain.steps import StepClaim
from promisepatch.graph.channel import split_channel
from promisepatch.observability import get_logger
from promisepatch.semantic import (
    ApparentIntent,
    ClassifyReplyIntentRequest,
    ReplyIntentReading,
    SemanticMetadata,
    SemanticProvider,
    SemanticProviderError,
    SemanticValidationError,
    UntrustedText,
)
from promisepatch.semantic.contracts import MAX_UNTRUSTED_CHARACTERS

logger = get_logger(__name__)

# ------------------------------------------------------------------------------- outcomes

FALLBACK_INTENT: Final = ApparentIntent.UNCLEAR.value
"""What the protocol proceeds on when no model produced a label. Fixed by §14.3.

Recorded in the provenance and nowhere else. It is never written to
``inbound_replies.apparent_intent``, because that column means "a classifier said this" and a
value put there by a fallback would be indistinguishable later from one a model produced.

It changes nothing that happens, which is the point of naming it: the label and the fallback
lead to the same message and the same state, so a provider outage is not a different protocol.
"""

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

OUTCOME_STALE: Final = "STALE"
"""The reading answers a question about a binding that is no longer this one."""

OUTCOME_UNBOUND: Final = "UNBOUND"
"""The reply no longer names a request. Nothing to confirm and nothing to conclude."""


class CustomerIntentStateError(RuntimeError):
    """A semantic reply step describes a shape of the world that cannot be true."""


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


def binding_fingerprint(binding: ReplyBinding) -> str:
    """A stable name for "this reply, on this request, as it stood".

    Recomputed by the consuming transaction under the case lock and compared with the one the
    preparation stored. A supersession, a re-plan, a decision or a rebound option between the
    call and the commit changes it, and a reading whose fingerprint no longer matches is
    discarded rather than applied to a request it was not about.

    The customer's words are hashed rather than carried. The fingerprint ends up on a step row
    and in a log line, and §26 keeps what somebody wrote in the table a reader has to be
    entitled to open -- so this identifies the text without reproducing a syllable of it.
    """
    payload = {
        "reply": str(binding.reply_id),
        "provider_message_id": binding.provider_message_id,
        "sender": binding.sender,
        "text": hashlib.sha256(binding.text.encode("utf-8")).hexdigest(),
        "request": str(binding.request_id),
        "track": str(binding.track_id),
        "option": str(binding.option_id),
        "option_code": binding.option_code,
        "channel": binding.customer_channel,
        "deadline": binding.deadline.isoformat(),
        "state": binding.state,
        "decided": binding.decided,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _blocking_reason(binding: ReplyBinding, *, case_state: str | None, now: datetime) -> str | None:
    """Why this reply must not be sent to a model, or ``None`` if it may be.

    Every one of these is also checked by the reply step before the work exists, and by the
    consuming transaction under the case lock afterwards. Repeating them here is not belt and
    braces for correctness -- the lock-held check is the authoritative one -- it is a cost
    control: the cheapest semantic call is the one nobody makes, and a request that settled
    while its interpretation queued is a call worth not making.
    """
    if case_state not in approvals.LIVE_CASE_STATES:
        return f"the case is {case_state}"
    if binding.decided or binding.state not in OPEN_APPROVAL_STATES:
        return f"the request is {binding.state}, not open"
    if binding.state != ApprovalRequestState.SENT.value:
        return "a confirmation prompt is already outstanding on this request"
    if now > binding.deadline:
        return "the approval window has closed"
    if binding.sender != binding.customer_channel:
        return "the reply did not arrive on the customer's own channel"
    if len(binding.text) > MAX_UNTRUSTED_CHARACTERS:
        # Longer than one customer message, so it is not one. Refused rather than truncated: a
        # reading of the first four thousand characters of something else is not a reading.
        return "the reply is longer than one customer message"
    return None


# ----------------------------------------------------------------------------- preparation


@dataclass(frozen=True, slots=True)
class PreparedIntent:
    """One question put to a model about a customer's reply, and what came back."""

    status: str
    payload: dict[str, Any]


async def prepare(
    database: RuntimeDatabase,
    provider: SemanticProvider,
    *,
    claim: StepClaim,
) -> PreparedIntent | None:
    """Fetch this step's reading, if it should have one, and store it on the claimed row.

    Called by the worker between claiming the step and executing it -- the only moment in the
    cycle when the process holds a lease on the work and no database transaction at all, which
    is exactly what a call to somebody else's service needs.

    It decides nothing. What it leaves behind is a label on a step row, and the transaction that
    consumes it re-reads the request under lock before that label is worth anything at all.
    """
    async with database.begin() as connection:
        stored = semantic_intake.stored_reading(await _stored_result(connection, claim.step_id))
        if stored is not None and stored.get("status") == semantic_intake.STATUS_READ:
            # A previous attempt already got an answer and died before the transition consumed
            # it. Asking again would cost money to learn the same thing.
            return None

        now = await database_now(connection)
        case_state = await _case_state(connection, claim.case_id)
        binding = await _binding(connection, approvals.reply_of(claim.step_key))
        blocked = (
            "the reply names no approval request"
            if binding is None
            else _blocking_reason(binding, case_state=case_state, now=now)
        )
        fingerprint = None if binding is None else binding_fingerprint(binding)

    if blocked is not None or binding is None:
        return await _store(
            database,
            claim=claim,
            prepared=PreparedIntent(
                status=semantic_intake.STATUS_UNNEEDED,
                payload={
                    "status": semantic_intake.STATUS_UNNEEDED,
                    "detail": blocked,
                    "request_hash": fingerprint,
                    "provider": provider.name,
                },
            ),
        )

    common: dict[str, Any] = {
        "request_hash": fingerprint,
        "provider": provider.name,
        "job": approvals.STEP_INTERPRET_CUSTOMER_REPLY,
    }
    # The reply text, and nothing else at all. No order, no option, no customer, no case, no
    # history -- §14.3 fixes this job's input as "reply text only", and a classifier that knew
    # which answer would be convenient would be a classifier with a reason to give it.
    request = ClassifyReplyIntentRequest(
        reply=UntrustedText(text=binding.text),
        metadata=SemanticMetadata(case_id=str(claim.case_id)),
    )

    crash.at(crash.BEFORE_SEMANTIC_CALL)
    try:
        result = await provider.run(request)
    except SemanticValidationError as rejected:
        # The model answered something the boundary refuses -- malformed output, or a word like
        # ``APPROVE`` that is not in this job's closed vocabulary. Never repaired into the
        # nearest acceptable label: silently widening ``APPROVE`` to ``APPARENT_APPROVE`` would
        # be the boundary letting a model reach for authority and then filing off the reach.
        prepared = PreparedIntent(
            status=semantic_intake.STATUS_REJECTED,
            payload={
                **common,
                "status": semantic_intake.STATUS_REJECTED,
                "failure": rejected.category.value,
                "detail": str(rejected),
            },
        )
    except SemanticProviderError as unavailable:
        prepared = PreparedIntent(
            status=semantic_intake.STATUS_UNAVAILABLE,
            payload={
                **common,
                "status": semantic_intake.STATUS_UNAVAILABLE,
                "retryable": unavailable.retryable,
                "detail": str(unavailable),
            },
        )
    else:
        telemetry = result.telemetry
        prepared = PreparedIntent(
            status=semantic_intake.STATUS_READ,
            payload={
                **common,
                "status": semantic_intake.STATUS_READ,
                "model_id": telemetry.model_id,
                "provider_attempts": telemetry.attempts,
                "input_tokens": telemetry.usage.input_tokens,
                "output_tokens": telemetry.usage.output_tokens,
                "latency_ms": telemetry.usage.latency_ms,
                # One label. Not the prompt, not the model's prose, and not a word of what the
                # customer wrote -- that is on ``inbound_replies``, where it belongs.
                "reading": result.value.model_dump(mode="json"),
            },
        )

    crash.at(crash.AFTER_SEMANTIC_CALL)
    return await _store(database, claim=claim, prepared=prepared)


async def _store(
    database: RuntimeDatabase, *, claim: StepClaim, prepared: PreparedIntent
) -> PreparedIntent | None:
    """Write the reading onto the claimed row, or discover the claim is no longer ours.

    Fenced by ``(state, lease_owner, attempts)`` like every other write this claim makes, so a
    worker that stalled past its lease and woke up holding a label cannot put that label on a
    row another worker is already executing.
    """
    async with database.begin() as connection:
        affected = (
            await connection.execute(
                update(CaseStep)
                .where(
                    CaseStep.id == claim.step_id,
                    CaseStep.state == "IN_FLIGHT",
                    CaseStep.lease_owner == claim.lease_owner,
                    CaseStep.attempts == claim.attempts,
                )
                .values(result={semantic_intake.RESULT_KEY: prepared.payload})
            )
        ).rowcount
    if affected != 1:
        logger.info(
            "worker.customer_intent.claim_lost",
            step_id=str(claim.step_id),
            step_key=claim.step_key,
            attempt=claim.attempts,
        )
        return None
    logger.info(
        "worker.customer_intent.prepared",
        step_id=str(claim.step_id),
        step_key=claim.step_key,
        attempt=claim.attempts,
        status=prepared.status,
        provider=prepared.payload.get("provider"),
        model_id=prepared.payload.get("model_id"),
        # The label, never the words. §26 keeps a customer's message in the table a reader has
        # to be entitled to open, and out of a log that is shipped, sampled and searchable.
        apparent_intent=_label_of(prepared.payload),
    )
    return prepared


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
    """Decide what the label fetched outside this transaction is worth. Usually: one message.

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

    row = (
        await connection.execute(
            select(CaseStep.result, CaseStep.attempts).where(
                CaseStep.case_id == case.id, CaseStep.step_key == step_key
            )
        )
    ).one()
    stored = semantic_intake.stored_reading(row.result) or {}
    status = stored.get("status")

    if stored.get("request_hash") not in (None, binding_fingerprint(binding)):
        return _noop(
            outcome=OUTCOME_STALE,
            detail="the reading was produced against a binding that has since changed",
            request_id=binding.request_id,
        )
    if status == semantic_intake.STATUS_UNAVAILABLE and not retry.is_exhausted(row.attempts):
        # Nothing is known about how the reply reads, and asking again may well work. Nothing is
        # concluded from silence and the retry ladder is the ordinary one.
        return StepOutcome(
            disposition=Disposition.RETRYING,
            event_type=EVENT_STEP_FAILED,
            error=f"semantic reading unavailable: {stored.get('detail') or status}",
        )

    return await _request_confirmation(
        connection,
        case=case,
        track=track,
        binding=binding,
        stored=stored,
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
    stored: dict[str, Any],
    now: datetime,
    worker: str,
    step_key: str,
) -> StepOutcome:
    """Ask the customer for one of the two words, and change nothing else in the world.

    Reached identically for every label and for every failure. ``APPARENT_APPROVE`` sends this
    message; ``APPARENT_DECLINE`` sends this message; ``UNCLEAR`` sends this message; a model
    that returned nonsense sends this message under §14.3's deterministic fallback, which is
    ``UNCLEAR``. §13.6 says a decline must be literal too, "because it escalates" -- so an
    apparent no is no more authoritative here than an apparent yes, and neither is authority.

    What this writes: the label on the reply row when a model actually produced one, the
    request to ``CONFIRMATION_PENDING``, and one outbox message. What it does not write: the
    track, which stays ``WAITING_FOR_CUSTOMER``; the case, which stays ``WAITING`` because a
    ``CONFIRMATION_PENDING`` request is still an open one; and any decision, ever.
    """
    label = _label_of(stored)
    addressee = await _addressee(connection, binding.order_id)
    text = messaging.build_confirmation_prompt(
        messaging.ApprovalMessage(
            customer_name=addressee.customer_name,
            order_reference=addressee.order_external_id,
            option_code=binding.option_code,
        )
    )
    if not messaging.carries_confirmation_literals(text, option_code=binding.option_code):
        # §13.6's pre-send check, applied to this message as well as to the request. The words
        # a customer is told to reply with are a fixed string in the builder and are never
        # drafted, so this cannot fail today -- and the guard predates any drafter on purpose.
        raise CustomerIntentStateError(
            f"the confirmation prompt for {binding.request_id} is missing its literals"
        )

    key = approvals.confirmation_idempotency_key(binding.request_id, binding.reply_id)
    kind, address = split_channel(binding.customer_channel)
    semantic = {
        "status": stored.get("status"),
        "provider": stored.get("provider"),
        "model_id": stored.get("model_id"),
        "provider_attempts": stored.get("provider_attempts"),
        "failure": stored.get("failure"),
        "request_hash": stored.get("request_hash"),
        "input_tokens": stored.get("input_tokens"),
        "output_tokens": stored.get("output_tokens"),
        "latency_ms": stored.get("latency_ms"),
        "apparent_intent": label,
        "fallback": None if label is not None else FALLBACK_INTENT,
    }

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
            "apparent_intent": label,
            "idempotency_key": key,
        },
        provenance={
            "request_id": str(binding.request_id),
            "inbound_reply_id": str(binding.reply_id),
            "provider_message_id": binding.provider_message_id,
            "inbox_event_id": None,
            "sender_identity": binding.sender,
            # Named explicitly, and null. A confirmation is not a reading of consent by any
            # parser, and the field being present and empty says so louder than its absence.
            "parser": None,
            "semantic": semantic,
            "executed_by": worker,
            "step_key": step_key,
        },
        occurred_at=now,
    ) as write:
        if label is not None:
            # Written only when a classifier genuinely produced it. A column filled in by
            # guesswork would be indistinguishable later from one filled in by a model that ran.
            await write.execute(
                update(InboundReply)
                .where(InboundReply.id == binding.reply_id)
                .values(apparent_intent=label)
            )
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
        apparent_intent=label,
        status=stored.get("status"),
        provider=stored.get("provider"),
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
                payload={"status": stored.get("status"), "apparent_intent": label},
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
            "apparent_intent": label,
            "status": stored.get("status"),
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


# ---------------------------------------------------------------------------------- reading


def _label_of(stored: dict[str, Any]) -> str | None:
    """The apparent intent a stored reading carries, validated on the way back out.

    Re-validated through the same strict model rather than read as a string, so a row edited by
    hand, or written by an older build, is refused here rather than becoming a label nobody
    checked. ``None`` is the ordinary answer whenever no model produced one.
    """
    if stored.get("status") != semantic_intake.STATUS_READ:
        return None
    reading = stored.get("reading")
    if not isinstance(reading, dict):
        return None
    return ReplyIntentReading.model_validate(reading).apparent_intent.value


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

    Used to find out *which* rows to lock, and -- in :func:`prepare`, where nothing is locked at
    all -- to decide whether a call is worth making. The authoritative reading is
    :func:`_bound`, against the request row this transaction holds.
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

    The reply's half cannot move -- ``inbound_replies`` is written once and never updated except
    for the label this module puts on it -- so only the request's half is re-read. That is the
    half a decision, an expiry or a supersession changes.
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


async def _case_state(connection: AsyncConnection, case_id: UUID) -> str | None:
    """The case's state, read without a lock: this is a decision about whether to spend money.

    The authoritative check is the one the consuming transaction makes under the case lock. A
    race here can only cause a reading nobody needed, which is a fraction of a cent and no
    correctness at all.
    """
    state = await connection.scalar(select(Case.state).where(Case.id == case_id))
    return None if state is None else str(state)


async def _stored_result(connection: AsyncConnection, step_id: UUID) -> object:
    return await connection.scalar(select(CaseStep.result).where(CaseStep.id == step_id))


__all__: Sequence[str] = [
    "FALLBACK_INTENT",
    "OUTCOME_ALREADY_SETTLED",
    "OUTCOME_CONFIRMATION_OUTSTANDING",
    "OUTCOME_CONFIRMATION_REQUESTED",
    "OUTCOME_STALE",
    "OUTCOME_TOO_LATE",
    "OUTCOME_UNAUTHORIZED",
    "OUTCOME_UNBOUND",
    "CustomerIntentStateError",
    "PreparedIntent",
    "ReplyBinding",
    "binding_fingerprint",
    "execute",
    "prepare",
]
