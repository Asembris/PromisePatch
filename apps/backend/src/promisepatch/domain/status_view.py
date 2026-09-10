"""What a case currently is, in the words the product is allowed to use.

:func:`~promisepatch.domain.analysis.read_case_status` answers the engineering question --
track states, classifications, rule ids, effect rows. This module answers the human one, and
answers it **deterministically**: it is a pure projection of that value into the truthful state
vocabulary the P5 product contract fixes, plus a rendering of that projection into sentences.

Two rules shape everything here.

**A phrase may not be spoken until its source exists.** The named risk is language outrunning
reality -- "approved", "asked", "recovered" said before they are true. So each product state is
bound to a durable condition and nothing else. The bindings are cheap because the durable state
machine already enforces them: a track only reaches ``WAITING_FOR_CUSTOMER`` once the provider
acknowledged the message, and only reaches ``RECOVERED`` once the order system's own state was
observed to agree. This module reads those postures; it does not re-derive them, and it cannot
reach a row to second-guess them.

**Nothing here decides.** No database, no provider, no clock, no environment: every value is
computed by the engine and the workflow and copied. A projection that could read a row would be
a second implementation of the ladder, and the two would eventually disagree about one case
with nothing to say which was right. The import-linter contract of the same name enforces it.

The rendering is the *only* status a user is shown. A conversational layer may frame it; it may
not restate it, because a paraphrase of "planned" is one word away from "done".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from promisepatch.domain.analysis import CaseStatus, TrackStatus

# --------------------------------------------------------------------------- the vocabulary


class CaseHeadline(StrEnum):
    """Where the case as a whole has got to. One value, read off the durable case state."""

    UNDERSTANDING = "UNDERSTANDING"
    CLARIFYING = "CLARIFYING"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    ANALYSED = "ANALYSED"
    PLANNED = "PLANNED"
    WORKING = "WORKING"
    WAITING = "WAITING"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class PromiseState(StrEnum):
    """What this case has done to one customer promise, so far.

    The first eleven are the P5 product contract's fixed vocabulary. ``LINKED`` and
    ``WITHDRAWN`` are durable track states the contract's table does not enumerate; they are
    reported under their own phrasing rather than folded into ``UNTOUCHED``, because a promise
    another case is already recovering has not been left alone -- it has been left to somebody
    else -- and saying otherwise would overstate the selectivity claim.

    ``AWAITING_PLAN`` is the fail-closed default. Any durable combination this projection does
    not recognise lands here, which says only that the case has not finished deciding. It never
    lands on a completed state, so an unforeseen posture understates rather than lies.
    """

    UNTOUCHED = "UNTOUCHED"
    PLANNED = "PLANNED"
    AUTHORIZED = "AUTHORIZED"
    REQUESTED = "REQUESTED"
    CONSENTED = "CONSENTED"
    DECLINED = "DECLINED"
    APPLYING = "APPLYING"
    RECOVERED = "RECOVERED"
    ESCALATED = "ESCALATED"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    LINKED = "LINKED"
    WITHDRAWN = "WITHDRAWN"
    AWAITING_PLAN = "AWAITING_PLAN"


class Authority(StrEnum):
    """Under whose authority this promise changes, which is band 3 of the case workspace."""

    NONE = "NONE"
    STANDING_PREFERENCE = "STANDING_PREFERENCE"
    CUSTOMER = "CUSTOMER"
    OWNER = "OWNER"
    UNDECIDED = "UNDECIDED"


CASE_HEADLINES: Final[dict[str, CaseHeadline]] = {
    "RECEIVED": CaseHeadline.UNDERSTANDING,
    "INTERPRETING": CaseHeadline.UNDERSTANDING,
    "CLARIFYING": CaseHeadline.CLARIFYING,
    "NEEDS_HUMAN_INTERPRETATION": CaseHeadline.NEEDS_HUMAN,
    "ANALYZED": CaseHeadline.ANALYSED,
    "PLANNED": CaseHeadline.PLANNED,
    "EXECUTING": CaseHeadline.WORKING,
    "REVALIDATING": CaseHeadline.WORKING,
    "RECONCILING": CaseHeadline.WORKING,
    "WAITING": CaseHeadline.WAITING,
    "RESOLVED": CaseHeadline.SETTLED,
    "CANCELLED": CaseHeadline.CANCELLED,
}
"""Every durable case state, mapped once. A state absent from this table is a schema change."""

_HEADLINE_SENTENCE: Final[dict[CaseHeadline, str]] = {
    CaseHeadline.UNDERSTANDING: "Still working out what this affects. Nothing has changed yet.",
    CaseHeadline.CLARIFYING: "Waiting for your answer before anything is decided.",
    CaseHeadline.NEEDS_HUMAN: "This needs a person to read it. Nothing has changed.",
    CaseHeadline.ANALYSED: "Worked out what is at risk. Still choosing what to do about it.",
    CaseHeadline.PLANNED: "Planned, and waiting for you. Nothing has been done yet.",
    CaseHeadline.WORKING: "Carrying out what you confirmed.",
    CaseHeadline.WAITING: "Waiting on a customer to answer.",
    CaseHeadline.SETTLED: "Finished.",
    CaseHeadline.CANCELLED: "Cancelled.",
}

_PROMISE_PHRASE: Final[dict[PromiseState, str]] = {
    PromiseState.UNTOUCHED: "left alone",
    PromiseState.PLANNED: "planned - waiting for you",
    PromiseState.AUTHORIZED: "covered by a standing preference",
    PromiseState.REQUESTED: "asked",
    PromiseState.CONSENTED: "said yes",
    PromiseState.DECLINED: "said no",
    PromiseState.APPLYING: "changing the order now",
    PromiseState.RECOVERED: "changed",
    PromiseState.ESCALATED: "needs you",
    PromiseState.STALE: "the plan no longer fits - re-planned",
    PromiseState.EXPIRED: "no answer by the deadline",
    PromiseState.LINKED: "already being handled by another case",
    PromiseState.WITHDRAWN: "withdrawn",
    PromiseState.AWAITING_PLAN: "not decided yet",
}

_AUTHORITY_BAND: Final[dict[Authority, str]] = {
    Authority.STANDING_PREFERENCE: "Covered by a standing preference",
    Authority.CUSTOMER: "Needs the customer",
    Authority.OWNER: "Needs the owner",
    Authority.UNDECIDED: "Not decided yet",
    Authority.NONE: "Left alone",
}

# ------------------------------------------------------------------------------- the values


@dataclass(frozen=True, slots=True)
class PromiseView:
    """One customer promise, as this case has left it."""

    promise_id: str
    customer_name: str
    order_external_id: str
    state: PromiseState
    phrase: str
    authority: Authority
    reason: str
    deadline_at: str | None
    track_id: str
    track_state: str
    classification: str | None
    rule_id: str | None


@dataclass(frozen=True, slots=True)
class CaseView:
    """One case, in the words the product is allowed to use, plus the evidence behind them."""

    case_id: str
    headline: CaseHeadline
    sentence: str
    needs_owner_attention: bool
    exception_category: str | None
    threatened: tuple[PromiseView, ...]
    untouched: tuple[PromiseView, ...]

    @property
    def promises(self) -> tuple[PromiseView, ...]:
        return self.threatened + self.untouched


# ---------------------------------------------------------------------------- the projection


def project(status: CaseStatus) -> CaseView:
    """Turn one engine-level case status into the product's own vocabulary. Pure."""
    headline = CASE_HEADLINES.get(status.state, CaseHeadline.UNDERSTANDING)
    views = tuple(_promise(status.state, track) for track in status.tracks)
    untouched = tuple(view for view in views if view.state is PromiseState.UNTOUCHED)
    threatened = tuple(view for view in views if view.state is not PromiseState.UNTOUCHED)
    return CaseView(
        case_id=str(status.case_id),
        headline=headline,
        sentence=_HEADLINE_SENTENCE[headline],
        needs_owner_attention=status.needs_owner_attention,
        exception_category=status.category,
        threatened=threatened,
        untouched=untouched,
    )


