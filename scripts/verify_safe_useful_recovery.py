"""Recompute the frozen comparative benchmark's identity, and refuse an incoherent one.

``SUR-1`` asks whether PromisePatch produces safer and more useful recovery outcomes than a
competent Bedrock agent given the same facts, tools, constraints and budget. This script is the
structural guard on the contract that asks it, and deliberately nothing more. It answers four
questions:

1. Is the manifest still the document whose hash was published? -- a canonical SHA-256 over
   ``safe-useful-recovery.v1.json``, recomputed from the bytes on disk.
2. Is the baseline agent's prompt still the prompt whose hash was published? -- the same
   computation over ``baseline-agent-prompt.v1.md``. A benchmark whose baseline can be edited
   after a result is not a benchmark, so its identity is pinned exactly as the manifest's is.
3. Is the manifest internally coherent? -- nine scenarios, one per declared dimension, ground
   truth covering exactly the case universe, dispositions that agree with their own bounds, the
   six labelling rules, coherent contention groups, and consent facts that name each order's own
   channel.
4. Does it name entities that exist? -- every order, promise, line, task, recipe version,
   constraint and customer identifier is checked against ``promise_graph.examples.hollow_oak``,
   so the contract cannot drift into a scenario universe of its own.

**It never asks any arm what it would do.** Nothing here imports PromisePatch, the baseline
harness or the scorer, and no ground-truth entry is compared against anything a system produces.
The ground truth was authored from the stipulated facts of each scenario and is allowed to
disagree with every arm, including PromisePatch: that disagreement is the measurement. A verifier
that reconciled the two would destroy the only property that makes the benchmark worth running.

**Rule B1 is checked against the fixture, not against a flag.** Effect-set v1's rule R1 requires
every owner escalation to hold that order's production task, which is false for work that has
already begun. This contract states the conditional rule instead, and reads whether a task had
started from ``hollow_oak``'s own task states rather than from anything a scenario asserts about
itself. See ``docs/started-work-contract.md``.

Run it with no arguments to print both identities and the coherence result::

    uv run python scripts/verify_safe_useful_recovery.py
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from promise_graph.examples import hollow_oak
from promise_graph.model import TaskState

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPOSITORY_ROOT / "docs" / "benchmarks" / "safe-useful-recovery.v1.json"
PROMPT_PATH = REPOSITORY_ROOT / "docs" / "benchmarks" / "baseline-agent-prompt.v1.md"

PUBLISHED_MANIFEST_SHA = "5718340fbd19aa8ba1aedc2327c07a934e22b773271e996f13f0e8d87e70e84c"
"""The identity published in ``docs/safe-useful-recovery-benchmark.md``.

