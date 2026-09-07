"""Gold data cannot reach a model. Proved by absence, not by intention.

An evaluation whose answers leak into its own questions measures nothing, and it does so
silently: every number goes up and the dataset looks better than the system. So the projection
from a gold case to a provider request is a deliberate narrowing, and this suite is the proof
that nothing survives it.

Two kinds of proof, and both are needed.

*Structural.* :class:`~evals.cases.ModelInput` has three fields and one of them is the request.
There is no field an expected label could travel in, so the leak is impossible rather than
merely absent today.

*Textual.* For every case in the committed dataset, the exact bytes a provider would be sent --
the request, and the rendered prompt production builds from it -- are searched for every piece
of gold information the case carries. This is the check that would catch a future change adding
a helpful hint to a prompt.
"""

from __future__ import annotations

import json

import pytest
from evals.cases import CustomerCase, ModelInput, WorkerCase, to_model_input
from evals.dataset import GoldDataset, load_dataset

from promisepatch.domain.grounding import SUPPORTED_CATEGORIES
from promisepatch.semantic import (
    ClassifyReplyIntentRequest,
    InterpretUtteranceRequest,
    SemanticMetadata,
)
from promisepatch.semantic.prompts import build_system_instruction, build_user_content, fence

FORBIDDEN_FIELD_NAMES = frozenset(
    {"expected", "gold", "label", "rationale", "note", "split", "tags", "answer"}
)


@pytest.fixture(scope="module")
def dataset() -> GoldDataset:
    return load_dataset()


def _case_specific_bytes(model_input: ModelInput) -> str:
    """Everything a provider is sent that varies with the case: the request and the prompt.

    Two deliberate narrowings, each because the alternative would fail on a coincidence rather
    than on a leak:

    *The system instruction is not searched.* It is the same text for every case of a job --
    asserted below -- so it cannot encode a per-case answer, and it contains ordinary English
    words like "question" that several tags are named after.

    *Field names are not searched, only values.* The request carries a ``clarification`` field
    that is null for every case here; matching the gold outcome ``CLARIFICATION`` against
    production's own key would say nothing about what any model is told.
    """
    request = model_input.request
    values = _string_values(json.loads(request.model_dump_json()))
    return "\n".join([*values, build_user_content(request)])


def _string_values(payload: object) -> list[str]:
    """Every string a request actually carries, keys excluded."""
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, dict):
        return [item for value in payload.values() for item in _string_values(value)]
    if isinstance(payload, list):
        return [item for value in payload for item in _string_values(value)]
    return []


def test_the_projection_has_no_field_gold_could_travel_in() -> None:
    """Structural. Not "we checked", but "there is nowhere to put it"."""
    assert set(ModelInput.model_fields) == {"case_id", "job", "request"}
    assert not FORBIDDEN_FIELD_NAMES & set(ModelInput.model_fields)


def test_a_request_carries_no_correlation_metadata(dataset: GoldDataset) -> None:
    """Even the case id stays out of the request, where a prompt builder could reach it."""
    for case in dataset.cases:
        assert to_model_input(case).request.metadata == SemanticMetadata()


def test_nothing_a_provider_is_sent_contains_the_gold_answer(dataset: GoldDataset) -> None:
    """Textual. Every gold string, searched for in the exact bytes that would be sent."""
    for case in dataset.cases:
        sent = _case_specific_bytes(to_model_input(case))
        for secret in _gold_strings(case):
            assert secret.casefold() not in sent.casefold(), f"{case.id} leaks {secret!r}"


def test_the_system_instruction_is_the_same_for_every_case_of_a_job(
    dataset: GoldDataset,
) -> None:
    """Constant per job, so there is nothing case-specific it could be carrying."""
    for job in {case.job for case in dataset.cases}:
        instruction = build_system_instruction(job.semantic_job)
        for case in dataset.cases:
            if case.job is not job:
                continue
            model_input = to_model_input(case)
            assert build_system_instruction(model_input.job.semantic_job) == instruction


