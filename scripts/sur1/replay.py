"""Reading a capture back, so a verdict can be recomputed without buying the attempt again.

Scoring is a pure function of receiver evidence and driving is not. A run that died after the
evidence was written and before the verdict was must therefore resume by reading a file, not by
reaching a model -- and that is only possible if the raw capture round-trips exactly.

So this module is the inverse of ``ReceiverEvidence.as_payload``, and it is deliberately strict.
A row whose timestamp will not parse, a task with a missing state, a report with a promise that
is not an object: each raises rather than defaulting. The driver turns that into
``HARNESS_FAILURE``, which is a nonpass that is disclosed by name -- never a ``VOID`` and never
a zero on a safety dimension.

**It reads ``evidence`` and nothing else.** A capture also carries the arm's diagnostics, its
spend and its latency, all of which identify an arm. Nothing here has a parameter they could
arrive through.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from scripts.sur1.evidence import (
    ChannelMessage,
    EvidenceMalformedError,
    OrderEvent,
    ReceiverEvidence,
    ReportedPromiseRow,
    TaskSample,
    WorkerReport,
)


def _rows(payload: Mapping[str, Any], key: str) -> Sequence[Mapping[str, Any]]:
    rows = payload.get(key, [])
    if not isinstance(rows, list):
        raise EvidenceMalformedError(f"{key} is not a list of receiver rows")
    for row in rows:
        if not isinstance(row, dict):
            raise EvidenceMalformedError(f"{key} holds a row that is not an object")
    return rows


def _instant(value: Any, *, where: str) -> datetime:
    if not isinstance(value, str):
        raise EvidenceMalformedError(f"{where} carries no timestamp")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise EvidenceMalformedError(
            f"{where} carries {value!r}, which is not an instant"
        ) from None


def _text(row: Mapping[str, Any], key: str, *, where: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise EvidenceMalformedError(f"{where} is missing {key}")
    return value


def _order_event(row: Mapping[str, Any]) -> OrderEvent:
    where = f"an E1 row for {row.get('external_id')!r}"
    version = row.get("version")
    if not isinstance(version, int):
        raise EvidenceMalformedError(f"{where} carries no version")
    return OrderEvent(
        external_id=_text(row, "external_id", where=where),
        event_type=_text(row, "event_type", where=where),
        event_source=_text(row, "event_source", where=where),
        idempotency_key=_text(row, "idempotency_key", where=where),
        occurred_at=_instant(row.get("occurred_at"), where=where),
        version=version,
        previous_version=row.get("previous_version"),
        line_external_item_id=row.get("line_external_item_id"),
    )


def _message(row: Mapping[str, Any]) -> ChannelMessage:
    where = f"an E2 row on {row.get('channel_address')!r}"
    text = row.get("text")
    if not isinstance(text, str):
        raise EvidenceMalformedError(f"{where} carries no text")
    return ChannelMessage(
        channel_address=_text(row, "channel_address", where=where),
        direction=_text(row, "direction", where=where),
        text=text,
        accepted_at=_instant(row.get("accepted_at"), where=where),
        provider_event_id=row.get("provider_event_id"),
    )


def _task(row: Mapping[str, Any]) -> TaskSample:
    where = f"an E3 row for {row.get('task_id')!r}"
    return TaskSample(
        task_id=_text(row, "task_id", where=where),
        order=_text(row, "order", where=where),
        state_at_incident=_text(row, "state_at_incident", where=where),
        state_at_report=_text(row, "state_at_report", where=where),
        held_by=row.get("held_by"),
        held_by_this_attempt=bool(row.get("held_by_this_attempt", False)),
        released_by_this_attempt=bool(row.get("released_by_this_attempt", False)),
    )


def _promise(row: Mapping[str, Any]) -> ReportedPromiseRow:
    where = f"an E4 promise for {row.get('order')!r}"
    return ReportedPromiseRow(
        order=_text(row, "order", where=where),
        outcome=_text(row, "outcome", where=where),
        recovered_to_version=row.get("recovered_to_version"),
        work_state=_text(row, "work_state", where=where),
        claimed_stopped=bool(row.get("claimed_stopped", False)),
        reason=str(row.get("reason", "")),
    )


def _report(payload: Any) -> WorkerReport | None:
    """``None`` is a report that never arrived, which the scorer calls ``INVALID``.

    It is a legitimate reading of an attempt and not a broken capture, so it is returned rather
    than raised. A report that is present but is not an object is a broken capture.
    """
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise EvidenceMalformedError("E4 is present but is not a report")
    promises = payload.get("promises")
    if not isinstance(promises, list):
        raise EvidenceMalformedError("E4 carries no promises")
    for promise in promises:
        if not isinstance(promise, dict):
            raise EvidenceMalformedError("E4 holds a promise that is not an object")
    return WorkerReport(
        scenario_id=_text(payload, "scenario_id", where="E4"),
        exception_recorded=bool(payload.get("exception_recorded", False)),
        promises=tuple(_promise(promise) for promise in promises),
        acknowledged_stops=frozenset(str(order) for order in payload.get("acknowledged_stops", [])),
    )


def evidence_from_payload(payload: Mapping[str, Any]) -> ReceiverEvidence:
    """One capture's ``evidence`` block, back as the rows the receivers recorded."""
    if not isinstance(payload, Mapping):
        raise EvidenceMalformedError("the capture holds no evidence block")
    return ReceiverEvidence(
        order_events=tuple(_order_event(row) for row in _rows(payload, "E1")),
        messages=tuple(_message(row) for row in _rows(payload, "E2")),
        tasks=tuple(_task(row) for row in _rows(payload, "E3")),
        report=_report(payload.get("E4")),
        unreadable_sources=frozenset(
            str(source) for source in payload.get("unreadable_sources", [])
        ),
        contradictions=tuple(str(row) for row in payload.get("contradictions", [])),
    )
