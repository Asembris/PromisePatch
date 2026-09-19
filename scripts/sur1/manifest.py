"""The run manifest: one record shape that three arms and nine scenarios are written into.

A comparative benchmark is only reproducible if every attempt says, in one vocabulary, what it
was an attempt at. Three arms with three record shapes would be three experiments joined by a
filename, and the first thing anybody would ask of the published number -- *which manifest, which
prompt, which model, which ceiling, which attempt* -- would be answerable for one of them.

So there is one :class:`RunManifest` per run and one :class:`AttemptManifest` per attempt, and
between them they hold everything the frozen result schema names.

**An attempt is identified, not described.** :class:`AttemptIdentity` is the resume key: run,
arm token, scenario, attempt index. It is a value, it is stable across a restart because the
token map is written once and read back, and it is what makes "skip what already finished"
a lookup rather than a guess about which file meant what.

**Latency and cost live here and never in the bundle.** Both are arm-identifying by nature, so
the contract has the driver collect them and join them after every verdict is written. Keeping
them on the attempt manifest -- which the scorer never sees -- is how that separation is
structural rather than remembered.

**The arm name lives here too, and the scorer never opens this file.** The manifest carries the
opaque ``arm_token``; the token-to-arm map is a separate artefact written once at run start.
"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from scripts.sur1 import DRIVER_VERSION
from scripts.sur1.frozen import Ceilings, FrozenIdentity, ModelConfiguration

ROOT: Final = Path(__file__).resolve().parent.parent.parent

TERMINAL_STATUSES: Final = (
    "SAFE_AND_COMPLETE",
    "SAFE_AND_INCOMPLETE",
    "DISQUALIFIED",
    "BUDGET_EXHAUSTED",
    "INVALID",
    "VOID",
    "HARNESS_FAILURE",
)
"""The frozen outcome vocabulary. The driver owns two of them and the scorer owns the rest."""

DRIVER_DECIDED: Final = frozenset({"BUDGET_EXHAUSTED", "HARNESS_FAILURE"})
"""Facts about an attempt the driver observed, never inferred from evidence by the scorer."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def implementation() -> tuple[str, bool]:
    """The commit this ran against, and whether the tree it ran from was dirty.

    A dirty tree is recorded rather than refused, exactly as the effect-set runner records it:
    refusing would make the harness unusable during the work that builds it, and hiding it would
    let a capture name a commit whose content was not what ran.
    """
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True
    return head, bool(status)


def environment() -> dict[str, Any]:
    """What ran it, and whether anything that could spend money was configured.

    Names and booleans only. A capture is committed, so it holds no value of any variable it
    reports on.
    """
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "model_provider_configured": bool(os.environ.get("PP_LLM_PROVIDER")),
        "aws_credentials_configured": any(
            os.environ.get(name) for name in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID")
        ),
    }


@dataclass(frozen=True, slots=True)
class AttemptIdentity:
    """What makes one attempt the same attempt across a restart.

    The attempt index is 1 for the first attempt and 2 for the single permitted retry. There is
    no third value, because the retry policy permits no third attempt.
    """

    run_id: str
    arm_token: str
    scenario_id: str
    attempt: int

    def __post_init__(self) -> None:
        if self.attempt not in (1, 2):
            raise ValueError(
                f"attempt {self.attempt} does not exist: the retry policy permits one retry, "
                "so an attempt is 1 or 2"
            )

    @property
    def key(self) -> str:
        """The filename-safe identity. Stable, so resume is a lookup and not a guess."""
        return f"{self.arm_token}-{self.scenario_id}-a{self.attempt}"

    @property
    def retried(self) -> bool:
        return self.attempt == 2

    def as_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "arm_token": self.arm_token,
            "scenario_id": self.scenario_id,
            "attempt": self.attempt,
            "retried": self.retried,
        }


@dataclass(frozen=True, slots=True)
class Spend:
    """What one attempt cost, in the four units the result schema names.

    ``estimated_usd`` is ``None`` for a model with no verified price, which the contract
    requires be recorded as unavailable and never as zero.
    """

    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_usd: Decimal | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_usd": (
                "unavailable" if self.estimated_usd is None else str(self.estimated_usd)
            ),
        }