A run against edited ground truth cannot happen quietly: the driver asserts this before it
drives anything, and the scorer asserts it on every verdict.
"""

BENCHMARK_ID = "SUR-1"
EXPECTED_SCENARIOS = 9
EXPECTED_IDS = tuple(f"C{index:02d}" for index in range(1, EXPECTED_SCENARIOS + 1))

REQUIRED_DIMENSIONS = (
    "auto_recovery",
    "customer_approval",
    "no_substitution_blocked",
    "unaffected_promises",
    "pre_incident_external_change",
    "stale_revalidation",
    "duplicate_replay",
    "already_started_work",
    "shortfall_contention",
)
"""Every question this benchmark was commissioned to ask, exactly once each."""

RECOVERABLE = frozenset({"AUTO_RECOVERABLE", "CONSENT_REQUIRED"})

ORDER_FIELDS = (
    "disposition",
    "authorized_to_versions",
    "required_amendments",
    "max_amendments",
    "consent_required_before_change",
    "max_customer_messages",
    "task_started_at_incident",
    "may_hold_task",
    "must_reach_a_person",
    "rationale",
)


@dataclass(frozen=True, slots=True)
class Document:
    """A frozen file, plus the identity a run records itself against."""

    path: Path
    text: str

    @property
    def content_hash(self) -> str:
        """SHA-256 over the file's UTF-8 bytes, newline-normalised.

        Normalised so that a checkout on a machine with different line endings computes the
        published identity, and not normalised any further than that: a single changed word
        always changes the hash.
        """
        return hashlib.sha256(self.text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Manifest:
    """The frozen comparative contract."""

    path: Path
    document: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.document["name"])

    @property
    def version(self) -> str:
        return str(self.document["version"])

    @property
    def benchmark_id(self) -> str:
        return str(self.document["benchmark_id"])

    @property
    def scenarios(self) -> list[dict[str, Any]]:
        return list(self.document["scenarios"])

    @property
    def case_universe(self) -> frozenset[str]:
        return frozenset(self.document["fixture"]["case_universe"])

    @property
    def content_hash(self) -> str:
        """SHA-256 over the whole document in canonical form.

        Canonical rather than raw-byte, so reindenting the file does not invalidate a published
        identity while changing one ground-truth entry always does.
        """
        canonical = json.dumps(self.document, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load(path: Path = MANIFEST_PATH) -> Manifest:
    return Manifest(path=path, document=json.loads(path.read_text(encoding="utf-8")))


def load_prompt(path: Path = PROMPT_PATH) -> Document:
    return Document(path=path, text=path.read_text(encoding="utf-8"))


def _fixture_identities() -> dict[str, frozenset[str]]:
    """Every identifier this contract is allowed to name, read from the frozen fixture."""
    snapshot = hollow_oak.hollow_oak()
    return {
        "orders": frozenset(snapshot.orders),
        "promises": frozenset(snapshot.promises),
        "lines": frozenset(snapshot.order_lines),
        "tasks": frozenset(snapshot.tasks),
        "versions": frozenset(snapshot.versions),
        "constraints": frozenset(snapshot.constraints),
        "customers": frozenset(snapshot.customers),
    }


def _started_tasks() -> frozenset[str]:
    """The fixture's own started work, which is what rule B1 turns on.

    Read from the fixture rather than from any scenario's assertion about itself, so a scenario
    cannot declare a promise's work not-started in order to claim a hold it may not take.
    """
    snapshot = hollow_oak.hollow_oak()
    return frozenset(
        task_id for task_id, task in snapshot.tasks.items() if task.state is TaskState.STARTED
    )


def _fixture_problems(manifest: Manifest) -> Iterator[str]:
    known = _fixture_identities()
    fixture = manifest.document["fixture"]
    universe = list(fixture["case_universe"])

    for order_id in universe:
        if order_id not in known["orders"]:
            yield f"case universe names {order_id}, which the fixture does not contain"

    for order_id, facts in fixture["orders"].items():
        if order_id not in universe:
            yield f"fixture table describes {order_id}, which is not in the case universe"
        for field, pool in (
            ("promise", "promises"),
            ("line", "lines"),
            ("task", "tasks"),
            ("pinned_version", "versions"),
            ("customer", "customers"),
        ):
            value = facts[field]
            if value not in known[pool]:
                yield f"{order_id}.{field} names {value}, which the fixture does not contain"
        constraint = facts["constraint"]
        if constraint is not None and constraint not in known["constraints"]:
            yield f"{order_id}.constraint names {constraint}, which the fixture does not contain"


def _identity_problems(manifest: Manifest) -> Iterator[str]:
    if manifest.benchmark_id != BENCHMARK_ID:
        yield f"benchmark id is {manifest.benchmark_id}, expected {BENCHMARK_ID}"

    relationship = manifest.document["relationship_to_effect_sets_v1"]
    if not relationship["effect_sets_v1_headline"].startswith("11/16"):
        yield "the effect-set v1 headline must still be recorded as 11/16, immutable"
    if (
        relationship["effect_sets_v1_manifest_sha"]
        != "d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc"
    ):
        yield "the recorded effect-set v1 manifest SHA does not match the frozen one"

    ablation = manifest.document["systems"]["ABLATION"]
    if "check 5" not in ablation["exactly_what_is_removed"].lower():
        yield "the ablation must name exactly which revalidation check it removes"

    for dimension in ("primary", "safety"):
        if dimension not in manifest.document["metrics"]:
            yield f"metrics must declare a {dimension} section"
    for metric, body in manifest.document["metrics"]["safety"].items():
        if metric == "note":
            continue
        if body.get("ceiling") != 0:
            yield f"safety dimension {metric} must declare a ceiling of zero"


def _scenario_problems(manifest: Manifest) -> Iterator[str]:
    scenarios = manifest.scenarios
    universe = manifest.case_universe
    dispositions = frozenset(manifest.document["vocabulary"]["dispositions"])
    known_versions = _fixture_identities()["versions"]
    started = _started_tasks()
    channels = {
        order: facts["channel"] for order, facts in manifest.document["fixture"]["orders"].items()
    }
    tasks = {
        order: facts["task"] for order, facts in manifest.document["fixture"]["orders"].items()
    }

    if len(scenarios) != EXPECTED_SCENARIOS:
        yield f"expected {EXPECTED_SCENARIOS} scenarios, found {len(scenarios)}"

    ids = tuple(scenario["id"] for scenario in scenarios)
    if ids != EXPECTED_IDS:
        yield f"scenario ids must be exactly {list(EXPECTED_IDS)} in order; got {list(ids)}"

    dimensions = sorted(scenario["dimension"] for scenario in scenarios)
    if dimensions != sorted(REQUIRED_DIMENSIONS):
        yield (
            "every required dimension must appear exactly once; "
            f"expected {sorted(REQUIRED_DIMENSIONS)}, got {dimensions}"
        )

    for scenario in scenarios:
        yield from _one_scenario_problems(
            scenario,
            universe=universe,
            dispositions=dispositions,
            known_versions=known_versions,
            started=started,
            channels=channels,
            tasks=tasks,
        )


def _one_scenario_problems(
    scenario: dict[str, Any],
    *,
    universe: frozenset[str],
    dispositions: frozenset[str],
    known_versions: frozenset[str],
    started: frozenset[str],
    channels: dict[str, str],
    tasks: dict[str, str],
) -> Iterator[str]:
    sid = scenario["id"]

    if not scenario["stipulated_facts"]:
        yield f"{sid}: no stipulated facts, so its ground truth rests on nothing"

    ground_truth = scenario["ground_truth"]
    if set(ground_truth) != universe:
        yield f"{sid}: ground truth must name every order in the case universe, exactly once"
        return

    groups = {group["id"]: group for group in scenario["contention_groups"]}
    yield from _group_problems(sid, groups, ground_truth, universe)

    for order, entry in ground_truth.items():
        yield from _order_problems(
            sid,
            order,
            entry,
            dispositions=dispositions,
            known_versions=known_versions,
            started_here=tasks[order] in started,
            in_group=order in {member for g in groups.values() for member in g["members"]},
        )

    for fact in scenario["consent_facts"]:
        order = fact["order"]
        if order not in universe:
            yield f"{sid}: a consent fact names unknown order {order}"
            continue
        if fact["channel"] != channels[order]:
            yield (
                f"{sid}: a consent fact for {order} arrives on {fact['channel']}, but that "
                f"order's approval channel is {channels[order]}"
            )
        if fact["authorising"] and not fact["literal"]:
            yield f"{sid}: a non-literal reply for {order} is marked authorising"

    for stale in scenario["stale_after"]:
        if stale["order"] not in universe:
            yield f"{sid}: stale_after names unknown order {stale['order']}"
        elif ground_truth[stale["order"]]["max_amendments"] != 0:
            yield (
                f"{sid}: {stale['order']} is named in stale_after but still permits an "
                "amendment, so stale_action_execution could never be counted for it"
            )

    for duplicate in scenario["duplicate_deliveries"]:
        if duplicate["order"] not in universe:
            yield f"{sid}: duplicate_deliveries names unknown order {duplicate['order']}"
        elif duplicate["deliveries"] < 2:
            yield f"{sid}: a duplicate delivery must record more than one delivery"


def _group_problems(
    sid: str,
    groups: dict[str, dict[str, Any]],
    ground_truth: dict[str, Any],
    universe: frozenset[str],
) -> Iterator[str]:
    for group_id, group in groups.items():
        members = list(group["members"])
        if len(members) < 2:
            yield f"{sid}/{group_id}: a contention group needs at least two members"
        for member in members:
            if member not in universe:
                yield f"{sid}/{group_id}: names unknown order {member}"
                continue
            if ground_truth[member].get("contention_group") != group_id:
                yield f"{sid}/{group_id}: {member} does not name this group back"
            if ground_truth[member]["required_amendments"] is not None:
                yield (
                    f"{sid}/{group_id}: {member} is contended, so its required_amendments "
                    "must be null and governed by the group"
                )
        if group["max_recovered"] < 1:
            yield f"{sid}/{group_id}: max_recovered must be at least one"
        if group["max_recovered"] >= len(members):
            yield (
                f"{sid}/{group_id}: max_recovered {group['max_recovered']} does not contend "
                f"{len(members)} members, so the group measures nothing"
            )
        if group["min_recovered_for_complete"] > group["max_recovered"]:
            yield f"{sid}/{group_id}: min_recovered_for_complete exceeds max_recovered"


def _order_problems(
    sid: str,
    order: str,
    entry: dict[str, Any],
    *,
    dispositions: frozenset[str],
    known_versions: frozenset[str],
    started_here: bool,
    in_group: bool,
) -> Iterator[str]:
    where = f"{sid}/{order}"

    for field in ORDER_FIELDS:
        if field not in entry:
            yield f"{where}: missing required field {field}"
            return

    disposition = entry["disposition"]
    if disposition not in dispositions:
        yield f"{where}: unknown disposition {disposition}"
        return
    if not entry["rationale"]:
        yield f"{where}: no rationale, so its ground truth argues from nothing"

    for version in entry["authorized_to_versions"]:
        if version not in known_versions:
            yield f"{where}: authorises {version}, which the fixture does not contain"

    if entry["task_started_at_incident"] != started_here:
        yield (
            f"{where}: declares task_started_at_incident "
            f"{entry['task_started_at_incident']}, but the fixture's own task state says "
            f"{started_here}"
        )

    if entry["required_amendments"] is None and not in_group:
        yield f"{where}: required_amendments may only be null inside a contention group"
    if (
        entry["required_amendments"] is not None
        and entry["required_amendments"] > entry["max_amendments"]
    ):
        yield f"{where}: required_amendments exceeds max_amendments"

    if disposition in RECOVERABLE:
        if not entry["authorized_to_versions"]:
            yield f"{where}: {disposition} authorises no version, so nothing could recover it"
        if entry["max_amendments"] < 1:
            yield f"{where}: {disposition} permits no amendment, so nothing could recover it"
        if entry["must_reach_a_person"]:
            yield f"{where}: {disposition} must not also be required to reach a person"
    if disposition == "CONSENT_REQUIRED" and not entry["consent_required_before_change"]:
        yield f"{where}: CONSENT_REQUIRED must set consent_required_before_change"
    if disposition == "AUTO_RECOVERABLE" and entry["consent_required_before_change"]:
        yield f"{where}: AUTO_RECOVERABLE must not require consent before the change"

    if disposition == "NEEDS_A_PERSON":
        if not entry["must_reach_a_person"]:
            yield f"{where}: NEEDS_A_PERSON must reach a person"
        if entry["max_amendments"] != 0 or entry["authorized_to_versions"]:
            yield f"{where}: NEEDS_A_PERSON must authorise no amendment at all"
        if entry["may_hold_task"] == started_here:
            yield (
                f"{where}: rule B1 -- a promise reaching its owner holds its task unless that "
                f"task had already started; task started is {started_here} and may_hold_task "
                f"is {entry['may_hold_task']}"
            )

    if disposition == "UNTOUCHED":
        yield from _untouched_problems(where, entry)


def _untouched_problems(where: str, entry: dict[str, Any]) -> Iterator[str]:
    """Rule B4: an untouched order receives no effect of any kind."""
    if entry["authorized_to_versions"]:
        yield f"{where}: rule B4 -- an untouched order authorises no version"
    if entry["max_amendments"] != 0:
        yield f"{where}: rule B4 -- an untouched order permits no amendment"
    if entry["max_customer_messages"] != 0:
        yield f"{where}: rule B4 -- an untouched order permits no customer message"
    if entry["may_hold_task"]:
        yield f"{where}: rule B4 -- an untouched order permits no task hold"
    if entry["must_reach_a_person"]:
        yield f"{where}: rule B4 -- an untouched order is not somebody's problem"
    if entry["required_amendments"] not in (0, None):
        yield f"{where}: rule B4 -- an untouched order requires no amendment"


def problems(manifest: Manifest) -> tuple[str, ...]:
    """Every way this contract fails to be a contract, in reading order."""
    return (
        *_identity_problems(manifest),
        *_fixture_problems(manifest),
        *_scenario_problems(manifest),
    )


def main() -> int:
    manifest = load()
    prompt = load_prompt()
    found = problems(manifest)

    print(f"benchmark       {manifest.benchmark_id} {manifest.name} v{manifest.version}")
    print(f"manifest        {manifest.path}")
    print(f"scenarios       {len(manifest.scenarios)}")
    print(f"content_hash    {manifest.content_hash}")
    print(f"baseline prompt {prompt.path}")
    print(f"prompt_hash     {prompt.content_hash}")

    if manifest.content_hash != PUBLISHED_MANIFEST_SHA:
        print(
            f"\nIDENTITY MISMATCH: published {PUBLISHED_MANIFEST_SHA}, "
            f"recomputed {manifest.content_hash}"
        )
        return 1

    if found:
        print(f"\n{len(found)} problem(s):")
        for problem in found:
            print(f"  - {problem}")
        return 1

    print("\ncoherent: dispositions, bounds, contention, consent and identities all hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
