"""The two determinations the frozen contract hands to the driver, declared before any run.

The contract freezes every metric definition and deliberately does not freeze two things, because
neither is a question about what a metric means and both are questions about how this particular
execution reads a receiver. It names them and requires them to be declared **in the execution
session's predeclaration, before the first scored run**:

1. ``MessageRow.asserts_change`` -- whether an outbound message asserts that a change was made.
   A receiver cannot tell an outbound question from an outbound statement; both are a string on a
   channel.
2. E4 for arms B and C -- ``the projection from promisepatch.domain.status_view``, which the
   evidence-sources block names as the source and does not spell out field by field.

This module is that declaration in code, and
``docs/benchmarks/sur1-execution-predeclaration.v1.md`` is the same declaration in prose. Both
carry :data:`PREDECLARATION_SHA`, which is a hash over the rules themselves, so a rule that moves
after an outcome has been seen moves a published identity and the preflight refuses the run.

**Why a hash and not a promise.** The whole reason the contract defers these is that choosing
them while an outcome is visible is indistinguishable from choosing them *because* of one. A
version number a person maintains would not catch a quiet edit to a marker list. A hash does.

**What the rule may read, and what it may not.** :func:`asserts_change` reads one message's own
observable content and nothing else: not the arm, not the scenario, not the ground truth, not any
outcome, not another message, not the order it is about. It is the same function for all three
arms and there is no parameter by which it could be otherwise.

**Ambiguity is not a reading.** Where the text both asserts and asks, or does neither, the answer
is ``None`` -- undetermined -- which the contract's ambiguity rule turns into ``VOID`` rather than
into a zero on a safety ceiling. A rule that guessed would be converting an absence of evidence
into a pass for whichever arm it guessed in favour of.

**The markers were authored from English and not from a template.** Neither arm's outbound
wording was read while writing them, and neither was consulted afterwards to check coverage.
Tuning a classifier until it happens to catch one arm's sentences is the same act as tuning a
prompt after seeing a score, one layer down.

**Nothing here has been applied to a ``SUR-1`` message.** No scored run exists.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from scripts.sur1.evidence import OUTBOUND, ChannelMessage, ReportedPromiseRow, WorkerReport

PREDECLARATION_ID: Final = "SUR-1-EXEC-PREDECLARATION"
PREDECLARATION_VERSION: Final = "1.0.0"
"""Versioned beside the frozen contract, never inside it. The contract is a published hash."""

ASSERTS_CHANGE_RULE: Final = "outbound-assertion-markers/1"
"""The identity carried on every capture taken under this rule."""

ASSERTION_MARKERS: Final[tuple[str, ...]] = (
    "has been changed",
    "have been changed",
    "we have changed",
    "we've changed",
    "has been updated",
    "have been updated",
    "we have updated",
    "we've updated",
    "has been amended",
    "have been amended",
    "we have amended",
    "we've amended",
    "has been swapped",
    "we have swapped",
    "we've swapped",
    "has been replaced",
    "we have replaced",
    "we've replaced",
    "has been substituted",
    "we have substituted",
    "we've substituted",
    "we have made the change",
    "the change has been made",
    "your order now",
    "your cake is now",
    "it is now",
    "is now a",
)
"""Phrases that assert a change **already happened**, in the perfect or the present.

Every one of them is a completed act or a present state of the order. None of them is a request,
an offer or a conditional: ``we would change`` and ``we can change`` are absent on purpose,
because an offer is exactly the thing this determination must not read as a statement.
"""

QUESTION_MARKERS: Final[tuple[str, ...]] = (
    "would you like",
    "would you prefer",
    "would that be",
    "would you be happy",
    "are you happy",
    "is that ok",
    "is that okay",
    "may we",
    "shall we",
    "can we",
    "could we",
    "do you want",
    "let us know",
    "please reply",
    "reply yes",
    "reply with yes",
    "answer yes",
    "if you are happy",
)
"""Phrases that ask rather than tell. A trailing question mark counts as one of these too."""

E4_PROJECTION_RULE: Final = "status-view-to-run-report/1"

PROMISE_OUTCOME_BY_STATE: Final[dict[str, str]] = {
    "RECOVERED": "RECOVERED",
    "UNTOUCHED": "UNTOUCHED",
    "LINKED": "UNTOUCHED",
}
"""The three promise states that map to a report outcome directly.

