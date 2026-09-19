"""What has to be true before a scored comparative attempt may be bought, checked one at a time.

A scored run of ``SUR-1`` is the headline whatever it says, it may be taken once, and the retry
policy permits no second opinion. So everything that would make the resulting number mean
something other than what it appears to mean is asked **before** an arm is constructed, in one
place, and any failure refuses the run.

Eleven checks, and each is a fact rather than a promise:

1. the three frozen identities recompute to their published values;
2. all three bindings say they are real, so a run cannot be driven by a double;
3. the model configuration is the contract's own, and names an explicit region;
4. every credential and address a scored run needs is configured;
5. every receiver answers, so no scenario is voided for an unreadable source afterwards;
6. the ``asserts_change`` rule is the declared one and hashes to its published identity;
7. every selected scenario has a world program that builds the world it declares;
8. the nine programs are the frozen nine, at their published hashes, and nothing on their
   preparation path can name a field that says what a correct answer is;
9. the output directory is new, or is a resumable run of the same experiment;
10. nothing on the scoring path can reach an arm's name;
11. nothing that fires a world event can name an arm, an answer or a scorer's reading.

**A preflight reads and never writes.** It opens clients, asks services whether they are ready
and recomputes hashes. It creates no run directory, mints no token, prepares no world and calls
no model -- invoking the model to find out whether the model can be invoked would spend exactly
the thing this exists to protect.

**Failing is the useful outcome.** :func:`require` raises with every failed check named, rather
than returning a boolean somebody has to remember to read.

**Passing is a capability, not a note.** :func:`authorise` turns a passing scored report into a
:class:`~scripts.sur1.authorisation.ScoredAuthorisation` bound to the exact inputs that were
checked, and the driver and the capture layer ask for that object. This is the only place one is
minted, so "the preflight ran" stopped being something a caller could be trusted to have done.

**Nothing here has minted a capability against real bindings, and no run has been taken.**
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from scripts.sur1 import predeclaration
from scripts.sur1.authorisation import (
    AuthorisationError,
    RunFingerprint,
    ScoredAuthorisation,
    _grant,
    digest_of,
)
from scripts.sur1.bindings import is_real
from scripts.sur1.bindings.config import BindingConfig
from scripts.sur1.bindings.setup import unprogrammed
from scripts.sur1.capture import RUNS_ROOT, RunDirectory
from scripts.sur1.evidence import UNDETERMINED, OutboundClassifier
from scripts.sur1.frozen import ARMS, Contract, FrozenIdentityError

SCORED: Final = "scored"

REQUIRED_CHECKS: Final = (
    "frozen_identities",
    "real_bindings",
    "model_identity",
    "configuration",
    "receivers",
    "classifier_identity",
    "world_programs",
    "world_program_freeze",
    "output_directory",
    "blinding",
    "event_blinding",
)
"""Every question a scored run must have been asked, named so a partial report cannot mint.

:func:`authorise` refuses a report that does not carry all of these, which is what stops a
capability being minted from a hand-built report holding one passing check. It is a constant
rather than a count because a report naming eleven checks, one of which is new and two of which
are missing, would pass a count. :func:`preflight` is asserted to produce exactly these names,
so this cannot drift away from what is actually asked.
"""

FORBIDDEN_ON_THE_SCORING_PATH: Final = (
    "promisepatch",
    "promise_graph",
    "scripts.sur1",
)
"""Packages the scorer may not import, because each of them is one arm or the driver of one."""

ARM_FIELD_NAMES: Final = frozenset({"arm", "arm_label", "label", "system", "adapter"})
"""Field names on the scorer's own bundle that would carry an arm's identity if they existed."""

FORBIDDEN_SCENARIO_FIELDS: Final = frozenset(
    {"ground_truth", "the_point", "expected_report", "ablation_target"}
)
"""Frozen scenario fields a world program may not read, because each says what an answer is.

``ground_truth`` and ``the_point`` state the expected disposition outright. ``expected_report``
is one scenario's expected run report and ``ablation_target`` names the check a scenario exists
to remove, both of which a program could shape a world around. They stay in the manifest --
removing them would edit a frozen document -- and nothing on the preparation path may name one.
"""


class PreflightRefusedError(RuntimeError):
    """A scored run was asked for and at least one precondition is not true."""


@dataclass(frozen=True, slots=True)
class Check:
    """One precondition, its answer, and the sentence that says why."""

    name: str
    passed: bool
    detail: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Every check, in the order they were asked. Written into a run's own record."""

    kind: str
    checks: tuple[Check, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if not check.passed)

    def as_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "passed": self.passed,
            "checks": [check.as_payload() for check in self.checks],
        }