def _gold_strings(case: WorkerCase | CustomerCase) -> list[str]:
    """Everything about this case a model must not be told, as literal text.

    Two gold vocabularies are deliberately absent from this list: ``Outcome`` and
    ``ClarificationSlot``. Their members are words production's own request vocabulary already
    contains -- every candidate list names ``COMMITMENT``, and the request carries a
    ``clarification`` field -- so searching for them would report a coincidence as a leak. The
    guarantee they need is a different and stronger one, and
    :func:`test_the_prompt_does_not_change_when_the_gold_answer_does` is it.
    """
    secrets = [case.id, case.split.value, *case.tags]
    if case.note:
        secrets.append(case.note)
    if isinstance(case, CustomerCase):
        secrets.append(case.expected.value)
        return secrets
    if case.deterministic_reason is not None:
        secrets.append(case.deterministic_reason.value)
    expected = case.expected
    if expected is not None:
        secrets.append(expected.grounding.value)
        if expected.escalation_reason is not None:
            secrets.append(expected.escalation_reason.value)
    return secrets


def test_the_prompt_does_not_change_when_the_gold_answer_does(dataset: GoldDataset) -> None:
    """The whole guarantee, stated as an experiment rather than as a search.

    Take a real case, replace its entire expected block with a different one, and build the
    provider request again. The bytes are identical, because the request is a function of the
    utterance and the frozen kitchen and of nothing else. No gold vocabulary can influence a
    prompt, whether or not any particular word of it would have shown up in a substring search.
    """
    case = next(item for item in dataset.worker if item.asked)
    original = to_model_input(case)

    payload = json.loads(case.model_dump_json())
    payload["expected"] = {
        "category": "STOCK_UNUSABLE",
        "resource_id": "res-blueberries",
        "proposed_resource_ids": ["res-blueberries"],
        "out_of_scope": True,
        "grounding": "AMBIGUOUS_RESOURCE",
        "outcome": "CLARIFICATION",
        "clarification_slot": "SCOPE",
        "escalation_reason": "NO_OPEN_COMMITMENT",
    }
    payload["tags"] = ["completely-different-tag"]
    payload["note"] = "a different note entirely"
    payload["split"] = "holdout" if case.split.value == "development" else "development"
    altered = to_model_input(WorkerCase.model_validate(payload))

    assert altered.request.model_dump_json() == original.request.model_dump_json()
    assert build_user_content(altered.request) == build_user_content(original.request)


def test_a_worker_case_is_offered_every_category_not_the_gold_one(
    dataset: GoldDataset,
) -> None:
    """Narrowing the categories towards the answer would be the subtlest possible leak."""
    for case in dataset.worker:
        if not case.asked:
            continue
        request = to_model_input(case).request
        assert isinstance(request, InterpretUtteranceRequest)
        assert request.categories == SUPPORTED_CATEGORIES


def test_a_worker_case_is_offered_the_candidates_production_would_offer(
    dataset: GoldDataset,
) -> None:
    """The candidate set is production's, so a gold identity is never privileged in it.

    The clearest case is the one whose gold answer is *no identity at all*: the candidate list
    it is sent still contains every ingredient the kitchen stocks, exactly as the workflow
    would send it.
    """
    berries = next(case for case in dataset.worker if case.id == "worker.ambiguous.berries.001")
    request = to_model_input(berries).request
    assert isinstance(request, InterpretUtteranceRequest)
    offered = {item.id for item in request.resources}
    assert {"res-raspberries", "res-strawberries", "res-blueberries"} <= offered


def test_a_customer_case_sends_the_reply_and_nothing_else(dataset: GoldDataset) -> None:
    """The whole user message for this job is the fenced reply. There is no room for a hint."""
    for case in dataset.customer:
        request = to_model_input(case).request
        assert isinstance(request, ClassifyReplyIntentRequest)
        assert build_user_content(request) == fence(request.reply)
        assert request.reply.text == case.reply


def test_the_projection_is_the_same_shape_production_builds(dataset: GoldDataset) -> None:
    """A dataset that built its own request would be measuring its own prompt."""
    case = next(case for case in dataset.worker if case.asked)
    request = to_model_input(case).request
    payload = json.loads(request.model_dump_json())
    assert payload["job"] == "interpret_utterance"
    assert payload["utterance"]["text"] == case.utterance
