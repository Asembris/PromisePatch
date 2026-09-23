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

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from promisepatch.domain.analysis import CaseStatus, TrackStatus
from promisepatch.domain.explanations import FactId, closed_phrase

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
    """The engine's own reason token, carried unchanged for the record that quotes it."""

    reason_phrase: str | None
    """The same reason, in the sentence the explanation layer already publishes for it.

    ``reason`` is a stored token -- ``PREAPPROVAL_COVERS``, ``NOSUB_CONSTRAINT`` -- and a token
    is evidence, not language. This is the words for it, looked up in the one table that owns
    the wording, so a surface showing a person why a promise was decided this way reads the
    domain's phrase rather than holding a dictionary of its own. ``None`` where this build has
    no phrase for the token, so a caller falls back to the token instead of to a guess.
    """

    deadline_at: str | None
    """The customer's own clock, machine-readable, for a surface that renders its own time."""

    deadline_phrase: str | None
    """The same moment in words, for the surfaces that have only a sentence to say it in.

    Spoken status has no structured field beside it, so the deadline has to survive inside the
    sentence -- and an ISO-8601 string with microseconds and an offset is machine vocabulary
    being read out loud. Composed here, once, from the moment that still has a type, because a
    caller reconstructing it from :attr:`deadline_at` would be a second implementation of the
    same wording.
    """

    consent: str | None
    """What this promise's customer was asked, and what came back. ``None`` where nobody was.

    Read from the durable approval record rather than from :attr:`state`, and that separation is
    the whole point of the field. The state says where the *promise* has got to, and it moves on:
    a promise whose customer said yes reads "changed" once the order system's own version agrees,
    and one whose approved change could not then be carried out reads "needs you". Both are true,
    and both are silent about the thing a worker most needs before they pick that promise up --
    that a person was asked, and answered. This carries the answer forward beside whatever the
    promise became, so a consent that succeeded is never hidden by a step that failed after it.

    It invents no word. A decision is stated in the two phrases the state vocabulary already
    owns, and every other posture is the sentence :mod:`promisepatch.domain.explanations` already
    publishes for that request state, so there is no second dictionary here to disagree with the
    first.
    """

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

    escalation_reason: str | None = None
    """The workflow's token for what handed this promise to the owner, for the record.

    Read from the transition's own domain event, never from the state beside it. ``None`` for a
    promise nothing escalated.
    """

    escalation_phrase: str | None = None
    """The same cause, in words: what *later* stopped the plan, not why the plan was made.

    :attr:`reason_phrase` answers "why was this promise planned this way" -- the classification
    the engine made. This answers "and then what stopped it", which is a different question with
    a different answer: a promise a standing preference covered can still escalate because
    nobody confirmed the plan in time. A screen that showed only the first answer made a covered
    promise reading "needs you" look like a contradiction. ``None`` where nothing escalated it,
    or where this build has no words for the token, so a caller falls back to the token.
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
    exception_phrase: str | None
    """What the category says, in words. ``None`` when there is no category or no phrase for it.

    Same argument as :attr:`PromiseView.reason_phrase`: ``SUPPLY_NOT_RECEIVED`` is what the
    engine filed the exception as, and "a supplier delivery did not arrive" is what a person is
    told. Both travel, because the drawer quotes the first and the bands read the second.
    """

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

    untouched_effect_count: int = 0
    """Outbound effects this case caused on the promises it left alone. The published zero.

    Counted from the effect rows of the tracks this projection placed in the untouched set, so
    it is a statement about *these* promises rather than a constant somebody typed. If the
    workflow ever raised an effect on an unreachable promise, this number would say so on the
    screen that claims it never does -- which is the only way such a claim is worth making.
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

    @property
    def promise_count(self) -> int:
        """Every promise this case considered, threatened and untouched together.

        The denominator of the product's published claim -- "0 incident-caused operational
        effects on 3 of 6 orders" -- and therefore a number the backend states rather than one
        a screen adds up. A surface that summed two lists it had been handed could sum a
        filtered, paginated or deduplicated copy of either and report a different universe than
        the one the case actually considered.
        """
        return len(self.threatened) + len(self.untouched)


