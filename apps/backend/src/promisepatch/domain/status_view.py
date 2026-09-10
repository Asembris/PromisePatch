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


class ActionOwner(StrEnum):
    """Whose move it is. Band 2 of the case workspace answers "what is mine?" with one of these.

    ``NOBODY`` is a real answer rather than an absent one. A case that is still being worked
    out asks nothing of anybody, and a blank band would read as a screen that had failed to
    load rather than as the truthful "there is nothing for you here yet".
    """

    YOU = "YOU"
    OWNER = "OWNER"
    CUSTOMER = "CUSTOMER"
    SYSTEM = "SYSTEM"
    NOBODY = "NOBODY"


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


def headline_sentence(headline: CaseHeadline) -> str:
    """The one sentence bound to a headline, for a caller that has a headline and no case.

    The case list has exactly that: a durable state per row and no reason to load six tracks to
    say what the state means. Reading the table through a function rather than exporting it
    keeps one place that decides what a headline says out loud.
    """
    return _HEADLINE_SENTENCE[headline]


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
    owner: ActionOwner
    """Whose move this one promise is. ``NOBODY`` where it is nobody's -- including untouched.

    Named separately from :attr:`authority` because they answer different questions. Authority
    says who *decides* the change; this says who has to do something next, and the two part
    company the moment a decision has been taken and the work is somebody else's to carry out.
    """

    next_action: str
    """The one thing that moves this promise, or a sentence saying nothing does.

    Never blank. A blocked promise whose next action were empty would be a promise that had
    quietly become nobody's, which is exactly the failure the escalation exists to prevent.
    """


@dataclass(frozen=True, slots=True)
class NextAction:
    """Band 2 of the case workspace: exactly one thing, and exactly one person it belongs to.

    One rather than a list, because a screen that offers a worker three next actions has not
    answered "what is mine?" -- it has restated the case. Where nothing is required of this
    worker the owner is somebody else or nobody at all, and the sentence says so rather than
    leaving the band empty.
    """

    owner: ActionOwner
    owner_label: str
    action: str


@dataclass(frozen=True, slots=True)
class OptionView:
    """One answer the open question will accept."""

    code: str
    label: str


@dataclass(frozen=True, slots=True)
class QuestionView:
    """The question this case is waiting on. Band 1, and never a result."""

    clarification_id: str
    question: str
    options: tuple[OptionView, ...]


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
    question: QuestionView | None = None
    next_action: NextAction = NextAction(
        owner=ActionOwner.NOBODY,
        owner_label="Nobody",
        action="Nothing is needed from anybody yet.",
    )
    """Band 2, and the fail-closed default is the one that asks nothing of anybody.

    A default that named a person would mean an unrecognised posture put work on somebody's
    desk that nobody had decided to put there. Understating is the only safe direction here.
    """

    plan_id: str | None = None
    """The identity of the plan on offer, present **only** while one is actually on offer.

    A case that is still understanding, already executing or long finished has no plan waiting
    for a yes, and handing a caller an identity for one would invite a confirmation of
    something nobody is being asked about. ``None`` is the honest answer everywhere else.
    """

    @property
    def awaiting_confirmation(self) -> bool:
        """Whether a worker's yes is the thing this case is waiting for. Never an act."""
        return self.plan_id is not None

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
    question = _question(status)
    return CaseView(
        case_id=str(status.case_id),
        headline=headline,
        sentence=_HEADLINE_SENTENCE[headline],
        needs_owner_attention=status.needs_owner_attention,
        exception_category=status.category,
        threatened=threatened,
        untouched=untouched,
        question=question,
        next_action=_next_action(headline, threatened, question),
        # Bound to the one headline in which a plan is genuinely waiting for a worker. Reading
        # the identity off any other state would let a confirmation be offered for a case that
        # is not asking for one -- the domain would refuse it, and the conversation would have
        # been wrong out loud first.
        plan_id=status.plan_id if headline is CaseHeadline.PLANNED and status.plan_id else None,
    )


