"""Fixture package: hand-authored deterministic data and one shared driver helper."""

from __future__ import annotations

from datetime import datetime

from promise_graph.availability import apply_exception_facts
from promise_graph.classification import AnalysisResult, analyze
from promise_graph.model import Classification, PhysicalException, PromiseId
from promise_graph.snapshot import GraphSnapshot


def settle(snapshot: GraphSnapshot, exception: PhysicalException, now: datetime) -> GraphSnapshot:
    """Persist the exception's physical facts into the snapshot, as the case engine would."""
    return apply_exception_facts(snapshot, exception, now).snapshot


def settle_and_analyze(
    snapshot: GraphSnapshot, exception: PhysicalException, now: datetime
) -> AnalysisResult:
    """The Phase-2 sequence, minus persistence: attest the facts, then classify."""
    return analyze(settle(snapshot, exception, now), exception, now)


def classifications(analysis: AnalysisResult) -> dict[PromiseId, Classification]:
    return {
        promise_id: result.classification for promise_id, result in analysis.classifications.items()
    }
