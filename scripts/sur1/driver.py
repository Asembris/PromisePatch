"""The execution loop: one place that decides what happens to an attempt, for all three arms.

Everything the contract says about budgets, retries, void and capture order is enforced here and
in no arm. An arm produces evidence; this module decides what that evidence was an attempt at,
whether the attempt may be repeated, what is written and in what order.

**The order of writes is load-bearing.**

1. The raw capture, with the receivers' own rows and the driver's own observations, written
   before anything judges it and refusing to overwrite.
2. The verdict, in a separate file, from a bundle projected out of that evidence.
3. The join, in a separate invocation, against the token map.

A process that dies between 1 and 2 resumes by re-scoring a file, which is free. A process that
dies between 2 and 3 has every verdict already written, which is the property the blinding rule
asks for: *verdicts are written before the map is joined.*

**Two outcomes never reach the scorer.** ``BUDGET_EXHAUSTED`` and ``HARNESS_FAILURE`` are facts
about an attempt the driver observed, and the scorer's own docstring says it will not infer
them. They are recorded directly and, crucially, are not ``VOID``: turning a nonpass into a void
is precisely how a bad attempt disappears from a denominator.

**One retry, one cause, one shape.** A retry happens when and only when attempt 1 ended ``VOID``,
runs the whole scenario from a clean fixture, and is the attempt whose verdict is scored. Both
attempts keep their captures. ``INVALID``, ``BUDGET_EXHAUSTED``, ``DISQUALIFIED`` and every
other verdict are never retried, and there is no third attempt because
:class:`~scripts.sur1.manifest.AttemptIdentity` refuses to be one.

**A scored run refuses to start under an undeclared rule.** The contract hands the driver one
determination -- whether an outbound message asserts a change -- and requires the rule to be
declared in the execution session's predeclaration. :func:`drive` refuses ``kind="scored"``
unless it has been handed a classifier that is not the undetermined default. A development run
may proceed without one; its messages are undetermined and its scenarios void, which is the
honest reading of a rule nobody has declared yet.

**A scored run refuses to start without a capability.** ``kind="scored"`` is not a string this
module will act on: it requires a :class:`~scripts.sur1.authorisation.ScoredAuthorisation`,
which only a passing scored preflight mints, and it claims that capability -- once -- against a
fingerprint recomputed from the world, the arms, the rule and the frozen documents this call was
actually handed. :func:`drive` stays callable for development and for the tests that prove these
rules; what it stopped being able to do is produce a scored artefact around the preflight.

**This driver has run one scored SUR-1 run**, ``20260919T2020Z-scored``, which is published
inconclusive and unaltered: 24 of its 27 attempts ended ``HARNESS_FAILURE`` for reasons that
have nothing to do with what any arm decided. See ``docs/sur1-first-scored-run-defect.md``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from scripts.score_safe_useful_recovery import ScenarioVerdict
from scripts.sur1 import DRIVER_VERSION
from scripts.sur1.arms import (
    ArmAdapter,
    ArmVoidError,
    AttemptRequest,
    HarnessFailureError,
    ScenarioWorld,
    scenario_without_ground_truth,
)
from scripts.sur1.authorisation import SCORED, ScoredAuthorisation, observe
from scripts.sur1.budget import AttemptBudget, BudgetExhaustedError
from scripts.sur1.capture import (
    RUNS_ROOT,
    RunDirectory,
    open_run,
    write_attempt,
    write_driver_verdict,
    write_verdict,
)
from scripts.sur1.evidence import (
    UNDETERMINED,
    EvidenceMalformedError,
    FixtureMap,
    OutboundClassifier,
    ReceiverEvidence,
)
from scripts.sur1.frozen import Contract
from scripts.sur1.manifest import (
    AttemptIdentity,
    AttemptManifest,
    RunManifest,
    implementation,
    utc_now,
)
from scripts.sur1.scoring import FROZEN, Scorer

RETRYABLE: Final = frozenset({"VOID"})
"""The one cause the contract permits a retry for. Widening this widens the benchmark."""

MAX_ATTEMPTS: Final = 2
"""One attempt plus at most one retry. There is no third."""


class PredeclarationError(RuntimeError):
    """A scored run was asked for under a rule nobody declared."""


class UnsubstitutableScoredRunError(RuntimeError):
    """A scored run was asked for against a contract or a scorer that is not the published one.

    The seam exists so the execution pipeline can be driven end to end at a scenario the frozen
    document never held -- a dress rehearsal -- without buying a scored attempt. What it must
    never become is a way to produce a scored artefact against ground truth or a metric somebody
    supplied, so ``kind="scored"`` refuses both parameters outright rather than validating them.
    """


class UnauthorisedScoredRunError(RuntimeError):
    """A scored run was asked for without the capability a passing preflight mints.

    Separate from :class:`PredeclarationError` because they are different absences. One says the
    rule that reads a message was never declared; this one says nobody checked whether the run
    could honestly be taken at all.
    """


@dataclass(frozen=True, slots=True)
class Clock:
    """The two clocks an attempt needs, injected together so neither is hidden.

    ``monotonic`` measures the wall-clock ceiling and ``wall`` stamps the capture. They are
    separate because a capture wants a date and a ceiling wants a duration, and using one for
    both is how a clock change becomes a budget event.
    """

    monotonic: Any
    wall: Any = utc_now


def _budget(contract: Contract, clock: Clock) -> AttemptBudget:
    return AttemptBudget(ceilings=contract.ceilings, clock=clock.monotonic)


def drive_attempt(
    *,
    arm: ArmAdapter,
    identity: AttemptIdentity,
    contract: Contract,
    world: ScenarioWorld,
    clock: Clock,
) -> tuple[ReceiverEvidence, Mapping[str, Any], str, str, AttemptBudget, float]:
    """Run one arm at one scenario once, and observe how it ended.

    Returns the evidence, the arm's diagnostics, the driver's terminal status or
    ``PENDING_SCORE``, a note, the spent budget and the latency. It never raises for a bad
    answer: an arm that produced nothing returns empty evidence and is scored ``INVALID``.

    **It never raises for an unexpected failure either.** A surface that refused, a transport
    that broke, a receiver that threw something this module has no name for -- each ends *this
    attempt* as ``HARNESS_FAILURE`` with the exception recorded, and the run goes on to the next
    one. A benchmark that lost twenty-six attempts because the first one hit an unnamed error
    would have nothing to publish and no way to say what was missing.
    """
    scenario = contract.scenario(identity.scenario_id)
    budget = _budget(contract, clock)
    started = clock.monotonic()

    request = AttemptRequest(
        identity=identity,
        scenario=scenario_without_ground_truth(scenario),
        contract=contract,
        budget=budget,
        world=world,
    )

    status = "PENDING_SCORE"
    note = ""
    evidence = ReceiverEvidence(unreadable_sources=frozenset({"E1", "E2", "E3", "E4"}))
    diagnostics: Mapping[str, Any] = {}

    try:
        world.prepare(scenario)
        attempt = arm.run(request)
        evidence = attempt.evidence
        diagnostics = attempt.diagnostics
    except BudgetExhaustedError as exhausted:
        status, note = "BUDGET_EXHAUSTED", str(exhausted)
        evidence = _salvage(world, note)
    except ArmVoidError as void:
        status, note = "VOID", f"declared void cause: {void.cause}"
        evidence = _salvage(world, note)
    except HarnessFailureError as failure:
        status, note = "HARNESS_FAILURE", str(failure)
        evidence = _salvage(world, note)
    except Exception as unexpected:
        # An attempt that failed in a way nobody named is still one attempt. Letting it out of
        # this function would end the *run* -- every later arm and every later scenario would
        # never be driven, and a comparative result would be missing rows nobody could account
        # for. So it is recorded as what it is: HARNESS_FAILURE, which is a nonpass, is disclosed
        # by name with the exception on it, is never VOID and is never retried. Nothing is
        # softened by catching it; what changes is that the other attempts still happen.
        status = "HARNESS_FAILURE"
        note = f"{type(unexpected).__name__}: {unexpected}"
        evidence = _salvage(world, note)

    latency = clock.monotonic() - started
    return evidence, diagnostics, status, note, budget, latency


def _salvage(world: ScenarioWorld, note: str) -> ReceiverEvidence:
    """Read the receivers even when the attempt ended badly.

    An attempt that crossed a ceiling still did things to the world, and the capture is where
    those things are recorded. If the receivers cannot be read either, that is itself evidence:
    the sources are declared unreadable rather than assumed empty, because an empty receiver and
    an unreadable one are different facts and only one of them is a zero.
    """
    try:
        return world.collect()
    except Exception:  # a receiver that cannot be read is a fact about the run, not a crash
        return ReceiverEvidence(
            unreadable_sources=frozenset({"E1", "E2", "E3", "E4"}),
            contradictions=(f"the receivers could not be read after: {note}",),
        )


def score_attempt(
    directory: RunDirectory,
    *,
    identity: AttemptIdentity,
    run_id: str,
    fixtures: FixtureMap,
    classifier: OutboundClassifier,
    scorer: Scorer = FROZEN,
) -> str:
    """Score one captured attempt, blind, and write the verdict beside it.

    Reads the raw capture and projects a bundle from its ``evidence`` alone. The capture's
    ``diagnostics`` are arm-identifying by construction -- arm C's ablation log is in there --
    and are deliberately not an input to this function.
    """
    from scripts.sur1.replay import evidence_from_payload

    document = directory.read_attempt(identity.key)
    recorded = str(document["attempt"]["status"])
    if recorded in ("BUDGET_EXHAUSTED", "HARNESS_FAILURE"):
        write_driver_verdict(
            directory,
            identity=identity,
            outcome=recorded,
            note=str(document["attempt"]["note"]),
            scorer=scorer,
        )
        return recorded

    try:
        evidence = evidence_from_payload(document["evidence"])
        bundle = blind(
            evidence,
            run_id=run_id,
            identity=identity,
            fixtures=fixtures,
            classifier=classifier,
        )
    except EvidenceMalformedError as malformed:
        write_driver_verdict(
            directory,
            identity=identity,
            outcome="HARNESS_FAILURE",
            note=f"the evidence could not be placed: {malformed}",
            scorer=scorer,
        )
        return "HARNESS_FAILURE"

    verdict: ScenarioVerdict = scorer.score(bundle)
    write_verdict(directory, identity=identity, verdict=verdict)
    return verdict.outcome


def blind(
    evidence: ReceiverEvidence,
    *,
    run_id: str,
    identity: AttemptIdentity,
    fixtures: FixtureMap,
    classifier: OutboundClassifier,
) -> Any:
    """The one place a bundle is built, so there is one place to check what it carries."""
    from scripts.sur1.evidence import blind_bundle

    return blind_bundle(
        evidence,
        run_id=run_id,
        scenario_id=identity.scenario_id,
        arm_token=identity.arm_token,
        fixtures=fixtures,
        classifier=classifier,
    )


def _world_clock(world: object) -> dict[str, Any] | None:
    """Where in time this world installs, read off the world rather than taken as a parameter.

    Not a parameter on purpose. A recorded anchor that came in beside the world could name an
    instant the world was not actually installed at, and a capture saying the wrong thing about
    when a run happened is worse than one saying nothing. Read from the object that will do the
    installing, so the two cannot disagree. See ADR-0019.
    """
    clock = getattr(world, "clock", None)
    describes = getattr(clock, "describes", None)
    if describes is None:
        return None
    recorded: dict[str, Any] = dict(describes())
    return recorded


def _product_runtime(world: object) -> dict[str, Any] | None:
    """What the process that executes semantic jobs says it is configured to call.

    Read off the worker control for the same reason :func:`_world_clock` is read off the world:
    a value that arrived beside the run could name a configuration the product does not have.
    ``None`` is *nothing could be asked*, which is what a run against a stand-in records and
    what every run taken so far would have recorded. A scored run is refused for it by
    :func:`~scripts.sur1.preflight.product_model_identity` long before this is written.
    """
    ask = getattr(getattr(world, "worker", None), "runtime_identity", None)
    if not callable(ask):
        return None
    try:
        published = dict(ask())
    except Exception:
        return None
    return published or None


def drive(
    *,
    arms: Sequence[ArmAdapter],
    world: ScenarioWorld,
    clock: Clock,
    run_id: str,
    kind: str,
    command: Sequence[str],
    classifier: OutboundClassifier = UNDETERMINED,
    scenarios: Sequence[str] = (),
    root: Path = RUNS_ROOT,
    authorisation: ScoredAuthorisation | None = None,
    contract: Contract | None = None,
    scorer: Scorer | None = None,
) -> RunDirectory:
    """Drive every arm over every scenario, resuming whatever already finished.

    The frozen identities are asserted before an arm is constructed. A scored run refuses to
    start under the undetermined default, because the rule that decides ``asserts_change`` has
    to be declared before a comparative outcome exists rather than chosen once one does.

    **A scored run is driven under a capability or not at all.** ``kind="scored"`` requires a
    :class:`~scripts.sur1.authorisation.ScoredAuthorisation`, which only a passing scored
    preflight mints. The capability is claimed here against a fingerprint observed from the
    objects this call was actually handed -- this world, these arms, this rule, this run id,
    this root, these scenarios, and the frozen identities as they are on disk right now -- so a
    capability minted against the real bindings cannot drive stubs, and one minted before a
    manifest moved cannot drive after it. The claim is single-use; a resume runs its own
    preflight and mints its own.

    A development run takes no capability and is refused one. It produces no comparative number,
    and letting it consume an authorisation would be the one way a scored capability could be
    spent on something that is not a scored run.
    """
    if kind == SCORED and (contract is not None or scorer is not None):
        raise UnsubstitutableScoredRunError(
            "a scored SUR-1 run is driven against the frozen contract and scored by the "
            "published scorer; both are pinned by their own hashes and neither is a parameter "
            "of a scored run. A caller with its own contract or its own scorer is driving "
            "something that is not SUR-1, which is what kind='development' is for."
        )
    contract = contract if contract is not None else Contract.load()
    scorer = scorer if scorer is not None else FROZEN
    if kind == SCORED:
        if classifier is UNDETERMINED:
            raise PredeclarationError(
                "a scored run needs the rule by which asserts_change is set, declared in this "
                "session's predeclaration before the first scored attempt; the harness ships "
                "the undetermined default and will not invent one"
            )
        if not isinstance(authorisation, ScoredAuthorisation):
            raise UnauthorisedScoredRunError(
                "a scored SUR-1 run is driven under an authorisation minted by a passing "
                f"preflight; this call was handed {type(authorisation).__name__}. Run the "
                "preflight through scripts.sur1.run.execute, which is where one comes from."
            )
    elif authorisation is not None:
        raise UnauthorisedScoredRunError(
            f"a {kind!r} run takes no scored authorisation; one authorises a scored run and "
            "spending it here would consume it on something that is not one"
        )

    selected = tuple(scenarios) or contract.scenario_ids
    unknown = [scenario for scenario in selected if scenario not in contract.scenario_ids]
    if unknown:
        raise KeyError(f"not scenarios of {contract.identity.benchmark_id}: {unknown}")

    if authorisation is not None:
        authorisation.claim(
            observe(
                kind=kind,
                run_id=run_id,
                root=root,
                scenarios=selected,
                world=world,
                arms=arms,
                classifier=classifier,
            )
        )

    head, dirty = implementation()
    manifest = RunManifest(
        run_id=run_id,
        kind=kind,
        identity=contract.identity,
        model_configuration=contract.model_configuration,
        ceilings=contract.ceilings,
        read_tools=contract.read_tools,
        write_tools=contract.write_tools,
        command=tuple(command),
        started_at=clock.wall(),
        implementation_sha=head,
        working_tree_dirty=dirty,
        driver_version=DRIVER_VERSION,
        world_clock=_world_clock(world),
        product_runtime=_product_runtime(world),
    )
    directory, tokens = open_run(
        manifest,
        labels=[arm.label for arm in arms],
        root=root,
        authorisation=authorisation,
    )
    fixtures = FixtureMap.read(contract.document)

    for arm in arms:
        token = tokens[arm.label]
        for scenario_id in selected:
            _drive_scenario(
                arm=arm,
                token=token,
                scenario_id=scenario_id,
                contract=contract,
                world=world,
                clock=clock,
                directory=directory,
                manifest=manifest,
                fixtures=fixtures,
                classifier=classifier,
                scorer=scorer,
            )
    return directory


def _drive_scenario(
    *,
    arm: ArmAdapter,
    token: str,
    scenario_id: str,
    contract: Contract,
    world: ScenarioWorld,
    clock: Clock,
    directory: RunDirectory,
    manifest: RunManifest,
    fixtures: FixtureMap,
    classifier: OutboundClassifier,
    scorer: Scorer = FROZEN,
) -> None:
    """One arm at one scenario, with at most one retry and only for a void."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        identity = AttemptIdentity(
            run_id=manifest.run_id, arm_token=token, scenario_id=scenario_id, attempt=attempt
        )
        if identity.key not in directory.completed_attempts():
            _execute(
                arm=arm,
                identity=identity,
                contract=contract,
                world=world,
                clock=clock,
                directory=directory,
                manifest=manifest,
            )
        if identity.key in directory.scored_attempts():
            outcome = str(
                json.loads(directory.verdict_file(identity).read_text(encoding="utf-8"))["outcome"]
            )
        else:
            outcome = score_attempt(
                directory,
                identity=identity,
                run_id=manifest.run_id,
                fixtures=fixtures,
                classifier=classifier,
                scorer=scorer,
            )
        if outcome not in RETRYABLE:
            return
    return


