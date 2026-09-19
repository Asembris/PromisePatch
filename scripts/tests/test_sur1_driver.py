"""The execution loop's rules: budgets, retries, captures, resume and the blinded join.

Every rule the contract states about *what happens to an attempt* is enforced in the driver and
in no arm, so every one of them is asserted here against stub arms and fabricated evidence.

**Nothing here is a run of ``SUR-1``.** The arms are stubs labelled ``HARNESS-A``, ``HARNESS-B``
and ``HARNESS-C`` so that no artefact these tests write could be mistaken for a comparative
attempt; the world is a value; the evidence is written by hand in this file; every run lands in
``tmp_path`` and never in the committed runs directory; and no model is reached. Scenario ``C01``
appears because the scorer loads ground truth by identifier out of the frozen document and will
not accept an invented one -- which is the property that keeps a caller from scoring against a
bound it would rather have.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts.sur1.arms import ArmAttempt, ArmVoidError, HarnessFailureError
from scripts.sur1.authorisation import ScoredAuthorisation, observe
from scripts.sur1.budget import BudgetExhaustedError
from scripts.sur1.capture import CaptureError, RunDirectory, write_once
from scripts.sur1.doubles import FakeClock, StubArm, SyntheticWorld
from scripts.sur1.driver import (
    Clock,
    PredeclarationError,
    UnauthorisedScoredRunError,
    drive,
    join,
)
from scripts.sur1.evidence import (
    UNDETERMINED,
    ChannelMessage,
    ReceiverEvidence,
    ReportedPromiseRow,
    TaskSample,
    WorkerReport,
)
from scripts.sur1.frozen import Contract, FrozenIdentityError
from scripts.sur1.preflight import REQUIRED_CHECKS, SCORED, Check, PreflightReport, authorise

CONTRACT = Contract.load()
UNIVERSE = CONTRACT.case_universe

WALL = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)


def clock() -> Clock:
    return Clock(monotonic=FakeClock(), wall=lambda: WALL)


def tasks() -> tuple[TaskSample, ...]:
    return tuple(
        TaskSample(f"task-ol-{order[-1]}", order, "SCHEDULED", "SCHEDULED") for order in UNIVERSE
    )


def worker_report(*, reason: str = "") -> WorkerReport:
    return WorkerReport(
        scenario_id="C01",
        exception_recorded=True,
        promises=tuple(
            ReportedPromiseRow(order, "UNTOUCHED", None, "SCHEDULED", False, reason)
            for order in UNIVERSE
        ),
    )


def safe_evidence(*, reason: str = "") -> ReceiverEvidence:
    """An attempt that did nothing and said so. Safe, incomplete, and scorable."""
    return ReceiverEvidence(tasks=tasks(), report=worker_report(reason=reason))


def void_evidence() -> ReceiverEvidence:
    """A declared evidence source that could not be read. The contract's third void cause."""
    return ReceiverEvidence(
        tasks=tasks(), report=worker_report(), unreadable_sources=frozenset({"E3"})
    )


def invalid_evidence() -> ReceiverEvidence:
    """No report at all. INVALID, which is a nonpass and explicitly not a void."""
    return ReceiverEvidence(tasks=tasks())


def stub(label: str, *outcomes: ArmAttempt | BaseException) -> StubArm:
    return StubArm(label=label, outcomes=list(outcomes))


def synthetic_authorisation(
    *,
    run_id: str,
    root: Path,
    world: object,
    arms: Sequence[object],
    classifier: object,
) -> ScoredAuthorisation:
    """A capability for a run made of stubs, minted through the one door that mints them.

    The report is fabricated here -- these stubs would fail ``real_bindings`` and the loopback
    receivers would fail ``receivers`` -- and that is the point: this file proves the driver's
    rules, not the preflight's, so it forges the answer and still has to go through
    :func:`~scripts.sur1.preflight.authorise` to turn it into authority. Nothing in the shipped
    package can do what these five lines do, which is why the boundary holds outside this file.
    """
    report = PreflightReport(
        kind=SCORED, checks=tuple(Check(name, True, "synthetic") for name in REQUIRED_CHECKS)
    )
    return authorise(
        report,
        observe(
            kind=SCORED,
            run_id=run_id,
            root=root,
            scenarios=("C01",),
            world=world,
            arms=arms,
            classifier=classifier,
        ),
    )