def _promise(case_state: str, track: TrackStatus) -> PromiseView:
    state = _promise_state(case_state, track)
    return PromiseView(
        promise_id=track.promise_id,
        customer_name=track.customer_name,
        order_external_id=track.order_external_id,
        state=state,
        phrase=_PROMISE_PHRASE[state],
        authority=_authority(state, track),
        reason=track.reason_detail or "",
        deadline_at=None if track.deadline_at is None else track.deadline_at.isoformat(),
        track_id=str(track.track_id),
        track_state=track.state,
        classification=track.classification,
        rule_id=track.rule_id,
    )


def _promise_state(case_state: str, track: TrackStatus) -> PromiseState:
    """The one place a durable posture becomes something the product says out loud.

    Ordered so that the settled answers are read first and the unsettled ones fall through to
    ``AWAITING_PLAN``. Every branch is a condition already established by the workflow -- this
    function adds no judgement of its own, which is what makes "asked" mean what the contract
    says it means and not what a reader hoped.
    """
    match track.state:
        case "UNAFFECTED":
            return PromiseState.UNTOUCHED
        case "LINKED":
            return PromiseState.LINKED
        case "WITHDRAWN":
            return PromiseState.WITHDRAWN
        case "STALE":
            return PromiseState.STALE
        case "ESCALATED":
            return PromiseState.ESCALATED
        case "RECOVERED":
            # The workflow reaches this state only after the order system's own version was
            # observed to carry the amendment. An acknowledgement alone leaves the track
            # ``APPLYING``, which is why "changed" can be said here and nowhere earlier.
            return PromiseState.RECOVERED
        case "APPLYING":
            return PromiseState.APPLYING
        case "WAITING_FOR_CUSTOMER":
            return _waiting_state(track)
        case "PENDING":
            return _pending_state(case_state, track)
    return PromiseState.AWAITING_PLAN