# ---------------------------------------------------------------------------- the projection


def project(status: CaseStatus) -> CaseView:
    """Turn one engine-level case status into the product's own vocabulary. Pure."""
    headline = CASE_HEADLINES.get(status.state, CaseHeadline.UNDERSTANDING)
    placed = tuple((track, _promise(status.state, track)) for track in status.tracks)
    untouched = tuple(view for _, view in placed if view.state is PromiseState.UNTOUCHED)
    threatened = tuple(view for _, view in placed if view.state is not PromiseState.UNTOUCHED)
    question = _question(status)
    return CaseView(
        case_id=str(status.case_id),
        headline=headline,
        sentence=_HEADLINE_SENTENCE[headline],
        needs_owner_attention=status.needs_owner_attention,
        exception_category=status.category,
        exception_phrase=closed_phrase(FactId.CASE_EXCEPTION, status.category),
        threatened=threatened,
        untouched=untouched,
        question=question,
        next_action=_next_action(headline, threatened, question),
        untouched_effect_count=sum(
            len(track.effects) for track, view in placed if view.state is PromiseState.UNTOUCHED
        ),
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
        reason_phrase=closed_phrase(FactId.IMPACT_REASON, track.reason_detail),
        deadline_at=None if track.deadline_at is None else track.deadline_at.isoformat(),
        deadline_phrase=None if track.deadline_at is None else _spoken_moment(track.deadline_at),
        track_id=str(track.track_id),
        track_state=track.state,
        classification=track.classification,
        rule_id=track.rule_id,
        owner=_promise_owner(state),
        next_action=_promise_next_action(state),
        consent=_consent(track),
        escalation_reason=None if track.escalation is None else track.escalation.reason,
        escalation_phrase=escalation_phrase(
            None if track.escalation is None else track.escalation.reason
        ),
    )


_ESCALATION_PHRASES: Final[dict[str, str]] = {
    "BLOCKED": "the confirmed plan had no change it could make to this order",
    "NO_CHOSEN_OPTION": "no recovery was recorded as chosen for it, which fails closed",
    "PLAN_UNCONFIRMED": "nobody confirmed the plan within its time limit, so nothing was changed",
    "PLAN_STALE": "the kitchen changed after the plan was confirmed, so the change was not made",
    "DOWNSTREAM_UNAVAILABLE": "the order system did not take the change after repeated tries",
    "MIRROR_NOT_RECONCILED": (
        "the order system never showed the change back, so it is not counted as made"
    ),
    "NO_APPROVAL_WINDOW": "there was no time left to ask the customer before the deadline",
    "APPROVAL_EXPIRED": "the approval window closed before the change could be made",
    "APPROVAL_DECLINED": "the customer said no to the change",
    "MESSAGE_UNDELIVERABLE": "the message to the customer could not be delivered",
    "CONFIRMATION_UNANSWERED": "the customer replied twice and neither reply was a yes or a no",
    "WITHDRAWN_AFTER_EFFECTS": (
        "the exception was withdrawn after something had already gone out, so what stands "
        "is checked by hand"
    ),
}
"""Words for the escalation reasons the workflow already records. Not a second reason system.

Keyed by the tokens :mod:`~promisepatch.domain.recovery`, :mod:`~promisepatch.domain.approvals`
and :mod:`~promisepatch.domain.withdrawal` write on the event that escalates a track -- every one
of them, which a test holds this table to. Nothing here decides that a promise escalated or why;
it only says, in a clause, what the transition that did it wrote down.
"""


def escalation_phrase(reason: str | None) -> str | None:
    """The words for one recorded escalation reason, or ``None`` when there are none."""
    return None if reason is None else _ESCALATION_PHRASES.get(reason)


