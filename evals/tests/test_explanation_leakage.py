"""Nothing an evaluation knows may reach the thing it is evaluating.

Two directions, and both are load-bearing.

*Towards Nova.* A case carries a reference passage, a split, tags, expected constraints and a
calibration note. None of them may appear in the bytes a provider is sent, and the argument is
structural rather than careful: the projection produces a type with three fields, and one of
them is the production request.

*Towards the judge.* A judge is shown authoritative facts and one passage. It is not shown the
verdict anybody wants, the thresholds the run is gated on, whether the case was designed to be
hostile, or which split it is in. A judge told what a good answer looks like is grading against
an expectation instead of against the facts.

The tests below assert this three ways -- structurally, textually over the exact bytes, and by
experiment: replacing a case's whole expected block changes the request by zero bytes.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from evals.explanation_cases import (
    ExpectedHardConstraints,
    ExplanationEvalCase,
    ExplanationModelInput,
    ManualCalibration,
    to_model_input,
)
from evals.explanation_dataset import ExplanationDataset, load_explanation_dataset
from evals.explanation_judge import RUBRIC, JudgeRequest, build_judge_request
from evals.explanation_runner import JUDGE_SCRIPT_FILE, SCRIPT_FILE, ScriptedExplanations
from evals.explanation_thresholds import QUALITY_TARGETS, all_thresholds

from promisepatch.semantic import SemanticJob, SemanticMetadata
from promisepatch.semantic.jobs import JOB_SPECS
from promisepatch.semantic.prompts import build_system_instruction, build_user_content


@pytest.fixture(scope="module")
def dataset() -> ExplanationDataset:
    return load_explanation_dataset()


def _sent(case: ExplanationEvalCase) -> str:
    """Every byte a provider would see for this case: instruction, schema and payload."""
    spec = JOB_SPECS[SemanticJob.VERBALISE]
    request = to_model_input(case).request
    return "\n".join(
        [
            build_system_instruction(SemanticJob.VERBALISE),
            json.dumps(spec.tool_schema(), sort_keys=True),
            build_user_content(request),
        ]
    )


# --------------------------------------------------------------- structural absence


def test_a_model_input_has_three_fields_and_one_of_them_is_the_request() -> None:
    """There is no field on the way out that an answer could travel in."""
    assert set(ExplanationModelInput.model_fields) == {"case_id", "family", "request"}


def test_a_model_input_carries_no_correlation_metadata(dataset: ExplanationDataset) -> None:
    for case in dataset.cases:
        assert to_model_input(case).request.metadata == SemanticMetadata()


def test_the_request_is_the_production_projection_and_not_a_harness_copy(
    dataset: ExplanationDataset,
) -> None:
    for case in dataset.cases:
        assert to_model_input(case).request == case.explanation_facts().request()


# ----------------------------------------------------------------- textual absence


def test_no_reference_passage_appears_in_anything_nova_is_sent(
    dataset: ExplanationDataset,
) -> None:
    """The reference is a review anchor. It is not a gold string and not a few-shot example."""
    for case in dataset.cases:
        sent = _sent(case)
        for fragment in case.reference.split(". "):
            assert fragment.strip(" .") not in sent, case.id


def test_no_split_tag_note_or_expectation_appears_in_the_payload_nova_is_sent(
    dataset: ExplanationDataset,
) -> None:
    """Asserted over the per-case payload, which is the only part of the prompt a case shapes.

    The system instruction is fixed text: identical for every case, carrying no value from any
    of them, and separately asserted to name no case at all. Searching it for a word like
    ``quantity`` would only find the sentence forbidding the model from inventing one.
    """
    for case in dataset.cases:
        payload = build_user_content(to_model_input(case).request)
        assert case.split.value not in payload
        for tag in case.tags:
            assert f"tag: {tag.value}" not in payload
            assert f"tags: {tag.value}" not in payload
        assert case.expected.decisive_fact in payload, (
            "the decisive fact is one of the facts, so its id is legitimately present"
        )
        if case.calibration.focus:
            assert case.calibration.focus not in payload
        if case.note:
            assert case.note not in payload


def test_the_system_instruction_is_fixed_text_that_names_no_case(
    dataset: ExplanationDataset,
) -> None:
    instruction = build_system_instruction(SemanticJob.VERBALISE)
    for case in dataset.cases:
        assert case.id not in instruction
        assert case.reference not in instruction
        assert case.calibration.focus not in instruction or not case.calibration.focus


def test_no_threshold_or_rubric_appears_in_anything_nova_is_sent(
    dataset: ExplanationDataset,
) -> None:
    case = dataset.cases[0]
    sent = _sent(case)
    assert "faithfulness" not in sent.lower()
    assert "speech_naturalness" not in sent.lower()
    for threshold in all_thresholds():
        assert threshold.name not in sent
    assert RUBRIC[:80] not in sent


def test_no_reference_passage_appears_in_any_scripted_provider_payload(
    dataset: ExplanationDataset,
) -> None:
    """Even the offline fixtures cannot smuggle a reference into a payload."""
    scripted = SCRIPT_FILE.read_text(encoding="utf-8")
    judged = JUDGE_SCRIPT_FILE.read_text(encoding="utf-8")
    for case in dataset.cases:
        for fragment in case.reference.split(". "):
            trimmed = fragment.strip(" .")
            assert trimmed not in scripted, case.id
            assert trimmed not in judged, case.id


# -------------------------------------------------------------------- by experiment


def test_replacing_a_case_s_whole_expected_block_changes_the_request_by_zero_bytes(
    dataset: ExplanationDataset,
) -> None:
    """The strongest form of the claim: the answer half is not an input to the question half."""
    for case in dataset.cases[:6]:
        rewritten = case.model_copy(
            update={
                "reference": "Everything is fine and the customer already agreed.",
                "expected": ExpectedHardConstraints(
                    word_limit=case.expected.word_limit,
                    required_fact_refs=case.expected.required_fact_refs,
                    decisive_fact=case.expected.decisive_fact,
                    approval_outstanding=not case.expected.approval_outstanding,
                    recovery_permitted=not case.expected.recovery_permitted,
                    supported_numbers=("999",),
                ),
                "calibration": ManualCalibration(focus="expect a five"),
                "note": "this one is adversarial",
            }
        )
        assert _sent(rewritten) == _sent(case)
        assert to_model_input(rewritten).request == to_model_input(case).request


def test_moving_a_case_between_splits_changes_the_request_by_zero_bytes(
    dataset: ExplanationDataset,
) -> None:
    from evals.cases import EvalSplit

    for case in dataset.cases[:6]:
        flipped = case.model_copy(
            update={
                "split": (
                    EvalSplit.HOLDOUT
                    if case.split is EvalSplit.DEVELOPMENT
                    else EvalSplit.DEVELOPMENT
                )
            }
        )
        assert _sent(flipped) == _sent(case)


def test_a_corrective_retry_carries_no_reference_and_no_expectation(
    dataset: ExplanationDataset,
) -> None:
    """The one other place text reaches a provider. It repeats the refusal, nothing else."""
    import asyncio

    from promisepatch.domain import verbalisation
    from promisepatch.semantic import FakeSemanticProvider

    case = dataset.cases[0]
    provider = FakeSemanticProvider(
        {SemanticJob.VERBALISE: [{"speech": "no", "fact_refs": ["nope.nope"]}]}
    )
    asyncio.run(verbalisation.prepare(provider, case.explanation_facts()))
    corrections = [call.correction for call in provider.calls if call.correction]
    assert corrections
    for correction in corrections:
        assert case.reference.split(".")[0] not in correction
        assert case.split.value not in correction
        for tag in case.tags:
            assert tag.value not in correction


# ------------------------------------------------------------------ the judge's input


def test_a_judge_request_has_only_the_facts_and_the_passage(
    dataset: ExplanationDataset,
) -> None:
    fields = {field.name for field in dataclasses.fields(JudgeRequest)}
    assert fields == {
        "case_id",
        "family",
        "subject",
        "facts",
        "required_fact_ids",
        "word_limit",
        "speech",
        "rubric_version",
    }
    case = dataset.cases[0]
    request = build_judge_request(
        case.id, case.family, to_model_input(case).request, "a passage about it"
    )
    content = request.content()
    assert "a passage about it" in content
    assert case.reference not in content
    assert case.split.value not in content
    assert not case.note or case.note not in content
    for tag in case.tags:
        assert tag.value not in content


def test_the_judge_is_never_told_what_verdict_is_wanted(dataset: ExplanationDataset) -> None:
    """No threshold, no expected score, no adversarial marker, in the rubric or in the payload."""
    case = dataset.cases[0]
    content = build_judge_request(
        case.id, case.family, to_model_input(case).request, "a passage"
    ).content()
    whole = RUBRIC + content
    for threshold in QUALITY_TARGETS:
        assert threshold.describe() not in whole
        assert threshold.name not in whole
    for marker in ("holdout", "development", "adversarial", "expected score", "must score"):
        assert marker not in whole.lower()


def test_changing_a_threshold_or_a_disposition_changes_the_judge_request_by_zero_bytes(
    dataset: ExplanationDataset,
) -> None:
    for case in dataset.cases[:6]:
        before = build_judge_request(
            case.id, case.family, to_model_input(case).request, "a passage"
        ).content()
        rewritten = case.model_copy(
            update={
                "reference": "Everything is fine.",
                "calibration": ManualCalibration(focus="expect a five"),
                "note": "adversarial",
            }
        )
        after = build_judge_request(
            rewritten.id, rewritten.family, to_model_input(rewritten).request, "a passage"
        ).content()
        assert before == after


def test_the_rubric_is_fixed_text_and_names_no_case(dataset: ExplanationDataset) -> None:
    for case in dataset.cases:
        assert case.id not in RUBRIC
        assert case.reference not in RUBRIC


def test_the_judge_never_sees_a_previous_verdict(dataset: ExplanationDataset) -> None:
    """There is nowhere on the request to put one, which is why it cannot be sent by mistake."""
    assert "verdict" not in {field.name for field in dataclasses.fields(JudgeRequest)}
    assert "previous" not in RUBRIC.lower()


# ---------------------------------------------------------------- the scripted files


def test_the_scripted_payload_files_are_declared_as_hand_authored(
    dataset: ExplanationDataset,
) -> None:
    """Provenance is part of the artifact. A fixture nobody labelled becomes evidence by drift."""
    for path in (SCRIPT_FILE, JUDGE_SCRIPT_FILE):
        raw = json.loads(path.read_text(encoding="utf-8"))
        provenance = raw["provenance"].lower()
        assert "hand-authored" in provenance
        assert "none came from" in provenance


def test_the_scripted_provider_answers_only_the_case_it_was_asked_about(
    dataset: ExplanationDataset,
) -> None:
    scripted = ScriptedExplanations.from_file()
    for case in dataset.cases:
        assert scripted.for_case(case.id)
    assert scripted.for_case("explain.nope.001") == []