def _waiting_state(track: TrackStatus) -> PromiseState:
    """A promise whose customer has been written to. What may be said depends on the receipt.

    ``REQUESTED`` -- "asked <customer>" -- requires the provider to have acknowledged delivery,
    which is exactly the condition under which the workflow stamps ``provider_ref`` on the
    request. A queued, claimed or retrying message has none, and this returns ``PLANNED``: the
    honest answer while a message is still in flight is that nothing has reached anybody.
    """
    approval = track.approval
    if approval is None:
        return PromiseState.AWAITING_PLAN
    if approval.decision == "APPROVE":
        return PromiseState.CONSENTED
    if approval.decision == "DECLINE":
        return PromiseState.DECLINED
    if approval.state == "EXPIRED":
        return PromiseState.EXPIRED
    if approval.provider_ref is None:
        return PromiseState.PLANNED
    return PromiseState.REQUESTED


def _pending_state(case_state: str, track: TrackStatus) -> PromiseState:
    """A classified promise nothing has been done to yet.

    Before the worker's confirmation the only honest word is "planned", whatever the
    classification says. ``AUTO_RECOVERABLE`` is a permission to act later, not an act, and the
    count of recovered orders while a case sits at ``PLANNED`` is zero.

    After confirmation the case is at ``EXECUTING`` or beyond, and a still-pending automatic
    track is genuinely authorised -- the worker said yes and the work is enqueued.
    """
    if case_state in _CONFIRMED_CASE_STATES and track.classification == "AUTO_RECOVERABLE":
        return PromiseState.AUTHORIZED
    if case_state in _PLANNED_CASE_STATES:
        return PromiseState.PLANNED
    return PromiseState.AWAITING_PLAN


_CONFIRMED_CASE_STATES: Final[frozenset[str]] = frozenset(
    {"EXECUTING", "WAITING", "REVALIDATING", "RECONCILING"}
)
"""Case states only reachable through a worker's confirmation of a specific plan."""

_PLANNED_CASE_STATES: Final[frozenset[str]] = frozenset({"PLANNED"})
"""The one state in which "planned - waiting for you" is the whole truth."""


def _authority(state: PromiseState, track: TrackStatus) -> Authority:
    """Who decides this promise's change. Band 3 of the case workspace, in one value."""
    if state in {PromiseState.UNTOUCHED, PromiseState.LINKED, PromiseState.WITHDRAWN}:
        return Authority.NONE
    match track.classification:
        case "AUTO_RECOVERABLE":
            return Authority.STANDING_PREFERENCE
        case "APPROVAL_REQUIRED":
            return Authority.CUSTOMER
        case "BLOCKED":
            return Authority.OWNER
    return Authority.UNDECIDED


# ----------------------------------------------------------------------------- the rendering


def render(view: CaseView) -> str:
    """The status a user is shown, rendered from the projection and from nothing else.

    Deterministic in the sense that matters: the same durable case produces the same sentences
    on every call, in every process, with no provider reached and no token spent. A
    conversational layer receives this text and delivers it; it is not a summary of a summary.
    """
    lines = [view.sentence]
    if view.threatened:
        lines.append("")
        for group in (Authority.STANDING_PREFERENCE, Authority.CUSTOMER, Authority.OWNER):
            promises = tuple(item for item in view.threatened if item.authority is group)
            if promises:
                lines.append(f"{_AUTHORITY_BAND[group]}:")
                lines.extend(f"  - {_promise_line(item)}" for item in promises)
        rest = tuple(
            item
            for item in view.threatened
            if item.authority in {Authority.UNDECIDED, Authority.NONE}
        )
        if rest:
            lines.append(f"{_AUTHORITY_BAND[Authority.UNDECIDED]}:")
            lines.extend(f"  - {_promise_line(item)}" for item in rest)
    lines.append("")
    lines.append(_untouched_line(view))
    lines.extend(
        f"  - {item.customer_name} ({item.order_external_id}): {_reason(item)}"
        for item in view.untouched
    )
    return "\n".join(lines)


def _promise_line(item: PromiseView) -> str:
    reason = _reason(item)
    deadline = "" if item.deadline_at is None else f", by {item.deadline_at}"
    return f"{item.customer_name} ({item.order_external_id}): {item.phrase}{deadline} - {reason}"


def _untouched_line(view: CaseView) -> str:
    """The claim the product exists to make, counted rather than asserted."""
    count = len(view.untouched)
    if count == 0:
        return "No promise in this case was left alone."
    if count == 1:
        return "1 promise was left alone:"
    return f"{count} promises were left alone:"


def _reason(item: PromiseView) -> str:
    if item.reason:
        return item.reason
    if item.rule_id:
        return f"rule {item.rule_id}"
    return "no reason recorded"
