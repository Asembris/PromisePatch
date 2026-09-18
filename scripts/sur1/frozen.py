"""The frozen identities ``SUR-1`` refuses to run without, and a typed read of the contract.

Three documents decide what this benchmark is, and each of them can be edited by a text editor:
the manifest that holds the nine scenarios and their ground truth, the baseline agent's operating
instructions, and the scorer that turns evidence into a verdict. A comparative run taken against
any of them after a quiet edit is not the benchmark whose identity was published, and nothing in
the resulting number would say so.

So this module is the gate, and it is a gate rather than a warning. :func:`assert_frozen` is
called by the driver before it constructs an arm, before it reads a scenario and before it opens
a transport. A mismatch raises :class:`FrozenIdentityError` and the run does not start.

**What is pinned, and how.** The manifest by a canonical SHA-256 over its parsed document -- so
reindenting the file keeps the identity and changing one ground-truth entry loses it. The prompt
by a SHA-256 over its newline-normalised bytes -- so a checkout on a machine with different line
endings computes the published value and a single changed word does not. The scorer by the two
constants it publishes about itself: its own version, and the manifest SHA it asserts on every
verdict. A scorer pinned to a different contract than the driver drives is two experiments.

**Nothing here is a default.** Every ceiling, every scenario identifier, every tool name and the
model configuration are read out of the frozen document rather than restated. A harness that
carried its own copy of a budget would eventually be the copy that ran, and the contract would
be a description of it rather than a constraint on it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parent.parent.parent

MANIFEST_PATH: Final = ROOT / "docs" / "benchmarks" / "safe-useful-recovery.v1.json"
PROMPT_PATH: Final = ROOT / "docs" / "benchmarks" / "baseline-agent-prompt.v1.md"

BENCHMARK_ID: Final = "SUR-1"
FROZEN_VERSION: Final = "1.0.0"

PUBLISHED_MANIFEST_SHA: Final = "5718340fbd19aa8ba1aedc2327c07a934e22b773271e996f13f0e8d87e70e84c"
PUBLISHED_PROMPT_SHA: Final = "772ba46025620a1aea4742fac3971c5906ec3252036d07725434e0a89ce47cb1"
"""Both published in ``docs/safe-useful-recovery-benchmark.md`` before any arm was driven."""

EXPECTED_SCORER_VERSION: Final = "1.0.0"
"""The scorer this harness was built against.

