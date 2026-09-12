"""Durable case state in, the case workspace out.

This module composes; it does not decide. Every sentence a worker reads comes from
:mod:`promisepatch.domain.status_view`, every posture comes from
:func:`promisepatch.domain.analysis.read_case_status`, and the only arrangement performed here
is the one the P5 product contract fixes: the order of the bands, and the order of the
authority groups inside band 3.

**One read service, not a second one.** The operator CLI, the MCP ``status`` tool and this
screen all describe a case by projecting the same value. A view that ran its own query would be
a third description of a case, and three descriptions eventually disagree about one of them
with nothing to say which was right.

**The words are not re-worded here.** ``phrase``, ``sentence``, ``reason`` and ``next_action``
are copied. A view layer that rephrased "planned" for the screen would be doing exactly what a
conversational layer is forbidden to do, and the frontend would then hold a vocabulary the
contract fixes in the backend.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.api.schemas.cases import (
    ApprovalEvidenceView,
    AuthorityBandView,
    CaseListResponse,
    CaseSummaryView,
    CaseWorkspaceResponse,
    CausalChainView,
    CausalStepView,
    ClarificationHistoryView,
    EffectEvidenceView,
    EvidenceView,
    InterpretationEvidenceView,
    NextActionView,
    PromiseWorkspaceView,
    QuestionOptionView,
    QuestionView,
    RevalidationCheckView,
    RevalidationEvidenceView,
    TrackEvidenceView,
)
from promisepatch.db.models import Case, CaseReport
from promisepatch.domain import analysis, causal, status_view

BAND_ORDER: Final[tuple[status_view.Authority, ...]] = (
    status_view.Authority.STANDING_PREFERENCE,
    status_view.Authority.CUSTOMER,
    status_view.Authority.OWNER,
    status_view.Authority.UNDECIDED,
    status_view.Authority.NONE,
)
"""Band 3, in the contract's order: standing preference, then the customer, then the owner.

The last two exist so that a threatened promise can never fall out of the screen. A promise the
projection could not place lands under "not decided yet" rather than being silently dropped,
which is what a filter written against the three expected groups would do.
"""

_BAND_TITLE: Final[dict[status_view.Authority, str]] = {
    status_view.Authority.STANDING_PREFERENCE: "Covered by a standing preference",
    status_view.Authority.CUSTOMER: "Needs the customer",
    status_view.Authority.OWNER: "Needs the owner",
    status_view.Authority.UNDECIDED: "Not decided yet",
    status_view.Authority.NONE: "Left alone",
}


@dataclass(frozen=True, slots=True)
class Opening:
    """The statement that opened a case: the worker's own words, and who is on the record.

    A value rather than a row, so the two strings cannot be swapped at a call site. The text is
    untrusted input and the attestor is a server-side fact, and confusing them is the one
    mistake in this file that would matter.
    """

    raw_text: str
    reported_by: str
    observed_at: datetime


async def first_report(connection: AsyncConnection, *, case_id: UUID) -> Opening | None:
    """The statement that opened this case, verbatim.

    The first one specifically: band 1 asks what was learned, and the opening sentence is what
    a worker recognises the case by. Later answers and corrections are part of the case's
    history and are visible through the question and the evidence, not by quietly replacing the
    sentence somebody said first.
    """
    row = (
        await connection.execute(
            select(CaseReport.raw_text, CaseReport.reported_by, CaseReport.observed_at)
            .where(CaseReport.case_id == case_id)
            .order_by(CaseReport.ordinal)
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return None
    return Opening(raw_text=row.raw_text, reported_by=row.reported_by, observed_at=row.observed_at)


async def openings(connection: AsyncConnection) -> dict[UUID, str]:
    """The opening statement of every case, keyed by case, for the list."""
    rows = (
        await connection.execute(
            select(CaseReport.case_id, CaseReport.raw_text).where(CaseReport.ordinal == 1)
        )
    ).all()
    return {row.case_id: row.raw_text for row in rows}


async def summaries(connection: AsyncConnection, *, limit: int) -> CaseListResponse:
    """Every case, newest first, with just enough of each to choose one."""
    rows = (
        await connection.execute(select(Case).order_by(Case.opened_at.desc(), Case.id).limit(limit))
    ).all()
    texts = await openings(connection)
    return CaseListResponse(
        cases=tuple(
            CaseSummaryView(
                case_id=row.id,
                state=row.state,
                headline=_headline(row.state).value,
                sentence=status_view.headline_sentence(_headline(row.state)),
                needs_owner_attention=row.needs_owner_attention,
                reported_text=texts.get(row.id),
                opened_at=row.opened_at,
                updated_at=row.updated_at,
            )
            for row in rows
        )
    )


def _headline(state: str) -> status_view.CaseHeadline:
    return status_view.CASE_HEADLINES.get(state, status_view.CaseHeadline.UNDERSTANDING)


def build(status: analysis.CaseStatus, *, opening: Opening | None) -> CaseWorkspaceResponse:
    """One case status, projected once and then arranged into the contract's five bands."""
    view = status_view.project(status)
    chains = {
        str(track.track_id): causal.chain_for(track, facts=status.node_facts)
        for track in status.tracks
    }
    return CaseWorkspaceResponse(
        case_id=status.case_id,
        headline=view.headline.value,
        sentence=view.sentence,
        exception_category=view.exception_category,
        exception_phrase=view.exception_phrase,
        reported_text=None if opening is None else opening.raw_text,
        reported_by=None if opening is None else opening.reported_by,
        reported_at=None if opening is None else opening.observed_at,
        needs_owner_attention=view.needs_owner_attention,
        question=_question(view),
        clarifications=tuple(_clarification(item) for item in status.clarifications),
        next_action=NextActionView(
            owner=view.next_action.owner.value,
            owner_label=view.next_action.owner_label,
            action=view.next_action.action,
        ),
        authority_bands=_bands(view, chains),
        untouched=tuple(_promise(item, chains) for item in view.untouched),
        untouched_count=len(view.untouched),
        threatened_count=len(view.threatened),
        promise_count=view.promise_count,
        untouched_effect_count=view.untouched_effect_count,
        plan_id=view.plan_id,
        awaiting_confirmation=view.awaiting_confirmation,
        evidence=_evidence(status),
    )