def run(
    tmp_path: Path,
    *arms: StubArm,
    world: SyntheticWorld | None = None,
    kind: str = "development",
    run_id: str = "harness-run",
    **overrides: object,
) -> RunDirectory:
    return drive(
        arms=list(arms),
        world=world or SyntheticWorld(),
        clock=clock(),
        run_id=run_id,
        kind=kind,
        command=("pytest",),
        scenarios=("C01",),
        root=tmp_path,
        **overrides,  # type: ignore[arg-type]
    )


def outcomes_in(directory: RunDirectory) -> dict[str, str]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))["outcome"]
        for path in sorted(directory.verdicts.glob("*.json"))
    }


# ------------------------------------------------------------------- three arms, one driver


def test_three_arms_are_driven_over_one_interface(tmp_path: Path) -> None:
    arms = [
        stub("HARNESS-A", ArmAttempt(evidence=safe_evidence())),
        stub("HARNESS-B", ArmAttempt(evidence=safe_evidence())),
        stub("HARNESS-C", ArmAttempt(evidence=safe_evidence(), diagnostics={"ablated_check": 5})),
    ]
    directory = run(tmp_path, *arms)
    assert len(directory.completed_attempts()) == 3
    assert set(outcomes_in(directory).values()) == {"SAFE_AND_INCOMPLETE"}
    for arm in arms:
        assert len(arm.requests) == 1


def test_an_arm_is_never_shown_the_answer_it_is_scored_against(tmp_path: Path) -> None:
    """A scenario reaches an arm without its ground truth and without its point."""
    arm = stub("HARNESS-A", ArmAttempt(evidence=safe_evidence()))
    run(tmp_path, arm)
    scenario = arm.requests[0].scenario
    assert "ground_truth" not in scenario
    assert "the_point" not in scenario
    assert scenario["stipulated_facts"]


def test_every_arm_is_given_the_same_ceilings(tmp_path: Path) -> None:
    arms = [stub(f"HARNESS-{letter}", ArmAttempt(evidence=safe_evidence())) for letter in "ABC"]
    run(tmp_path, *arms)
    ceilings = {arm.requests[0].budget.ceilings for arm in arms}
    assert ceilings == {CONTRACT.ceilings}


# --------------------------------------------------------------------- one retry, one cause


def test_a_void_is_retried_exactly_once(tmp_path: Path) -> None:
    arm = stub(
        "HARNESS-A",
        ArmAttempt(evidence=void_evidence()),
        ArmAttempt(evidence=void_evidence()),
        ArmAttempt(evidence=safe_evidence()),
    )
    directory = run(tmp_path, arm)
    assert len(arm.requests) == 2
    attempts = sorted(directory.completed_attempts())
    assert [key[-2:] for key in attempts] == ["a1", "a2"]
    assert set(outcomes_in(directory).values()) == {"VOID"}


def test_both_attempts_are_captured_and_neither_is_dropped(tmp_path: Path) -> None:
    """No best-of-N, and no selecting which attempt to publish."""
    arm = stub(
        "HARNESS-A",
        ArmAttempt(evidence=void_evidence()),
        ArmAttempt(evidence=safe_evidence()),
    )
    directory = run(tmp_path, arm)
    outcomes = outcomes_in(directory)
    assert len(outcomes) == 2
    assert sorted(outcomes.values()) == ["SAFE_AND_INCOMPLETE", "VOID"]
    retried = {
        key: json.loads((directory.verdicts / f"{key}.json").read_text())["retried"]
        for key in outcomes
    }
    assert sorted(retried.values()) == [False, True]


def test_an_invalid_report_is_not_retried_and_is_not_a_void(tmp_path: Path) -> None:
    arm = stub(
        "HARNESS-A",
        ArmAttempt(evidence=invalid_evidence()),
        ArmAttempt(evidence=safe_evidence()),
    )
    directory = run(tmp_path, arm)
    assert len(arm.requests) == 1
    assert list(outcomes_in(directory).values()) == ["INVALID"]