@dataclass(frozen=True, slots=True)
class RunManifest:
    """One comparative run: what it was taken against, when, and by what.

    Written once at run start and read back on resume. Every field the frozen ``result_schema``
    names for a run is here, and nothing that identifies an arm is.
    """

    run_id: str
    kind: str
    """``scored`` or ``development``. A development run is not a comparative result."""

    identity: FrozenIdentity
    model_configuration: ModelConfiguration
    ceilings: Ceilings
    read_tools: tuple[str, ...]
    write_tools: tuple[str, ...]
    command: tuple[str, ...]
    started_at: datetime
    implementation_sha: str
    working_tree_dirty: bool
    driver_version: str = DRIVER_VERSION
    finished_at: datetime | None = None
    environment: dict[str, Any] = field(default_factory=environment)
    world_clock: dict[str, Any] | None = None
    """Where in time this invocation installed its worlds, and which rule chose it.

    Provenance rather than identity, which is why it is not in :attr:`identity_fields`. The
    identity of a starting world is its digest, and a digest is rendered as offsets from the
    anchor and is therefore invariant under it -- two invocations at two anchors that publish the
    same digests started from the same worlds. What an absolute instant answers is *which day was
    this attempt driven on*, and a run resumed on a later day should say so rather than leave it
    to be assumed. See ADR-0019.
    """

    def __post_init__(self) -> None:
        if self.kind not in ("scored", "development"):
            raise ValueError(f"a run is scored or development, not {self.kind!r}")

    def as_payload(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.identity.benchmark_id,
            "manifest_version": self.identity.manifest_version,
            "manifest_sha": self.identity.manifest_sha,
            "baseline_prompt_sha": self.identity.baseline_prompt_sha,
            "scorer_version": self.identity.scorer_version,
            "driver_version": self.driver_version,
            "implementation_sha": self.implementation_sha,
            "working_tree_dirty": self.working_tree_dirty,
            "run_id": self.run_id,
            "kind": self.kind,
            "command": list(self.command),
            "started_at": self.started_at.isoformat(),
            "finished_at": None if self.finished_at is None else self.finished_at.isoformat(),
            "model_configuration": self.model_configuration.as_payload(),
            "budgets": self.ceilings.as_payload(),
            "tool_surface": {"reads": list(self.read_tools), "writes": list(self.write_tools)},
            "environment": dict(self.environment),
            "world_clock": None if self.world_clock is None else dict(self.world_clock),
        }

    @property
    def identity_fields(self) -> dict[str, Any]:
        """What must match for a later invocation to be a continuation of this run.

        Borrowed wholesale from ``evals.store``'s rule, for the reason that module gives: a
        resumed run whose pinned documents had changed in between would be two experiments in
        one summary, and the identity check is the only thing standing between that and a number
        nobody could interpret.
        """
        return {
            "benchmark_id": self.identity.benchmark_id,
            "manifest_sha": self.identity.manifest_sha,
            "baseline_prompt_sha": self.identity.baseline_prompt_sha,
            "scorer_version": self.identity.scorer_version,
            "driver_version": self.driver_version,
            "kind": self.kind,
            "model_configuration": self.model_configuration.as_payload(),
            "budgets": self.ceilings.as_payload(),
        }


@dataclass(frozen=True, slots=True)
class AttemptManifest:
    """One attempt at one scenario by one arm, with everything but the verdict.

    Written before the verdict exists and never edited afterwards. The verdict is a separate
    artefact, so the raw record of what a receiver saw cannot be revised by what it was later
    judged to mean.
    """

    identity: AttemptIdentity
    started_at: datetime
    finished_at: datetime
    status: str
    """The driver's terminal status, or ``None``-equivalent ``PENDING_SCORE`` until scored."""

    spend: Spend
    latency_seconds: float
    evidence_ref: str
    """The filename of the raw evidence this attempt produced."""

    note: str = ""
    """Why the driver ended the attempt where it did. Never a metric, never an excuse."""

    def __post_init__(self) -> None:
        if self.status not in (*TERMINAL_STATUSES, "PENDING_SCORE"):
            raise ValueError(f"{self.status!r} is not in the frozen outcome vocabulary")

    def as_payload(self) -> dict[str, Any]:
        return {
            **self.identity.as_payload(),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "status": self.status,
            "latency_seconds": self.latency_seconds,
            "cost": self.spend.as_payload(),
            "evidence_ref": self.evidence_ref,
            "note": self.note,
        }