def _bands(
    view: status_view.CaseView, chains: Mapping[str, causal.CausalChain]
) -> tuple[AuthorityBandView, ...]:
    """Band 3, grouped by authority. A group with nothing in it is not shown at all.

    **A group exists because the projection placed a promise in it**, and for no other reason.
    An always-present set of headers would mean drawing "Needs the customer: 0" on a case at
    ``CLARIFYING``, which has concluded nothing and must show no partition at all; and it would
    mean drawing the two fail-closed groups -- "Not decided yet" and "Left alone" -- as standing
    categories, when they exist so that a promise the projection could not place has somewhere
    to land rather than falling off the screen. The count below is stated for each group that
    does exist so that a screen never takes the length of a list it has already filtered.
    """
    bands = []
    for authority in BAND_ORDER:
        promises = tuple(item for item in view.threatened if item.authority is authority)
        if not promises:
            continue
        bands.append(
            AuthorityBandView(
                authority=authority.value,
                title=_BAND_TITLE[authority],
                promises=tuple(_promise(item, chains) for item in promises),
                count=len(promises),
            )
        )
    return tuple(bands)


def _question(view: status_view.CaseView) -> QuestionView | None:
    if view.question is None:
        return None
    return QuestionView(
        clarification_id=UUID(view.question.clarification_id),
        question=view.question.question,
        options=tuple(
            QuestionOptionView(code=option.code, label=option.label)
            for option in view.question.options
        ),
    )


def _clarification(record: analysis.AnsweredClarification) -> ClarificationHistoryView:
    """Band 1's history, copied. Nothing is worded here: both texts are somebody's own."""
    return ClarificationHistoryView(
        clarification_id=record.clarification_id,
        ordinal=record.ordinal,
        slot=record.slot,
        question=record.question,
        options=tuple(
            QuestionOptionView(code=option.code, label=option.label) for option in record.options
        ),
        asked_at=record.asked_at,
        answered=record.answered,
        answer_text=record.answer_text,
        answered_by=record.answered_by,
        answered_at=record.answered_at,
        resolved_option_code=record.resolved_option_code,
    )


