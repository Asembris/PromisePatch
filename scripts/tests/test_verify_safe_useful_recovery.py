"""The frozen comparative contract, and the verifier that refuses an incoherent one.

Three things are tested here and they are not the same thing.

The first is the **contract itself**: it is frozen, so its identity is asserted as a literal,
and so is the baseline agent prompt's. A change to any ground-truth entry, stipulated fact,
budget, metric definition or rule changes the manifest hash; a change to a single word of the
baseline's instructions changes the prompt hash. Either one fails this file until somebody says
out loud that a frozen thing moved. That is the whole point of freezing them before any arm has
been driven.

The second is the **verifier**: every coherence rule is exercised by breaking the contract in
memory and asserting the verifier notices. A structural check nobody has ever seen fail is not
a check.

The third is the **relationship to effect-set v1**: this benchmark is new, separate and
additive, and the assertions below fail if any part of it starts describing itself as a repair
of the 11/16 headline.

Nothing here runs an arm. No ground-truth entry is compared against anything PromisePatch or a
baseline agent produces, because that disagreement is the measurement and a test that
reconciled the two would delete it.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from scripts.verify_safe_useful_recovery import (
    BENCHMARK_ID,
    EXPECTED_SCENARIOS,
    PUBLISHED_MANIFEST_SHA,
    Manifest,
    load,
    load_prompt,
    problems,
)

FROZEN_VERSION = "1.0.0"
FROZEN_PROMPT_HASH = "772ba46025620a1aea4742fac3971c5906ec3252036d07725434e0a89ce47cb1"
EFFECT_SETS_V1_SHA = "d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc"


@pytest.fixture
def manifest() -> Manifest:
    return load()


def broken(manifest: Manifest, mutate: Any) -> tuple[str, ...]:
    """Every problem in a copy of the contract that ``mutate`` has damaged."""
    document = copy.deepcopy(manifest.document)
    mutate(document)
    return problems(Manifest(path=manifest.path, document=document))


def scenario(document: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    return next(entry for entry in document["scenarios"] if entry["id"] == scenario_id)


# ------------------------------------------------------------------------------- the freeze


def test_the_frozen_contract_still_has_its_published_identity(manifest: Manifest) -> None:
    """The published SHA is a promise. Moving ground truth without saying so breaks it."""
    assert manifest.benchmark_id == BENCHMARK_ID
    assert manifest.version == FROZEN_VERSION
    assert manifest.content_hash == PUBLISHED_MANIFEST_SHA


def test_the_baseline_prompt_still_has_its_published_identity() -> None:
    """A benchmark whose baseline can be quietly rewritten measures nothing."""
    assert load_prompt().content_hash == FROZEN_PROMPT_HASH


def test_the_frozen_contract_is_coherent(manifest: Manifest) -> None:
    assert problems(manifest) == ()


def test_every_commissioned_question_is_asked_exactly_once(manifest: Manifest) -> None:
    dimensions = [entry["dimension"] for entry in manifest.scenarios]
    assert len(manifest.scenarios) == EXPECTED_SCENARIOS
    assert len(set(dimensions)) == EXPECTED_SCENARIOS


def test_the_benchmark_can_state_an_outcome_that_refutes_its_own_thesis(
    manifest: Manifest,
) -> None:
    """A benchmark with no publishable way to lose is an advertisement."""
    falsification = " ".join(manifest.document["falsification"])
    assert "refuted and published as refuted" in falsification
    assert "DISQUALIFIED for PROMISEPATCH" in falsification


# ------------------------------------------------------------- effect-set v1 stays untouched


def test_the_contract_records_the_immutable_effect_set_headline(manifest: Manifest) -> None:
    relationship = manifest.document["relationship_to_effect_sets_v1"]
    assert relationship["effect_sets_v1_headline"].startswith("11/16")
    assert relationship["effect_sets_v1_manifest_sha"] == EFFECT_SETS_V1_SHA
    assert "not a version two" in relationship["statement"]


def test_the_contract_refuses_to_launder_the_development_result(manifest: Manifest) -> None:
    relationship = manifest.document["relationship_to_effect_sets_v1"]
    assert "it is not a score" in relationship["effect_sets_v1_development_result"]
    assert any("16/16" in rule for rule in relationship["forbidden"])
    assert any("scenarios.v1.json" in rule for rule in relationship["forbidden"])


def test_a_softened_effect_set_headline_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: document["relationship_to_effect_sets_v1"].__setitem__(
            "effect_sets_v1_headline", "16/16 after repairs"
        ),
    )
    assert any("11/16" in problem for problem in found)


def test_a_moved_effect_set_manifest_sha_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: document["relationship_to_effect_sets_v1"].__setitem__(
            "effect_sets_v1_manifest_sha", "0" * 64
        ),
    )
    assert any("effect-set v1 manifest SHA" in problem for problem in found)


# ---------------------------------------------------------------------------- the ablation


def test_the_ablation_names_exactly_one_check(manifest: Manifest) -> None:
    ablation = manifest.document["systems"]["ABLATION"]
    assert "check 5" in ablation["exactly_what_is_removed"].lower()
    assert "Nothing else." in ablation["exactly_what_is_removed"]
    untouched = " ".join(ablation["what_is_not_touched"])
    assert "packages/" in untouched


def test_a_vague_ablation_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: document["systems"]["ABLATION"].__setitem__(
            "exactly_what_is_removed", "some revalidation"
        ),
    )
    assert any("exactly which revalidation check" in problem for problem in found)


# ------------------------------------------------------------ safety cannot be averaged away


def test_every_safety_dimension_has_a_ceiling_of_zero(manifest: Manifest) -> None:
    safety = manifest.document["metrics"]["safety"]
    dimensions = {name: body for name, body in safety.items() if name != "note"}
    assert set(dimensions) == {
        "unauthorized_effects",
        "unaffected_promise_effects",
        "consent_violations",
        "stale_action_execution",
        "duplicate_effects",
        "premature_completion_claims",
        "started_work_untruths",
    }
    assert all(body["ceiling"] == 0 for body in dimensions.values())


def test_a_raised_safety_ceiling_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: document["metrics"]["safety"]["consent_violations"].__setitem__(
            "ceiling", 1
        ),
    )
    assert any("ceiling of zero" in problem for problem in found)


def test_safety_and_usefulness_are_never_combined(manifest: Manifest) -> None:
    assert "never averaged" in manifest.document["metrics"]["reporting_rule"]
    assert "no composite score" in manifest.document["metrics"]["reporting_rule"]


# ------------------------------------------------------------------- the ground-truth rules


def test_an_untouched_order_that_permits_an_effect_is_refused(manifest: Manifest) -> None:
    """Rule B4, in each of the ways it can be broken."""
    for field, value in (
        ("max_amendments", 1),
        ("max_customer_messages", 1),
        ("may_hold_task", True),
        ("must_reach_a_person", True),
    ):
        found = broken(
            manifest,
            lambda document, field=field, value=value: scenario(document, "C04")["ground_truth"][
                "ord-f"
            ].__setitem__(field, value),
        )
        assert any("rule B4" in problem for problem in found), field


def test_a_hold_on_started_work_is_refused(manifest: Manifest) -> None:
    """Rule B1. This is the clause effect-set v1's R1 gets wrong, and it is enforced here."""
    found = broken(
        manifest,
        lambda document: scenario(document, "C08")["ground_truth"]["ord-e"].__setitem__(
            "may_hold_task", True
        ),
    )
    assert any("rule B1" in problem for problem in found)


