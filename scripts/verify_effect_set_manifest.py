"""Recompute the frozen effect-set manifest's identity, and refuse an incoherent one.

This is a **structural** verifier and deliberately nothing more. It answers three questions:

1. Is the manifest still the document whose hash was published? -- a canonical SHA-256 over
   ``scenarios.v1.json`` (or the separately versioned ``scenarios.v2.json``), recomputed from the
   bytes on disk.
2. Is it internally coherent? -- sixteen scenarios, one per roadmap item, disjoint partitions
   covering exactly the declared case universe, ordered checkpoints, a closed effect and
   refusal vocabulary, and the two labelling implications (``owner_escalation`` holds a task,
   an applied ``order_amendment`` changes reservations).
3. Does it name entities that exist? -- every order, promise, line, version, constraint and
   customer identifier is checked against ``promise_graph.examples.hollow_oak``, so the
   manifest cannot drift into a scenario universe of its own.

Two manifests exist and neither replaces the other. ``v1`` is the frozen original, scored once for
the immutable 11/16 headline, and its R1 is checked exactly as it was frozen: every escalation
holds a task, unconditionally. ``v2`` is a label correction of v1 (see
``docs/effect-set-manifest-v2.md``) whose R1 is conditional: an order whose production task the
fixture records as ``STARTED`` is escalated without a hold, and may never carry one. The started
set is read from the fixture's own task states, never from a per-scenario flag.

**It never asks PromisePatch what it would classify.** Nothing here imports the classifier, the
propagation pass, the option enumerator or any part of the backend, and no expected label is
compared against anything the engine produces. The labels were authored from the stipulated
facts of each scenario and are allowed to disagree with the implementation: that disagreement is
the measurement the P8 run is for. A verifier that reconciled the two would destroy the only
property that makes the suite worth running.

Run it with no arguments to print the identity and the coherence result::

    uv run python scripts/verify_effect_set_manifest.py
    uv run python scripts/verify_effect_set_manifest.py --manifest v2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from promise_graph.examples import hollow_oak
from promise_graph.model import TaskState

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPOSITORY_ROOT / "docs" / "effect-sets" / "scenarios.v1.json"
MANIFEST_V2_PATH = REPOSITORY_ROOT / "docs" / "effect-sets" / "scenarios.v2.json"
MANIFEST_PATHS = {"v1": MANIFEST_PATH, "v2": MANIFEST_V2_PATH}

EXPECTED_SCENARIOS = 16
PARTITION_NAMES = ("auto_repairable", "consent_required", "blocked", "untouched")
THREATENED_NAMES = ("auto_repairable", "consent_required", "blocked")


@dataclass(frozen=True, slots=True)
class Manifest:
    """The frozen document, plus the identity a run records itself against."""

    path: Path
    document: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.document["name"])

    @property
    def version(self) -> str:
        return str(self.document["version"])

    @property
    def scenarios(self) -> list[dict[str, Any]]:
        return list(self.document["scenarios"])

    @property
    def started_work_escalates_without_a_hold(self) -> bool:
        """Whether this manifest's R1 is the conditional rule of v2 rather than v1's.

        Decided by the manifest's own major version, which is inside the hashed document, so a
        v1 manifest cannot acquire the conditional rule without ceasing to be v1.
        """
        return int(self.version.split(".")[0]) >= 2

    @property
    def content_hash(self) -> str:
        """SHA-256 over the whole document in canonical form.

        Canonical rather than raw-byte, so reindenting the file does not invalidate a
        published identity while changing one label always does.
        """
        canonical = json.dumps(self.document, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load(path: Path = MANIFEST_PATH) -> Manifest:
    return Manifest(path=path, document=json.loads(path.read_text(encoding="utf-8")))


def _fixture_identities() -> dict[str, frozenset[str]]:
    """Every identifier the manifest is allowed to name, read from the frozen fixture."""
    snapshot = hollow_oak.hollow_oak()
    return {
        "orders": frozenset(snapshot.orders),
        "promises": frozenset(snapshot.promises),
        "lines": frozenset(snapshot.order_lines),
        "versions": frozenset(snapshot.versions),
        "constraints": frozenset(snapshot.constraints),
        "customers": frozenset(snapshot.customers),
    }


def started_orders() -> frozenset[str]:
    """The orders whose production task the frozen fixture records as already ``STARTED``."""
    snapshot = hollow_oak.hollow_oak()
    return frozenset(
        snapshot.order_lines[task.order_line_id].order_id
        for task in snapshot.tasks.values()
        if task.state is TaskState.STARTED
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
            ("pinned_version", "versions"),
            ("customer", "customers"),
        ):
            value = facts[field]
            if value not in known[pool]:
                yield f"{order_id}.{field} names {value}, which the fixture does not contain"
        constraint = facts["constraint"]
        if constraint is not None and constraint not in known["constraints"]:
            yield f"{order_id}.constraint names {constraint}, which the fixture does not contain"


def _scenario_problems(manifest: Manifest) -> Iterator[str]:
    document = manifest.document
    universe = frozenset(document["fixture"]["case_universe"])
    effect_kinds = frozenset(document["vocabulary"]["effect_kinds"])
    refusal_kinds = frozenset(document["vocabulary"]["refusal_kinds"])
    checkpoint_names = document["vocabulary"]["checkpoint_order"]
    scenarios = manifest.scenarios

    if len(scenarios) != EXPECTED_SCENARIOS:
        yield f"expected {EXPECTED_SCENARIOS} scenarios, found {len(scenarios)}"

    ids = [scenario["id"] for scenario in scenarios]
    if len(set(ids)) != len(ids):
        yield "scenario ids are not unique"
    items = sorted(scenario["roadmap_item"] for scenario in scenarios)
    if items != list(range(1, EXPECTED_SCENARIOS + 1)):
        yield f"roadmap items are not 1..{EXPECTED_SCENARIOS} exactly once: {items}"

    started = started_orders() if manifest.started_work_escalates_without_a_hold else frozenset()
    for scenario in scenarios:
        yield from _one_scenario_problems(
            scenario, universe, effect_kinds, refusal_kinds, checkpoint_names, started
        )


def _one_scenario_problems(
    scenario: dict[str, Any],
    universe: frozenset[str],
    effect_kinds: frozenset[str],
    refusal_kinds: frozenset[str],
    checkpoint_names: list[str],
    started: frozenset[str] = frozenset(),
) -> Iterator[str]:
    sid = scenario["id"]

    if not scenario["stipulated_facts"]:
        yield f"{sid}: no stipulated facts, so its labels rest on nothing"
    if set(scenario["rationale"]) != universe:
        yield f"{sid}: rationale must name every order in the case universe, exactly once"

    checkpoints = scenario["checkpoints"]
    if [checkpoint["ordinal"] for checkpoint in checkpoints] != list(
        range(1, len(checkpoints) + 1)
    ):
        yield f"{sid}: checkpoint ordinals must run 1..n in order"
    positions = [checkpoint_names.index(checkpoint["name"]) for checkpoint in checkpoints]
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        yield f"{sid}: checkpoints are not a strictly increasing subsequence of the vocabulary"
    if checkpoints[0]["name"] != "PLANNED":
        yield f"{sid}: the first checkpoint must be PLANNED"
    if checkpoints[-1]["name"] != "SETTLED":
        yield f"{sid}: the last checkpoint must be SETTLED"
    if checkpoints[0]["effects_added"]:
        yield f"{sid}: planning must produce no operational effect at all"

    cumulative: dict[tuple[str, str], int] = {}
    untouched_at_settled: frozenset[str] = frozenset()

    for checkpoint in checkpoints:
        partition = checkpoint["partition"]
        if set(partition) != set(PARTITION_NAMES):
            yield f"{sid}/{checkpoint['name']}: partition keys must be exactly {PARTITION_NAMES}"
            continue

        threatened: list[str] = [order for name in THREATENED_NAMES for order in partition[name]]
        if len(set(threatened)) != len(threatened):
            yield f"{sid}/{checkpoint['name']}: threatened partitions are not disjoint"
        listed = [*threatened, *partition["untouched"]]
        if sorted(listed) != sorted(universe):
            yield (
                f"{sid}/{checkpoint['name']}: partitions must cover the case universe exactly "
                f"once; got {sorted(listed)}"
            )
        for name in PARTITION_NAMES:
            if list(partition[name]) != sorted(partition[name]):
                yield f"{sid}/{checkpoint['name']}: {name} is not in canonical order"

        for refusal in checkpoint["refusals"]:
            if refusal not in refusal_kinds:
                yield f"{sid}/{checkpoint['name']}: unknown refusal kind {refusal}"

        for effect in checkpoint["effects_added"]:
            order, kind, count = effect["order"], effect["kind"], effect["count"]
            if order not in universe:
                yield f"{sid}/{checkpoint['name']}: effect names unknown order {order}"
            if kind not in effect_kinds:
                yield f"{sid}/{checkpoint['name']}: unknown effect kind {kind}"
            if count < 1:
                yield f"{sid}/{checkpoint['name']}: effects_added must record a positive count"
            cumulative[order, kind] = cumulative.get((order, kind), 0) + count

        untouched = frozenset(partition["untouched"])
        untouched_at_settled = untouched
        for (order, kind), count in cumulative.items():
            if order in untouched and count:
                yield (
                    f"{sid}/{checkpoint['name']}: untouched order {order} carries "
                    f"{count} {kind}; rule R5 forbids any incident-caused effect"
                )

        for order in universe:
            escalations = cumulative.get((order, "owner_escalation"), 0)
            holds = cumulative.get((order, "task_hold"), 0)
            if order in started:
                if holds:
                    yield (
                        f"{sid}/{checkpoint['name']}: {order}'s task had already started, so it "
                        f"may not carry a task hold (R1, conditional)"
                    )
            elif escalations and not holds:
                yield f"{sid}/{checkpoint['name']}: {order} escalates without a task hold (R1)"
            amendments = cumulative.get((order, "order_amendment"), 0)
            reservations = cumulative.get((order, "reservation_change"), 0)
            if amendments != reservations:
                yield (
                    f"{sid}/{checkpoint['name']}: {order} has {amendments} amendments and "
                    f"{reservations} reservation changes (R2)"
                )

    if scenario["untouched_baseline"] != len(untouched_at_settled):
        yield (
            f"{sid}: untouched_baseline is {scenario['untouched_baseline']} but the settled "
            f"partition holds {len(untouched_at_settled)} untouched orders"
        )


def problems(manifest: Manifest) -> tuple[str, ...]:
    """Every way this manifest fails to be a manifest, in reading order."""
    return (*_fixture_problems(manifest), *_scenario_problems(manifest))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--manifest",
        choices=tuple(MANIFEST_PATHS),
        default="v1",
        help="Which manifest to verify. v1 is the frozen original; v2 is its label correction.",
    )
    args = parser.parse_args(argv)
    manifest = load(MANIFEST_PATHS[args.manifest])
    found = problems(manifest)

    print(f"manifest      {manifest.name} v{manifest.version}")
    print(f"path          {manifest.path}")
    print(f"scenarios     {len(manifest.scenarios)}")
    print(f"content_hash  {manifest.content_hash}")

    if found:
        print(f"\n{len(found)} problem(s):")
        for problem in found:
            print(f"  - {problem}")
        return 1

    print("\ncoherent: partitions, checkpoints, effects and identities all hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
