"""The pure half of the workflow, tested without a database because it does not have one.

Every assertion here runs in microseconds and needs no PostgreSQL, which is the payoff for
keeping the handlers pure: what a step *decides* is separable from whether the decision
committed, and the two failure modes stop hiding behind each other.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from promisepatch.db.types import CASE_STATES, STEP_STATES
from promisepatch.domain import handlers, retry
from promisepatch.domain.identity import MAX_LENGTH, WorkerIdentity
from promisepatch.domain.model import (
    CASE_SUBJECT,
    FAKE_EFFECT_KIND,
    TERMINAL_CASE_STATES,
    WAKEUP_TIMER_KIND,
    Disposition,
    StepContext,
    StepKind,
)

NOW = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)
CASE = uuid4()


def context(
    kind: StepKind, *, step_key: str = "", attempts: int = 1, state: str = "EXECUTING"
) -> StepContext:
    return StepContext(
        step_id=uuid4(),
        case_id=CASE,
        step_key=step_key or kind.value.lower(),
        kind=kind,
        attempts=attempts,
        case_state=state,
        now=NOW,
    )


# ------------------------------------------------------------------------------- vocabulary


def test_the_terminal_case_states_are_real_case_states() -> None:
    """The pure layer restates this vocabulary rather than importing it; it must not drift.

    ``model`` may not reach into the persistence layer, so it cannot import the ``CHECK`` the
    database enforces. This is the seam, and it is the only thing holding the two together.
    """
    assert set(CASE_STATES) >= TERMINAL_CASE_STATES


def test_every_disposition_is_a_state_the_database_accepts() -> None:
    """A disposition is written straight into ``case_steps.state`` with no translation.

    That is the design -- one vocabulary rather than two and a mapping between them -- and this
    is what makes it safe. A member the ``CHECK`` would refuse fails here rather than as a
    constraint violation in the middle of a transition that was otherwise about to commit.
    """
    assert {disposition.value for disposition in Disposition} <= set(STEP_STATES)


def test_every_step_kind_has_a_handler() -> None:
    """A stored step naming a kind nothing handles would be work that silently never runs."""
    for kind in StepKind:
        assert handlers.handle(context(kind)) is not None


def test_an_unknown_kind_is_refused_rather_than_ignored() -> None:
    """Loudly, because treating it as a no-op would mark work done that nothing did.

    Reachable during a rolling deploy: an older build claims a step an newer one enqueued.
    """
    ghost = replace(context(StepKind.NOOP), kind=cast(StepKind, "GHOST"))
    with pytest.raises(handlers.UnknownStepKindError):
        handlers.handle(ghost)


# ----------------------------------------------------------------------------- step handlers


def test_a_noop_finishes_and_asks_for_nothing() -> None:
    outcome = handlers.handle(context(StepKind.NOOP))
    assert outcome.disposition is Disposition.DONE
    assert outcome.successors == ()
    assert outcome.timers == ()
    assert outcome.effects == ()


def test_a_chain_enqueues_its_own_successor_by_a_derived_key() -> None:
    """Derived, so a transition replayed after a crash proposes the identical key."""
    outcome = handlers.handle(context(StepKind.CHAIN, step_key="chain:0"))
    assert [successor.step_key for successor in outcome.successors] == ["chain:1"]

    again = handlers.handle(context(StepKind.CHAIN, step_key="chain:0"))
    assert again.successors == outcome.successors


def test_a_chain_stops_at_its_bound() -> None:
    """A handler that always enqueues a successor is a workflow that never finishes."""
    last = handlers.CHAIN_LENGTH - 1
    outcome = handlers.handle(context(StepKind.CHAIN, step_key=f"chain:{last}"))
    assert outcome.successors == ()


def test_arming_a_timer_asks_for_a_delay_and_never_for_a_clock() -> None:
    outcome = handlers.handle(context(StepKind.ARM_TIMER, step_key="arm-timer:30"))
    assert len(outcome.timers) == 1
    timer = outcome.timers[0]
    assert timer.kind == WAKEUP_TIMER_KIND
    assert timer.subject_type == CASE_SUBJECT
    assert timer.subject_id == str(CASE)
    assert timer.delay == timedelta(seconds=30)


def test_an_effect_carries_a_key_derived_only_from_server_side_identifiers() -> None:
    """Same decision, same key -- which is what makes a redelivery a redelivery."""
    outcome = handlers.handle(context(StepKind.EMIT_EFFECT, step_key="emit-effect:1"))
    assert len(outcome.effects) == 1
    effect = outcome.effects[0]
    assert effect.kind == FAKE_EFFECT_KIND
    assert effect.idempotency_key == handlers.effect_key(CASE, "emit-effect:1")
    assert handlers.handle(context(StepKind.EMIT_EFFECT, step_key="emit-effect:1")).effects == (
        effect,
    )


def test_a_different_step_gets_a_different_effect_key() -> None:
    first = handlers.handle(context(StepKind.EMIT_EFFECT, step_key="emit-effect:1")).effects[0]
    second = handlers.handle(context(StepKind.EMIT_EFFECT, step_key="emit-effect:2")).effects[0]
    assert first.idempotency_key != second.idempotency_key


def test_a_retryable_failure_asks_for_a_retry_and_changes_nothing_else() -> None:
    outcome = handlers.handle(context(StepKind.FAIL_RETRYABLE))
    assert outcome.disposition is Disposition.RETRYING
    assert outcome.case_change.needs_owner_attention is None
    assert outcome.error is not None


def test_a_terminal_failure_puts_the_case_on_a_human_desk() -> None:
    outcome = handlers.handle(context(StepKind.FAIL_TERMINAL))
    assert outcome.disposition is Disposition.FAILED
    assert outcome.case_change.needs_owner_attention is True


@pytest.mark.parametrize("state", sorted(TERMINAL_CASE_STATES))
def test_a_guard_skips_itself_when_the_case_is_already_over(state: str) -> None:
    outcome = handlers.handle(context(StepKind.SKIP_IF_TERMINAL, state=state))
    assert outcome.disposition is Disposition.SKIPPED
    assert outcome.result["skipped_because"] == state


def test_a_guard_runs_when_the_case_is_still_live() -> None:
    outcome = handlers.handle(context(StepKind.SKIP_IF_TERMINAL, state="EXECUTING"))
    assert outcome.disposition is Disposition.DONE


def test_a_handler_decides_only_from_its_context() -> None:
    """Two identical contexts, two identical answers -- the definition of replayable."""
    for kind in StepKind:
        first = handlers.handle(context(kind, step_key=f"{kind.value.lower()}:1"))
        second = handlers.handle(context(kind, step_key=f"{kind.value.lower()}:1"))
        assert first == second


def test_a_step_key_parameter_is_read_from_the_key_and_defaults_to_zero() -> None:
    assert handlers.step_parameter("chain:7") == 7
    assert handlers.step_parameter("noop") == 0
    assert handlers.step_parameter("timer:not-a-number") == 0


# ------------------------------------------------------------------------- inbound normalising


def test_an_unknown_source_is_terminal_rather_than_retriable() -> None:
    """Returning to a record nothing in this build can read would mean returning forever."""
    outcome = handlers.normalize_inbound("telegram", "{}")
    assert outcome.state == "FAILED"
    assert outcome.step_kind is None


def test_a_synthetic_record_naming_a_case_produces_one_successor() -> None:
    case_id = uuid4()
    outcome = handlers.normalize_inbound(
        handlers.SYNTHETIC_SOURCE, json.dumps({"case_id": str(case_id)})
    )
    assert outcome.state == "PROCESSED"
    assert outcome.case_id == case_id
    assert outcome.step_kind is StepKind.NOOP


def test_a_synthetic_record_naming_no_case_is_understood_and_produces_nothing() -> None:
    """``IGNORED`` rather than ``PROCESSED``: there is no successor, and saying so matters."""
    outcome = handlers.normalize_inbound(handlers.SYNTHETIC_SOURCE, json.dumps({}))
    assert outcome.state == "IGNORED"
    assert outcome.step_kind is None


@pytest.mark.parametrize("body", ["", "not json", "[]", '{"case_id": "not-a-uuid"}'])
def test_unreadable_material_fails_rather_than_raising(body: str) -> None:
    """A stored record the parser cannot use is a verdict, not an exception in the worker loop."""
    outcome = handlers.normalize_inbound(handlers.SYNTHETIC_SOURCE, body)
    assert outcome.state == "FAILED"
    assert outcome.error


# ------------------------------------------------------------------------------ retry ladder


def test_the_ladder_is_the_one_the_architecture_fixes() -> None:
    assert [delay.total_seconds() for delay in retry.BACKOFF_LADDER] == [1, 5, 30, 120, 600]


def test_each_attempt_waits_longer_than_the_last() -> None:
    delays = [retry.backoff_after(n) for n in range(1, retry.MAX_ATTEMPTS)]
    assert None not in delays
    scheduled = [delay for delay in delays if delay is not None]
    assert scheduled == sorted(scheduled)


def test_the_bound_ends_the_ladder() -> None:
    assert retry.backoff_after(retry.MAX_ATTEMPTS) is None
    assert retry.is_exhausted(retry.MAX_ATTEMPTS)
    assert not retry.is_exhausted(retry.MAX_ATTEMPTS - 1)


def test_an_attempt_count_below_one_is_a_programming_error() -> None:
    """``attempts`` is post-increment, so zero means the claim never happened."""
    with pytest.raises(ValueError, match="at least 1"):
        retry.backoff_after(0)


# --------------------------------------------------------------------------- worker identity


def test_an_identity_fits_the_lease_column() -> None:
    identity = WorkerIdentity.create()
    assert len(identity.value) <= MAX_LENGTH


def test_two_identities_from_one_machine_differ() -> None:
    """The boot id is why. Without it a restarted container could match a dead claim's fence."""
    assert WorkerIdentity.create() != WorkerIdentity.create()


def test_an_identity_too_long_for_the_column_is_refused() -> None:
    with pytest.raises(ValueError, match="lease column"):
        WorkerIdentity("x" * (MAX_LENGTH + 1))


def test_an_empty_identity_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        WorkerIdentity("")
