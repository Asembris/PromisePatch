"""Evidence assembly: one rendering for the UI, the audit ledger and the plan summary."""

from __future__ import annotations

import json
from datetime import datetime

from promise_graph.evidence import Reachability, build_case_evidence, build_promise_evidence
from promise_graph.fingerprint import canonical_json
from promise_graph.model import Classification
from tests.fixtures import adversarial as adv
from tests.fixtures import hollow_oak as ho
from tests.fixtures import settle, settle_and_analyze


def test_case_evidence_separates_affected_from_untouched(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    evidence = build_case_evidence(settled, settle_and_analyze(snapshot, exception, anchor), anchor)

    assert evidence.exception_id == exception.id
    assert evidence.entry_node_refs == (ho.VP_TODAY_RASPBERRY,)
    assert evidence.affected_promise_ids == (ho.PROMISE_A, ho.PROMISE_B, ho.PROMISE_C)
    assert evidence.unaffected_promise_ids == (ho.PROMISE_D, ho.PROMISE_E, ho.PROMISE_F)


def test_promise_evidence_carries_paths_rules_and_arithmetic(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    analysis = settle_and_analyze(snapshot, exception, anchor)
    evidence = build_promise_evidence(settled, analysis, ho.PROMISE_B, anchor)

    assert evidence.reachability is Reachability.AFFECTED
    assert evidence.order_id == ho.ORDER_B
    assert evidence.customer_id == "cus-tomas"
    assert evidence.paths
    assert evidence.quantifications[0].shortfall is not None
    assert {view.resource_id for view in evidence.availability} == {
        ho.RASPBERRIES,
        ho.STRAWBERRIES,
    }
    assert evidence.classification.classification is Classification.APPROVAL_REQUIRED
    assert len(evidence.valid_options) == 1


def test_citations_carry_provenance(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    analysis = settle_and_analyze(snapshot, exception, anchor)
    evidence = build_promise_evidence(settled, analysis, ho.PROMISE_C, anchor)
    assert [citation.id for citation in evidence.citations] == [ho.CONSTRAINT_C_NOSUB]
    assert evidence.citations[0].recorded_by == ho.AUTHOR
    assert evidence.citations[0].recorded_at
    assert evidence.citations[0].kind == "NO_SUBSTITUTION"


def test_unaffected_promises_render_as_no_path(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    analysis = settle_and_analyze(snapshot, exception, anchor)
    evidence = build_promise_evidence(settled, analysis, ho.PROMISE_D, anchor)
    assert evidence.reachability is Reachability.NO_PATH
    assert evidence.paths == ()
    assert evidence.valid_options == ()
    assert evidence.rejected_candidates == ()
    assert evidence.availability == ()


def test_reachable_but_covered_renders_distinctly(anchor: datetime) -> None:
    snapshot = adv.with_ample_raspberries(ho.with_lena_mutation(ho.hollow_oak(anchor)))
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    analysis = settle_and_analyze(snapshot, exception, anchor)
    evidence = build_promise_evidence(settled, analysis, ho.PROMISE_A, anchor)
    assert evidence.reachability is Reachability.REACHABLE_COVERED
    assert evidence.paths


def test_rejected_candidates_are_kept_as_evidence(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.whole_delivery(anchor)
    settled = settle(snapshot, exception, anchor)
    analysis = settle_and_analyze(snapshot, exception, anchor)
    evidence = build_promise_evidence(settled, analysis, ho.PROMISE_A, anchor)
    assert evidence.valid_options == ()
    assert evidence.rejected_candidates
    assert evidence.rejected_candidates[0].note


def test_evidence_is_json_serialisable(anchor: datetime) -> None:
    """The same record feeds the screen and the audit payload, so it must serialise."""
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.raspberry_only(anchor)
    settled = settle(snapshot, exception, anchor)
    analysis = settle_and_analyze(snapshot, exception, anchor)
    payload = canonical_json(build_case_evidence(settled, analysis, anchor))
    decoded = json.loads(payload)
    assert decoded["exception_id"] == exception.id
    assert set(decoded["promises"]) == set(settled.promises)


def test_equipment_evidence_names_the_alternative(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    exception = ho.deck_oven_down(anchor)
    settled = settle(snapshot, exception, anchor)
    analysis = settle_and_analyze(snapshot, exception, anchor)
    evidence = build_promise_evidence(settled, analysis, ho.PROMISE_A, anchor)
    assert evidence.valid_options[0].to_equipment_id == ho.CONVECTION_OVEN
    assert evidence.quantifications == ()


def test_availability_falls_back_to_now_without_a_task(anchor: datetime) -> None:
    snapshot = ho.with_lena_mutation(ho.hollow_oak(anchor))
    tasks = {
        task_id: task for task_id, task in snapshot.tasks.items() if task.order_line_id != ho.LINE_E
    }
    trimmed = snapshot.replace(tasks=tasks)
    exception = ho.cream_unusable(anchor)
    settled = settle(trimmed, exception, anchor)
    analysis = settle_and_analyze(trimmed, exception, anchor)
    evidence = build_promise_evidence(settled, analysis, ho.PROMISE_E, anchor)
    assert all(view.at == anchor for view in evidence.availability)