def revalidation_phrase(outcome: str | None) -> str | None:
    """What a recorded revalidation concluded, in the explanation layer's own words.

    The verdict clause only -- "the plan is still valid", "the approval window closed" -- so an
    evidence surface prints a sentence where it used to print ``PROCEED``. Not the clause that
    says what follows: for ``PROCEED`` that is "the approved change is applied", and beside a
    promise whose amendment is still unconfirmed, or was never observed and went to the owner,
    it would claim a change nobody saw. Whether the change landed is the promise's own state to
    say, and it says "changed" only once the order system showed it. ``None`` for a token with
    no phrase, so the caller shows the token rather than a guess.
    """
    return closed_phrase(FactId.REVALIDATION_OUTCOME, outcome)


_DECISION_STATES: Final[dict[str, PromiseState]] = {
    "APPROVE": PromiseState.CONSENTED,
    "DECLINE": PromiseState.DECLINED,
}
"""The two literal answers, mapped to the states whose phrases already name them.

Mapped rather than re-worded. "said yes" and "said no" live in :data:`_PROMISE_PHRASE`, and this
borrows them, so the product's word for a decision changes in one place and changes everywhere.
"""


def _consent(track: TrackStatus) -> str | None:
    """The customer's side of one promise, independent of where the promise itself got to.

    Two gates, and each is one the state vocabulary already applies elsewhere in this module.

    A recorded decision is read first, for the reason :func:`_escalated_state` gives: a customer
    who answered answered, whatever a later timer or a refused revalidation wrote on the request
    afterwards.

    Where there is no decision, an undelivered message says nothing. ``provider_ref`` is stamped
    when the provider acknowledged delivery, so without it nobody has been asked -- and a request
    still queued produces no sentence rather than "the customer has been asked", which is exactly
    the refusal :func:`_waiting_state` makes about the word "asked".
    """
    approval = track.approval
    if approval is None:
        return None
    decided = _DECISION_STATES.get(approval.decision or "")
    if decided is not None:
        return f"the customer {_PROMISE_PHRASE[decided]}"
    if approval.provider_ref is None:
        return None
    return closed_phrase(FactId.APPROVAL_STATE, approval.state)


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
            return _escalated_state(track)
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


def _escalated_state(track: TrackStatus) -> PromiseState:
    """An escalated promise, told apart by whether its own approval request explains it.

    Every escalation is the owner's, and they are not all the same thing to read. A decline and
    an expiry are settled answers about a question that was genuinely asked -- "said no", "no
    answer by the deadline" -- and the product contract gives each its own phrase and its own
    next action. A track that escalated for any other reason has none of that behind it, and
    "needs you" is the whole truth about it.

    They arrive here rather than through :func:`_waiting_state` because the transition that
    settles either one escalates the track in the *same* transaction that records it: there is
    no committed state in which a declined promise is still waiting for its customer. Reading
    the request from the escalated track is therefore the only way this distinction survives,
    and without it a worker is told a customer's "no" in the same words as a missing recipe.

    The order is the protocol's. A decision is read first, because a customer who answered
    before their window closed answered, whatever a later timer wrote on the request.
    """
    approval = track.approval
    if approval is None:
        return PromiseState.ESCALATED
    if approval.decision == "DECLINE":
        return PromiseState.DECLINED
    if approval.decision == "APPROVE":
        # An approval that escalated did not escalate *because* of the answer -- it was refused
        # afterwards, or the work it authorised could not be done. Saying "said yes" here would
        # describe the consent and hide the outcome, so this stays the owner's plain escalation.
        return PromiseState.ESCALATED
    if approval.state == "EXPIRED":
        return PromiseState.EXPIRED
    return PromiseState.ESCALATED


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

_UNADDRESSED_WORKER_LABEL: Final = "The worker"
"""``YOU``, named for a reader who is not the worker it means."""