def frozen_identities() -> Check:
    try:
        identity = Contract.load().identity
    except FrozenIdentityError as moved:
        return Check("frozen_identities", False, str(moved))
    return Check(
        "frozen_identities",
        True,
        f"manifest {identity.manifest_sha[:8]}, prompt {identity.baseline_prompt_sha[:8]}, "
        f"scorer {identity.scorer_version}",
    )


def real_bindings(*, model: object, world: object, surface: object) -> Check:
    """Every binding declares itself real. A double is refused by value, not by type.

    :func:`~scripts.sur1.bindings.is_real` reads the declared kind rather than checking a
    protocol, because a runtime-checkable protocol only asks whether the members exist and a
    stand-in with the right attribute names satisfies it.
    """
    stand_ins = [
        name
        for name, binding in (("model", model), ("world", world), ("surface", surface))
        if not is_real(binding)
    ]
    if stand_ins:
        return Check(
            "real_bindings",
            False,
            f"a scored run cannot be driven by a stand-in: {', '.join(stand_ins)}",
        )
    return Check("real_bindings", True, "model, world and worker surface are real bindings")


def model_identity(*, model: object, contract: Contract) -> Check:
    """The model a run would call is the one the contract froze, in a named region."""
    identity = getattr(model, "identity", None)
    if not callable(identity):
        return Check("model_identity", False, "this model binding names no identity")
    declared: Mapping[str, Any] = identity()
    configured = contract.model_configuration
    differences = [
        f"{field}: contract {expected!r}, binding {declared.get(field)!r}"
        for field, expected in (
            ("provider", configured.provider),
            ("model_id", configured.model_id),
            ("api", configured.api),
            ("temperature", configured.temperature),
        )
        if declared.get(field) != expected
    ]
    if differences:
        return Check("model_identity", False, "; ".join(differences))
    if not declared.get("region"):
        return Check("model_identity", False, "no region is named, so where it ran is unrecorded")
    return Check(
        "model_identity",
        True,
        f"{declared['model_id']} at temperature {declared['temperature']} in {declared['region']}",
    )


def configuration(config: BindingConfig) -> Check:
    missing = config.missing()
    if missing:
        return Check("configuration", False, f"not configured: {', '.join(missing)}")
    return Check("configuration", True, "every address and credential a scored run needs is set")


def receivers(*, world: object, surface: object) -> Check:
    """Ask every source whether it answers. Reads only, and the answers are recorded."""
    probes = []
    for binding in (world, surface):
        every = getattr(binding, "probes", None)
        if callable(every):
            probes.extend(every())
            continue
        one = getattr(binding, "probe", None)
        if callable(one):
            probes.append(one())
    unreachable = [f"{probe.source}: {probe.detail}" for probe in probes if not probe.reachable]
    if unreachable:
        return Check("receivers", False, "; ".join(unreachable))
    return Check(
        "receivers", True, f"reachable: {', '.join(sorted(probe.source for probe in probes))}"
    )


def classifier_identity(classifier: OutboundClassifier) -> Check:
    """The ``asserts_change`` rule is declared, and is the one whose identity was published."""
    if classifier is UNDETERMINED:
        return Check(
            "classifier_identity",
            False,
            "the harness's undetermined default decides nothing; a scored run needs the rule "
            "declared in the execution predeclaration",
        )
    if classifier is not predeclaration.asserts_change:
        return Check(
            "classifier_identity",
            False,
            f"this run would use {getattr(classifier, '__qualname__', classifier)!r}, which is "
            "not the declared rule",
        )
    recomputed = predeclaration.identity_sha()
    if recomputed != predeclaration.PREDECLARATION_SHA:
        return Check(
            "classifier_identity",
            False,
            f"the declared rules have moved: published {predeclaration.PREDECLARATION_SHA}, "
            f"recomputed {recomputed}",
        )
    return Check(
        "classifier_identity",
        True,
        f"{predeclaration.ASSERTS_CHANGE_RULE} at {recomputed[:8]}",
    )