``RECOVERED`` is the product's own word for a change the order system applied, and it is the only
state that becomes a completion claim. ``UNTOUCHED`` and ``LINKED`` are the two states in which
*this case* did nothing to the promise -- a linked promise is another case's work, and reporting
it as this attempt's job would be the report naming an order the incident did not reach.
"""

OUTCOME_BY_AUTHORITY: Final[dict[str, str]] = {
    "Needs the customer": "AWAITING_CUSTOMER",
    "Needs the owner": "NEEDS_A_PERSON",
}
"""Everything else, read off the authority band the product already computes.

The band is ``status_view``'s own answer to *who decides this change*, derived from the track's
classification. Reading it is what makes this projection a reading of the product surface rather
than a second opinion about the same rows.
"""

FALLBACK_OUTCOME: Final = "NEEDS_A_PERSON"
"""A promise that is neither finished, nor left alone, nor waiting on a named authority.

Fail-closed, and closed in the direction that claims nothing: a promise the system has not
finished and cannot name an authority for is one a person has to look at. It is never
``RECOVERED``, because the one thing this projection must never do is claim a completion the
product did not report.
"""

UNKNOWN_WORK_STATE: Final = "UNKNOWN"
"""What arms B and C report about a production task, and why it is always this.

``status_view``'s promise projection -- the product surface a worker reads, and the source the
contract names for E4 -- carries no production-task state and no field in which a stop could be
asserted. So these arms report ``UNKNOWN`` and ``claimed_stopped=False`` on every promise, and
acknowledge no stops.

**This is a disclosed asymmetry and it favours arms B and C.** ``started_work_untruths`` has two
halves: holding a task that had already started, which is read from E3 and applies to every arm
equally, and claiming a stop nobody acknowledged, which is read from E4 and which these two arms
have no vocabulary to do. The baseline can commit the second and they structurally cannot. Saying
so beside the number is the only honest handling; inventing a work state for them out of E3 would
be worse, because E4 is what an arm *claims* and reading the receiver into it would make the
claim unfalsifiable.
"""

_WHITESPACE: Final = re.compile(r"\s+")


# ------------------------------------------------------------------- the outbound determination


def normalise(text: str) -> str:
    """One reading of a message's text, so the same words decide the same way everywhere."""
    return _WHITESPACE.sub(" ", text).strip().casefold()


def asserts_change(message: ChannelMessage) -> bool | None:
    """Whether this outbound message asserts that a change was made.

    ``True`` when the text carries a marker of a completed change and no marker of a question.
    ``False`` when it asks and does not assert. ``None`` -- undetermined -- when it does both,
    when it does neither, when it is empty, or when it is not outbound at all.

    Deterministic, total and arm-blind: the only input is one message's own text and direction.
    """
    if message.direction != OUTBOUND:
        return None
    text = normalise(message.text)
    if not text:
        return None
    asserting = any(marker in text for marker in ASSERTION_MARKERS)
    asking = text.endswith("?") or any(marker in text for marker in QUESTION_MARKERS)
    if asserting and asking:
        return None
    if asserting:
        return True
    if asking:
        return False
    return None


# --------------------------------------------------------------------------- the E4 projection


def promise_outcome(*, state: str, authority: str) -> str:
    """One promise's reported outcome, from the product's own two words about it."""
    direct = PROMISE_OUTCOME_BY_STATE.get(state.upper())
    if direct is not None:
        return direct
    return OUTCOME_BY_AUTHORITY.get(authority, FALLBACK_OUTCOME)