def test_a_verdict_of_any_kind_ends_the_scenario(tmp_path: Path) -> None:
    arm = stub(
        "HARNESS-A", ArmAttempt(evidence=safe_evidence()), ArmAttempt(evidence=safe_evidence())
    )
    directory = run(tmp_path, arm)
    assert len(arm.requests) == 1
    assert len(directory.completed_attempts()) == 1


# ------------------------------------------------------------------------ the two the driver owns


def test_budget_exhaustion_ends_the_attempt_and_is_never_a_void(tmp_path: Path) -> None:
    """A crossed ceiling that could become a void would shrink the denominator it belongs in."""
    arm = stub(
        "HARNESS-A",
        BudgetExhaustedError("model_calls", 24, 25),
        ArmAttempt(evidence=safe_evidence()),
    )
    directory = run(tmp_path, arm)
    assert len(arm.requests) == 1
    assert list(outcomes_in(directory).values()) == ["BUDGET_EXHAUSTED"]

    verdict = json.loads(next(directory.verdicts.glob("*.json")).read_text(encoding="utf-8"))
    assert verdict["decided_by"] == "driver"
    assert set(verdict["safety"].values()) == {0}
    assert verdict["primary"]["complete_allowed_recovery"] is False
    assert "model_calls ceiling 24" in verdict["notes"][0]


def test_a_harness_failure_is_a_nonpass_disclosed_by_name(tmp_path: Path) -> None:
    arm = stub("HARNESS-A", HarnessFailureError("the world would not prepare"))
    directory = run(tmp_path, arm)
    assert list(outcomes_in(directory).values()) == ["HARNESS_FAILURE"]


def test_a_declared_void_cause_from_an_arm_is_a_void_and_is_retried(tmp_path: Path) -> None:
    arm = stub(
        "HARNESS-A",
        ArmVoidError("the model provider returned no answer at all"),
        ArmAttempt(evidence=safe_evidence()),
    )
    directory = run(tmp_path, arm)
    assert len(arm.requests) == 2
    assert sorted(outcomes_in(directory).values()) == ["SAFE_AND_INCOMPLETE", "VOID"]


def test_receivers_are_read_even_when_the_attempt_ended_badly(tmp_path: Path) -> None:
    """An attempt that crossed a ceiling still did things, and the capture is where they land."""
    world = SyntheticWorld(evidence=safe_evidence())
    arm = stub("HARNESS-A", BudgetExhaustedError("tool_calls", 60, 61))
    directory = run(tmp_path, arm, world=world)
    captured = directory.read_attempt(next(iter(directory.completed_attempts())))
    assert len(captured["evidence"]["E3"]) == len(UNIVERSE)


def test_receivers_that_cannot_be_read_are_declared_rather_than_assumed_empty(
    tmp_path: Path,
) -> None:
    world = SyntheticWorld(unreadable=True)
    arm = stub("HARNESS-A", BudgetExhaustedError("tool_calls", 60, 61))
    directory = run(tmp_path, arm, world=world)
    captured = directory.read_attempt(next(iter(directory.completed_attempts())))
    assert sorted(captured["evidence"]["unreadable_sources"]) == ["E1", "E2", "E3", "E4"]


def test_malformed_evidence_fails_closed_to_a_harness_failure(tmp_path: Path) -> None:
    """A receiver row nobody can place is a broken measurement, never a zero on a ceiling."""
    stranger = ReceiverEvidence(
        tasks=tasks(),
        messages=(
            ChannelMessage("tg:9999", "INBOUND", "YES", datetime(2026, 9, 19, 9, 1, tzinfo=UTC)),
        ),
        report=worker_report(),
    )
    directory = run(tmp_path, stub("HARNESS-A", ArmAttempt(evidence=stranger)))
    assert list(outcomes_in(directory).values()) == ["HARNESS_FAILURE"]


# ------------------------------------------------------------------- captures and resume


def test_raw_evidence_and_the_verdict_are_separate_artefacts(tmp_path: Path) -> None:
    directory = run(tmp_path, stub("HARNESS-A", ArmAttempt(evidence=safe_evidence())))
    key = next(iter(directory.completed_attempts()))
    assert (directory.attempts / f"{key}.json").exists()
    assert (directory.verdicts / f"{key}.json").exists()
    captured = directory.read_attempt(key)
    assert "outcome" not in captured["attempt"]
    assert captured["attempt"]["status"] == "PENDING_SCORE"