A bumped metric definition has to be seen rather than inherited, so the driver refuses instead
of quietly scoring a comparative run against a rule that changed after the contract froze.
"""

ARMS: Final = ("BASELINE", "PROMISEPATCH", "ABLATION")


class FrozenIdentityError(RuntimeError):
    """A document this benchmark is made of is not the one whose identity was published."""


def manifest_sha(document: Any) -> str:
    """The manifest's canonical identity, computed exactly as the verifier computes it."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prompt_sha(text: str) -> str:
    """The prompt's identity, computed exactly as the verifier computes it."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FrozenIdentity:
    """What the three pinned documents actually were, recorded in every capture."""

    benchmark_id: str
    manifest_version: str
    manifest_sha: str
    baseline_prompt_sha: str
    scorer_version: str

    def as_payload(self) -> dict[str, str]:
        return {
            "benchmark_id": self.benchmark_id,
            "manifest_version": self.manifest_version,
            "manifest_sha": self.manifest_sha,
            "baseline_prompt_sha": self.baseline_prompt_sha,
            "scorer_version": self.scorer_version,
        }


def _scorer_identity() -> tuple[str, str]:
    """The scorer's own two constants, read from the module rather than described.

    Imported inside the function on purpose. The scorer's blinding claim is asserted by parsing
    its import surface, and nothing is gained by making it a module-level dependency of the
    frozen reader, which is useful in contexts that have not decided to score anything yet.
    """
    from scripts.score_safe_useful_recovery import PUBLISHED_MANIFEST_SHA as SCORER_PINS
    from scripts.score_safe_useful_recovery import SCORER_VERSION

    return SCORER_VERSION, SCORER_PINS


def assert_frozen() -> FrozenIdentity:
    """Recompute all three identities, or refuse to let a run start.

    Called before an arm is constructed, not after a result exists. Everything this benchmark
    could be accused of -- edited ground truth, a rewritten baseline, a softened metric -- is a
    quiet edit away, and the only defence that works is refusing to execute against one.
    """
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    found_manifest = manifest_sha(document)
    if found_manifest != PUBLISHED_MANIFEST_SHA:
        raise FrozenIdentityError(
            f"the frozen contract has moved: published {PUBLISHED_MANIFEST_SHA}, "
            f"recomputed {found_manifest}"
        )
    if document["benchmark_id"] != BENCHMARK_ID or document["version"] != FROZEN_VERSION:
        raise FrozenIdentityError(
            f"{MANIFEST_PATH} is not {BENCHMARK_ID} v{FROZEN_VERSION}: it says "
            f"{document['benchmark_id']} v{document['version']}"
        )

    found_prompt = prompt_sha(PROMPT_PATH.read_text(encoding="utf-8"))
    if found_prompt != PUBLISHED_PROMPT_SHA:
        raise FrozenIdentityError(
            f"the frozen baseline prompt has moved: published {PUBLISHED_PROMPT_SHA}, "
            f"recomputed {found_prompt}"
        )

    scorer_version, scorer_manifest_sha = _scorer_identity()
    if scorer_version != EXPECTED_SCORER_VERSION:
        raise FrozenIdentityError(
            f"the scorer is version {scorer_version} and this harness was built against "
            f"{EXPECTED_SCORER_VERSION}; a changed metric definition must be seen, not inherited"
        )
    if scorer_manifest_sha != PUBLISHED_MANIFEST_SHA:
        raise FrozenIdentityError(
            f"the scorer pins {scorer_manifest_sha} and the driver pins "
            f"{PUBLISHED_MANIFEST_SHA}; two contracts is two experiments"
        )

    return FrozenIdentity(
        benchmark_id=BENCHMARK_ID,
        manifest_version=str(document["version"]),
        manifest_sha=found_manifest,
        baseline_prompt_sha=found_prompt,
        scorer_version=scorer_version,
    )


# ------------------------------------------------------------------------- the contract, typed


@dataclass(frozen=True, slots=True)
class Ceilings:
    """Every budget ceiling, read from the contract and never restated here."""

    wall_clock_seconds: int
    model_calls: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    authorisation_phrase: str

    @classmethod
    def read(cls, document: dict[str, Any]) -> Ceilings:
        per = document["budgets"]["per_scenario_per_arm"]
        dollar = document["budgets"]["dollar_ceiling"]
        return cls(
            wall_clock_seconds=int(per["wall_clock_seconds"]),
            model_calls=int(per["model_calls"]),
            tool_calls=int(per["tool_calls"]),
            input_tokens=int(per["input_tokens"]),
            output_tokens=int(per["output_tokens"]),
            authorisation_phrase=str(dollar["authorisation_phrase"]),
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "wall_clock_seconds": self.wall_clock_seconds,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


@dataclass(frozen=True, slots=True)
class ModelConfiguration:
    """Which model every arm runs on, and on what terms. One configuration, three arms."""

    provider: str
    model_id: str
    api: str
    temperature: float

    @classmethod
    def read(cls, document: dict[str, Any]) -> ModelConfiguration:
        block = document["model_configuration"]
        return cls(
            provider=str(block["provider"]),
            model_id=str(block["model_id"]),
            api=str(block["api"]),
            temperature=float(block["temperature"]),
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "api": self.api,
            "temperature": self.temperature,
        }


@dataclass(frozen=True, slots=True)
class Contract:
    """The frozen document, read once, after its identity has been asserted."""

    identity: FrozenIdentity
    document: dict[str, Any]

    @classmethod
    def load(cls) -> Contract:
        identity = assert_frozen()
        document: dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return cls(identity=identity, document=document)

    @property
    def ceilings(self) -> Ceilings:
        return Ceilings.read(self.document)

    @property
    def model_configuration(self) -> ModelConfiguration:
        return ModelConfiguration.read(self.document)

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        return tuple(str(scenario["id"]) for scenario in self.document["scenarios"])

    @property
    def case_universe(self) -> tuple[str, ...]:
        return tuple(str(order) for order in self.document["fixture"]["case_universe"])

    @property
    def read_tools(self) -> tuple[str, ...]:
        return tuple(str(tool["name"]) for tool in self.document["tool_surface"]["reads"])

    @property
    def write_tools(self) -> tuple[str, ...]:
        return tuple(str(tool["name"]) for tool in self.document["tool_surface"]["writes"])

    def scenario(self, scenario_id: str) -> dict[str, Any]:
        for scenario in self.document["scenarios"]:
            if scenario["id"] == scenario_id:
                return dict(scenario)
        raise KeyError(f"{scenario_id} is not a scenario of {BENCHMARK_ID}")

    def baseline_prompt(self) -> str:
        """The frozen instructions, verbatim, with the identity already asserted.

        No caller may supplement this and no caller may edit it. It is the bytes on disk
        decoded, and the only thing standing between it and a quiet rewrite is that
        :meth:`load` refused to build this object against a prompt with a different hash.
        """
        return PROMPT_PATH.read_text(encoding="utf-8")