def world_programs(scenario_ids: Sequence[str]) -> Check:
    """Every selected scenario has a program, and every program builds the world it declares.

    Building it is the check. A program that names a version the fixture does not have, or
    stipulates a task state the fixture contradicts, raises while it is projected -- and it has
    to raise here, before an attempt is bought, rather than inside the preparation of the third
    arm's second scenario.
    """
    missing = unprogrammed(scenario_ids)
    if missing:
        return Check(
            "world_programs",
            False,
            f"no world program for {', '.join(missing)}; their stipulated facts are prose in the "
            "frozen contract and nobody has authored them into world steps",
        )
    from scripts.sur1.bindings.setup import program_for
    from scripts.sur1.bindings.worldsnapshot import digest_of

    unprepared = []
    for scenario_id in scenario_ids:
        try:
            digest_of(program_for(scenario_id))
        except Exception as failure:  # a program that cannot build a world prepares nothing
            unprepared.append(f"{scenario_id}: {type(failure).__name__}: {failure}")
    if unprepared:
        return Check("world_programs", False, "; ".join(unprepared))
    return Check("world_programs", True, f"{len(scenario_ids)} scenarios can be prepared")


def world_program_freeze(contract: Contract | None) -> Check:
    """The nine programs are the frozen nine, and nothing on their path can read an answer.

    Four facts in one check because they fail together and are useless apart: a hash that
    matches a declaration listing eight scenarios says nothing, and nine matching hashes
    computed by code that had started branching on the expected disposition say less.
    """
    if contract is None:
        return Check("world_program_freeze", False, "the frozen contract did not load")
    from scripts.sur1.bindings.declaration import differences
    from scripts.sur1.bindings.programs import programs

    try:
        built = programs()
    except Exception as failure:
        return Check("world_program_freeze", False, f"{type(failure).__name__}: {failure}")

    expected = tuple(contract.scenario_ids)
    if tuple(sorted(built)) != tuple(sorted(expected)):
        return Check(
            "world_program_freeze",
            False,
            f"the program set is {sorted(built)} and the contract's scenarios are "
            f"{sorted(expected)}",
        )

    reachable = ground_truth_reachable()
    if reachable:
        return Check(
            "world_program_freeze",
            False,
            f"a world program could read what a correct answer is: {'; '.join(reachable)}",
        )

    moved = differences()
    if moved:
        return Check("world_program_freeze", False, "; ".join(moved))
    return Check(
        "world_program_freeze",
        True,
        f"{len(built)} programs frozen at the published set and world digests",
    )


EVENT_MODULES: Final = ("events", "worldsink")
"""The modules that decide when a declared world event fires and what it does.

Named here rather than inferred, because the whole value of the check below is that adding a
module to the firing path and forgetting to list it is itself visible in a diff.
"""

SCORING_MODULE: Final = "scripts.score_safe_useful_recovery"
"""What event code may never import. A trigger that could read a reading is not a trigger."""


def event_blinding() -> Check:
    """Nothing that fires a world event can name an arm, an answer or a scorer's reading.

    The same argument :func:`blinding` makes about the scoring path, made about the firing path,
    and for a sharper reason: a world whose events fired differently depending on which arm was
    driving would make every later number a comparison between three different worlds, and the
    failure would be invisible in all of them.

    Three structural facts. What a trigger is allowed to read carries no field an arm label
    could travel in; no module on the firing path names an arm, an expected disposition or a
    scorer's own vocabulary as code; and none of them can import the scorer at all.
    """
    from scripts.sur1.bindings.events import Observation

    leaking = sorted(set(Observation.__dataclass_fields__) & ARM_FIELD_NAMES)
    if leaking:
        return Check("event_blinding", False, f"a trigger's observation carries {leaking}")

    forbidden = FORBIDDEN_SCENARIO_FIELDS | ARM_FIELD_NAMES | frozenset(ARMS)
    found: list[str] = []
    for path in _event_sources():
        for name in sorted(_names_in(path, forbidden)):
            found.append(f"{path.name} names {name!r}")
        imported = _imports_of(path)
        if any(
            name == SCORING_MODULE or name.startswith(f"{SCORING_MODULE}.") for name in imported
        ):
            found.append(f"{path.name} imports the scorer")
    if found:
        return Check("event_blinding", False, "; ".join(found))
    return Check(
        "event_blinding",
        True,
        f"{len(EVENT_MODULES)} firing modules name no arm, no answer and no reading",
    )


