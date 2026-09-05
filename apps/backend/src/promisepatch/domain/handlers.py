"""The synthetic handlers, and the source normaliser. Pure functions, both.

These are not PromisePatch's exception semantics and are not a sketch of them. Each one exists
to drive one persistence boundary to its edge, so that the infrastructure underneath can be
proven before anything that matters is built on it:

===================  =====================================================================
``NOOP``             a transition with no consequence beyond itself
``CHAIN``            a successor step, enqueued in the transaction that decided on it
``ARM_TIMER``        a deadline that must survive the process that armed it
``TIMER_WAKEUP``     the step a fired timer creates, closing the loop back into the workflow
``EMIT_EFFECT``      an outbound effect, enqueued with the decision and sent afterwards
``FAIL_RETRYABLE``   the backoff ladder, and the bound at the end of it
``FAIL_TERMINAL``    escalation: the case needs a human, and says so
``SKIP_IF_TERMINAL`` a guard that reads case state, proving state reaches a handler at all
===================  =====================================================================

**Parameters travel in the step key.** ``chain:2`` is the third link, ``arm-timer:30`` is a
deadline thirty seconds out. The key is already the deterministic, unique-per-case name of a
unit of work, so encoding the parameter there means a replayed transition proposes the
identical key and the database refuses the duplicate -- which is the property being proven. A
separate input column would have to be kept consistent with the key by hand.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Final
from uuid import UUID

from promisepatch.domain.model import (
    CASE_SUBJECT,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_FAILED,
    EVENT_STEP_SKIPPED,
    FAKE_EFFECT_KIND,
    WAKEUP_TIMER_KIND,
    ArmTimer,
    CaseChange,
    CreateStep,
    Disposition,
    EmitEffect,
    InboundOutcome,
    StepContext,
    StepKind,
    StepOutcome,
)

CHAIN_LENGTH: Final = 3
"""How many links a ``CHAIN`` lays down before stopping.

A bound, because a handler that always enqueues a successor is a workflow that never finishes,
and the point of the fixture is a workflow that demonstrably does.
"""

SYNTHETIC_SOURCE: Final = "synthetic"
"""The source that exercises the ledger itself, and carries no business meaning.

What it proves is what sits underneath every real source: that a duplicate delivery is
deduplicated by the database, and that a crash mid-processing leaves the record retriable rather
than half-consumed.
"""

CUSTOMER_REPLY_SOURCE: Final = "customer-reply"
"""A reply that arrived on a customer's own channel.

Telegram's ingress, its secret-header check and its ``update_id`` are a later slice; what they
will change is who fills this row in, never what is done with it. Normalisation here reads the
*stored* body and reaches nothing outside its arguments, so the same record read back in a year
produces the same reading it produced on the day -- which is what makes a consent protocol
auditable rather than merely logged.
"""

REQUIRED_REPLY_FIELDS: Final[tuple[str, ...]] = (
    "request_id",
    "sender",
    "text",
    "provider_message_id",
)
"""What a reply must carry to be actionable at all.

``sender`` is the customer channel identity the transport observed, and it is data rather than
a claim of authority: whether it is *the* channel this request was sent to is decided later,
against the persisted request, by the step that could act on it.