def _promise(
    item: status_view.PromiseView, chains: Mapping[str, causal.CausalChain]
) -> PromiseWorkspaceView:
    return PromiseWorkspaceView(
        promise_id=item.promise_id,
        customer_name=item.customer_name,
        order_external_id=item.order_external_id,
        state=item.state.value,
        phrase=item.phrase,
        authority=item.authority.value,
        reason=item.reason,
        reason_phrase=item.reason_phrase,
        deadline_at=item.deadline_at,
        owner=item.owner.value,
        next_action=item.next_action,
        track_id=UUID(item.track_id),
        track_state=item.track_state,
        classification=item.classification,
        rule_id=item.rule_id,
        causal_chain=_chain(chains[item.track_id]),
    )


def _chain(chain: causal.CausalChain) -> CausalChainView:
    """The traversal, copied. The slots, labels and sentences are all the domain's own."""
    return CausalChainView(
        present=chain.present,
        steps=tuple(
            CausalStepView(
                slot=step.slot.value,
                label=step.label,
                detail=step.detail,
                node_ref=step.node_ref,
            )
            for step in chain.steps
        ),
        absence_reason=chain.absence_reason,
        path_count=chain.path_count,
        deciding_rule=chain.deciding_rule,
    )


def _evidence(status: analysis.CaseStatus) -> EvidenceView:
    """Band 5. Every value copied off the same status the sentences above were projected from."""
    return EvidenceView(
        case_id=status.case_id,
        case_state=status.state,
        case_version=status.case_version,
        plan_id=status.plan_id,
        exception_id=status.exception_id,
        interpretation=_interpretation(status.interpretation),
        tracks=tuple(_track_evidence(track) for track in status.tracks),
    )


def _interpretation(
    reading: analysis.InterpretationStatus | None,
) -> InterpretationEvidenceView | None:
    if reading is None:
        return None
    return InterpretationEvidenceView(
        source=reading.source,
        outcome=reading.outcome,
        attestor=reading.attestor,
        step_state=reading.step_state,
        provider=reading.provider,
        model_id=reading.model_id,
        deterministic_reason=reading.deterministic_reason,
        grounded=reading.grounded,
        rejected=reading.rejected,
        failure=reading.failure,
        last_error=reading.last_error,
    )


def _track_evidence(track: analysis.TrackStatus) -> TrackEvidenceView:
    return TrackEvidenceView(
        promise_id=track.promise_id,
        track_id=track.track_id,
        track_state=track.state,
        classification=track.classification,
        rule_id=track.rule_id,
        reason_detail=track.reason_detail,
        fingerprint=track.fingerprint,
        order_external_id=track.order_external_id,
        order_external_version=track.order_external_version,
        mirrored_versions=dict(track.mirrored_versions),
        paths=track.paths,
        watched_entities=track.watched_entities,
        effects=tuple(
            EffectEvidenceView(
                kind=effect.kind,
                state=effect.state,
                idempotency_key=effect.idempotency_key,
                provider_ref=effect.provider_ref,
                attempts=effect.attempts,
                result=None if effect.result is None else dict(effect.result),
                delivered_at=effect.delivered_at,
                last_error=effect.last_error,
            )
            for effect in track.effects
        ),
        approval=_approval(track.approval),
        revalidation=_revalidation(track.revalidation),
    )


def _approval(approval: analysis.ApprovalStatus | None) -> ApprovalEvidenceView | None:
    if approval is None:
        return None
    return ApprovalEvidenceView(
        request_id=approval.request_id,
        option_code=approval.option_code,
        state=approval.state,
        decided=approval.decided,
        sent_at=approval.sent_at,
        deadline=approval.deadline,
        provider_ref=approval.provider_ref,
        decision=approval.decision,
        parser=approval.parser,
        replies=approval.replies,
    )


def _revalidation(
    revalidation: analysis.RevalidationStatus | None,
) -> RevalidationEvidenceView | None:
    if revalidation is None:
        return None
    return RevalidationEvidenceView(
        outcome=revalidation.outcome,
        deciding_check=revalidation.deciding_check,
        detail=revalidation.detail,
        fingerprint=revalidation.fingerprint,
        checks=tuple(
            RevalidationCheckView(
                index=check.index,
                name=check.name,
                passed=check.passed,
                expected=check.expected,
                actual=check.actual,
            )
            for check in revalidation.checks
        ),
    )