def owner_label(owner: ActionOwner, *, reader_may_act: bool) -> str:
    """Whose move it is, named for the person actually reading it.

    ``YOU`` is the worker who can move this case, and every sentence that names it was written
    for them. A reader the domain will not let act on the case -- the judge's observer session
    is the one there is -- is not that worker, and "You" beside an instruction to confirm a plan
    offers them a move they do not have. For that reader the same owner is named in the third
    person. Only the name changes: the owner, the action and every permission are exactly what
    the projection decided, and the domain still refuses the reader whatever the label says.
    """
    if owner is ActionOwner.YOU and not reader_may_act:
        return _UNADDRESSED_WORKER_LABEL
    return _OWNER_LABEL[owner]


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
    PromiseState.REQUESTED: "Nothing until the customer answers on their approval page.",
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


def _spoken_moment(moment: datetime) -> str:
    """A moment in the shape the customer's own message already uses, rather than as ISO-8601.

    ``%Y-%m-%d %H:%M`` rather than a written-out weekday, for the reason
    :func:`promisepatch.domain.messaging.render_due` gives: ``strftime``'s names follow whatever
    locale the process is in, and wording that depends on a container's environment is wording
    no test can pin down.

    The zone is named and not converted. This module may not read the environment, so it cannot
    know the kitchen's own zone -- and a sentence that states a clock time without saying whose
    clock it is has made the reader guess.
    """
    return f"{moment.astimezone(UTC):%Y-%m-%d %H:%M} (UTC)"


def _promise_next_action(state: PromiseState) -> str:
    """This promise's next action.

    The deadline is deliberately *not* restated here. Every surface that renders this sentence
    renders :attr:`PromiseView.deadline_at` beside it, in its own reader's clock, so repeating
    the moment inside the sentence put two readings of one instant on adjacent lines -- and the
    one inside the sentence was the machine's.
    """
    return _PROMISE_ACTIONS.get(state, "Nothing yet. This promise has not been decided.")


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
    deadline = "" if item.deadline_phrase is None else f", by {item.deadline_phrase}"
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
    """Why this promise was decided this way, in words rather than in the engine's token.

    ``reason_detail`` is a stored enum -- ``NOSUB_CONSTRAINT``, ``SUPPLY_NOT_RECEIVED`` -- and
    reading one aloud asks a baker to know the engine's vocabulary in order to understand their
    own kitchen. The words for it already exist, in the one table that owns the wording, and
    :attr:`PromiseView.reason_phrase` is that lookup already done.

    The token remains on the value and remains in the evidence that quotes it; what changes here
    is only what is *spoken*. The fallbacks stay tokens on purpose: a build with no phrase for a
    stored reason says the token rather than inventing a sentence for it, because a wrong reason
    read out confidently is worse than an unfamiliar one read out plainly.
    """
    if item.reason_phrase:
        return item.reason_phrase
    if item.reason:
        return item.reason
    if item.rule_id:
        return f"rule {item.rule_id}"
    return "no reason recorded"


# --------------------------------------------------------- the same case, short enough to hear


_SPOKEN_ORDER: Final[tuple[PromiseState, ...]] = tuple(PromiseState)
"""The order counted groups are spoken in: the vocabulary's own declaration order.

Fixed rather than derived from the case, so the same case is read out in the same order every
time and a listener hearing two statuses a minute apart is comparing like with like.
"""

_SELF_EVIDENT_BAND: Final[frozenset[PromiseState]] = frozenset(
    {PromiseState.UNTOUCHED, PromiseState.LINKED, PromiseState.WITHDRAWN}
)
"""States whose authority band is a restatement of the state rather than a second fact.

:func:`_authority` returns ``NONE`` for exactly these, *because of* the state. Saying the band
beside the phrase would be saying the same thing twice, so the spoken form says it once.
"""