def test_refusing_to_hold_scheduled_work_that_reaches_its_owner_is_refused(
    manifest: Manifest,
) -> None:
    """B1 is an implication with one exception, not a licence to hold nothing."""
    found = broken(
        manifest,
        lambda document: scenario(document, "C08")["ground_truth"]["ord-c"].__setitem__(
            "may_hold_task", False
        ),
    )
    assert any("rule B1" in problem for problem in found)


def test_a_started_flag_that_contradicts_the_fixture_is_refused(manifest: Manifest) -> None:
    """The flag is checked against hollow_oak's own task states, never trusted."""
    found = broken(
        manifest,
        lambda document: scenario(document, "C08")["ground_truth"]["ord-e"].__setitem__(
            "task_started_at_incident", False
        ),
    )
    assert any("the fixture's own task state" in problem for problem in found)


def test_a_promise_needing_a_person_may_authorise_no_amendment(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C01")["ground_truth"]["ord-c"].__setitem__(
            "max_amendments", 1
        ),
    )
    assert any("NEEDS_A_PERSON must authorise no amendment" in problem for problem in found)


def test_a_recoverable_promise_with_nothing_to_recover_to_is_refused(
    manifest: Manifest,
) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C01")["ground_truth"]["ord-a"].__setitem__(
            "authorized_to_versions", []
        ),
    )
    assert any("authorises no version" in problem for problem in found)


def test_an_auto_recovery_that_needs_consent_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C01")["ground_truth"]["ord-a"].__setitem__(
            "consent_required_before_change", True
        ),
    )
    assert any("must not require consent" in problem for problem in found)


def test_a_consent_requirement_without_the_flag_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C01")["ground_truth"]["ord-b"].__setitem__(
            "consent_required_before_change", False
        ),
    )
    assert any("CONSENT_REQUIRED must set" in problem for problem in found)


def test_an_invented_recovery_target_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C01")["ground_truth"]["ord-a"].__setitem__(
            "authorized_to_versions", ["rv-invented-9"]
        ),
    )
    assert any("the fixture does not contain" in problem for problem in found)


# ---------------------------------------------------------------------------- contention


def test_a_contention_group_that_contends_nothing_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C09")["contention_groups"][0].__setitem__(
            "max_recovered", 2
        ),
    )
    assert any("measures nothing" in problem for problem in found)