``provider_message_id`` is required rather than derived. It is what makes one stored reply out
of one message, and a fallback that reused the request id would make every reply after the first
collide with the first -- silently discarding exactly the second reply the consent protocol
exists to read.
"""


class UnknownStepKindError(ValueError):
    """Raised when a stored step names a handler this build does not have.

    A real possibility during a rolling deploy, and it must fail loudly. Treating it as a no-op
    would mark work done that nothing did.
    """


def step_parameter(step_key: str) -> int:
    """The integer after the last colon in a step key, or zero.

    ``chain:2`` is 2, ``noop`` is 0. Tolerant on purpose: a key with no parameter is a handler
    that takes none, and neither should be a crash.
    """
    _, _, suffix = step_key.rpartition(":")
    return int(suffix) if suffix.isdigit() else 0


def handle(context: StepContext) -> StepOutcome:
    """Decide what should be persisted for one step. Deterministic in ``context`` alone."""
    handler = _HANDLERS.get(context.kind)
    if handler is None:
        raise UnknownStepKindError(f"no handler for step kind {context.kind!r}")
    return handler(context)


# --------------------------------------------------------------------------------- handlers


def _noop(context: StepContext) -> StepOutcome:
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        result={"kind": StepKind.NOOP.value},
    )


def _chain(context: StepContext) -> StepOutcome:
    """Lay down the next link, unless this was the last one.

    The successor's key is derived from this one, so a transaction that ran, failed to commit
    and ran again proposes the identical key the second time -- and the unique index, not the
    handler, is what stops a second link appearing.
    """
    position = step_parameter(context.step_key)
    successors = (
        (CreateStep(step_key=f"chain:{position + 1}", kind=StepKind.CHAIN),)
        if position + 1 < CHAIN_LENGTH
        else ()
    )
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        successors=successors,
        result={"kind": StepKind.CHAIN.value, "position": position},
    )


def _arm_timer(context: StepContext) -> StepOutcome:
    """Arm a wake-up for this case, ``n`` seconds out, where ``n`` is the step's parameter."""
    delay = timedelta(seconds=step_parameter(context.step_key))
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        timers=(
            ArmTimer(
                kind=WAKEUP_TIMER_KIND,
                subject_type=CASE_SUBJECT,
                subject_id=str(context.case_id),
                delay=delay,
            ),
        ),
        result={"kind": StepKind.ARM_TIMER.value, "delay_seconds": int(delay.total_seconds())},
    )


def _timer_wakeup(context: StepContext) -> StepOutcome:
    """The workflow, resumed by a deadline rather than by a message.

    Cancelling the timer that created this step would be redundant -- firing it is what made it
    non-live -- so this asks for the cancellation of nothing and simply carries on.
    """
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        result={"kind": StepKind.TIMER_WAKEUP.value, "woken": True},
    )


def _emit_effect(context: StepContext) -> StepOutcome:
    """Enqueue one outbound effect, keyed so a redelivery cannot become a second one."""
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        effects=(
            EmitEffect(
                kind=FAKE_EFFECT_KIND,
                payload={"case_id": str(context.case_id), "step_key": context.step_key},
                idempotency_key=effect_key(context.case_id, context.step_key),
            ),
        ),
        result={"kind": StepKind.EMIT_EFFECT.value},
    )


def _fail_retryable(context: StepContext) -> StepOutcome:
    return StepOutcome(
        disposition=Disposition.RETRYING,
        event_type=EVENT_STEP_FAILED,
        error=f"synthetic retryable failure on attempt {context.attempts}",
    )


def _fail_terminal(context: StepContext) -> StepOutcome:
    """A failure no retry can help with. The case gains a human's attention, and says so."""
    return StepOutcome(
        disposition=Disposition.FAILED,
        event_type=EVENT_STEP_FAILED,
        case_change=CaseChange(needs_owner_attention=True),
        error="synthetic terminal failure",
    )


def _skip_if_terminal(context: StepContext) -> StepOutcome:
    """Read the case state the transaction locked, and decide whether there is anything to do."""
    if context.case_is_terminal:
        return StepOutcome(
            disposition=Disposition.SKIPPED,
            event_type=EVENT_STEP_SKIPPED,
            result={"kind": StepKind.SKIP_IF_TERMINAL.value, "skipped_because": context.case_state},
        )
    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        result={"kind": StepKind.SKIP_IF_TERMINAL.value, "skipped_because": None},
    )


_HANDLERS: Final[Mapping[StepKind, Callable[[StepContext], StepOutcome]]] = {
    StepKind.NOOP: _noop,
    StepKind.CHAIN: _chain,
    StepKind.ARM_TIMER: _arm_timer,
    StepKind.TIMER_WAKEUP: _timer_wakeup,
    StepKind.EMIT_EFFECT: _emit_effect,
    StepKind.FAIL_RETRYABLE: _fail_retryable,
    StepKind.FAIL_TERMINAL: _fail_terminal,
    StepKind.SKIP_IF_TERMINAL: _skip_if_terminal,
}