def render_spoken(view: CaseView) -> str:
    """The same case as :func:`render`, counted instead of named, for a worker who is listening.

    G7 gives a spoken reply 40 words and a spoken plan 70. ``render`` spends one line of about
    thirteen words on every promise -- a name, an order id, a phrase, a deadline and a reason --
    so a case with more than two or three promises cannot fit, and the canonical six-promise
    case is 104 words. This composes the same case shorter rather than cutting the long one:
    **there is no truncation anywhere in this function**, and a case with more distinct postures
    than the budget has room for is read out long rather than read out wrong.

    What is dropped is identity -- which customer, which order, by when, and why. All of it
    stays on the screen, which renders ``render``'s text and the per-promise bands beside it.

    What is kept is every distinction the truthful vocabulary carries: the headline, the open
    question and its options, each promise state present with its count, each authority band
    present with its count, the escalation, and the counted claim about what was left alone.
    """
    lines = [view.sentence]
    if view.question is not None:
        # The same rule as ``render``: a worker told only that an answer is wanted has to guess
        # what was asked, and a model filling that gap is the invention the boundary exists to
        # stop. The options are joined with "or" because they are alternatives, not a list.
        lines.append(view.question.question)
        labels = [option.label for option in view.question.options]
        if labels:
            lines.append(f"Answer {_either(labels)}.")
    if view.threatened:
        lines.extend(_counted(view.threatened))
    if view.promises:
        lines.append(_untouched_claim(view))
    return "\n".join(lines)


def _counted(threatened: tuple[PromiseView, ...]) -> list[str]:
    """Every threatened promise, as counts per state -- with the band named where it varies.

    Two shapes, chosen by whether the authority band is a shared fact or a distinguishing one.
    Where every threatened promise sits in one band the band is a header and is said once;
    where they are spread, each state clause carries its own breakdown. Naming a shared thing
    once is not an omission, and it is what makes the plan of a six-promise case fit in 35
    words rather than 43.
    """
    groups = [
        (state, tuple(item for item in threatened if item.state is state))
        for state in _SPOKEN_ORDER
    ]
    present = [(state, items) for state, items in groups if items]
    bands = _band_counts(threatened)
    if len(bands) == 1 and any(state not in _SELF_EVIDENT_BAND for state, _ in present):
        clauses = [_clause(items) for _, items in present]
        header = _AUTHORITY_BAND[bands[0][0]]
        # One state, whose own phrase is the band's: heading it with the band would say the
        # same five words twice. `AUTHORIZED` is the case -- it is "covered by a standing
        # preference" and so is the only band it can sit in.
        if len(clauses) == 1 and present[0][1][0].phrase == _band_word(bands[0][0]):
            return [f"{clauses[0]}."]
        return [f"{header}: {_joined(clauses)}."]
    return [_qualified(state, items) + "." for state, items in present]


def _band_counts(items: tuple[PromiseView, ...]) -> list[tuple[Authority, int]]:
    """How many of these promises sit in each authority band, in the band order ``render`` uses.

    ``NONE`` is folded into ``UNDECIDED`` exactly as ``render`` folds it, so the two renderings
    group one case the same way and cannot drift into two different accounts of it.
    """
    counts: list[tuple[Authority, int]] = []
    for band in (
        Authority.STANDING_PREFERENCE,
        Authority.CUSTOMER,
        Authority.OWNER,
        Authority.UNDECIDED,
    ):
        found = sum(1 for item in items if _spoken_band(item.authority) is band)
        if found:
            counts.append((band, found))
    return counts


def _spoken_band(authority: Authority) -> Authority:
    return Authority.UNDECIDED if authority is Authority.NONE else authority


def _clause(items: tuple[PromiseView, ...]) -> str:
    """One promise state and how many promises are in it. The phrase is the table's, unchanged."""
    return f"{len(items)} {items[0].phrase}"


def _qualified(state: PromiseState, items: tuple[PromiseView, ...]) -> str:
    """One state's clause, carrying whose authority those promises change under.

    Dropped in two cases, neither of which loses anything. A state whose band is a restatement
    of itself is said once. And a band phrase that is word for word the state phrase --
    ``AUTHORIZED`` is "covered by a standing preference", and so is its band -- is a stutter
    rather than a second fact.
    """
    clause = _clause(items)
    if state in _SELF_EVIDENT_BAND:
        return clause
    bands = _band_counts(items)
    if len(bands) == 1:
        phrase = _band_word(bands[0][0])
        return clause if phrase == items[0].phrase else f"{clause}, {phrase}"
    return f"{clause}: " + _joined([f"{count} {_band_word(band)}" for band, count in bands])


