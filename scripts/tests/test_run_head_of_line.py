"""The head-of-line harness: what it injects, what it will not compute, what it may not drift from.

Three claims are under test here, and they are the three the predeclared protocol rests on.

**The harness and the predeclaration cannot drift apart.** Every number the protocol fixes ---
the delay, the repetitions, the bound, the eight sentences, the alternating order --- is asserted
against `docs/g8-head-of-line-predeclaration.md` itself, so a constant edited in one place and
not the other fails here rather than producing a capture that quietly measured something else.

**The harness computes no verdict.** The capture it writes carries raw instants and nothing
derived: no wait, no median, no added delay, no ``H`` and no threshold. That separation is what
makes a later session's arithmetic an application of the protocol rather than a reading of
whatever the harness felt like publishing.

**The delay is injected without a production change.** ``Worker`` already exposes ``semantic`` as
a constructor field and ``StructuredSemanticProvider`` already exists to be subclassed; the
harness uses both, and the control arm runs the same class with the number set to zero.

Amendment 1 added a third arm, and the drift assertions cover it on the same terms: the
representative delay must be the number §14 derived, it must be named in the predeclaration, and
it must sit inside the lease like every other arm.

Nothing here opens a database, starts a worker or reaches a provider --- the directory's own
guard refuses anything that is not loopback, and no test in this file needs even that.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
from scripts.run_head_of_line import (
    BOUND_SECONDS,
    DELAY_MS,
    DELAYED_SENTENCE,
    PREDECLARATION,
    PREFLIGHT_QUIET_SECONDS,
    REPETITIONS,
    REPRESENTATIVE_DELAY_MS,
    RUNNER_VERSION,
    SMOKE_DELAY_MS,
    SMOKE_REPETITIONS,
    UNRELATED_SENTENCES,
    Arm,
    DelayingProvider,
    RefusingProvider,
    RunRecord,
    StagingProviderCalledError,
    _capture,
    main,
    sequence,
)

from promisepatch.domain.steps import LEASE_DURATION
from promisepatch.semantic import FakeSemanticProvider
from promisepatch.semantic.contracts import SemanticJob
from promisepatch.semantic.jobs import JOB_SPECS
from promisepatch.worker import Worker

ROOT = Path(__file__).resolve().parents[2]
SPEC = JOB_SPECS[SemanticJob.INTERPRET_UTTERANCE]


@pytest.fixture(scope="module")
def predeclaration() -> str:
    return (ROOT / PREDECLARATION).read_text(encoding="utf-8")


# ------------------------------------------------------- the harness may not drift from the doc


def test_the_predeclaration_this_harness_names_exists(predeclaration: str) -> None:
    assert "# Predeclaring the G8 head-of-line measurement" in predeclaration


@pytest.mark.parametrize(
    ("declared", "phrase"),
    [
        (DELAY_MS, "**8 000 ms**"),
        (REPRESENTATIVE_DELAY_MS, "**1 500 ms**"),
        (REPETITIONS, "**Three runs per arm"),
        (BOUND_SECONDS, "120-second bound"),
        (PREFLIGHT_QUIET_SECONDS, "waits two seconds"),
    ],
)
def test_every_number_the_harness_uses_is_the_number_the_protocol_fixed(
    predeclaration: str, declared: object, phrase: str
) -> None:
    """The constant and the prose are asserted against each other, not trusted separately."""
    assert declared is not None
    assert phrase in predeclaration


def test_the_eight_unrelated_sentences_are_the_eight_the_protocol_declared(
    predeclaration: str,
) -> None:
    assert len(UNRELATED_SENTENCES) == 8
    assert len(set(UNRELATED_SENTENCES)) == 8
    assert DELAYED_SENTENCE not in UNRELATED_SENTENCES
    for sentence in (DELAYED_SENTENCE, *UNRELATED_SENTENCES):
        assert sentence in predeclaration, sentence


def test_the_delay_stays_inside_the_lease_it_would_otherwise_lose() -> None:
    """A call held past ``LEASE_DURATION`` would measure lease recovery, not scheduling."""
    assert LEASE_DURATION.total_seconds() > DELAY_MS / 1000
    assert LEASE_DURATION.total_seconds() > REPRESENTATIVE_DELAY_MS / 1000
    assert LEASE_DURATION.total_seconds() > SMOKE_DELAY_MS / 1000


def test_the_representative_delay_is_the_one_the_amendment_derived(predeclaration: str) -> None:
    """§14 derives it from two recorded deployed calls. Both must still be named in the document.

    A figure edited in the harness and not in the prose --- or a prose figure whose evidence quietly
    left --- fails here rather than producing a capture that measured a number nobody justified.
    """
    assert REPRESENTATIVE_DELAY_MS == 1500
    assert "`D_representative` = 1 500 ms" in predeclaration
    for reading in ("latency_ms: 1487", "latency_ms: 1444"):
        assert reading in predeclaration, reading
    assert REPRESENTATIVE_DELAY_MS >= 1487
    assert REPRESENTATIVE_DELAY_MS >= 1444


def test_the_three_arms_are_three_distinct_delays() -> None:
    """A representative arm equal to either neighbour would answer nothing the others do not."""
    assert 0 < REPRESENTATIVE_DELAY_MS < DELAY_MS


def test_the_smoke_shape_cannot_be_mistaken_for_the_measurement(predeclaration: str) -> None:
    """All four numbers, and the sentence in the protocol that distinguishes them."""
    assert {SMOKE_DELAY_MS, DELAY_MS} == {500, 8000}
    assert {SMOKE_REPETITIONS, REPETITIONS} == {1, 3}
    assert "a 500 ms delay instead of 8 000" in predeclaration


# ---------------------------------------------------------------------------- the run sequence


def _measurement_arms() -> tuple[Any, ...]:
    return sequence(
        repetitions=REPETITIONS,
        delay_ms=DELAY_MS,
        representative_delay_ms=REPRESENTATIVE_DELAY_MS,
    )


def test_the_arms_alternate_so_drift_falls_on_every_one_of_them() -> None:
    arms = _measurement_arms()
    assert [arm.arm for arm in arms] == ["control", "representative", "treatment"] * REPETITIONS
    assert [arm.ordinal for arm in arms] == list(range(1, 3 * REPETITIONS + 1))


def test_a_control_run_is_the_same_run_with_one_integer_changed() -> None:
    arms = _measurement_arms()
    assert {arm.delay_ms for arm in arms if arm.arm == "control"} == {0}
    assert {arm.delay_ms for arm in arms if arm.arm == "representative"} == {
        REPRESENTATIVE_DELAY_MS
    }
    assert {arm.delay_ms for arm in arms if arm.arm == "treatment"} == {DELAY_MS}


def test_every_arm_runs_the_declared_number_of_times() -> None:
    """Three per arm, nine in all. A dropped run is a missing median, not a smaller denominator."""
    arms = _measurement_arms()
    assert len(arms) == 3 * REPETITIONS
    for name in ("control", "representative", "treatment"):
        assert len([arm for arm in arms if arm.arm == name]) == REPETITIONS


# ------------------------------------------------------------------------------ the injection


def test_the_delay_is_injected_through_a_field_the_product_already_exposes() -> None:
    """No production change: ``Worker.semantic`` is a constructor field, typed to the protocol."""
    assert "semantic" in {field.name for field in fields(Worker)}
    assert issubclass(DelayingProvider, FakeSemanticProvider)
    assert set(vars(DelayingProvider)) & {"invoke"} == {"invoke"}
    assert "run" not in vars(DelayingProvider)


async def test_a_held_call_answers_exactly_what_the_unmodified_fake_answers() -> None:
    plain = await FakeSemanticProvider().invoke(SPEC, "anything", correction=None)
    held = await DelayingProvider(1).invoke(SPEC, "anything", correction=None)
    assert held.payload == plain.payload


async def test_a_control_call_sleeps_for_nothing_and_still_records_its_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    real = asyncio.sleep

    async def watched(seconds: float, *arguments: Any, **keywords: Any) -> Any:
        slept.append(seconds)
        return await real(seconds, *arguments, **keywords)

    monkeypatch.setattr(asyncio, "sleep", watched)
    provider = DelayingProvider(0)
    await provider.invoke(SPEC, "anything", correction=None)
    assert slept == []
    assert len(provider.holds_ms) == 1


async def test_a_staging_cycle_that_reaches_the_provider_fails_loudly() -> None:
    """The delay belongs inside the timed window; spending it during staging must not be quiet."""
    with pytest.raises(StagingProviderCalledError):
        await RefusingProvider().invoke(SPEC, "anything", correction=None)


# ------------------------------------------------------------------ the harness judges nothing


def _record(label: str) -> RunRecord:
    return RunRecord(
        arm=Arm(arm="treatment", repetition=1, ordinal=2, delay_ms=DELAY_MS),
        label=label,
        invocation_id="00000000-0000-0000-0000-000000000000",
        worker_identity="host:1:boot",
    )


def _written(label: str) -> dict[str, Any]:
    return _capture(_record(label), environment={}, sha="0" * 40, dirty=[])


def test_a_capture_carries_every_field_the_arithmetic_reads() -> None:
    written = _written("measurement")
    for key in (
        "runner_version",
        "label",
        "arm",
        "repetition",
        "delay_ms",
        "implementation_sha",
        "working_tree_clean",
        "environment",
        "worker_identity",
        "preflight",
        "arrangement",
        "provider",
        "window",
        "delayed_case",
        "items",
        "step_executed_actor_ids",
        "failures",
    ):
        assert key in written, key
    assert written["runner_version"] == RUNNER_VERSION


def test_a_capture_carries_no_wait_no_median_and_no_verdict() -> None:
    """Every subtraction belongs to §9, applied by a session that did not run this harness."""
    written = _written("measurement")
    forbidden = {"wait_ms", "service_ms", "added_ms", "median", "H", "verdict", "passed", "gate"}
    assert set(written) & forbidden == set()
    assert written["computed"].startswith("nothing")


def test_the_harness_holds_no_threshold_at_all() -> None:
    """A harness that knew the gate could be accused of having been written around it."""
    import scripts.run_head_of_line as harness

    source = inspect.getsource(harness)
    assert "1000.0" not in source
    assert "IDLE_INTERVAL" not in source


def test_a_smoke_capture_says_in_words_that_it_is_not_the_measurement() -> None:
    smoke = _written("smoke")
    assert smoke["label"] == "smoke"
    assert smoke["protocol"].startswith("NOT the measurement")
    assert _written("measurement")["protocol"].startswith("the measurement predeclared")


# --------------------------------------------------------------------------------- the clone


def test_the_clone_check_opens_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--check"]) == 0
    printed = capsys.readouterr().out
    assert PREDECLARATION in printed
    assert "no database was opened" in printed
