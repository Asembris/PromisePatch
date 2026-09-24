"""The frozen effect-set manifest, and the verifier that refuses an incoherent one.

Two things are tested here and they are not the same thing.

The first is the **manifest itself**: it is frozen, so its identity is asserted as a literal.
A change to any label, count, checkpoint or stipulated fact changes the content hash, and this
file fails until somebody says out loud that the frozen labels moved. That is the point of
freezing them before the runner exists.

The second is the **verifier**: every coherence rule is exercised by breaking the manifest in
memory and asserting the verifier notices. A structural check nobody has ever seen fail is not
a check.

Nothing here calls PromisePatch's classifier. The manifest's labels are hand-authored from
stipulated facts and are deliberately not reconciled with implementation output; a test that
compared them would delete the measurement the suite exists to take.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from scripts.verify_effect_set_manifest import (
    EXPECTED_SCENARIOS,
    MANIFEST_V2_PATH,
    Manifest,
    load,
    problems,
    started_orders,
)

FROZEN_CONTENT_HASH = "d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc"
FROZEN_VERSION = "1.0.0"

V2_CONTENT_HASH = "77286e77a2919244118a7c39ace7632290ecca50eacf4318e45a4a72606cb0dd"
V2_VERSION = "2.0.0"


@pytest.fixture
def manifest() -> Manifest:
    return load()


def broken(manifest: Manifest, mutate: Any) -> tuple[str, ...]:
    """Every problem in a copy of the manifest that ``mutate`` has damaged."""
    document = copy.deepcopy(manifest.document)
    mutate(document)
    return problems(Manifest(path=manifest.path, document=document))


# ------------------------------------------------------------------------------- the freeze


def test_the_frozen_manifest_still_has_its_published_identity(manifest: Manifest) -> None:
    """The published SHA is a promise. Changing a label without saying so breaks it."""
    assert manifest.version == FROZEN_VERSION
    assert manifest.content_hash == FROZEN_CONTENT_HASH


def test_the_frozen_manifest_is_coherent(manifest: Manifest) -> None:
    assert problems(manifest) == ()


def test_the_manifest_holds_sixteen_scenarios_one_per_roadmap_item(manifest: Manifest) -> None:
    scenarios = manifest.scenarios
    assert len(scenarios) == EXPECTED_SCENARIOS
    assert sorted(scenario["roadmap_item"] for scenario in scenarios) == list(
        range(1, EXPECTED_SCENARIOS + 1)
    )
    assert len({scenario["slug"] for scenario in scenarios}) == EXPECTED_SCENARIOS


def test_the_content_hash_survives_reformatting_and_not_relabelling(manifest: Manifest) -> None:
    """Canonical, not raw-byte: reindenting is free, moving one order is not."""
    reformatted = Manifest(
        path=manifest.path, document=json.loads(json.dumps(manifest.document, indent=8))
    )
    assert reformatted.content_hash == manifest.content_hash

    relabelled = copy.deepcopy(manifest.document)
    checkpoint = relabelled["scenarios"][0]["checkpoints"][0]
    checkpoint["partition"]["blocked"] = ["ord-c"]
    checkpoint["partition"]["untouched"] = ["ord-d", "ord-e", "ord-f"]
    assert Manifest(path=manifest.path, document=relabelled).content_hash != manifest.content_hash


# ------------------------------------------------------------------------ the partition algebra


def test_planning_may_never_declare_an_operational_effect(manifest: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["scenarios"][0]["checkpoints"][0]["effects_added"] = [
            {"order": "ord-a", "kind": "order_amendment", "count": 1}
        ]

    assert any("no operational effect" in problem for problem in broken(manifest, mutate))


def test_an_order_in_two_threatened_partitions_is_refused(manifest: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["scenarios"][0]["checkpoints"][0]["partition"]["blocked"] = [
            "ord-a",
            "ord-c",
            "ord-d",
        ]

    assert any("not disjoint" in problem for problem in broken(manifest, mutate))


def test_an_order_in_no_partition_at_all_is_refused(manifest: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["scenarios"][0]["checkpoints"][0]["partition"]["untouched"] = ["ord-e"]

    assert any("cover the case universe" in problem for problem in broken(manifest, mutate))


def test_an_untouched_order_may_not_carry_an_effect(manifest: Manifest) -> None:
    """Rule R5, which is the claim the whole funnel rests on."""

    def mutate(document: dict[str, Any]) -> None:
        document["scenarios"][0]["checkpoints"][1]["effects_added"].append(
            {"order": "ord-e", "kind": "customer_message", "count": 1}
        )

    assert any("rule R5 forbids" in problem for problem in broken(manifest, mutate))


def test_the_untouched_baseline_must_match_the_settled_partition(manifest: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["scenarios"][0]["untouched_baseline"] = 3

    assert any("untouched_baseline" in problem for problem in broken(manifest, mutate))


# ---------------------------------------------------------------------------- the labelling rules


def test_an_escalation_without_a_task_hold_is_refused(manifest: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        effects = document["scenarios"][0]["checkpoints"][1]["effects_added"]
        document["scenarios"][0]["checkpoints"][1]["effects_added"] = [
            effect for effect in effects if effect["kind"] != "task_hold"
        ]

    assert any("(R1)" in problem for problem in broken(manifest, mutate))


def test_an_amendment_without_a_reservation_change_is_refused(manifest: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        effects = document["scenarios"][0]["checkpoints"][1]["effects_added"]
        document["scenarios"][0]["checkpoints"][1]["effects_added"] = [
            effect for effect in effects if effect["kind"] != "reservation_change"
        ]

    assert any("(R2)" in problem for problem in broken(manifest, mutate))


# -------------------------------------------------------------------------------- the vocabulary


def test_an_effect_kind_outside_the_vocabulary_is_refused(manifest: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["scenarios"][0]["checkpoints"][1]["effects_added"].append(
            {"order": "ord-a", "kind": "order_deleted", "count": 1}
        )

    assert any("unknown effect kind" in problem for problem in broken(manifest, mutate))


def test_a_refusal_kind_outside_the_vocabulary_is_refused(manifest: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["scenarios"][0]["checkpoints"][0]["refusals"].append("model_said_no")

    assert any("unknown refusal kind" in problem for problem in broken(manifest, mutate))


def test_checkpoints_out_of_order_are_refused(manifest: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        checkpoints = document["scenarios"][0]["checkpoints"]
        checkpoints[1]["name"], checkpoints[2]["name"] = (
            checkpoints[2]["name"],
            checkpoints[1]["name"],
        )

    assert any("increasing subsequence" in problem for problem in broken(manifest, mutate))


def test_a_scenario_without_a_settled_checkpoint_is_refused(manifest: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["scenarios"][0]["checkpoints"].pop()

    assert any("must be SETTLED" in problem for problem in broken(manifest, mutate))


# ---------------------------------------------------------------------------- the shared universe


def test_an_identifier_the_fixture_does_not_contain_is_refused(manifest: Manifest) -> None:
    """The manifest must reuse the canonical fixture, not invent a rival kitchen."""

    def mutate(document: dict[str, Any]) -> None:
        document["fixture"]["orders"]["ord-a"]["pinned_version"] = "rv-invented-9"

    assert any("fixture does not contain" in problem for problem in broken(manifest, mutate))


def test_every_scenario_explains_every_order_in_the_universe(manifest: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        del document["scenarios"][0]["rationale"]["ord-f"]

    assert any("rationale must name every order" in problem for problem in broken(manifest, mutate))


def test_a_scenario_with_no_stipulated_facts_is_refused(manifest: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["scenarios"][0]["stipulated_facts"] = []

    assert any("rest on nothing" in problem for problem in broken(manifest, mutate))


def test_a_missing_scenario_is_refused(manifest: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        document["scenarios"].pop()

    found = broken(manifest, mutate)
    assert any("expected 16 scenarios" in problem for problem in found)
    assert any("roadmap items are not" in problem for problem in found)


# ---------------------------------------------------- v2: the separately versioned correction
#
# v2 corrects one rule of v1 and nothing else: R1 becomes conditional on the order's production
# task not having started. v1 is not edited, not weakened and not re-verified under v2's rule;
# the tests below prove all three, and pin v2's own identity exactly as v1's is pinned above.


@pytest.fixture
def corrected() -> Manifest:
    return load(MANIFEST_V2_PATH)


def _s12(document: dict[str, Any]) -> dict[str, Any]:
    return next(scenario for scenario in document["scenarios"] if scenario["id"] == "S12")


def _confirmed(scenario: dict[str, Any]) -> dict[str, Any]:
    return next(point for point in scenario["checkpoints"] if point["name"] == "CONFIRMED")


def test_the_corrected_manifest_has_its_own_published_identity(corrected: Manifest) -> None:
    assert corrected.version == V2_VERSION
    assert corrected.content_hash == V2_CONTENT_HASH
    assert corrected.content_hash != FROZEN_CONTENT_HASH


def test_the_corrected_manifest_is_coherent(corrected: Manifest) -> None:
    assert problems(corrected) == ()


def test_the_fixture_has_exactly_one_started_task_and_it_is_ahmeds() -> None:
    assert started_orders() == frozenset({"ord-e"})


def test_the_rule_is_chosen_by_the_hashed_major_version(
    manifest: Manifest, corrected: Manifest
) -> None:
    assert not manifest.started_work_escalates_without_a_hold
    assert corrected.started_work_escalates_without_a_hold


def test_v1_still_refuses_ahmeds_escalation_without_a_hold(manifest: Manifest) -> None:
    """v1's R1 is unconditional exactly as frozen: v2's corrected S12 label is invalid under it."""

    def mutate(document: dict[str, Any]) -> None:
        point = _confirmed(_s12(document))
        point["effects_added"] = [
            effect
            for effect in point["effects_added"]
            if (effect["order"], effect["kind"]) != ("ord-e", "task_hold")
        ]

    assert any("ord-e escalates without a task hold (R1)" in p for p in broken(manifest, mutate))


def test_v2_refuses_a_hold_on_work_that_had_already_started(corrected: Manifest) -> None:
    def mutate(document: dict[str, Any]) -> None:
        _confirmed(_s12(document))["effects_added"].append(
            {"order": "ord-e", "kind": "task_hold", "count": 1}
        )

    assert any("R1, conditional" in problem for problem in broken(corrected, mutate))


def test_v2_still_refuses_an_unheld_escalation_on_scheduled_work(corrected: Manifest) -> None:
    """The exemption is the started set and nothing wider: ord-c's task is SCHEDULED."""

    def mutate(document: dict[str, Any]) -> None:
        point = _confirmed(_s12(document))
        point["effects_added"] = [
            effect
            for effect in point["effects_added"]
            if (effect["order"], effect["kind"]) != ("ord-c", "task_hold")
        ]

    assert any("ord-c escalates without a task hold (R1)" in p for p in broken(corrected, mutate))