def _band_word(band: Authority) -> str:
    """A band title as it reads mid-sentence. The words are the table's; only the case changes."""
    title = _AUTHORITY_BAND[band]
    return title[0].lower() + title[1:]


def _untouched_claim(view: CaseView) -> str:
    """The product's central claim, counted -- the same sentence ``render`` heads its band with."""
    count = len(view.untouched)
    if count == 0:
        return "No promise in this case was left alone."
    if count == 1:
        return "1 promise was left alone."
    return f"{count} promises were left alone."


def _either(labels: list[str]) -> str:
    """Options offered as alternatives. A joining word, and nothing that could be a claim."""
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])}, or {labels[-1]}"


def render_report_receipt() -> str:
    """What is said back the instant a worker's report is stored, and nothing more.

    Fixed text, because at this moment there is genuinely nothing to report: the words are
    durable and the interpreter has not run. Naming an outcome, a promise or an order here would
    be describing work nobody has done, and the case may still turn out to be about something
    else entirely. The next truthful sentence about it comes from :func:`render`.
    """
    return (
        "I have written that down exactly as you said it. "
        "Nothing has changed yet - I am working out what it means for your promises."
    )


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


def render_approval_recorded() -> str:
    """What a recorded approval has done, which is put a decision on the record and no more.

    Deliberately flat and short. An approval is not a confirmation: nothing is enqueued, no order
    is being changed and nobody is being asked, and a sentence that sounded like progress would be
    the exact failure every other rendering in this module is written to avoid. It says what was
    written down and who may now act on it.
    """
    return (
        "Noted - your approval of this plan is on the record. "
        "Nothing has been carried out yet, and nothing will be until it is."
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


def render_confirmation_spoken(
    *, applying: int, awaiting_approval: int, escalated: int, already_confirmed: bool
) -> str:
    """The same confirmation, for a worker who is listening rather than reading.

    :func:`render_confirmation` reaches 41 words in one branch -- applying *and* awaiting
    approval *and* escalated, all non-zero -- which is one over the spoken budget. The only
    thing this drops is the closing invitation to ask for the status, which is guidance about
    the conversation rather than a fact about the case.

    Every count survives, each band keeps its own wording, and "Nothing has been changed yet"
    survives, because that clause is the whole reason the long one ends the way it does: a
    listener who heard only the numbers is still told that nothing is done.
    """
    if already_confirmed:
        return render_confirmation(
            applying=applying,
            awaiting_approval=awaiting_approval,
            escalated=escalated,
            already_confirmed=True,
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
    return f"Confirmed: {_joined(parts)}. Nothing has been changed yet."


_REVERSED_SENTENCES: Final[dict[str, tuple[str, str]]] = {
    "TASK_HOLD": (
        "released 1 production task this case had put on hold",
        "released {count} production tasks this case had put on hold",
    ),
    "OPEN_REQUEST": (
        "stood down 1 approval request, so nothing it carried authorises anything now",
        "stood down {count} approval requests, so nothing they carried authorises anything now",
    ),
    "UNSENT_EFFECT": (
        "stopped 1 change that was queued and had not gone out",
        "stopped {count} changes that were queued and had not gone out",
    ),
    "PLANNED_WORK": (
        "cancelled 1 piece of work that had not started",
        "cancelled {count} pieces of work that had not started",
    ),
}
"""What a withdrawal actually stood down, in a sentence per kind. Singular and plural, written.

Every one of these is in the past tense and every one of them is true: the row was changed in
the transaction that produced the count. Nothing here is a forecast.
"""

_APPLIED_SENTENCES: Final[dict[str, tuple[str, str]]] = {
    "ORDER_AMENDED": (
        "1 order had already been changed in the order system, and that change stands",
        "{count} orders had already been changed in the order system, and those changes stand",
    ),
    "CUSTOMER_ASKED": (
        "1 customer had already been asked, and a sent message cannot be unsent",
        "{count} customers had already been asked, and a sent message cannot be unsent",
    ),
    "EFFECT_IN_FLIGHT": (
        "1 change was already being sent when you withdrew, so I cannot say whether it landed",
        "{count} changes were already being sent when you withdrew, "
        "so I cannot say whether they landed",
    ),
}
"""What had already happened, said as something that is not undone.

The wording is deliberately blunt in the one direction that matters. "That change stands" and
"cannot be unsent" are the sentences that stop a withdrawal reading as an undo, and the
in-flight one refuses to claim an outcome nobody observed.
"""


def render_reversals(reversals: Sequence[tuple[str, int]]) -> tuple[str, ...]:
    """One sentence per thing a withdrawal stood down, in the order it was given."""
    return tuple(_countable(_REVERSED_SENTENCES, kind, count) for kind, count in reversals)


def render_applied(applied: Sequence[tuple[str, int]]) -> tuple[str, ...]:
    """One sentence per thing a withdrawal could not stop, in the order it was given."""
    return tuple(_countable(_APPLIED_SENTENCES, kind, count) for kind, count in applied)


def _countable(table: dict[str, tuple[str, str]], kind: str, count: int) -> str:
    """The written sentence for a kind, or a plain fallback rather than a blank line.

    An unrecognised kind is a mapping this module has not been taught, and a surface showing
    nothing for it would hide a consequence. It says what it knows -- the kind and the count --
    which is understated rather than untrue.
    """
    forms = table.get(kind)
    if forms is None:
        return f"{count} x {kind.lower().replace('_', ' ')}"
    return forms[0] if count == 1 else forms[1].format(count=count)


def render_withdrawal(
    *,
    withdrawn: int,
    escalated: int,
    reversals: Sequence[tuple[str, int]],
    applied: Sequence[tuple[str, int]],
    already_withdrawn: bool,
) -> str:
    """What a worker's withdrawal stopped, and -- never omitted -- what it did not stop.

    Three rules hold this text together, and each of them is a way the sentence could otherwise
    lie:

    * **The applied half is never dropped.** If anything had already reached a customer or the
      order system it is said out loud, in the same breath as the withdrawal, so no listener
      hears "withdrawn" and infers "undone".
    * **No physical fact is mentioned as reversed**, because none is. A withdrawal is a decision
      about what may be done to a promise; what happened in the kitchen is a separate authority
      and is untouched (§11.8).
    * **An escalation is named as somebody's job**, not as a tidy ending. When something had
      already gone out the owner has work, and the closing clause says so.
    """
    if already_withdrawn:
        return (
            "You had already withdrawn this one - I have not done it twice. "
            "Ask me for the status to hear where it stands."
        )
    parts: list[str] = ["Withdrawn"]
    stopped = render_reversals(reversals)
    if stopped:
        parts.append(f"I {_joined(list(stopped))}")
    elif not applied:
        parts.append("there was nothing outstanding to stop")
    sentence = f"{parts[0]}: {'; '.join(parts[1:])}." if len(parts) > 1 else f"{parts[0]}."
    if not applied:
        if withdrawn:
            return f"{sentence} {_promises(withdrawn)} are out of this case, and nothing was sent."
        return f"{sentence} Nothing was sent and no order was changed."
    already = _joined(list(render_applied(applied)))
    owner = (
        f" {_promises(escalated)} are with the owner now."
        if escalated
        else " The owner picks this up from here."
    )
    return f"{sentence} I could not undo what had already happened: {already}.{owner}"


def _orders(count: int) -> str:
    return "1 order" if count == 1 else f"{count} orders"


def _joined(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"