def test_a_contended_order_with_a_fixed_requirement_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C09")["ground_truth"]["ord-a"].__setitem__(
            "required_amendments", 1
        ),
    )
    assert any("governed by the group" in problem for problem in found)


def test_a_group_whose_member_does_not_name_it_back_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C09")["ground_truth"]["ord-b"].__setitem__(
            "contention_group", "g-elsewhere"
        ),
    )
    assert any("does not name this group back" in problem for problem in found)


# --------------------------------------------------------------------------------- consent


def test_a_reply_from_the_wrong_channel_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C01")["consent_facts"][0].__setitem__(
            "channel", "tg:1005"
        ),
    )
    assert any("that order's approval channel is" in problem for problem in found)


def test_a_nonliteral_reply_may_not_be_marked_authorising(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C02")["consent_facts"][0].__setitem__(
            "authorising", True
        ),
    )
    assert any("non-literal reply" in problem for problem in found)


def test_c02_records_that_an_agreeable_sentence_decides_nothing(manifest: Manifest) -> None:
    facts = scenario(manifest.document, "C02")["consent_facts"]
    apparent, literal = facts[0], facts[1]
    assert apparent["literal"] is False and apparent["authorising"] is False
    assert literal["text"] == "YES" and literal["authorising"] is True


# ------------------------------------------------------------------------ staleness and replay


def test_a_stale_order_that_still_permits_an_amendment_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C06")["ground_truth"]["ord-b"].__setitem__(
            "max_amendments", 1
        ),
    )
    assert any("named in stale_after" in problem for problem in found)


def test_a_single_delivery_is_not_a_duplicate(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C07")["duplicate_deliveries"][0].__setitem__(
            "deliveries", 1
        ),
    )
    assert any("more than one delivery" in problem for problem in found)


# -------------------------------------------------------------------------------- structure


def test_a_missing_scenario_is_refused(manifest: Manifest) -> None:
    found = broken(manifest, lambda document: document["scenarios"].pop())
    assert any("expected 9 scenarios" in problem for problem in found)


def test_a_ground_truth_that_skips_an_order_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C01")["ground_truth"].pop("ord-f"),
    )
    assert any("every order in the case universe" in problem for problem in found)


def test_a_scenario_with_no_stipulated_facts_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: scenario(document, "C01").__setitem__("stipulated_facts", []),
    )
    assert any("rests on nothing" in problem for problem in found)


def test_an_entity_the_fixture_does_not_hold_is_refused(manifest: Manifest) -> None:
    found = broken(
        manifest,
        lambda document: document["fixture"]["orders"]["ord-a"].__setitem__(
            "task", "task-ol-imaginary"
        ),
    )
    assert any("the fixture does not contain" in problem for problem in found)


# ------------------------------------------------------------------- the execution guardrails


def test_the_scorer_is_blind_by_construction(manifest: Manifest) -> None:
    blinding = manifest.document["blinding"]
    mechanism = " ".join(blinding["mechanism"])
    assert "imports nothing from promisepatch" in mechanism
    assert "before the map is joined" in mechanism
    assert blinding["where_blinding_is_technically_unavoidable"]


def test_void_is_capped_and_a_nonpass_is_never_hidden_in_it(manifest: Manifest) -> None:
    rules = manifest.document["void_rules"]
    assert "At most two" in rules["cap"]
    assert "never removed from the denominator" in rules["denominator"]
    not_void = " ".join(rules["explicitly_not_void"])
    assert "INVALID" in not_void and "BUDGET_EXHAUSTED" in not_void


def test_retries_cannot_become_best_of_n(manifest: Manifest) -> None:
    forbidden = " ".join(manifest.document["retry_policy"]["forbidden"])
    assert "Best-of-N" in forbidden
    assert "Selecting which attempt to publish" in forbidden


def test_the_freeze_covers_everything_that_could_be_tuned(manifest: Manifest) -> None:
    frozen = " ".join(manifest.document["freeze"]["frozen_before_execution"]).lower()
    for subject in ("scenarios", "prompt", "model", "tool surface", "budget", "scorer", "void"):
        assert subject in frozen, subject
    assert "whatever it says" in manifest.document["freeze"]["first_run_is_the_headline"]


def test_both_arms_share_one_model_and_the_limitation_is_disclosed(manifest: Manifest) -> None:
    configuration = manifest.document["model_configuration"]
    assert configuration["applies_to"] == ["BASELINE", "PROMISEPATCH", "ABLATION"]
    assert configuration["temperature"] == 0.0
    assert "never in place of it" in configuration["declared_limitation"]


def test_the_baseline_is_denied_internals_and_not_competence(manifest: Manifest) -> None:
    baseline = manifest.document["systems"]["BASELINE"]
    withheld = " ".join(baseline["does_not_receive"]).lower()
    assert "revalidation" in withheld
    assert "consent protocol" in withheld
    given = " ".join(baseline["receives"]).lower()
    assert "recorded constraint" in given
    assert "substitution policies" in given
    assert "measure ignorance rather than architecture" in baseline["note"]
