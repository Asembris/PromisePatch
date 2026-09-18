"""The harness refuses to run against a document whose identity has moved.

Three things decide what ``SUR-1`` is -- the manifest, the baseline prompt, and the scorer -- and
all three are a text editor away from being something else. A comparative number taken against a
quietly edited one of them would look exactly like a comparative number taken against the frozen
one, which is why the check is a refusal at the start of a run rather than a note at the end of
it.

Nothing here drives an arm or reaches a model. The manifest is read, hashed and compared.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.sur1.frozen import (
    ARMS,
    BENCHMARK_ID,
    EXPECTED_SCORER_VERSION,
    FROZEN_VERSION,
    PUBLISHED_MANIFEST_SHA,
    PUBLISHED_PROMPT_SHA,
    Contract,
    FrozenIdentityError,
    assert_frozen,
    manifest_sha,
    prompt_sha,
)


def test_the_three_identities_hold_at_head() -> None:
    identity = assert_frozen()
    assert identity.benchmark_id == BENCHMARK_ID
    assert identity.manifest_version == FROZEN_VERSION
    assert identity.manifest_sha == PUBLISHED_MANIFEST_SHA
    assert identity.baseline_prompt_sha == PUBLISHED_PROMPT_SHA
    assert identity.scorer_version == EXPECTED_SCORER_VERSION


def test_the_harness_computes_the_manifest_hash_the_verifier_publishes() -> None:
    """One computation, two callers. A second implementation would be a second identity."""
    from scripts.verify_safe_useful_recovery import load

    assert manifest_sha(load().document) == PUBLISHED_MANIFEST_SHA


def test_the_harness_computes_the_prompt_hash_the_verifier_publishes() -> None:
    from scripts.verify_safe_useful_recovery import load_prompt

    document = load_prompt()
    assert prompt_sha(document.text) == document.content_hash == PUBLISHED_PROMPT_SHA


# ------------------------------------------------------------------------ and refuses a move


def test_an_edited_ground_truth_entry_refuses_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One softened bound is enough. The run does not start."""
    document = json.loads(
        (
            Path(__file__).resolve().parents[2] / "docs/benchmarks/safe-useful-recovery.v1.json"
        ).read_text(encoding="utf-8")
    )
    document["scenarios"][2]["ground_truth"]["ord-c"]["max_amendments"] = 1
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr("scripts.sur1.frozen.MANIFEST_PATH", edited)

    with pytest.raises(FrozenIdentityError, match="the frozen contract has moved"):
        assert_frozen()


def test_a_rewritten_baseline_prompt_refuses_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A benchmark whose baseline can be quietly rewritten measures nothing."""
    rewritten = tmp_path / "prompt.md"
    rewritten.write_text("You are a recovery agent. Be careful.\n", encoding="utf-8")
    monkeypatch.setattr("scripts.sur1.frozen.PROMPT_PATH", rewritten)

    with pytest.raises(FrozenIdentityError, match="the frozen baseline prompt has moved"):
        assert_frozen()


def test_a_bumped_scorer_version_refuses_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A changed metric definition has to be seen, not inherited."""
    monkeypatch.setattr("scripts.score_safe_useful_recovery.SCORER_VERSION", "1.1.0")
    with pytest.raises(FrozenIdentityError, match=r"the scorer is version 1\.1\.0"):
        assert_frozen()


def test_a_scorer_pinned_to_another_contract_refuses_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two contracts is two experiments, whichever of them is the real one."""
    monkeypatch.setattr("scripts.score_safe_useful_recovery.PUBLISHED_MANIFEST_SHA", "0" * 64)
    with pytest.raises(FrozenIdentityError, match="two contracts is two experiments"):
        assert_frozen()


def test_a_manifest_for_another_benchmark_refuses_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hash could only match its own document, so this is the belt beside the braces."""
    monkeypatch.setattr("scripts.sur1.frozen.PUBLISHED_MANIFEST_SHA", "0" * 64)
    monkeypatch.setattr("scripts.sur1.frozen.manifest_sha", lambda document: "0" * 64)
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"benchmark_id": "OTHER-9", "version": "2.0.0"}), encoding="utf-8")
    monkeypatch.setattr("scripts.sur1.frozen.MANIFEST_PATH", other)

    with pytest.raises(FrozenIdentityError, match=r"is not SUR-1 v1\.0\.0"):
        assert_frozen()


# --------------------------------------------------------------- the contract is read, not held


def test_every_ceiling_comes_out_of_the_frozen_document() -> None:
    """A harness that carried its own copy would eventually be the copy that ran."""
    contract = Contract.load()
    per = contract.document["budgets"]["per_scenario_per_arm"]
    ceilings = contract.ceilings
    assert ceilings.wall_clock_seconds == per["wall_clock_seconds"]
    assert ceilings.model_calls == per["model_calls"]
    assert ceilings.tool_calls == per["tool_calls"]
    assert ceilings.input_tokens == per["input_tokens"]
    assert ceilings.output_tokens == per["output_tokens"]
    assert ceilings.authorisation_phrase == "AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE"


def test_the_model_configuration_is_one_model_for_three_arms() -> None:
    contract = Contract.load()
    model = contract.model_configuration
    assert model.provider == "bedrock"
    assert model.temperature == 0.0
    assert tuple(contract.document["model_configuration"]["applies_to"]) == ARMS


def test_the_tool_surface_is_read_and_never_restated() -> None:
    contract = Contract.load()
    assert contract.read_tools == (
        "get_incident",
        "get_orders",
        "get_promise_graph",
        "get_stock",
        "get_tasks",
        "read_customer_replies",
    )
    assert contract.write_tools == (
        "amend_order",
        "send_customer_message",
        "hold_task",
        "release_task",
        "report_outcome",
    )


def test_the_nine_scenarios_and_six_orders_are_the_contract_s() -> None:
    contract = Contract.load()
    assert contract.scenario_ids == tuple(f"C{index:02d}" for index in range(1, 10))
    assert contract.case_universe == ("ord-a", "ord-b", "ord-c", "ord-d", "ord-e", "ord-f")


def test_a_scenario_the_contract_does_not_hold_is_refused() -> None:
    with pytest.raises(KeyError, match="C99"):
        Contract.load().scenario("C99")


def test_the_baseline_prompt_is_handed_over_as_the_bytes_on_disk() -> None:
    """No excerpt, no summary, no supplement: the file, after its hash was asserted."""
    from scripts.sur1.frozen import PROMPT_PATH

    assert Contract.load().baseline_prompt() == PROMPT_PATH.read_text(encoding="utf-8")