def effect_key(case_id: UUID, step_key: str) -> str:
    """The idempotency key for an effect, derived only from server-side identifiers.

    Stable across every retry of the same decision, and different for every other decision. It
    is what a redelivery presents to the provider, which is the whole of the at-least-once
    story: we send again under the same key, and the provider decides whether that is one
    effect or two.
    """
    return f"pp:fake:{case_id}:{step_key}"


def timer_step_key(timer_id: UUID) -> str:
    """The step a fired timer creates. Derived from the timer, so firing twice enqueues once."""
    return f"timer:{timer_id}"


def inbox_step_key(inbox_id: UUID) -> str:
    """The step a processed inbound record creates, likewise derived rather than invented."""
    return f"inbox:{inbox_id}"


# ------------------------------------------------------------------------- inbound normalising


def normalize_inbound(source: str, body: str | None) -> InboundOutcome:
    """Turn one stored inbound record into a decision about it.

    Reads the *stored* row, never a live request, and reaches nothing outside its arguments --
    so replaying an inbox row a year later produces the same answer it produced at the time.

    An unrecognised source is terminal rather than retriable. Retrying a record nothing in this
    build can read would mean returning to it forever; failing it leaves the raw material on
    the row for a later build to replay deliberately.
    """
    if source not in (SYNTHETIC_SOURCE, CUSTOMER_REPLY_SOURCE):
        return InboundOutcome(state="FAILED", error=f"no handler for inbound source {source!r}")

    try:
        parsed = json.loads(body or "")
    except (TypeError, ValueError) as error:
        return InboundOutcome(state="FAILED", error=f"unreadable {source} body: {error}")
    if not isinstance(parsed, dict):
        return InboundOutcome(state="FAILED", error=f"{source} body is not an object")
    if source == CUSTOMER_REPLY_SOURCE:
        return _customer_reply(parsed)

    raw_case = parsed.get("case_id")
    if raw_case is None:
        # Nothing to act on, and nothing wrong: the record is understood and deliberately
        # produces no work. IGNORED says that, where PROCESSED would imply a successor exists.
        return InboundOutcome(state="IGNORED", normalized={"source": source, "case_id": None})

    try:
        case_id = UUID(str(raw_case))
    except ValueError as error:
        return InboundOutcome(state="FAILED", error=f"unusable case_id: {error}")

    return InboundOutcome(
        state="PROCESSED",
        normalized={"source": source, "case_id": str(case_id)},
        case_id=case_id,
        step_kind=StepKind.NOOP,
    )


def _customer_reply(parsed: Mapping[str, object]) -> InboundOutcome:
    """Read one customer reply out of a stored record, and decide nothing else about it.

    Deliberately incomplete: it produces the normalised material and no ``case_id``, because
    which case a reply belongs to is a question about persisted rows and this function may not
    ask one. :func:`promisepatch.domain.approvals.bind_customer_reply` answers it, and the step
    that follows is what checks whether the sender was entitled to say anything at all.

    The reply text is carried through untouched -- not trimmed, not lowered, not interpreted.
    The literal parser normalises its own copy when it compares; the stored words stay the
    customer's.
    """
    missing = [field for field in REQUIRED_REPLY_FIELDS if not str(parsed.get(field, "")).strip()]
    if missing:
        return InboundOutcome(
            state="FAILED", error=f"customer reply is missing {', '.join(sorted(missing))}"
        )

    return InboundOutcome(
        state="PROCESSED",
        normalized={
            "source": CUSTOMER_REPLY_SOURCE,
            "request_id": str(parsed["request_id"]),
            "sender": str(parsed["sender"]),
            "text": str(parsed["text"]),
            "provider_message_id": str(parsed["provider_message_id"]),
        },
    )


__all__ = [
    "CHAIN_LENGTH",
    "CUSTOMER_REPLY_SOURCE",
    "REQUIRED_REPLY_FIELDS",
    "SYNTHETIC_SOURCE",
    "UnknownStepKindError",
    "effect_key",
    "handle",
    "inbox_step_key",
    "normalize_inbound",
    "step_parameter",
    "timer_step_key",
]
