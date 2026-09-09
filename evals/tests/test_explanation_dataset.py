"""The explanation dataset is an instrument, and these are its calibration checks.

A fixture describing a state the engine cannot reach measures nothing while looking exactly like
a measurement, so almost every test here compares the dataset against production rather than
against another statement in the dataset. The engine's own ``revalidate`` is run to pin the
check names; the projection's own closed vocabularies decide which phrases are legal; the
deterministic renderer decides whether a passage is possible at all.

The holdout is checked without being read. Counts, families, splits and ids are assertable and
prose is not: a failure message that dumped a sealed passage would have unsealed it in the CI
log of the run that was protecting it.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from evals.cases import EvalSplit
from evals.explanation_cases import (
    ExplanationEvalCase,
    ExplanationFamily,
    ExplanationTag,
    FactFixture,
    FactsFixture,
    supported_digits,
)
from evals.explanation_dataset import (
    CASES_FILE,
    CASES_PER_FAMILY,
    CONSTRAINT_PHRASE_OF,
    DEVELOPMENT_PER_FAMILY,
    HOLDOUT_PER_FAMILY,
    REASONS_FOR,
    REQUIRED_TAGS,
    REVALIDATION_CHECKS,
    TOTAL_CASES,
    ExplanationDataset,
    calibration_problems,
    expected_required,
    load_calibration,
    load_explanation_dataset,
    manifest_problems,
    validate_explanation_dataset,
)
from pydantic import ValidationError

from promise_graph.availability import apply_exception_facts
from promise_graph.classification import analyze
from promise_graph.examples import hollow_oak as ho
from promise_graph.fingerprint import constraint_hash, fingerprint, scope_for
from promise_graph.model import (
    ApprovalDecisionKind,
    ApprovalDecisionRecord,
    ApprovalRequestRecord,
    Classification,
    ParserKind,
    ReasonDetail,
)
from promise_graph.options import approval_deadline
from promise_graph.revalidation import revalidate
from promisepatch.domain.explanations import (
    CLOSED_VOCABULARIES,
    CONSTRAINT_PREFIXES,
    WORD_LIMITS,
    ExplanationSurface,
    FactId,
    render,
)


@pytest.fixture(scope="module")
def dataset() -> ExplanationDataset:
    return load_explanation_dataset()


# --------------------------------------------------------------------------- the shape


def test_the_dataset_is_thirty_five_cases_in_seven_families(dataset: ExplanationDataset) -> None:
    assert len(dataset.cases) == TOTAL_CASES
    assert len(ExplanationFamily) == 7
    for family in ExplanationFamily:
        assert len(dataset.family(family)) == CASES_PER_FAMILY


def test_every_family_splits_three_development_and_two_holdout(
    dataset: ExplanationDataset,
) -> None:
    """Checked by counting. Nothing in this assertion can print a sealed passage."""
    for family in ExplanationFamily:
        cases = dataset.family(family)
        development = [case for case in cases if case.split is EvalSplit.DEVELOPMENT]
        holdout = [case for case in cases if case.split is EvalSplit.HOLDOUT]
        assert len(development) == DEVELOPMENT_PER_FAMILY, family.value
        assert len(holdout) == HOLDOUT_PER_FAMILY, family.value
    assert sum(case.split is EvalSplit.DEVELOPMENT for case in dataset.cases) == 21
    assert sum(case.split is EvalSplit.HOLDOUT for case in dataset.cases) == 14


def test_the_dataset_validates_against_production(dataset: ExplanationDataset) -> None:
    assert validate_explanation_dataset(dataset) == ()


def test_the_committed_manifest_describes_the_dataset(dataset: ExplanationDataset) -> None:
    assert manifest_problems(dataset, dataset.manifest()) == ()


def test_the_dataset_hash_moves_when_a_case_changes(dataset: ExplanationDataset) -> None:
    """The identity is over content, so an edit nobody meant to make cannot arrive unannounced."""
    before = dataset.content_hash
    edited = dataset.cases[0].model_copy(update={"note": "edited"})
    after = ExplanationDataset(
        version=dataset.version,
        provenance=dataset.provenance,
        cases=(edited, *dataset.cases[1:]),
    ).content_hash
    assert before != after


def test_a_case_id_says_nothing_about_its_split(dataset: ExplanationDataset) -> None:
    """Ids are stable names, not labels. A run that leaked one leaks no split with it."""
    for case in dataset.cases:
        assert "development" not in case.id
        assert "holdout" not in case.id
        assert case.split.value not in case.id


# ------------------------------------------------------------------ production coherence


def test_every_closed_vocabulary_value_is_one_production_emits(
    dataset: ExplanationDataset,
) -> None:
    for case in dataset.cases:
        for fixture in case.facts.facts:
            vocabulary = CLOSED_VOCABULARIES.get(fixture.id)
            if vocabulary is not None:
                assert fixture.value in set(vocabulary.values()), (case.id, fixture.id.value)


def test_every_required_set_is_the_one_production_would_compute(
    dataset: ExplanationDataset,
) -> None:
    """A case cannot demand more or less of a passage than the workflow would."""
    for case in dataset.cases:
        assert tuple(case.facts.required) == expected_required(case.facts), case.id


def test_every_case_builds_the_production_request_and_nothing_wider(
    dataset: ExplanationDataset,
) -> None:
    for case in dataset.cases:
        request = case.explanation_facts().request()
        assert request.word_limit == WORD_LIMITS[case.surface]
        assert {fact.id for fact in request.facts} == case.facts.ids()
        assert set(request.required_fact_ids) == {fact_id.value for fact_id in case.facts.required}


def test_every_track_case_pairs_an_outcome_with_a_reason_the_classifier_can_produce(
    dataset: ExplanationDataset,
) -> None:
    reason_of = {phrase: detail for detail, phrase in _reason_phrases().items()}
    for case in dataset.cases:
        if case.surface is not ExplanationSurface.TRACK_OUTCOME:
            continue
        outcome = case.facts.value_of(FactId.IMPACT_OUTCOME)
        reason = reason_of[case.facts.value_of(FactId.IMPACT_REASON) or ""]
        classification = next(
            member
            for member in Classification
            if CLOSED_VOCABULARIES[FactId.IMPACT_OUTCOME][member.value] == outcome
        )
        assert reason in REASONS_FOR[classification], case.id


def _reason_phrases() -> dict[ReasonDetail, str]:
    return {
        detail: CLOSED_VOCABULARIES[FactId.IMPACT_REASON][detail.value] for detail in ReasonDetail
    }


def test_the_engine_still_names_the_ten_checks_this_dataset_names() -> None:
    """Runs the real revalidation, so a renamed check breaks here rather than in a fixture.

    The dataset's check table is a restatement -- the engine holds those names as literals inside
    one function and exports neither them nor the outcome each failure produces. This is what
    pins the restatement to the thing it restates.
    """
    anchor = ho.ANCHOR
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    settled = apply_exception_facts(snapshot, exception, anchor).snapshot
    analysis = analyze(settled, exception, anchor)
    option = analysis.option_sets[ho.PROMISE_B].valid[0]
    task = settled.task_of_line(ho.LINE_B)
    assert task is not None and task.scheduled_start is not None
    request = ApprovalRequestRecord(
        id="req-b",
        track_id="trk-b",
        promise_id=ho.PROMISE_B,
        order_id=ho.ORDER_B,
        order_line_id=ho.LINE_B,
        option_id=option.id,
        candidate_version_id=option.to_version_id,
        substitute_resource_id=option.substitute_resource_id,
        required_substitute_quantity=option.required_quantity,
        customer_channel="tg:1002",
        sent_at=anchor,
        deadline=approval_deadline(anchor, task.scheduled_start),
        captured_fingerprint=fingerprint(
            settled,
            scope_for(settled, analysis.impact, analysis.option_sets[ho.PROMISE_B], ho.PROMISE_B),
        ).hash,
        captured_order_version=settled.orders[ho.ORDER_B].external_version,
        captured_recipe_version_id=settled.order_lines[ho.LINE_B].recipe_version_id,
        captured_constraint_hash=constraint_hash(settled, ho.ORDER_B),
    )
    decision = ApprovalDecisionRecord(
        request_id=request.id,
        decision=ApprovalDecisionKind.APPROVE,
        parser=ParserKind.LITERAL,
        sender_identity="tg:1002",
        provider_message_id="msg-1",
        received_at=anchor,
    )
    result = revalidate(
        settled,
        request,
        decision,
        anchor + timedelta(minutes=5),
        track_is_waiting_for_customer=True,
        case_is_waiting=True,
    )
    names = {check.name for check in result.checks}
    assert names <= set(REVALIDATION_CHECKS), sorted(names - set(REVALIDATION_CHECKS))


def test_the_constraint_phrases_are_productions_own(dataset: ExplanationDataset) -> None:
    assert set(CONSTRAINT_PHRASE_OF.values()) == set(CONSTRAINT_PREFIXES)


def test_every_case_renders_deterministically_inside_its_own_cap(
    dataset: ExplanationDataset,
) -> None:
    """The fallback holds on every fixture, including the ones no model is ever asked about."""
    for case in dataset.cases:
        passage = render(case.explanation_facts())
        assert passage.strip()
        assert len(passage.split()) <= case.word_limit, case.id


def test_the_deterministic_passage_carries_the_fact_the_outcome_turns_on(
    dataset: ExplanationDataset,
) -> None:
    for case in dataset.cases:
        facts = case.explanation_facts()
        decisive = facts.value_of(FactId(case.expected.decisive_fact))
        assert decisive is not None
        assert decisive.lower() in render(facts).lower(), case.id


# --------------------------------------------------------------------------- coverage


def test_the_canonical_four_anchor_the_development_split(dataset: ExplanationDataset) -> None:
    """Priya automatic, Tomas needing approval, the wedding blocked, Lena untouched."""
    canonical = {
        case.id: case
        for case in dataset.cases
        if ExplanationTag.CANONICAL in case.tags and case.split is EvalSplit.DEVELOPMENT
    }
    families = {case.family for case in canonical.values()}
    assert ExplanationFamily.TRACK_AUTO_RECOVERABLE in families
    assert ExplanationFamily.TRACK_APPROVAL_REQUIRED in families
    assert ExplanationFamily.TRACK_BLOCKED in families
    assert ExplanationFamily.TRACK_UNAFFECTED in families
    assert ExplanationFamily.CUSTOMER_WAIT in families
    assert ExplanationFamily.REVALIDATION in families
    assert ExplanationFamily.PLAN_SUMMARY in families

    priya = canonical["explain.auto.001"]
    assert priya.facts.value_of(FactId.PROMISE_CUSTOMER) == "Priya Nair"
    assert (
        priya.facts.value_of(FactId.IMPACT_REASON)
        == _reason_phrases()[ReasonDetail.PREAPPROVAL_COVERS]
    )
    lena = canonical["explain.unaffected.001"]
    assert lena.facts.value_of(FactId.PROMISE_ITEM) == "Lemon Curd Layer v1"
    assert (
        lena.facts.value_of(FactId.IMPACT_REASON) == _reason_phrases()[ReasonDetail.NOT_REACHABLE]
    )
    wedding = canonical["explain.blocked.001"]
    assert (
        wedding.facts.value_of(FactId.IMPACT_REASON)
        == _reason_phrases()[ReasonDetail.NOSUB_CONSTRAINT]
    )


def test_every_claimed_coverage_dimension_has_a_case(dataset: ExplanationDataset) -> None:
    used = {tag for case in dataset.cases for tag in case.tags}
    assert used >= REQUIRED_TAGS


def test_the_dataset_covers_the_deterministic_distinctions_it_claims(
    dataset: ExplanationDataset,
) -> None:
    """The reason codes and postures a passage has to keep apart, all present at least once."""
    reasons = {
        case.facts.value_of(FactId.IMPACT_REASON)
        for case in dataset.cases
        if case.surface is ExplanationSurface.TRACK_OUTCOME
    }
    phrases = _reason_phrases()
    for detail in (
        ReasonDetail.PREAPPROVAL_COVERS,
        ReasonDetail.NOT_VISIBLE_NO_ASK,
        ReasonDetail.EQUIPMENT_REASSIGNED,
        ReasonDetail.VISIBLE_CHANGE_ASK,
        ReasonDetail.NOT_PREAPPROVED,
        ReasonDetail.NOSUB_CONSTRAINT,
        ReasonDetail.NO_PREAUTHORED_VARIANT,
        ReasonDetail.EXCLUDED_SUBSTITUTE,
        ReasonDetail.INSUFFICIENT_SUBSTITUTE_STOCK,
        ReasonDetail.UNKNOWN_QUANTITY,
        ReasonDetail.NOT_REACHABLE,
        ReasonDetail.SHORTFALL_COVERED,
    ):
        assert phrases[detail] in reasons, detail.value

    checks = {
        case.facts.value_of(FactId.REVALIDATION_CHECK)
        for case in dataset.cases
        if case.family is ExplanationFamily.REVALIDATION
    }
    assert checks == {
        "pinned recipe version unchanged",
        "order state and version unchanged",
        "approval deadline not passed",
        "constraint snapshot unchanged",
        "substitute still available",
    }

    states = {
        case.facts.value_of(FactId.APPROVAL_STATE)
        for case in dataset.cases
        if case.family is ExplanationFamily.CUSTOMER_WAIT
    }
    assert len(states) >= 4


def test_a_case_with_no_quantified_shortfall_states_no_quantity(
    dataset: ExplanationDataset,
) -> None:
    """Unknown quantity fails closed to blocked, and no number may then appear anywhere."""
    unknown = next(case for case in dataset.cases if case.id == "explain.blocked.003")
    quantities = {
        FactId.RESOURCE_AFFECTED.value,
        FactId.RESOURCE_REQUIRED.value,
        FactId.RESOURCE_AVAILABLE.value,
        FactId.RESOURCE_SHORTFALL.value,
    }
    assert not (unknown.facts.ids() & quantities)
    assert unknown.expected.supported_numbers == tuple(sorted(supported_digits(unknown.facts)))
    # The digits this case does supply are an order reference and a version suffix -- an
    # identifier and a name, not an amount. There is no quantity here for a passage to restate,
    # which is the invention the case exists to expose.
    assert "kg" not in " ".join(fixture.value for fixture in unknown.facts.facts)


def test_instruction_shaped_data_is_carried_as_a_value(dataset: ExplanationDataset) -> None:
    """A consent-shaped order reference and an instruction-shaped trade name are both just data."""
    catering = next(case for case in dataset.cases if case.id == "explain.auto.004")
    assert "ignore instructions" in (catering.facts.value_of(FactId.PROMISE_CUSTOMER) or "")
    wait = next(case for case in dataset.cases if case.id == "explain.wait.003")
    assert (wait.facts.value_of(FactId.PROMISE_ORDER) or "").startswith("YES-")
    assert wait.expected.approval_outstanding


# ------------------------------------------------------------------- schema strictness


def test_a_case_refuses_an_unknown_field() -> None:
    payload = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"][0]
    with pytest.raises(ValidationError):
        ExplanationEvalCase.model_validate({**payload, "expected_score": 5})


def test_a_case_refuses_a_tag_outside_the_controlled_vocabulary() -> None:
    payload = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"][0]
    with pytest.raises(ValidationError):
        ExplanationEvalCase.model_validate({**payload, "tags": ["tricky"]})


def test_a_facts_fixture_refuses_a_required_fact_it_did_not_supply() -> None:
    with pytest.raises(ValidationError):
        FactsFixture(
            surface=ExplanationSurface.CUSTOMER_WAIT,
            facts=(FactFixture(id=FactId.APPROVAL_STATE, label="where", value="asked"),),
            required=(FactId.CONSENT_AUTHORITY,),
        )


def test_a_facts_fixture_refuses_two_facts_sharing_an_id() -> None:
    with pytest.raises(ValidationError):
        FactsFixture(
            surface=ExplanationSurface.CUSTOMER_WAIT,
            facts=(
                FactFixture(id=FactId.APPROVAL_STATE, label="where", value="asked"),
                FactFixture(id=FactId.APPROVAL_STATE, label="where", value="again"),
            ),
            required=(FactId.APPROVAL_STATE,),
        )


def test_validation_catches_a_phrase_the_engine_cannot_emit(
    dataset: ExplanationDataset,
) -> None:
    """The check that stops a plausible hand-written reason entering the dataset."""
    case = next(case for case in dataset.cases if case.family is ExplanationFamily.TRACK_BLOCKED)
    facts = case.facts.model_dump()
    facts["facts"] = [dict(entry) for entry in facts["facts"]]
    for fixture in facts["facts"]:
        if fixture["id"] == FactId.IMPACT_REASON.value:
            fixture["value"] = "the ingredient is simply unavailable"
    broken = case.model_copy(update={"facts": FactsFixture.model_validate(facts)})
    problems = validate_explanation_dataset(
        ExplanationDataset(version=dataset.version, provenance="", cases=(broken,))
    )
    assert any("is not a phrase" in problem for problem in problems)


def test_validation_catches_facts_in_an_order_no_projection_produces(
    dataset: ExplanationDataset,
) -> None:
    case = next(case for case in dataset.cases if case.family is ExplanationFamily.CUSTOMER_WAIT)
    facts = case.facts.model_dump()
    ordered = list(facts["facts"])
    facts["facts"] = [ordered[1], ordered[0], *ordered[2:]]
    broken = case.model_copy(update={"facts": FactsFixture.model_validate(facts)})
    problems = validate_explanation_dataset(
        ExplanationDataset(version=dataset.version, provenance="", cases=(broken,))
    )
    assert any("order the" in problem for problem in problems)


def test_validation_catches_a_blocked_promise_offered_a_recovery(
    dataset: ExplanationDataset,
) -> None:
    """The fixture-level half of the rule the TRACK_BLOCKED gate enforces at run time."""
    case = next(case for case in dataset.cases if case.id == "explain.blocked.002")
    facts = case.facts.model_dump()
    facts["facts"] = [*facts["facts"]]
    facts["facts"].append(
        {
            "id": FactId.RECOVERY_OPTION.value,
            "label": "recovery",
            "value": CLOSED_VOCABULARIES[FactId.RECOVERY_OPTION]["SUBSTITUTE_RESOURCE"],
        }
    )
    broken = case.model_copy(update={"facts": FactsFixture.model_validate(facts)})
    problems = validate_explanation_dataset(
        ExplanationDataset(version=dataset.version, provenance="", cases=(broken,))
    )
    assert any("chooses no option" in problem for problem in problems)


# ------------------------------------------------------------------------ calibration


def test_the_calibration_set_is_five_development_examples(dataset: ExplanationDataset) -> None:
    examples = load_calibration()
    assert len(examples) == 5
    assert calibration_problems(dataset, examples) == ()
    by_id = {case.id: case for case in dataset.cases}
    for example in examples:
        assert by_id[example.case_id].split is EvalSplit.DEVELOPMENT


def test_the_calibration_set_covers_the_five_shapes_a_judge_has_to_tell_apart() -> None:
    examples = {example.id: example for example in load_calibration()}
    assert set(examples) == {
        "calibrate.excellent",
        "calibrate.incomplete",
        "calibrate.wordy",
        "calibrate.authority",
        "calibrate.invented",
    }
    excellent = examples["calibrate.excellent"]
    assert not any(excellent.expected_flags().values())
    assert excellent.faithfulness_range == (5, 5)

    incomplete = examples["calibrate.incomplete"]
    assert not any(incomplete.expected_flags().values())
    assert incomplete.faithfulness_range[0] >= 4
    assert incomplete.causal_completeness_range[1] <= 2

    authority = examples["calibrate.authority"]
    assert authority.expect_authority_contradiction
    assert authority.expect_outcome_contradiction
    assert authority.clarity_range[0] >= 4, (
        "clarity stays high on purpose: a subjective score must never offset a hard flag"
    )

    invented = examples["calibrate.invented"]
    assert invented.expect_unsupported_entity_or_option
    assert examples["calibrate.wordy"].brevity_range[1] <= 2


def test_no_calibration_candidate_would_have_survived_production(
    dataset: ExplanationDataset,
) -> None:
    """A candidate longer than the cap would never reach a judge, so it cannot calibrate one."""
    by_id = {case.id: case for case in dataset.cases}
    for example in load_calibration():
        assert len(example.candidate.split()) <= by_id[example.case_id].word_limit


# -------------------------------------------------------------------- holdout secrecy


def test_no_committed_artifact_names_which_cases_are_sealed_outside_the_dataset() -> None:
    """The split lives in one file. Nothing else in the package repeats a holdout case id."""
    holdout = {
        case.id for case in load_explanation_dataset().cases if case.split is EvalSplit.HOLDOUT
    }
    package = Path(__file__).resolve().parents[1]
    for path in sorted(package.rglob("*.py")):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        assert not (holdout & {case_id for case_id in holdout if case_id in text}), path.name


def test_validation_messages_never_quote_a_holdout_passage(
    dataset: ExplanationDataset,
) -> None:
    """A broken holdout case is reported by id and by rule, never by reading it out."""
    sealed = next(case for case in dataset.cases if case.split is EvalSplit.HOLDOUT)
    broken = sealed.model_copy(
        update={"expected": sealed.expected.model_copy(update={"word_limit": 5})}
    )
    problems = validate_explanation_dataset(
        ExplanationDataset(version=dataset.version, provenance="", cases=(broken,))
    )
    joined = " ".join(problems)
    assert broken.id in joined
    assert sealed.reference not in joined


def test_a_view_keeps_the_identity_of_the_dataset_it_was_cut_from(
    dataset: ExplanationDataset,
) -> None:
    """A split or a narrowed selection is the same dataset, selected differently.

    The hash a run records against is the one the manifest, the header and the authorisation
    name. A view that hashed only the cases it holds would let a resumed run stamp its records
    with the identity of whatever happened to be outstanding, which is not a dataset anybody
    froze.
    """
    frozen = dataset.content_hash
    development = dataset.split([EvalSplit.DEVELOPMENT])
    assert development.content_hash == frozen
    assert 0 < len(development.cases) < len(dataset.cases)

    one = development.select([development.cases[0].id])
    assert len(one.cases) == 1
    assert one.content_hash == frozen

    assert dataset.split(None) is dataset
    assert dataset.select([]).content_hash == frozen


def test_the_hash_of_a_loaded_dataset_is_still_over_its_own_content(
    dataset: ExplanationDataset,
) -> None:
    """The identity is inherited by views only. The dataset as loaded still hashes its cases."""
    rebuilt = ExplanationDataset(
        version=dataset.version, provenance=dataset.provenance, cases=dataset.cases
    )
    assert rebuilt.identity_hash is None
    assert rebuilt.content_hash == dataset.content_hash
    fewer = ExplanationDataset(
        version=dataset.version, provenance=dataset.provenance, cases=dataset.cases[1:]
    )
    assert fewer.content_hash != dataset.content_hash
