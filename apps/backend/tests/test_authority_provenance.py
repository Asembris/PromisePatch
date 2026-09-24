"""Whose authority a recovery carries, from the amendment it emits to the audit that finishes it.

Two rows in the ledger speak for one recovery: ``RECOVERY_APPLIED``, written in the transaction
that queues the amendment for the order system, and ``RECOVERY_COMPLETED``, written once that
amendment is durably delivered and the track settles ``RECOVERED``. They must name the same
authority, because they describe one change.

Until Phase 7 the second did not ask: completion recorded ``POLICY`` (or ``CONSTRAINT``) for every
track, so a change a customer approved finished in the ledger as if a pre-authored policy had
permitted it. The approval was still visible on the first row; the row that says the change is
done said something else. These two tests pin both directions:

- an automatic recovery never claims a customer's approval, at either row;
- a customer-approved recovery keeps ``HUMAN_APPROVAL`` and the same request and decision all the
  way to completion.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from _intake_support import TOMAS_CHANNEL, Intake
from _intake_support import physical as physical
from test_recovery_revalidation import amendments_for, approved_case, track_of

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import ParserKind
from promisepatch.domain import recovery

pytestmark = pytest.mark.integration

A, B = ho.PROMISE_A, ho.PROMISE_B

_CONSENT_KEYS = ("approval_request_id", "approval_decision_id", "customer_decision", "parser")


async def recovery_rows(intake: Intake, case_id: UUID, track_id: UUID) -> tuple[Any, Any]:
    """The one applied and the one completed audit row for a track."""
    rows = [row for row in await intake.audits(case_id) if row.track_id == track_id]
    [applied] = [row for row in rows if row.type == recovery.AUDIT_RECOVERY_APPLIED]
    [completed] = [row for row in rows if row.type == recovery.AUDIT_RECOVERY_COMPLETED]
    return applied, completed


async def test_an_automatic_recovery_never_claims_a_customer_s_approval(physical: Intake) -> None:
    """A recovers under the order's standing preference, in a case where B's customer said yes.

    The sibling's consent is in the same case and the same ledger; none of it reaches A's rows.
    """
    case_id, _ = await approved_case(physical)
    track_a = await track_of(physical, case_id, A)
    await physical.drain(limit=40)

    assert (await track_of(physical, case_id, A)).state == recovery.TRACK_RECOVERED
    [amendment] = await amendments_for(physical, track_a.id)
    assert amendment.state == "DELIVERED"

    applied, completed = await recovery_rows(physical, case_id, track_a.id)
    assert applied.authority in {"POLICY", "CONSTRAINT"}
    assert completed.authority == applied.authority
    for row in (applied, completed):
        assert row.authority != "HUMAN_APPROVAL"
        assert not set(_CONSENT_KEYS) & set(row.provenance)
    assert completed.after["idempotency_key"] == amendment.idempotency_key


async def test_a_customer_approved_recovery_keeps_its_authority_to_completion(
    physical: Intake,
) -> None:
    """B's change is Tomas's, from the amendment the order system receives to the settled row."""
    case_id, request = await approved_case(physical)
    track_b = await track_of(physical, case_id, B)
    await physical.drain(limit=40)

    assert (await track_of(physical, case_id, B)).state == recovery.TRACK_RECOVERED
    [amendment] = await amendments_for(physical, track_b.id)
    assert amendment.state == "DELIVERED"
    assert amendment.payload["option_id"] == str(request.option_id)

    [decision] = await physical.decisions()
    applied, completed = await recovery_rows(physical, case_id, track_b.id)
    for row in (applied, completed):
        assert row.authority == "HUMAN_APPROVAL"
        assert row.provenance["approval_request_id"] == str(request.id)
        assert row.provenance["approval_decision_id"] == str(decision.id)
        assert row.provenance["customer_decision"] == "APPROVE"
        assert row.provenance["parser"] == ParserKind.LITERAL.value
        assert row.provenance["sender_identity"] == TOMAS_CHANNEL
    assert completed.after["idempotency_key"] == amendment.idempotency_key
    assert completed.after["provider_ref"] == amendment.provider_ref
