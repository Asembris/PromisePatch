"""Where a run's evidence lands, in what order, and what may never be written twice.

The contract's immutability sentence is the whole design of this module::

    A capture is written before anything may be repaired, is committed, and is never edited. A
    later diagnosis is a new document referencing the capture by filename and by the
    implementation SHA it names.

**Raw evidence is a different artefact from the verdict that judged it.** An attempt writes
``attempts/<key>.json`` -- the receivers' own rows, the arm's diagnostics, the spend and the
latency -- and then, separately, ``verdicts/<key>.json``. Keeping them apart is what stops a
re-score from rewriting what a receiver saw, and it is what makes "re-score without re-running"
possible at all: the expensive half is on disk and the cheap half is a pure function.

**Every write is a write-once.** :func:`write_once` refuses a path that exists. An attempt that
tried to overwrite its own capture would be the one place a bad result could quietly become a
better one, so it fails instead.

**The token map is a separate file the scorer never opens.** Blinding is not a promise about
where anybody looks; it is a fact about what the scoring path can reach. The scorer takes a
bundle carrying a token, and the only thing that can turn a token into an arm name lives here,
in a file whose name appears nowhere in the scorer's import surface.

**Resume is by attempt identity, not by filename convention.** :func:`completed_attempts` reads
the attempts directory and returns the keys that finished. The driver skips them. A run that
died after seven attempts resumes at the eighth and does not buy the first seven again.

**A resumed run must be the same run.** :func:`open_run` compares the manifest's identity fields
against the ones the run started with and refuses a mismatch, for the reason ``evals.store``
gives about its own header: a resumed run whose pinned documents changed in between would be two
experiments in one summary.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from scripts.sur1.authorisation import SCORED, ScoredAuthorisation
from scripts.sur1.evidence import ReceiverEvidence
from scripts.sur1.frozen import ROOT
from scripts.sur1.manifest import AttemptIdentity, AttemptManifest, RunManifest
from scripts.sur1.scoring import FROZEN, Scorer

RUNS_ROOT: Final = ROOT / "docs" / "benchmarks" / "runs"

RUN_FILE: Final = "run.json"
ARM_MAP_FILE: Final = "arm_map.json"
RESULT_FILE: Final = "result.json"
ATTEMPTS_DIR: Final = "attempts"
VERDICTS_DIR: Final = "verdicts"


class CaptureError(RuntimeError):
    """A capture would have been overwritten, or a run would have been silently continued."""


def write_once(path: Path, document: Any) -> Path:
    """Write a capture, or refuse because one is already there.

    The refusal is the point. Nothing in this benchmark has a legitimate reason to rewrite an
    attempt, and the one thing that would want to is a session that has seen an outcome.
    """
    if path.exists():
        raise CaptureError(f"{path} already exists; a capture is never edited")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def mint_tokens(labels: Sequence[str]) -> dict[str, str]:
    """One opaque token per arm, minted at run start and never derived from the label.

    Derivation would be worse than useless: three candidate labels and a published rule is a
    map anybody can invert. These are random, written once, and read back on resume so an
    attempt keeps its identity across a restart.
    """
    return {label: f"tok-{secrets.token_hex(8)}" for label in labels}


@dataclass(frozen=True, slots=True)
class RunDirectory:
    """One run's artefacts, and the only thing that knows where they are."""

    path: Path

    @property
    def run_file(self) -> Path:
        return self.path / RUN_FILE

    @property
    def arm_map_file(self) -> Path:
        return self.path / ARM_MAP_FILE

    @property
    def result_file(self) -> Path:
        return self.path / RESULT_FILE

    @property
    def attempts(self) -> Path:
        return self.path / ATTEMPTS_DIR

    @property
    def verdicts(self) -> Path:
        return self.path / VERDICTS_DIR

    def attempt_file(self, identity: AttemptIdentity) -> Path:
        return self.attempts / f"{identity.key}.json"

    def verdict_file(self, identity: AttemptIdentity) -> Path:
        return self.verdicts / f"{identity.key}.json"

    # ------------------------------------------------------------------- resume

    def completed_attempts(self) -> frozenset[str]:
        """Attempt keys that already have a raw capture. The driver skips exactly these."""
        if not self.attempts.is_dir():
            return frozenset()
        return frozenset(path.stem for path in self.attempts.glob("*.json"))

    def scored_attempts(self) -> frozenset[str]:
        """Attempt keys that already have a verdict.

        Separate from :meth:`completed_attempts` on purpose. A process that died between writing
        the evidence and writing the verdict left an attempt that must be re-scored and must not
        be re-driven: scoring is a pure function of a file, and driving costs money.
        """
        if not self.verdicts.is_dir():
            return frozenset()
        return frozenset(path.stem for path in self.verdicts.glob("*.json"))

    def read_attempt(self, key: str) -> dict[str, Any]:
        path = self.attempts / f"{key}.json"
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return document

    def read_arm_map(self) -> dict[str, str]:
        """Token to arm. Read by the join step, and by nothing on the scoring path."""
        document: dict[str, str] = json.loads(self.arm_map_file.read_text(encoding="utf-8"))
        return document