def _event_sources() -> tuple[Path, ...]:
    """The files the firing path is made of, resolved from the modules themselves."""
    from scripts.sur1.bindings import events as events_module
    from scripts.sur1.bindings import worldsink as worldsink_module

    by_name = {"events": events_module, "worldsink": worldsink_module}
    return tuple(Path(by_name[name].__file__ or "") for name in EVENT_MODULES)


def ground_truth_reachable() -> tuple[str, ...]:
    """Whether any module on the world-program path can name what a correct answer is.

    Read from the syntax rather than from behaviour, the way :func:`blinding` reads the
    scorer's imports. A program that branched on the expected disposition would produce a world
    built towards its own answer, and the failure would be invisible in every number afterwards
    -- so the guard is the one thing here that must not depend on a program choosing to be
    honest at runtime.
    """
    from scripts.sur1.bindings import declaration as declaration_module

    found: list[str] = []
    for module in declaration_module.IMPLEMENTATION_MODULES:
        path = Path(module.__file__ or "")
        for name in sorted(_forbidden_names_in(path)):
            found.append(f"{path.name} names {name!r}")
    return tuple(found)


def _forbidden_names_in(path: Path) -> set[str]:
    """Every forbidden field name this file mentions, as an attribute, a key or a literal."""
    return _names_in(path, FORBIDDEN_SCENARIO_FIELDS)


def _names_in(path: Path, forbidden: frozenset[str]) -> set[str]:
    """Which of these names this file uses as code: a literal, an attribute or a name.

    Exact equality, and never a substring of prose. A module that explains in its docstring why
    a trigger must not consult an arm is doing the right thing; one with ``PROMISEPATCH`` in an
    expression is not, and only the second is a name in the syntax.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found |= {name for name in forbidden if name == node.value}
        elif isinstance(node, ast.Attribute) and node.attr in forbidden:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in forbidden:
            found.add(node.id)
    return found


def output_directory(run_id: str, *, root: Path = RUNS_ROOT, contract: Contract | None) -> Check:
    """A new run, or a resumable one that is the same experiment. Never a third thing.

    A directory holding a run started against different frozen identities is refused here for the
    same reason :func:`~scripts.sur1.capture.open_run` refuses it later: two contracts in one
    summary is two experiments.
    """
    directory = RunDirectory(root / run_id)
    if not directory.path.exists():
        return Check("output_directory", True, f"{directory.path} is new")
    if not directory.run_file.exists():
        return Check(
            "output_directory",
            False,
            f"{directory.path} exists and holds no run manifest, so it is neither new nor "
            "resumable",
        )
    started = json.loads(directory.run_file.read_text(encoding="utf-8"))
    if contract is not None and started.get("manifest_sha") != contract.identity.manifest_sha:
        return Check(
            "output_directory",
            False,
            f"{run_id} was started against manifest {started.get('manifest_sha')!r} and this "
            f"run pins {contract.identity.manifest_sha!r}",
        )
    if not directory.arm_map_file.exists():
        return Check("output_directory", False, f"{run_id} has no token map and cannot be resumed")
    completed = len(directory.completed_attempts())
    return Check("output_directory", True, f"{run_id} resumes with {completed} attempts captured")


def blinding() -> Check:
    """Nothing on the scoring path can reach an arm's name.

    Two structural facts rather than a review. The scorer's bundle has no field an arm label
    could travel in -- ``arm_token`` is opaque and is minted per run -- and the scorer's own
    import surface is parsed, so a module that started importing an arm fails here rather than
    being trusted not to.
    """
    from scripts.score_safe_useful_recovery import EvidenceBundle

    fields = set(EvidenceBundle.__dataclass_fields__)
    leaking = sorted(fields & ARM_FIELD_NAMES)
    if leaking:
        return Check("blinding", False, f"the scorer's bundle carries {leaking}")

    source = Path(__file__).resolve().parent.parent / "score_safe_useful_recovery.py"
    imported = _imports_of(source)
    forbidden = sorted(
        name
        for name in imported
        if any(
            name == banned or name.startswith(f"{banned}.")
            for banned in FORBIDDEN_ON_THE_SCORING_PATH
        )
    )
    if forbidden:
        return Check("blinding", False, f"the scorer imports {forbidden}")

    text = source.read_text(encoding="utf-8")
    named = sorted(arm for arm in ARMS if arm in text)
    if named:
        return Check("blinding", False, f"the scorer names {named}")
    return Check("blinding", True, "no arm name is reachable from a bundle or from the scorer")


def _imports_of(path: Path) -> tuple[str, ...]:
    """Every module one file imports, read from its syntax rather than from its behaviour."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return tuple(sorted(set(found)))