def _execute(
    *,
    arm: ArmAdapter,
    identity: AttemptIdentity,
    contract: Contract,
    world: ScenarioWorld,
    clock: Clock,
    directory: RunDirectory,
    manifest: RunManifest,
) -> None:
    started_at = clock.wall()
    evidence, diagnostics, status, note, budget, latency = drive_attempt(
        arm=arm, identity=identity, contract=contract, world=world, clock=clock
    )
    write_attempt(
        directory,
        attempt=AttemptManifest(
            identity=identity,
            started_at=started_at,
            finished_at=clock.wall(),
            status=status,
            spend=budget.spend,
            latency_seconds=latency,
            evidence_ref=directory.attempt_file(identity).name,
            note=note,
        ),
        evidence=evidence,
        diagnostics=diagnostics,
        run=manifest,
    )


def join(directory: RunDirectory) -> dict[str, Any]:
    """The separate, later step: put an arm name beside a verdict that was written without one.

    Runs after every verdict exists, reads the token map for the first time on the result path,
    and writes ``result.json``. Latency and cost are joined here too, out of the attempt
    captures, because they are arm-identifying and never entered a bundle.
    """
    by_token = directory.read_arm_map()
    attempts = []
    for path in sorted(directory.verdicts.glob("*.json")):
        verdict = json.loads(path.read_text(encoding="utf-8"))
        capture = directory.read_attempt(path.stem)["attempt"]
        attempts.append(
            verdict
            | {
                "arm": by_token[str(verdict["arm_token"])],
                "latency_seconds": capture["latency_seconds"],
                "cost": capture["cost"],
            }
        )
    document = {
        "run": json.loads(directory.run_file.read_text(encoding="utf-8")),
        "attempts": attempts,
    }
    from scripts.sur1.capture import write_once

    write_once(directory.result_file, document)
    return document
