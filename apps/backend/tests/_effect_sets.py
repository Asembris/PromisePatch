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

**Which frozen document is read is chosen once, by the runner, and defaults to v1.** Two exist:
`scenarios.v1.json`, the original that scored the immutable 11/16, and `scenarios.v2.json`, its
separately versioned label correction (`docs/effect-set-manifest-v2.md`). The runner names its
choice in ``PP_EFFECT_SET_MANIFEST`` for the pytest process it starts; with nothing named, every
reader here and every identity assertion is v1's exactly as before. Each document is asserted
against its own published hash, so neither can stand in for the other.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Final

from scripts.run_effect_sets import MANIFEST_VARIABLE

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
MANIFEST_PATH: Final = REPOSITORY_ROOT / "docs" / "effect-sets" / "scenarios.v1.json"

PUBLISHED_SHA: Final = "d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc"
"""The identity published in `docs/effect-set-manifest.md` and frozen at commit 9a7f4a8."""

MANIFEST_V2_PATH: Final = REPOSITORY_ROOT / "docs" / "effect-sets" / "scenarios.v2.json"

PUBLISHED_V2_SHA: Final = "77286e77a2919244118a7c39ace7632290ecca50eacf4318e45a4a72606cb0dd"
"""The identity published in `docs/effect-set-manifest-v2.md`, the label correction of v1."""

MANIFESTS: Final = {
    "v1": (MANIFEST_PATH, PUBLISHED_SHA),
    "v2": (MANIFEST_V2_PATH, PUBLISHED_V2_SHA),
}

PARTITIONS: Final = ("auto_repairable", "consent_required", "blocked", "untouched")

Partition = dict[str, frozenset[str]]
Effects = dict[tuple[str, str], int]


def selected() -> str:
    """The manifest this process judges against: the runner's choice, or v1 when none is named."""
    choice = os.environ.get(MANIFEST_VARIABLE) or "v1"
    if choice not in MANIFESTS:
        raise ValueError(f"{MANIFEST_VARIABLE}={choice!r} names no manifest: {sorted(MANIFESTS)}")
    return choice


def published_sha() -> str:
    """The published identity of the selected manifest."""
    return MANIFESTS[selected()][1]


def manifest() -> dict[str, Any]:
    return dict(json.loads(MANIFESTS[selected()][0].read_text(encoding="utf-8")))


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