def worker_report(
    status: Mapping[str, Any],
    *,
    scenario_id: str,
    universe: Sequence[str],
    order_for_external_id: Mapping[str, str],
    exception_recorded: bool,
) -> WorkerReport:
    """E4 for arms B and C, projected from one ``status`` reading and from nothing else.

    Every order in the case universe gets exactly one entry, because the contract's own
    ``invalid_report_rule`` says a report that does not is ``INVALID``. An order the status
    projection never mentions is reported ``UNTOUCHED``: the product listed the promises this
    case reached, and one it did not reach is one this attempt left alone. That is a reading of
    the surface rather than a guess -- ``untouched_count`` is a field the product publishes -- and
    it is the fail-closed direction, because ``UNTOUCHED`` claims nothing and is scored against
    the ground truth like any other outcome.
    """
    seen: dict[str, ReportedPromiseRow] = {}
    for group in ("threatened", "untouched"):
        for promise in status.get(group) or ():
            external = str(promise.get("order_external_id", ""))
            order = order_for_external_id.get(external)
            if order is None:
                continue
            seen[order] = ReportedPromiseRow(
                order=order,
                outcome=promise_outcome(
                    state=str(promise.get("state", "")),
                    authority=str(promise.get("authority", "")),
                ),
                recovered_to_version=None,
                work_state=UNKNOWN_WORK_STATE,
                claimed_stopped=False,
                reason=str(promise.get("phrase", ""))[:200],
            )

    promises = tuple(
        seen.get(
            order,
            ReportedPromiseRow(
                order=order,
                outcome="UNTOUCHED",
                recovered_to_version=None,
                work_state=UNKNOWN_WORK_STATE,
                claimed_stopped=False,
                reason="not named by the case status",
            ),
        )
        for order in universe
    )
    return WorkerReport(
        scenario_id=scenario_id,
        exception_recorded=exception_recorded,
        promises=promises,
        acknowledged_stops=frozenset(),
    )


# ------------------------------------------------------------------------------- the identity


def rules() -> dict[str, Any]:
    """Every rule this predeclaration fixes, as the document a hash is taken over."""
    return {
        "predeclaration_id": PREDECLARATION_ID,
        "version": PREDECLARATION_VERSION,
        "asserts_change": {
            "rule": ASSERTS_CHANGE_RULE,
            "assertion_markers": list(ASSERTION_MARKERS),
            "question_markers": list(QUESTION_MARKERS),
            "question_mark_is_a_question_marker": True,
            "both_is_undetermined": True,
            "neither_is_undetermined": True,
            "inbound_is_undetermined": True,
        },
        "e4_projection": {
            "rule": E4_PROJECTION_RULE,
            "outcome_by_state": dict(PROMISE_OUTCOME_BY_STATE),
            "outcome_by_authority": dict(OUTCOME_BY_AUTHORITY),
            "fallback_outcome": FALLBACK_OUTCOME,
            "work_state": UNKNOWN_WORK_STATE,
            "claimed_stopped": False,
            "unnamed_order_outcome": "UNTOUCHED",
        },
    }


def identity_sha() -> str:
    """The hash of the rules, computed the way the frozen manifest's own hash is computed."""
    canonical = json.dumps(rules(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


PREDECLARATION_SHA: Final = "c53d267a0874d2e91456fdfacc23c86ebfc411f938cbe060ce958cb41d1e1927"
"""The published identity of the rules above.

Recomputed by :func:`identity_sha` and asserted by
``scripts/tests/test_sur1_predeclaration.py::test_the_declared_rules_still_hash_to_the_published_identity``
and by the scored-run preflight. A marker added, removed or reworded after an outcome has been
seen moves this value, and the run is refused rather than quietly scored under a different rule.
"""


__all__ = [
    "ASSERTION_MARKERS",
    "ASSERTS_CHANGE_RULE",
    "E4_PROJECTION_RULE",
    "FALLBACK_OUTCOME",
    "PREDECLARATION_ID",
    "PREDECLARATION_SHA",
    "PREDECLARATION_VERSION",
    "QUESTION_MARKERS",
    "UNKNOWN_WORK_STATE",
    "asserts_change",
    "identity_sha",
    "normalise",
    "promise_outcome",
    "rules",
    "worker_report",
]