def test_a_capture_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "attempt.json"
    write_once(path, {"a": 1})
    with pytest.raises(CaptureError, match="never edited"):
        write_once(path, {"a": 2})


def test_resume_skips_completed_attempt_identities(tmp_path: Path) -> None:
    first = stub("HARNESS-A", ArmAttempt(evidence=safe_evidence()))
    run(tmp_path, first)
    second = stub("HARNESS-A", ArmAttempt(evidence=safe_evidence()))
    directory = run(tmp_path, second)
    assert second.requests == []
    assert len(directory.completed_attempts()) == 1


def test_a_run_that_died_before_scoring_is_scored_without_being_re_driven(
    tmp_path: Path,
) -> None:
    """Scoring is a pure function of a file. Driving costs money. Only one of them repeats."""
    directory = run(tmp_path, stub("HARNESS-A", ArmAttempt(evidence=safe_evidence())))
    key = next(iter(directory.completed_attempts()))
    (directory.verdicts / f"{key}.json").unlink()

    arm = stub("HARNESS-A", ArmAttempt(evidence=safe_evidence()))
    resumed = run(tmp_path, arm)
    assert arm.requests == []
    assert outcomes_in(resumed) == {key: "SAFE_AND_INCOMPLETE"}


def test_a_token_survives_a_restart_so_an_attempt_keeps_its_identity(tmp_path: Path) -> None:
    directory = run(tmp_path, stub("HARNESS-A", ArmAttempt(evidence=safe_evidence())))
    before = directory.read_arm_map()
    run(tmp_path, stub("HARNESS-A", ArmAttempt(evidence=safe_evidence())))
    assert directory.read_arm_map() == before


def test_a_resumed_run_against_different_identities_is_refused(tmp_path: Path) -> None:
    run(tmp_path, stub("HARNESS-A", ArmAttempt(evidence=safe_evidence())))
    started = json.loads((tmp_path / "harness-run" / "run.json").read_text(encoding="utf-8"))
    started["baseline_prompt_sha"] = "0" * 64
    (tmp_path / "harness-run" / "run.json").write_text(json.dumps(started), encoding="utf-8")

    with pytest.raises(CaptureError, match="baseline_prompt_sha"):
        run(tmp_path, stub("HARNESS-A", ArmAttempt(evidence=safe_evidence())))


# ---------------------------------------------------------------- blinding and the join


def test_a_verdict_carries_a_token_and_the_map_is_a_file_beside_it(tmp_path: Path) -> None:
    directory = run(tmp_path, stub("HARNESS-A", ArmAttempt(evidence=safe_evidence())))
    verdict = json.loads(next(directory.verdicts.glob("*.json")).read_text(encoding="utf-8"))
    assert verdict["arm_token"].startswith("tok-")
    assert "arm" not in verdict
    assert "HARNESS-A" not in json.dumps(verdict)
    assert directory.read_arm_map() == {verdict["arm_token"]: "HARNESS-A"}


def test_the_free_text_an_arm_wrote_never_reaches_a_verdict(tmp_path: Path) -> None:
    prose = "arm C dropped the substitute check"
    directory = run(tmp_path, stub("HARNESS-A", ArmAttempt(evidence=safe_evidence(reason=prose))))
    verdict = next(directory.verdicts.glob("*.json")).read_text(encoding="utf-8")
    assert prose not in verdict
    captured = next(directory.attempts.glob("*.json")).read_text(encoding="utf-8")
    assert prose in captured


def test_latency_and_cost_are_captured_and_joined_only_after_every_verdict(
    tmp_path: Path,
) -> None:
    """Both are arm-identifying, so they are collected by the driver and never enter a bundle."""
    directory = run(tmp_path, stub("HARNESS-A", ArmAttempt(evidence=safe_evidence())))
    verdict = json.loads(next(directory.verdicts.glob("*.json")).read_text(encoding="utf-8"))
    assert "latency_seconds" not in verdict
    assert "cost" not in verdict

    captured = directory.read_attempt(next(iter(directory.completed_attempts())))["attempt"]
    assert captured["latency_seconds"] == 0.0
    assert captured["cost"]["estimated_usd"] == "unavailable"

    joined = join(directory)
    assert joined["attempts"][0]["arm"] == "HARNESS-A"
    assert joined["attempts"][0]["latency_seconds"] == 0.0
    assert joined["attempts"][0]["cost"]["model_calls"] == 0


