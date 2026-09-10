"""The frozen effect-set manifest, read as data by tests that may not invent an expectation.

`docs/effect-sets/scenarios.v1.json` was hand-labelled from stipulated facts and committed with
a published SHA before the remaining implementation existed. A test that typed its expected
partitions and effects out by hand would be re-authoring those labels, and nothing would then
stop them drifting towards whatever the code happened to do. So the expectations are loaded from
the frozen document itself, and :func:`identity` is asserted against the published hash, which
makes an edit to the manifest fail the suite rather than quietly move the target.

This module reads. It never classifies, never imports the engine or the backend, and holds no
opinion about whether a label is right -- exactly like `scripts/verify_effect_set_manifest.py`,
and for the same reason.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
MANIFEST_PATH: Final = REPOSITORY_ROOT / "docs" / "effect-sets" / "scenarios.v1.json"

PUBLISHED_SHA: Final = "d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc"
"""The identity published in `docs/effect-set-manifest.md` and frozen at commit 9a7f4a8."""

PARTITIONS: Final = ("auto_repairable", "consent_required", "blocked", "untouched")

Partition = dict[str, frozenset[str]]
Effects = dict[tuple[str, str], int]


def manifest() -> dict[str, Any]:
    return dict(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def identity(document: dict[str, Any] | None = None) -> str:
    """The canonical SHA-256 of the manifest, recomputed exactly as the verifier does."""
    document = manifest() if document is None else document
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def orders() -> dict[str, dict[str, Any]]:
    """The manifest's own order table: which promise, line and external id each label names."""
    return dict(manifest()["fixture"]["orders"])


def case_universe() -> tuple[str, ...]:
    return tuple(manifest()["fixture"]["case_universe"])


def scenario(scenario_id: str) -> dict[str, Any]:
    for entry in manifest()["scenarios"]:
        if entry["id"] == scenario_id:
            return dict(entry)
    raise KeyError(scenario_id)


def checkpoint_names(scenario_document: dict[str, Any]) -> tuple[str, ...]:
    return tuple(point["name"] for point in scenario_document["checkpoints"])


def partition_at(scenario_document: dict[str, Any], checkpoint: str) -> Partition:
    for point in scenario_document["checkpoints"]:
        if point["name"] == checkpoint:
            return {name: frozenset(point["partition"][name]) for name in PARTITIONS}
    raise KeyError(checkpoint)


def cumulative_effects_at(scenario_document: dict[str, Any], checkpoint: str) -> Effects:
    """Every ``(order, kind)`` declared up to and including ``checkpoint``.

    Effects are declared incrementally, and the manifest is explicit that a pair absent from the
    sum is a claim of exactly zero rather than a silence -- so the mapping this returns is the
    whole expectation, and anything not in it must be absent from the world.
    """
    total: Effects = {}
    for point in scenario_document["checkpoints"]:
        for effect in point["effects_added"]:
            key = (effect["order"], effect["kind"])
            total[key] = total.get(key, 0) + int(effect["count"])
        if point["name"] == checkpoint:
            return total
    raise KeyError(checkpoint)


def refusals_at(scenario_document: dict[str, Any], checkpoint: str) -> frozenset[str]:
    for point in scenario_document["checkpoints"]:
        if point["name"] == checkpoint:
            return frozenset(point["refusals"])
    raise KeyError(checkpoint)