def preflight(
    *,
    kind: str,
    run_id: str,
    model: object,
    world: object,
    surface: object,
    config: BindingConfig,
    classifier: OutboundClassifier = UNDETERMINED,
    scenarios: Sequence[str] = (),
    root: Path = RUNS_ROOT,
) -> PreflightReport:
    """Ask every precondition once and report all the answers, failures included.

    Deliberately not short-circuiting. A caller fixing a run wants every reason it was refused,
    not the first one, and a report that stopped at the first failure would be found out one
    correction at a time.
    """
    identities = frozen_identities()
    contract = Contract.load() if identities.passed else None
    selected = tuple(scenarios) or (contract.scenario_ids if contract is not None else ())

    checks = [
        identities,
        real_bindings(model=model, world=world, surface=surface),
        (
            model_identity(model=model, contract=contract)
            if contract is not None
            else Check("model_identity", False, "the frozen contract did not load")
        ),
        configuration(config),
        receivers(world=world, surface=surface),
        classifier_identity(classifier),
        world_programs(selected),
        world_program_freeze(contract),
        output_directory(run_id, root=root, contract=contract),
        blinding(),
        event_blinding(),
    ]
    return PreflightReport(kind=kind, checks=tuple(checks))


def require(report: PreflightReport) -> PreflightReport:
    """Refuse a scored run that failed any check, naming every one of them.

    A development run is reported and permitted: it produces no comparative number, it voids the
    scenarios whose evidence it could not read, and refusing it would make the harness unusable
    during the work that prepares a scored one.
    """
    if report.kind != SCORED or report.passed:
        return report
    raise PreflightRefusedError(
        "a scored SUR-1 run was refused:\n"
        + "\n".join(f"  - {check.name}: {check.detail}" for check in report.failures)
    )


def authorise(report: PreflightReport, fingerprint: RunFingerprint) -> ScoredAuthorisation:
    """Mint the capability a scored run is driven under. The only way one comes into existence.

    Three refusals, and each closes a different way of arriving here without having asked the
    questions. The report has to *be* a :class:`PreflightReport` rather than an object shaped
    like one. It has to name every check in :data:`REQUIRED_CHECKS`, so a report carrying a
    single passing check cannot mint. And every check it names has to have passed, which is
    :func:`require`'s rule restated as a precondition on authority rather than on proceeding.

    The fingerprint is the caller's observation of the run it is about to drive, and the
    capability binds it. Nothing here re-observes it: the recomputation that matters happens in
    :func:`~scripts.sur1.driver.drive`, against the objects the driver was actually handed, which
    is the only place where a substitution between the preflight and the run would show up.
    """
    if not isinstance(report, PreflightReport):
        raise AuthorisationError(
            f"a scored authorisation is minted from a preflight report, not from "
            f"{type(report).__name__}"
        )
    if report.kind != SCORED or fingerprint.kind != SCORED:
        raise AuthorisationError(
            f"only a scored preflight authorises a scored run: report {report.kind!r}, "
            f"fingerprint {fingerprint.kind!r}"
        )
    missing = tuple(name for name in REQUIRED_CHECKS if name not in {c.name for c in report.checks})
    if missing:
        raise AuthorisationError(
            f"this report did not ask every question a scored run is gated on: {list(missing)}"
        )
    if not report.passed:
        raise PreflightRefusedError(
            "a scored SUR-1 run cannot be authorised:\n"
            + "\n".join(f"  - {check.name}: {check.detail}" for check in report.failures)
        )
    return _grant(fingerprint, digest_of(report.as_payload()))


__all__ = [
    "EVENT_MODULES",
    "FORBIDDEN_SCENARIO_FIELDS",
    "REQUIRED_CHECKS",
    "SCORED",
    "Check",
    "PreflightRefusedError",
    "PreflightReport",
    "authorise",
    "blinding",
    "classifier_identity",
    "configuration",
    "event_blinding",
    "frozen_identities",
    "ground_truth_reachable",
    "model_identity",
    "output_directory",
    "preflight",
    "real_bindings",
    "receivers",
    "require",
    "world_program_freeze",
    "world_programs",
]