def test_v2_differs_from_v1_only_by_its_declared_delta(
    manifest: Manifest, corrected: Manifest
) -> None:
    """One rule, one effect, one rationale sentence, and the metadata that says so."""
    original, revised = manifest.document, corrected.document

    assert revised["correction"]["corrects"] == {
        "name": original["name"],
        "version": FROZEN_VERSION,
        "content_hash": FROZEN_CONTENT_HASH,
    }
    assert revised["correction"]["kind"] == "label correction, not product repair"

    carried = ("name", "schema_version", "authored_by", "fixture", "pass_rule")
    assert {key: revised[key] for key in carried} == {key: original[key] for key in carried}
    assert set(revised) - set(original) == {"correction"}
    assert set(original) <= set(revised)

    vocabulary = dict(revised["vocabulary"])
    frozen_vocabulary = dict(original["vocabulary"])
    assert vocabulary["labelling_rules"][1:] == frozen_vocabulary["labelling_rules"][1:]
    assert vocabulary["labelling_rules"][0] != frozen_vocabulary["labelling_rules"][0]
    del vocabulary["labelling_rules"], frozen_vocabulary["labelling_rules"]
    assert vocabulary == frozen_vocabulary

    for before, after in zip(original["scenarios"], revised["scenarios"], strict=True):
        if before["id"] != "S12":
            assert after == before
            continue
        expected = copy.deepcopy(before)
        point = _confirmed(expected)
        point["effects_added"].remove({"order": "ord-e", "kind": "task_hold", "count": 1})
        expected["rationale"]["ord-e"] = after["rationale"]["ord-e"]
        assert after == expected
        assert after["rationale"]["ord-e"].startswith(before["rationale"]["ord-e"])