def _question(status: CaseStatus) -> QuestionView | None:
    pending = status.clarification
    if pending is None:
        return None
    return QuestionView(
        clarification_id=str(pending.clarification_id),
        question=pending.question,
        options=tuple(OptionView(code=item.code, label=item.label) for item in pending.options),
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
        owner=_promise_owner(state),
        next_action=_promise_next_action(state, track),
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


_OWNER_LABEL: Final[dict[ActionOwner, str]] = {
    ActionOwner.YOU: "You",
    ActionOwner.OWNER: "The owner",
    ActionOwner.CUSTOMER: "The customer",
    ActionOwner.SYSTEM: "PromisePatch",
    ActionOwner.NOBODY: "Nobody",
}


_PROMISE_OWNERS: Final[dict[PromiseState, ActionOwner]] = {
    PromiseState.UNTOUCHED: ActionOwner.NOBODY,
    PromiseState.LINKED: ActionOwner.NOBODY,
    PromiseState.WITHDRAWN: ActionOwner.NOBODY,
    PromiseState.RECOVERED: ActionOwner.NOBODY,
    PromiseState.PLANNED: ActionOwner.YOU,
    PromiseState.AWAITING_PLAN: ActionOwner.NOBODY,
    PromiseState.AUTHORIZED: ActionOwner.SYSTEM,
    PromiseState.APPLYING: ActionOwner.SYSTEM,
    PromiseState.REQUESTED: ActionOwner.CUSTOMER,
    PromiseState.CONSENTED: ActionOwner.SYSTEM,
    PromiseState.DECLINED: ActionOwner.OWNER,
    PromiseState.ESCALATED: ActionOwner.OWNER,
    PromiseState.STALE: ActionOwner.OWNER,
    PromiseState.EXPIRED: ActionOwner.OWNER,
}
"""Whose move each promise state is.

Every state a case can leave a promise in appears once, so a new one is a mapping error rather
than a promise that silently becomes nobody's. ``DECLINED``, ``STALE`` and ``EXPIRED`` are the
owner's for the same reason ``ESCALATED`` is: no further automatic step exists for them, and a
promise with no automatic step and no person is a promise that stops moving without saying so.
"""

_PROMISE_ACTIONS: Final[dict[PromiseState, str]] = {
    PromiseState.UNTOUCHED: "Nothing. This promise is not reachable from what happened.",
    PromiseState.LINKED: "Nothing here. Another case is already recovering this promise.",
    PromiseState.WITHDRAWN: "Nothing. This promise was withdrawn from the case.",
    PromiseState.RECOVERED: "Nothing. The order system carries the change.",
    PromiseState.PLANNED: "Read the plan and confirm it, or leave it as it is.",
    PromiseState.AWAITING_PLAN: "Nothing yet. This promise has not been decided.",
    PromiseState.AUTHORIZED: "Nothing. Your standing preference covers it and it is queued.",
    PromiseState.APPLYING: "Nothing. The order change has gone out and is not confirmed yet.",
    PromiseState.REQUESTED: "Nothing. The customer has been asked and has not answered.",
    PromiseState.CONSENTED: "Nothing. The customer agreed and the change is queued.",
    PromiseState.DECLINED: "The owner decides what to offer instead. Nothing else will happen.",
    PromiseState.ESCALATED: (
        "The owner handles this one by hand. Nothing will change until they do."
    ),
    PromiseState.STALE: "The owner checks the re-planned outcome before anything else is done.",
    PromiseState.EXPIRED: "The owner decides what to do now the deadline has passed.",
}
"""What moves each promise, said as a thing somebody does rather than as a status.

Deliberately blunt about the states nothing automatic follows: "nothing will change until they
do" is the sentence that stops a blocked promise reading as work in progress.
"""


def _promise_owner(state: PromiseState) -> ActionOwner:
    return _PROMISE_OWNERS.get(state, ActionOwner.NOBODY)


def _promise_next_action(state: PromiseState, track: TrackStatus) -> str:
    """This promise's next action, with the customer's own deadline where there is one."""
    action = _PROMISE_ACTIONS.get(state, "Nothing yet. This promise has not been decided.")
    if state is PromiseState.REQUESTED and track.deadline_at is not None:
        return f"{action[:-1]} by {track.deadline_at.isoformat()}."
    return action


def _next_action(
    headline: CaseHeadline,
    threatened: tuple[PromiseView, ...],
    question: QuestionView | None,
) -> NextAction:
    """The one thing this case is waiting on, chosen in the order a case actually stalls in.

    Ordered rather than scored. A case can be waiting on a question *and* holding an escalated
    promise, and the answer to "what is mine?" has to be one thing -- so the earliest unmet
    obligation wins, and the bands below still show the rest. An escalation outranks a customer
    deadline because a customer's clock runs on its own and an owner's does not: nothing at all
    happens to a blocked promise until a person picks it up.
    """
    if question is not None:
        return _action(ActionOwner.YOU, "Answer the question above, in your own words.")
    if headline is CaseHeadline.NEEDS_HUMAN:
        return _action(ActionOwner.YOU, "Read what was reported and say what it means.")
    if headline is CaseHeadline.PLANNED:
        return _action(
            ActionOwner.YOU, "Read the plan below and confirm it before anything is done."
        )
    owners = tuple(item for item in threatened if item.owner is ActionOwner.OWNER)
    if owners:
        count = len(owners)
        verb = "needs" if count == 1 else "need"
        return _action(
            ActionOwner.OWNER,
            f"{_promises(count)} below {verb} the owner by hand. "
            "Nothing will change until somebody picks them up.",
        )
    waiting = tuple(item for item in threatened if item.owner is ActionOwner.CUSTOMER)
    if waiting:
        count = len(waiting)
        customers = "1 customer" if count == 1 else f"{count} customers"
        return _action(
            ActionOwner.CUSTOMER,
            f"Nothing is yours right now. Waiting on {customers} to answer.",
        )
    if headline is CaseHeadline.WORKING:
        return _action(
            ActionOwner.SYSTEM,
            "Nothing is yours right now. The confirmed work is being carried out.",
        )
    if headline in {CaseHeadline.SETTLED, CaseHeadline.CANCELLED}:
        return _action(ActionOwner.NOBODY, "Nothing. This case is finished.")
    return _action(ActionOwner.NOBODY, "Nothing yet. Still working out what this affects.")


def _action(owner: ActionOwner, action: str) -> NextAction:
    return NextAction(owner=owner, owner_label=_OWNER_LABEL[owner], action=action)


def _promises(count: int) -> str:
    return "1 promise" if count == 1 else f"{count} promises"


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
    if view.question is not None:
        # The open question is read out as a question. A surface that only said "waiting for
        # your answer" would leave a worker to guess what was asked, and a model filling that
        # gap from the original sentence is the invention this whole boundary exists to stop.
        lines.append("")
        lines.append(view.question.question)
        lines.extend(f"  - {option.label}" for option in view.question.options)
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
    if view.promises:
        # Only once the case has actually looked at something. A case still asking a question
        # has assessed no promise at all, and "no promise was left alone" would be a claim
        # about work that has not happened -- this band carries the product's central claim,
        # and a claim made before there is anything to claim is the wrong kind of confident.
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


def render_clarification_receipt() -> str:
    """What is said back the instant a worker's answer is stored, and nothing more.

    Fixed text, because there is nothing yet to report: the answer is durable and the
    interpreter has not run. Anything that named an outcome here would be describing work that
    has not happened. The next truthful sentence about this case comes from ``render``.
    """
    return (
        "Got it, and I have written that down exactly as you said it. "
        "Nothing has changed yet - I am working out what it means for your promises."
    )


def render_confirmation(
    *, applying: int, awaiting_approval: int, escalated: int, already_confirmed: bool
) -> str:
    """What a worker's yes has authorised, counted -- and explicitly not what it has done.

    Every clause is a permission or a queued intention. "Covered by a standing preference" is
    the contract's ``AUTHORIZED`` wording precisely because it is not ``RECOVERED``; the
    customer band says the customer has still to be *asked*, which has not happened either.
    The closing sentence exists so a listener who heard only the numbers is still told that
    nothing is done.
    """
    if already_confirmed:
        return (
            "You had already confirmed this one - I have not done it twice. "
            "Ask me for the status to hear where it has got to."
        )
    parts: list[str] = []
    if applying:
        parts.append(f"{_orders(applying)} covered by a standing preference")
    if awaiting_approval:
        parts.append(f"{_orders(awaiting_approval)} where I still have to ask the customer")
    if escalated:
        parts.append(f"{_orders(escalated)} that need the owner")
    if not parts:
        return (
            "Confirmed. There was nothing left for me to carry out, so no order is being changed."
        )
    return (
        f"Confirmed: {_joined(parts)}. Nothing has been changed yet - "
        "ask me for the status to hear what actually happened."
    )


def _orders(count: int) -> str:
    return "1 order" if count == 1 else f"{count} orders"


def _joined(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"