def open_run(
    manifest: RunManifest,
    *,
    labels: Sequence[str],
    root: Path = RUNS_ROOT,
    authorisation: ScoredAuthorisation | None = None,
) -> tuple[RunDirectory, dict[str, str]]:
    """Start a run, or continue one, refusing to continue a different experiment.

    Returns the directory and the arm-to-token map: minted on a first start, read back on a
    resume, so that an attempt identity survives a restart. The labels are passed in rather than
    read off the manifest, because a run manifest is written into every capture and an arm name
    in a capture is a leak waiting to be committed.

    **A scored layout is opened only under a capability.** This is the one function that creates
    ``run.json`` and the token map, so it is the narrowest place to stand between a caller and a
    directory of scored artefacts. A caller reaching past :func:`~scripts.sur1.driver.drive`
    straight to here still has to hold a :class:`~scripts.sur1.authorisation.ScoredAuthorisation`
    minted for this run id at this root, which only a passing scored preflight produces.
    """
    if manifest.kind == SCORED:
        if not isinstance(authorisation, ScoredAuthorisation):
            raise CaptureError(
                f"a scored run directory is opened only under a scored authorisation; "
                f"{manifest.run_id} was asked for with {type(authorisation).__name__}. A scored "
                "SUR-1 run is authorised by a passing preflight and by nothing else."
            )
        if not authorisation.authorises_run(run_id=manifest.run_id, kind=manifest.kind, root=root):
            raise CaptureError(
                f"this authorisation is not about {manifest.run_id} at {root}: it authorises "
                f"{authorisation.run_id}"
            )
    directory = RunDirectory(root / manifest.run_id)
    if not directory.run_file.exists():
        directory.path.mkdir(parents=True, exist_ok=True)
        write_once(directory.run_file, manifest.as_payload())
        tokens = mint_tokens(sorted(labels))
        write_once(directory.arm_map_file, {token: arm for arm, token in tokens.items()})
        return directory, tokens

    started: dict[str, Any] = json.loads(directory.run_file.read_text(encoding="utf-8"))
    mismatched = _identity_mismatch(started, manifest)
    if mismatched:
        raise CaptureError(
            f"run {manifest.run_id} was started against different identities and cannot be "
            f"continued: {'; '.join(mismatched)}"
        )
    by_token = directory.read_arm_map()
    return directory, {arm: token for token, arm in by_token.items()}


def _identity_mismatch(started: Mapping[str, Any], manifest: RunManifest) -> tuple[str, ...]:
    """Every field on which a resumed run would be a different experiment."""
    return tuple(
        f"{key}: started {started.get(key)!r}, now {value!r}"
        for key, value in manifest.identity_fields.items()
        if started.get(key) != value
    )


def write_attempt(
    directory: RunDirectory,
    *,
    attempt: AttemptManifest,
    evidence: ReceiverEvidence,
    diagnostics: Mapping[str, Any],
    run: RunManifest,
) -> Path:
    """The raw, immutable record of one attempt, written before anything judges it.

    It carries the run's pinned identities so a capture read on its own says what it was taken
    against, and it carries the arm's diagnostics -- arm C's ablation log among them -- which
    are audit material and never reach a bundle.
    """
    document = {
        "run": run.identity_fields | {"run_id": run.run_id, "kind": run.kind},
        "attempt": attempt.as_payload(),
        "evidence": evidence.as_payload(),
        "diagnostics": dict(diagnostics),
    }
    return write_once(directory.attempt_file(attempt.identity), document)


def write_verdict(directory: RunDirectory, *, identity: AttemptIdentity, verdict: Any) -> Path:
    """The scored output, separate from the evidence and written after it.

    Carries the token the scorer saw and never the arm. The join that turns one into the other
    is a later step against a file this path never opens.
    """
    document = {
        "scenario_id": verdict.scenario_id,
        "arm_token": verdict.arm_token,
        "scorer_version": verdict.scorer_version,
        "outcome": verdict.outcome,
        "retried": identity.retried,
        "primary": {
            "complete_allowed_recovery": verdict.complete_allowed_recovery,
            "recoverable_recovered": verdict.recoverable_recovered,
            "recoverable_denominator": verdict.recoverable_denominator,
            "appropriate_escalations": verdict.appropriate_escalations,
            "escalation_denominator": verdict.escalation_denominator,
        },
        "safety": dict(verdict.safety),
        "findings": [
            {
                "dimension": finding.dimension,
                "order": finding.order,
                "evidence": finding.evidence,
                "detail": finding.detail,
            }
            for finding in verdict.findings
        ],
        "notes": list(verdict.notes),
    }
    return write_once(directory.verdict_file(identity), document)


def write_driver_verdict(
    directory: RunDirectory,
    *,
    identity: AttemptIdentity,
    outcome: str,
    note: str,
    scorer: Scorer = FROZEN,
) -> Path:
    """A verdict the driver reached without the scorer, for the two outcomes it owns.

    ``BUDGET_EXHAUSTED`` and ``HARNESS_FAILURE`` are facts about an attempt the driver observed
    and are never inferred from evidence. They are written in the same shape as a scored verdict
    so the join reads one file format, with every metric left at zero and the reason recorded --
    never a pass, and never quietly a ``VOID``.
    """
    document = {
        "scenario_id": identity.scenario_id,
        "arm_token": identity.arm_token,
        "scorer_version": scorer.version,
        "outcome": outcome,
        "retried": identity.retried,
        "decided_by": "driver",
        "primary": {
            "complete_allowed_recovery": False,
            "recoverable_recovered": 0,
            "recoverable_denominator": 0,
            "appropriate_escalations": 0,
            "escalation_denominator": 0,
        },
        "safety": dict.fromkeys(scorer.safety_dimensions, 0),
        "findings": [],
        "notes": [note],
    }
    return write_once(directory.verdict_file(identity), document)
