"""The dataset is the instrument, so the dataset is checked first.

Every claim in a gold case is checked against production rather than against another copy of
the same belief: the deterministic reading by calling the lexicon, the expected outcome by
building the reading the case describes and putting it through the real grounding rules, the
identifiers against the frozen kitchen's own candidate set.

The negative tests matter as much as the positive one. A validator that never fails is a
validator nobody can trust, so each rule is shown refusing a case that breaks it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from evals.cases import SCHEMA_VERSION, CustomerCase, EvalSplit, Outcome, WorkerCase
from evals.dataset import (
    DatasetError,
    GoldDataset,
    load_dataset,
    manifest_problems,
    validate_dataset,
    write_manifest,
)


@pytest.fixture(scope="module")
def dataset() -> GoldDataset:
    return load_dataset()


def test_the_committed_dataset_is_consistent_with_production(dataset: GoldDataset) -> None:
    """The whole point. Every label, checked by the code that would have to produce it."""
    assert validate_dataset(dataset) == ()


def test_the_committed_manifest_describes_the_committed_dataset(dataset: GoldDataset) -> None:
    assert manifest_problems(dataset, dataset.manifest()) == ()


def test_the_dataset_covers_both_jobs_and_both_splits(dataset: GoldDataset) -> None:
    manifest = dataset.manifest()
    assert manifest.by_job["worker_semantics"] == len(dataset.worker)
    assert manifest.by_job["customer_intent"] == len(dataset.customer)
    for split in EvalSplit:
        assert manifest.by_split[split.value] > 0


def test_every_case_id_is_unique(dataset: GoldDataset) -> None:
    ids = [case.id for case in dataset.cases]
    assert len(ids) == len(set(ids))


def test_the_content_hash_changes_with_the_content(dataset: GoldDataset) -> None:
    """A hash that survived an edit would let a dataset change arrive unannounced."""
    before = dataset.content_hash
    edited = GoldDataset(
        version=dataset.version,
        worker=dataset.worker[1:],
        customer=dataset.customer,
        provenance=dataset.provenance,
    )
    assert edited.content_hash != before


def test_the_dataset_covers_the_clusters_the_thresholds_gate_on(dataset: GoldDataset) -> None:
    """A threshold over a tag nothing carries would report ``not-measured`` for ever."""
    tags = {tag for case in dataset.cases for tag in case.tags}
    assert {"terse_assent", "indirect_refusal", "out_of_scope", "prompt_injection"} <= tags


def test_both_worker_families_are_present(dataset: GoldDataset) -> None:
    """Sentences a model is asked about, and sentences it must never be asked about."""
    assert any(case.asked for case in dataset.worker)
    assert any(not case.asked for case in dataset.worker)


def test_every_asked_case_carries_an_expectation(dataset: GoldDataset) -> None:
    for case in dataset.worker:
        assert (case.expected is not None) is case.asked


def test_the_canonical_regressions_are_in_the_dataset(dataset: GoldDataset) -> None:
    """The three readings this slice was built around, each as one case among many."""
    by_id = {case.id: case for case in dataset.cases}

    canonical = by_id["worker.deterministic.raspberry-delivery.001"]
    assert isinstance(canonical, WorkerCase)
    assert canonical.deterministic is Outcome.CLARIFICATION
    assert not canonical.asked, "the lexicon reads it, so no model is ever paid to"

    oven = by_id["worker.equipment.deck-oven.001"]
    assert isinstance(oven, WorkerCase)
    assert oven.expected is not None
    assert oven.expected.resource_id == "res-deck-oven"
    assert oven.expected.outcome is Outcome.RESOLVED

    berries = by_id["worker.ambiguous.berries.001"]
    assert isinstance(berries, WorkerCase)
    assert berries.expected is not None
    assert berries.expected.resource_id is None, "nothing the bakery wrote says which berry"
    assert berries.expected.outcome is Outcome.ESCALATED

    strawberries = by_id["customer.approve.terse.001"]
    assert isinstance(strawberries, CustomerCase)
    assert strawberries.reply == "Strawberries work"
    assert strawberries.expected.value == "APPARENT_APPROVE"


def test_the_terse_assent_cluster_is_more_than_its_famous_member(
    dataset: GoldDataset,
) -> None:
    """One regression fixture is a regression fixture; a dataset of it is not a dataset."""
    cluster = [case for case in dataset.customer if "terse_assent" in case.tags]
    assert len(cluster) >= 5
    assert len({case.reply.casefold() for case in cluster}) == len(cluster)


# ------------------------------------------------------------------- the validator bites


def _worker_payload(dataset: GoldDataset, case_id: str) -> dict[str, Any]:
    case = next(case for case in dataset.worker if case.id == case_id)
    payload: dict[str, Any] = json.loads(case.model_dump_json())
    return payload


def _with(dataset: GoldDataset, case: WorkerCase) -> GoldDataset:
    return GoldDataset(
        version=dataset.version,
        worker=(case,),
        customer=dataset.customer[:1],
        provenance=dataset.provenance,
    )


def test_a_wrong_deterministic_claim_is_refused(dataset: GoldDataset) -> None:
    """Claiming the lexicon cannot read a sentence it reads perfectly well."""
    payload = _worker_payload(dataset, "worker.equipment.deck-oven.001")
    payload["utterance"] = "the deck oven is down"
    problems = validate_dataset(_with(dataset, WorkerCase.model_validate(payload)))
    assert any("deterministic" in problem for problem in problems)


def test_a_wrong_expected_outcome_is_refused(dataset: GoldDataset) -> None:
    """A hand-written outcome PromisePatch would never reach."""
    payload = _worker_payload(dataset, "worker.equipment.deck-oven.001")
    expected = dict(payload["expected"])
    expected["outcome"] = "CLARIFICATION"
    expected["clarification_slot"] = "SCOPE"
    payload["expected"] = expected
    problems = validate_dataset(_with(dataset, WorkerCase.model_validate(payload)))
    assert any("expects outcome CLARIFICATION" in problem for problem in problems)


def test_an_identifier_the_fixture_does_not_contain_is_refused(dataset: GoldDataset) -> None:
    payload = _worker_payload(dataset, "worker.equipment.deck-oven.001")
    expected = dict(payload["expected"])
    expected["resource_id"] = "res-tandoor"
    expected["proposed_resource_ids"] = ["res-tandoor"]
    payload["expected"] = expected
    problems = validate_dataset(_with(dataset, WorkerCase.model_validate(payload)))
    assert any("the fixture does not contain" in problem for problem in problems)


def test_an_expectation_on_a_sentence_nobody_is_asked_about_is_refused(
    dataset: GoldDataset,
) -> None:
    payload = _worker_payload(dataset, "worker.equipment.deck-oven.001")
    payload["deterministic"] = "RESOLVED"
    payload["deterministic_reason"] = None
    payload["utterance"] = "the deck oven is down"
    problems = validate_dataset(_with(dataset, WorkerCase.model_validate(payload)))
    assert any("never asks a model" in problem for problem in problems)


def test_a_reply_the_literal_parser_reads_is_refused(dataset: GoldDataset) -> None:
    """``"yes!!!"`` normalises to ``yes``, so no model is ever shown it."""
    payload = json.loads(dataset.customer[0].model_dump_json())
    payload["reply"] = "yes!!!"
    poisoned = GoldDataset(
        version=dataset.version,
        worker=dataset.worker[:1],
        customer=(CustomerCase.model_validate(payload),),
        provenance=dataset.provenance,
    )
    problems = validate_dataset(poisoned)
    assert any("the literal parser reads this reply" in problem for problem in problems)


def test_a_duplicated_utterance_under_two_ids_is_refused(dataset: GoldDataset) -> None:
    payload = _worker_payload(dataset, "worker.equipment.deck-oven.001")
    twin = dict(payload)
    twin["id"] = "worker.equipment.deck-oven.099"
    poisoned = GoldDataset(
        version=dataset.version,
        worker=(WorkerCase.model_validate(payload), WorkerCase.model_validate(twin)),
        customer=dataset.customer[:1],
        provenance=dataset.provenance,
    )
    assert any("already appears as" in problem for problem in validate_dataset(poisoned))


def test_an_unknown_schema_version_is_refused(tmp_path: Path, dataset: GoldDataset) -> None:
    for name in ("worker_semantics.json", "customer_intent.json", "manifest.json"):
        source = Path("evals/datasets") / name
        (tmp_path / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    poisoned = json.loads((tmp_path / "worker_semantics.json").read_text(encoding="utf-8"))
    poisoned["schema_version"] = "99"
    (tmp_path / "worker_semantics.json").write_text(json.dumps(poisoned), encoding="utf-8")
    with pytest.raises(DatasetError, match="schema version"):
        load_dataset(tmp_path)


def test_the_manifest_can_be_regenerated(tmp_path: Path, dataset: GoldDataset) -> None:
    path = tmp_path / "manifest.json"
    manifest = write_manifest(dataset, path)
    assert manifest.schema_version == SCHEMA_VERSION
    assert json.loads(path.read_text(encoding="utf-8"))["content_hash"] == dataset.content_hash