def test_the_join_is_written_once(tmp_path: Path) -> None:
    directory = run(tmp_path, stub("HARNESS-A", ArmAttempt(evidence=safe_evidence())))
    join(directory)
    with pytest.raises(CaptureError):
        join(directory)


# --------------------------------------------------------------------- refusing to start


def test_a_scored_run_refuses_an_undeclared_outbound_rule(tmp_path: Path) -> None:
    """The contract requires that rule to be declared before the first scored attempt."""
    arm = stub("HARNESS-A", ArmAttempt(evidence=safe_evidence()))
    with pytest.raises(PredeclarationError, match="will not invent one"):
        run(tmp_path, arm, kind="scored")
    assert arm.requests == []


def test_a_scored_run_refuses_to_start_without_an_authorisation(tmp_path: Path) -> None:
    """A declared rule is not enough. ``kind="scored"`` is a capability, not a string.

    This is the bypass the boundary closed: before it, this exact call -- stub arms, a value for
    a world, a rule declared inline in a test -- wrote a directory of scored artefacts that read
    identically to an authorised run's, having asked none of the preflight's questions.
    """

    def declared(message: ChannelMessage) -> bool | None:
        return False

    arm = stub("HARNESS-A", ArmAttempt(evidence=safe_evidence()))
    with pytest.raises(UnauthorisedScoredRunError, match="minted by a passing"):
        run(tmp_path, arm, kind="scored", classifier=declared)
    assert arm.requests == []
    assert not (tmp_path / "harness-run").exists()


def test_a_declared_rule_and_an_authorisation_let_a_scored_run_start(tmp_path: Path) -> None:
    def declared(message: ChannelMessage) -> bool | None:
        return False

    world = SyntheticWorld()
    arm = stub("HARNESS-A", ArmAttempt(evidence=safe_evidence()))
    directory = run(
        tmp_path,
        arm,
        world=world,
        kind="scored",
        classifier=declared,
        authorisation=synthetic_authorisation(
            run_id="harness-run",
            root=tmp_path,
            world=world,
            arms=[arm],
            classifier=declared,
        ),
    )
    assert json.loads(directory.run_file.read_text(encoding="utf-8"))["kind"] == "scored"


def test_a_development_run_is_refused_a_scored_authorisation(tmp_path: Path) -> None:
    """Spending a scored capability on a run that produces no comparative number would spend it."""
    world = SyntheticWorld()
    arm = stub("HARNESS-A", ArmAttempt(evidence=safe_evidence()))
    granted = synthetic_authorisation(
        run_id="harness-run", root=tmp_path, world=world, arms=[arm], classifier=UNDETERMINED
    )
    with pytest.raises(UnauthorisedScoredRunError, match="takes no scored authorisation"):
        run(tmp_path, arm, world=world, kind="development", authorisation=granted)
    assert not granted.claimed


def test_a_moved_manifest_refuses_before_any_arm_is_constructed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("scripts.sur1.frozen.PUBLISHED_MANIFEST_SHA", "0" * 64)
    arm = stub("HARNESS-A", ArmAttempt(evidence=safe_evidence()))
    with pytest.raises(FrozenIdentityError):
        run(tmp_path, arm)
    assert arm.requests == []
    assert not (tmp_path / "harness-run").exists()


def test_a_scenario_the_contract_does_not_hold_refuses_the_run(tmp_path: Path) -> None:
    arm = stub("HARNESS-A", ArmAttempt(evidence=safe_evidence()))
    with pytest.raises(KeyError, match="C99"):
        drive(
            arms=[arm],
            world=SyntheticWorld(),
            clock=clock(),
            run_id="harness-run",
            kind="development",
            command=("pytest",),
            scenarios=("C99",),
            root=tmp_path,
        )
    assert arm.requests == []


def test_there_is_no_third_attempt(tmp_path: Path) -> None:
    from scripts.sur1.manifest import AttemptIdentity

    with pytest.raises(ValueError, match="the retry policy permits one retry"):
        AttemptIdentity("run-1", "tok-1", "C01", 3)
