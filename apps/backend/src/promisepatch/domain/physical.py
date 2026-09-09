"""Making a deterministic reading durable: facts, settlements, ledger rows and questions.

This is the persistence half of intake. It reads the graph, hands values to the pure
interpreter, and turns whatever comes back into rows -- or into no rows at all, which is the
outcome for every branch where the words did not support a conclusion.

**Two authorities, two audit rows, one transaction.** A resolved interpretation writes
``PHYSICAL_FACT_RECORDED`` naming the *worker who saw it*, under authority ``NONE``, because no
policy and no customer permitted the raspberries to be missing -- a person standing in the
kitchen said so. The step transition that carries it writes ``WORKFLOW_STEP_EXECUTED`` naming
the *worker process*. Collapsing the two would lose the distinction between who attested a fact
and what executed the transition, which is exactly the distinction §11.8 rests on.

**Lock order.** Every transaction here runs inside the step executor and therefore already
holds the ``case_steps`` row and the ``cases`` row. It then takes the commitment lines it is
about to settle, in ascending line id, and writes everything else through rows it has just
created. The domain event is appended last, by the step executor, after this module has
finished -- so the spine's ordering lock is still the last lock the transaction takes.

**Exactly once, twice over.** A replayed settlement is refused by
``UNIQUE(source_kind, source_id)`` on ``inventory_ledger`` and by the ``received_state =
'EXPECTED'`` predicate on the line update; a replayed fact is refused by a primary key derived
from what the fact is about rather than minted fresh. Neither depends on the worker having run
once, which is the only assumption a durable engine may not make.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.availability import LedgerPosting, apply_exception_facts
from promise_graph.model import (
    CommitmentLine as EngineCommitmentLine,
)
from promise_graph.model import (
    ExceptionCategory,
    LedgerSourceKind,
    ReceivedState,
    ResourceKind,
)
from promise_graph.model import (
    InventoryLedgerEntry as EngineLedgerEntry,
)
from promise_graph.model import (
    PhysicalException as EngineException,
)
from promise_graph.model import (
    Resource as EngineResource,
)
from promise_graph.model import (
    Supplier as EngineSupplier,
)
from promise_graph.model import (
    SupplierCommitment as EngineCommitment,
)
from promise_graph.snapshot import GraphSnapshot
from promisepatch.config import get_settings
from promisepatch.db.models import (
    Case,
    CaseReport,
    CaseStep,
    CommitmentLine,
    EquipmentOutage,
    ExceptionClarification,
    ExceptionFact,
    InventoryLedgerEntry,
    PhysicalException,
    Resource,
    ResourceAlias,
    Supplier,
    SupplierCommitment,
)
from promisepatch.db.uow import Actor, GovernedWrite, UnitOfWork
from promisepatch.domain import analysis, grounding, interpretation, retry
from promisepatch.domain.cases import LockedCase
from promisepatch.domain.model import (
    EVENT_STEP_COMPLETED,
    EVENT_STEP_FAILED,
    EVENT_STEP_SKIPPED,
    AppendEvent,
    CaseChange,
    CreateStep,
    Disposition,
    StepOutcome,
)
from promisepatch.domain.observation import (
    AUDIT_CLARIFICATION_REQUESTED,
    AUDIT_NEEDS_HUMAN_INTERPRETATION,
    AUDIT_PHYSICAL_FACT_CORRECTED,
    AUDIT_PHYSICAL_FACT_RECORDED,
    AUDIT_SEMANTIC_INTERPRETATION_REQUESTED,
    CASE_CLARIFYING,
    CASE_INTERPRETING,
    CASE_NEEDS_HUMAN,
    EVENT_CLARIFICATION_REQUIRED,
    EVENT_FACT_CORRECTED,
    EVENT_FACT_RECORDED,
    EVENT_NEEDS_HUMAN,
    EVENT_READY_FOR_ANALYSIS,
    EVENT_SEMANTIC_REQUESTED,
    EVENT_SEMANTIC_RESOLVED,
    FACT_TARGET_COMMITMENT_LINE,
    FACT_TARGET_EQUIPMENT,
    FACT_TARGET_RESOURCE,
    RULE_PHYSICAL_FACT_ATTESTED,
    SOURCE_DETERMINISTIC,
    SOURCE_SEMANTIC_ASSISTED,
    STEP_BEGIN_INTERPRETATION,
    STEP_INTERPRET_SEMANTICALLY,
    BoundExceptionView,
    ClarificationOption,
    ClarificationRequired,
    ClarificationSlot,
    ClarificationView,
    CommitmentLineView,
    CommitmentView,
    CorrectionResolved,
    EscalationReason,
    HumanInterpretationRequired,
    InterpretationOutcome,
    ObservationContext,
    ReportKind,
    ResolvedObservation,
    ResourceView,
    Statement,
    semantic_step_key,
    statement_id_of,
)

NAMESPACE: Final = UUID("6f2b1c4e-9a1d-5f7c-8b3a-1d0e5a7c4b92")
"""The namespace every derived intake identifier is minted in.

Derived rather than random, because an id that changes on replay is an id that cannot make a
replay idempotent: the exception, the facts and the ledger source of a re-run resolution have
to be the *same* rows, or the append-only tables would grow a second copy of one attestation.
"""


class IntakeStateError(RuntimeError):
    """The case is not in a state where this statement means anything."""


# ------------------------------------------------------------------------------ identifiers


def case_id_for(command_id: UUID) -> UUID:
    """The case a command opens. One command, one case, however many times it is delivered."""
    return uuid5(NAMESPACE, f"case:{command_id}")


def exception_id_for(case_id: UUID) -> UUID:
    return uuid5(NAMESPACE, f"exception:{case_id}")


def clarification_id_for(case_id: UUID, ordinal: int) -> UUID:
    return uuid5(NAMESPACE, f"clarification:{case_id}:{ordinal}")


def fact_id_for(exception_id: UUID, target_kind: str, target_id: str, source: UUID) -> UUID:
    """A fact's identity: what it is about, and which statement attested it.

    The statement is in the key because a correction is a *second* fact about the same line,
    and the two must coexist. Replaying either produces the same id and the primary key
    refuses the duplicate.
    """
    return uuid5(NAMESPACE, f"fact:{exception_id}:{target_kind}:{target_id}:{source}")


# --------------------------------------------------------------------------------- executor


async def execute(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    kind: str,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Run one intake step against a case whose row this transaction already holds."""
    if kind == STEP_BEGIN_INTERPRETATION:
        return interpretation.begin(case_state=case.state, step_key=step_key)
    if kind == STEP_INTERPRET_SEMANTICALLY:
        return await _consume_semantic(
            connection, case=case, step_key=step_key, now=now, worker=worker
        )
    return await _resolve(
        connection, case=case, statement_id=statement_id_of(step_key), now=now, worker=worker
    )


async def _resolve(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    statement_id: UUID,
    now: datetime,
    worker: str,
) -> StepOutcome:
    context = await hydrate(connection, case_id=case.id, statement_id=statement_id, now=now)
    outcome = interpretation.interpret(context)

    if isinstance(outcome, HumanInterpretationRequired) and grounding.is_fallback_eligible(
        context, outcome
    ):
        return await _defer_to_semantic(
            connection, case=case, context=context, outcome=outcome, now=now, worker=worker
        )
    return await _settle_outcome(
        connection, case=case, context=context, outcome=outcome, now=now, worker=worker
    )


async def _settle_outcome(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    context: ObservationContext,
    outcome: InterpretationOutcome,
    now: datetime,
    worker: str,
    semantic: Mapping[str, Any] | None = None,
) -> StepOutcome:
    """Persist whatever a reading concluded, by the one path every reading takes.

    ``semantic`` is provenance and nothing else: it names who helped read the sentence, and it
    changes none of the four branches below. A fact reached with a model's help is written by
    the same function, into the same table, under the same rule id, attributed to the same
    person -- which is what "downstream cannot tell" means in practice.
    """
    if isinstance(outcome, ClarificationRequired):
        return await _ask(
            connection,
            case=case,
            context=context,
            outcome=outcome,
            now=now,
            worker=worker,
            semantic=semantic,
        )
    if isinstance(outcome, ResolvedObservation):
        return await _record(
            connection, case=case, context=context, outcome=outcome, now=now, semantic=semantic
        )
    if isinstance(outcome, CorrectionResolved):
        return await _correct(connection, case=case, context=context, outcome=outcome, now=now)
    return await _escalate(
        connection,
        case=case,
        context=context,
        outcome=outcome,
        now=now,
        worker=worker,
        semantic=semantic,
    )


# ------------------------------------------------------------------- semantic fallback


def _semantic_provenance(semantic: Mapping[str, Any] | None) -> dict[str, Any]:
    """How a reading was arrived at, in the shape every intake audit row carries.

    Always present, always one of two values, so "was a model involved" is answerable by
    looking rather than by noticing an absent key. When one was, what is recorded is the
    provider, the model, how many candidates it was offered and which identifiers survived --
    never a prompt, never model prose, and never a claim that the model observed anything.
    """
    if semantic is None:
        return {"interpretation_source": SOURCE_DETERMINISTIC}
    return {
        "interpretation_source": SOURCE_SEMANTIC_ASSISTED,
        "semantic": dict(semantic),
    }


async def _defer_to_semantic(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    context: ObservationContext,
    outcome: HumanInterpretationRequired,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """The lexicon could not read this sentence. Enqueue a second reading and stop here.

    Nothing is concluded and nothing is written: the case stays in ``INTERPRETING``, no fact
    exists, no question has been asked, and the successor step is the only thing that changed.
    A worker that dies immediately after this leaves a case whose next claim is the semantic
    step, which is the whole reason this is a durable step rather than a call in a branch.
    """
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_SEMANTIC_INTERPRETATION_REQUESTED,
        # The worker *process*, because what happened is that PromisePatch decided to ask.
        # Nothing here is attributed to the person who spoke, or to whatever answers.
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        before={"case_state": case.state},
        after={"case_state": case.state, "reason": outcome.reason.value},
        provenance={
            "statement": str(context.current.id),
            "detail": outcome.detail,
            "deterministic_outcome": "NEEDS_HUMAN_INTERPRETATION",
        },
        occurred_at=now,
    ):
        pass

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        successors=(
            CreateStep(
                step_key=semantic_step_key(context.current.id),
                kind=STEP_INTERPRET_SEMANTICALLY,
            ),
        ),
        events=(
            AppendEvent(
                type=EVENT_SEMANTIC_REQUESTED,
                payload={"reason": outcome.reason.value},
                entity_refs=({"kind": "case", "id": str(case.id)},),
            ),
        ),
        result={
            "outcome": "SEMANTIC_INTERPRETATION_REQUESTED",
            "reason": outcome.reason.value,
            "detail": outcome.detail,
        },
    )


async def _consume_semantic(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    step_key: str,
    now: datetime,
    worker: str,
) -> StepOutcome:
    """Decide what the reading fetched outside this transaction is worth, under the case lock.

    Deterministic first, again. The lexicon is re-run here because the case may have moved
    since the model was asked -- a clarification answered, a delivery corrected -- and a
    sentence it can now read is a sentence whose reading is not a model's to influence.

    Then the fingerprint. A reading is an answer to one question about one kitchen, and if the
    kitchen that question described is not the kitchen this transaction is looking at, the
    answer is discarded and the work is done again. Nothing stale is ever committed.
    """
    from promisepatch.domain import semantic_intake

    if case.state != CASE_INTERPRETING:
        # The case moved on while the model was being asked -- clarified by another statement,
        # bound by an owner, retracted. A reading is only ever about a case that is still
        # trying to understand its own sentence, so this one is dropped rather than applied.
        return StepOutcome(
            disposition=Disposition.SKIPPED,
            event_type=EVENT_STEP_SKIPPED,
            result={"skipped_because": case.state},
        )

    statement_id = statement_id_of(step_key)
    context = await hydrate(connection, case_id=case.id, statement_id=statement_id, now=now)
    outcome = interpretation.interpret(context)

    if not (
        isinstance(outcome, HumanInterpretationRequired)
        and grounding.is_fallback_eligible(context, outcome)
    ):
        # The deterministic reading concluded while the model was being asked. Its answer is
        # not consulted at all: understanding that did not need buying is not paid for.
        return await _settle_outcome(
            connection, case=case, context=context, outcome=outcome, now=now, worker=worker
        )

    # The row this transaction is executing, read for the reading somebody left on it and
    # for the attempt count that says whether the retry budget has anything left.
    row = (
        await connection.execute(
            select(CaseStep.result, CaseStep.attempts).where(
                CaseStep.case_id == case.id, CaseStep.step_key == step_key
            )
        )
    ).one()
    stored = semantic_intake.stored_reading(row.result)
    status = None if stored is None else stored.get("status")

    if status == semantic_intake.STATUS_REJECTED:
        # The model answered and the answer was refused. Asking again would produce the same
        # refusal, so this stops now, under the reason the sentence was unread for all along.
        return await _escalate(
            connection,
            case=case,
            context=context,
            outcome=outcome,
            now=now,
            worker=worker,
            semantic=dict(stored or {}),
        )
    if status != semantic_intake.STATUS_READ:
        if not retry.is_exhausted(row.attempts):
            return _retry_semantic(stored)
        return await _escalate(
            connection,
            case=case,
            context=context,
            outcome=HumanInterpretationRequired(
                reason=EscalationReason.SEMANTIC_UNAVAILABLE,
                detail=(
                    "no semantic provider could be reached to read this sentence; the report "
                    "is unchanged and nothing has been concluded from it"
                ),
            ),
            now=now,
            worker=worker,
            semantic=dict(stored or {"status": "MISSING"}),
        )

    reading = stored or {}
    fingerprint = grounding.request_fingerprint(grounding.build_request(context), context)
    if reading.get("request_hash") != fingerprint:
        return _stale_semantic()

    proposal = semantic_intake.reading_of(reading)
    if proposal is None:
        # The row says a model was read and carries nothing a model could have said -- a
        # payload written by a build that shaped it differently, or edited underneath us.
        # Treated exactly as a refused answer is: no binding, and the sentence goes to a person
        # under the stop it was always unread for.
        return await _escalate(
            connection,
            case=case,
            context=context,
            outcome=outcome,
            now=now,
            worker=worker,
            semantic=dict(reading),
        )

    resolution = grounding.resolve_semantic_observation(
        context, proposal, deterministic_reason=outcome.reason
    )
    settled = await _settle_outcome(
        connection,
        case=case,
        context=context,
        outcome=resolution.outcome,
        now=now,
        worker=worker,
        semantic={
            "provider": reading.get("provider"),
            "model_id": reading.get("model_id"),
            "provider_attempts": reading.get("provider_attempts"),
            "candidates": reading.get("candidates"),
            "request_hash": reading.get("request_hash"),
            "deterministic_reason": outcome.reason.value,
            # The normalised proposal itself, kept because "what did the model actually
            # say, and what did we do with it" is the question this whole record exists to
            # answer. Identifiers, a category and where in the sentence they were seen.
            "reading": reading.get("reading"),
            "grounding": resolution.grounding.as_payload(),
        },
    )
    return replace(
        settled,
        events=(
            *settled.events,
            AppendEvent(
                type=EVENT_SEMANTIC_RESOLVED,
                payload={
                    "grounded": resolution.grounding.grounded,
                    "failure": resolution.grounding.failure.value,
                },
                entity_refs=({"kind": "case", "id": str(case.id)},),
            ),
        ),
    )


def _retry_semantic(stored: Mapping[str, Any] | None) -> StepOutcome:
    """A provider that could not be reached has said nothing about the sentence.

    So the step waits on the ordinary ladder and asks again. Nothing is concluded from silence,
    and in particular a temporary outage never becomes a case a person has to bind by hand
    while the retry budget still has room in it.
    """
    detail = "no reading was prepared for this step"
    if stored is not None:
        detail = str(stored.get("detail") or stored.get("status") or detail)
    return StepOutcome(
        disposition=Disposition.RETRYING,
        event_type=EVENT_STEP_FAILED,
        error=f"semantic interpretation unavailable: {detail}",
    )


def _stale_semantic() -> StepOutcome:
    """The question this answer belongs to is no longer the question that would be asked."""
    return StepOutcome(
        disposition=Disposition.RETRYING,
        event_type=EVENT_STEP_FAILED,
        error=(
            "the semantic reading was produced against an interpretation context that has "
            "since changed; it is discarded and the sentence will be read again"
        ),
    )


# --------------------------------------------------------------------------------- hydration


async def hydrate(
    connection: AsyncConnection, *, case_id: UUID, statement_id: UUID, now: datetime
) -> ObservationContext:
    """Build the interpreter's whole world out of rows, and hand it values.

    No SQLAlchemy object crosses this boundary. What the interpreter receives is names,
    quantities and instants, so "the reading is decided by its inputs" is a property of the
    call rather than a claim about discipline.
    """
    statements = await _statements(connection, case_id)
    current = next((item for item in statements if item.id == statement_id), None)
    if current is None:
        raise IntakeStateError(f"statement {statement_id} does not belong to case {case_id}")
    report = next((item for item in statements if item.kind is ReportKind.REPORT), statements[0])

    resources = await _resources(connection)
    commitments = await _commitments(connection)
    on_hand = await _on_hand(connection)
    clarifications = await _clarifications(connection, case_id)
    open_clarification = clarifications[-1] if clarifications else None
    day_start, day_end = bakery_day(now)

    return ObservationContext(
        now=now,
        day_start=day_start,
        day_end=day_end,
        resources=resources,
        commitments=commitments,
        on_hand=on_hand,
        report=report,
        current=current,
        open_clarification=open_clarification,
        clarifications_asked=len(clarifications),
        bound=await _bound(connection, case_id),
    )


def bakery_day(now: datetime) -> tuple[datetime, datetime]:
    """The calendar day "today" means, in the kitchen's own timezone.

    A delivery due at eight in the morning and one due at six the next morning are six hours
    apart in UTC on some dates and on either side of midnight on others. "Today" is a claim
    about the bakery's day, so it is measured in the bakery's zone and passed to the
    interpreter as two instants -- which is also what keeps the interpreter free of a clock.
    """
    settings = get_settings()
    try:
        zone = ZoneInfo(settings.bakery_tz)
    except (ZoneInfoNotFoundError, ValueError):  # pragma: no cover - configuration error
        zone = ZoneInfo("UTC")
    local = now.astimezone(zone)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(now.tzinfo), (start + timedelta(days=1)).astimezone(now.tzinfo)


async def _statements(connection: AsyncConnection, case_id: UUID) -> tuple[Statement, ...]:
    rows = (
        await connection.execute(
            select(CaseReport).where(CaseReport.case_id == case_id).order_by(CaseReport.ordinal)
        )
    ).all()
    if not rows:
        raise IntakeStateError(f"case {case_id} has no recorded statement to interpret")
    return tuple(
        Statement(
            id=row.id,
            kind=ReportKind(row.kind),
            raw_text=row.raw_text,
            reported_by=row.reported_by,
            observed_at=row.observed_at,
        )
        for row in rows
    )


async def _resources(connection: AsyncConnection) -> tuple[ResourceView, ...]:
    aliases: dict[str, list[str]] = {}
    for row in (
        await connection.execute(
            select(ResourceAlias).order_by(ResourceAlias.resource_id, ResourceAlias.ordinal)
        )
    ).all():
        aliases.setdefault(row.resource_id, []).append(row.alias)

    rows = (await connection.execute(select(Resource).order_by(Resource.id))).all()
    return tuple(
        ResourceView(
            id=row.id,
            kind=ResourceKind(row.kind),
            name=row.name,
            aliases=tuple(aliases.get(row.id, ())),
        )
        for row in rows
    )


async def _commitments(connection: AsyncConnection) -> tuple[CommitmentView, ...]:
    lines: dict[str, list[CommitmentLineView]] = {}
    for row in (await connection.execute(select(CommitmentLine).order_by(CommitmentLine.id))).all():
        lines.setdefault(row.commitment_id, []).append(
            CommitmentLineView(
                id=row.id,
                resource_id=row.resource_id,
                quantity=row.quantity,
                received_state=ReceivedState(row.received_state),
            )
        )

    rows = (
        await connection.execute(
            select(SupplierCommitment, Supplier.name.label("supplier_name"))
            .join(Supplier, Supplier.id == SupplierCommitment.supplier_id)
            .order_by(SupplierCommitment.id)
        )
    ).all()
    return tuple(
        CommitmentView(
            id=row.id,
            supplier_id=row.supplier_id,
            supplier_name=row.supplier_name,
            due_at=row.due_at,
            lines=tuple(lines.get(row.id, ())),
        )
        for row in rows
    )


async def _on_hand(connection: AsyncConnection) -> Mapping[str, Decimal | None]:
    """Physical stock now, as the sum of the append-only ledger. ``None`` if any delta is."""
    totals: dict[str, Decimal | None] = {}
    for row in (
        await connection.execute(
            select(InventoryLedgerEntry.resource_id, InventoryLedgerEntry.delta)
        )
    ).all():
        running = totals.get(row.resource_id, Decimal("0"))
        if running is None or row.delta is None:
            totals[row.resource_id] = None
        else:
            totals[row.resource_id] = running + row.delta
    return totals


async def _clarifications(
    connection: AsyncConnection, case_id: UUID
) -> tuple[ClarificationView, ...]:
    rows = (
        await connection.execute(
            select(ExceptionClarification)
            .where(ExceptionClarification.case_id == case_id)
            .order_by(ExceptionClarification.ordinal)
        )
    ).all()
    return tuple(
        ClarificationView(
            id=row.id,
            ordinal=row.ordinal,
            slot=ClarificationSlot(row.slot),
            question=row.question,
            options=tuple(_option(item) for item in row.options),
            answer_text=row.answer_text,
            category=_stored_category(row.context),
            resource_id=(row.context or {}).get("resource_id"),
            commitment_id=(row.context or {}).get("commitment_id"),
        )
        for row in rows
    )


def _stored_category(context: Mapping[str, Any] | None) -> ExceptionCategory | None:
    """The category a question was asked about, read back through the closed enum.

    Through the enum rather than as a string, so a value that is not a category this build
    knows fails here instead of travelling on as one.
    """
    value = (context or {}).get("category")
    return None if value is None else ExceptionCategory(value)


def _option(raw: Mapping[str, Any]) -> ClarificationOption:
    return ClarificationOption(
        code=str(raw["code"]),
        label=str(raw["label"]),
        keywords=tuple(str(item) for item in raw.get("keywords", ())),
        scope_line_ids=tuple(str(item) for item in raw.get("scope_line_ids", ())),
        commitment_id=raw.get("commitment_id"),
    )


async def _bound(connection: AsyncConnection, case_id: UUID) -> BoundExceptionView | None:
    row = (
        await connection.execute(
            select(PhysicalException)
            .join(Case, Case.exception_id == PhysicalException.id)
            .where(Case.id == case_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return BoundExceptionView(
        id=row.id,
        category=ExceptionCategory(row.category),
        commitment_id=row.commitment_id,
        scope_line_ids=tuple(str(item) for item in row.scope_line_ids),
        resource_id=row.resource_id,
    )


# ---------------------------------------------------------------------------- clarification


async def _ask(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    context: ObservationContext,
    worker: str,
    outcome: ClarificationRequired,
    now: datetime,
    semantic: Mapping[str, Any] | None = None,
) -> StepOutcome:
    """Persist the question and stop. No fact, no settlement, no ledger row, no guess.

    The options carry the line ids that choosing them would settle, so the answer resolves
    against rows that already existed when the question was asked. That is what stops an
    answer from naming a line the delivery never had.
    """
    ordinal = context.clarifications_asked + 1
    clarification_id = clarification_id_for(case.id, ordinal)
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_CLARIFICATION_REQUESTED,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        before={"case_state": case.state},
        after={
            "case_state": CASE_CLARIFYING,
            "slot": outcome.slot.value,
            "question": outcome.question,
            "options": [option.code for option in outcome.options],
        },
        provenance={
            "statement": str(context.current.id),
            "derived_from": outcome.context,
            **_semantic_provenance(semantic),
        },
        occurred_at=now,
    ) as write:
        await write.execute(
            pg_insert(ExceptionClarification)
            .values(
                id=clarification_id,
                case_id=case.id,
                ordinal=ordinal,
                slot=outcome.slot.value,
                question=outcome.question,
                options=[_serialize(option) for option in outcome.options],
                context=outcome.context,
                asked_at=now,
            )
            .on_conflict_do_nothing(index_elements=[ExceptionClarification.id])
        )

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=CASE_CLARIFYING),
        events=(
            AppendEvent(
                type=EVENT_CLARIFICATION_REQUIRED,
                payload={"slot": outcome.slot.value, "ordinal": ordinal},
                entity_refs=({"kind": "clarification", "id": str(clarification_id)},),
            ),
        ),
        result={
            "outcome": "CLARIFICATION_REQUIRED",
            "slot": outcome.slot.value,
            "question": outcome.question,
            "options": [option.code for option in outcome.options],
            "clarification_id": str(clarification_id),
            **_semantic_provenance(semantic),
        },
    )


def _serialize(option: ClarificationOption) -> dict[str, Any]:
    return {
        "code": option.code,
        "label": option.label,
        "keywords": list(option.keywords),
        "scope_line_ids": list(option.scope_line_ids),
        "commitment_id": option.commitment_id,
    }


# ------------------------------------------------------------------------- resolved facts


async def _record(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    context: ObservationContext,
    outcome: ResolvedObservation,
    now: datetime,
    semantic: Mapping[str, Any] | None = None,
) -> StepOutcome:
    """The moment the binding becomes attested, and physical reality is written down.

    The settlement arithmetic is the engine's own: ``apply_exception_facts`` decides which
    lines settle how and what is posted, so the database and the propagation model can never
    disagree about the same delivery. This function's job is to persist that answer exactly
    once and to say who attested it.
    """
    exception_id = exception_id_for(case.id)
    attestor = context.report.reported_by
    await _lock_lines(connection, outcome.commitment_id)

    snapshot = await _snapshot(connection)
    # A supply exception binds *lines*, never a bare resource: the engine refuses the second
    # shape, and the row has to be one the engine could load back.
    bound_resource = (
        None if outcome.category is ExceptionCategory.SUPPLY_NOT_RECEIVED else outcome.resource_id
    )
    engine_exception = EngineException(
        id=str(exception_id),
        category=outcome.category,
        commitment_id=outcome.commitment_id,
        scope_line_ids=outcome.scope_line_ids,
        resource_id=bound_resource,
        quantity=outcome.quantity,
        outage_until=outcome.outage_until,
        reported_by=attestor,
        reported_at=context.report.observed_at,
        raw_utterance=context.report.raw_text,
    )
    settlement = apply_exception_facts(snapshot, engine_exception, now)

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_PHYSICAL_FACT_RECORDED,
        actor=Actor(kind="WORKER", id=attestor),
        # No policy and no consent permitted this: a person who was there said what they saw.
        authority="NONE",
        rule_id=RULE_PHYSICAL_FACT_ATTESTED,
        case_id=case.id,
        before={"case_state": case.state},
        after={
            "category": outcome.category.value,
            "commitment_id": outcome.commitment_id,
            "scope_line_ids": list(outcome.scope_line_ids),
            "resource_id": outcome.resource_id,
            "settlements": [
                {"line": item.commitment_line_id, "state": item.to_state.value}
                for item in settlement.settlements
            ],
        },
        provenance={
            "statement": str(context.current.id),
            "raw_utterance": context.report.raw_text,
            "observed_at": context.report.observed_at.isoformat(),
            "clarified": context.clarifications_asked > 0,
            # Who helped *read* the sentence, beside the person who attested what it says.
            # The actor above is the worker and the authority is `NONE`, and neither moves
            # because a model was involved: a model that parses a phrasing has observed
            # nothing, and an audit row implying otherwise would be the one lie this whole
            # design exists to make impossible.
            **_semantic_provenance(semantic),
        },
        occurred_at=now,
    ) as write:
        await _persist_exception(
            write,
            exception_id=exception_id,
            case=case,
            outcome=outcome,
            resource_id=bound_resource,
            context=context,
        )
        facts = await _settle_lines(
            write,
            exception_id=exception_id,
            settlement_lines=settlement.settlements,
            postings=settlement.postings,
            attestor=attestor,
            source=context.current.id,
            now=now,
        )
        facts += await _apply_resource_effects(
            write,
            exception_id=exception_id,
            outcome=outcome,
            postings=settlement.postings,
            attestor=attestor,
            source=context.current.id,
            now=now,
        )

    refs = tuple(
        {"kind": FACT_TARGET_COMMITMENT_LINE, "id": item.commitment_line_id}
        for item in settlement.settlements
    ) or (({"kind": "exception", "id": str(exception_id)},))

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        # The facts are attested, so the next thing that should happen is that somebody works
        # out what they cost. Enqueued in the transaction that recorded them, keyed by the
        # statement that attested them, so a replay proposes the identical step and gets one.
        successors=(
            CreateStep(
                step_key=analysis.analyze_step_key(context.current.id),
                kind=analysis.STEP_ANALYZE_IMPACT,
            ),
        ),
        events=(
            AppendEvent(
                type=EVENT_FACT_RECORDED,
                payload={"category": outcome.category.value, "facts": len(facts)},
                entity_refs=refs,
            ),
            AppendEvent(
                type=EVENT_READY_FOR_ANALYSIS,
                payload={"exception_id": str(exception_id)},
                entity_refs=({"kind": "exception", "id": str(exception_id)},),
            ),
        ),
        result={
            "outcome": "RESOLVED",
            "ready_for_analysis": True,
            **_semantic_provenance(semantic),
            "exception_id": str(exception_id),
            "category": outcome.category.value,
            "scope_line_ids": list(outcome.scope_line_ids),
            "settlements": {
                item.commitment_line_id: item.to_state.value for item in settlement.settlements
            },
            "postings": [
                {"resource": item.resource_id, "delta": _text(item.delta)}
                for item in settlement.postings
            ],
            "facts": [str(item) for item in facts],
        },
    )


async def _persist_exception(
    write: GovernedWrite,
    *,
    exception_id: UUID,
    case: LockedCase,
    outcome: ResolvedObservation,
    resource_id: str | None,
    context: ObservationContext,
) -> None:
    """The interpreted exception, and the case's pointer at it. Idempotent by derived id."""
    await write.execute(
        pg_insert(PhysicalException)
        .values(
            id=exception_id,
            category=outcome.category.value,
            commitment_id=outcome.commitment_id,
            scope_line_ids=list(outcome.scope_line_ids),
            resource_id=resource_id,
            quantity=outcome.quantity,
            outage_until=outcome.outage_until,
            raw_utterance=context.report.raw_text,
            reported_by=context.report.reported_by,
            reported_at=context.report.observed_at,
        )
        .on_conflict_do_nothing(index_elements=[PhysicalException.id])
    )
    await write.execute(
        update(Case)
        .where(Case.id == case.id, Case.exception_id.is_(None))
        .values(exception_id=exception_id)
    )


async def _settle_lines(
    write: GovernedWrite,
    *,
    exception_id: UUID,
    settlement_lines: Sequence[Any],
    postings: Sequence[LedgerPosting],
    attestor: str,
    source: UUID,
    now: datetime,
) -> list[UUID]:
    """Close each line once, post what physically arrived once, and record both as facts."""
    posted_by_line = {
        posting.source_id: posting
        for posting in postings
        if posting.source_kind is LedgerSourceKind.COMMITMENT_RECEIPT
    }
    facts: list[UUID] = []
    for line in settlement_lines:
        applied = await write.execute(
            update(CommitmentLine)
            .where(
                CommitmentLine.id == line.commitment_line_id,
                CommitmentLine.received_state == ReceivedState.EXPECTED.value,
            )
            .values(
                received_state=line.to_state.value,
                received_qty=line.received_qty,
                settled_at=line.settled_at,
                attested_by=attestor,
            )
        )
        if applied.rowcount != 1:
            # Already settled: a replay, or a correction got here first. Neither is an error,
            # and neither may post a second physical quantity.
            continue

        posting = posted_by_line.get(line.commitment_line_id)
        ledger_ids = await _post(write, posting, now) if posting is not None else []
        facts.append(
            await _fact(
                write,
                exception_id=exception_id,
                target_kind=FACT_TARGET_COMMITMENT_LINE,
                target_id=line.commitment_line_id,
                before={"received_state": ReceivedState.EXPECTED.value},
                after={
                    "received_state": line.to_state.value,
                    "received_qty": _text(line.received_qty),
                },
                posted=ledger_ids,
                attestor=attestor,
                source=source,
                now=now,
            )
        )
    return facts


async def _apply_resource_effects(
    write: GovernedWrite,
    *,
    exception_id: UUID,
    outcome: ResolvedObservation,
    postings: Sequence[LedgerPosting],
    attestor: str,
    source: UUID,
    now: datetime,
) -> list[UUID]:
    """Unusable stock and equipment outages: the two categories with no commitment line."""
    if outcome.category is ExceptionCategory.STOCK_UNUSABLE:
        posting = next(
            (item for item in postings if item.source_kind is LedgerSourceKind.EXCEPTION_FACT),
            None,
        )
        if posting is None:
            return []
        ledger_ids = await _post(write, posting, now)
        if not ledger_ids:
            return []
        return [
            await _fact(
                write,
                exception_id=exception_id,
                target_kind=FACT_TARGET_RESOURCE,
                target_id=str(outcome.resource_id),
                before=None,
                after={"delta": _text(posting.delta), "reason": "STOCK_UNUSABLE"},
                posted=ledger_ids,
                attestor=attestor,
                source=source,
                now=now,
            )
        ]

    if outcome.category is not ExceptionCategory.EQUIPMENT_UNAVAILABLE:
        return []

    outage_id = f"outage:{exception_id}"
    created = await write.execute(
        pg_insert(EquipmentOutage)
        .values(
            id=outage_id,
            equipment_id=outcome.resource_id,
            starts_at=now,
            ends_at=outcome.outage_until,
        )
        .on_conflict_do_nothing(index_elements=[EquipmentOutage.id])
    )
    if created.rowcount != 1:
        return []
    return [
        await _fact(
            write,
            exception_id=exception_id,
            target_kind=FACT_TARGET_EQUIPMENT,
            target_id=str(outcome.resource_id),
            before=None,
            after={
                "outage_id": outage_id,
                "starts_at": now.isoformat(),
                "ends_at": None
                if outcome.outage_until is None
                else outcome.outage_until.isoformat(),
            },
            posted=[],
            attestor=attestor,
            source=source,
            now=now,
        )
    ]


# ------------------------------------------------------------------------------ corrections


async def _correct(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    context: ObservationContext,
    outcome: CorrectionResolved,
    now: datetime,
) -> StepOutcome:
    """A later attestation, recorded as a compensation rather than as an edit.

    Nothing is deleted and nothing is rewritten. The superseded fact stays exactly where it
    was, the ledger keeps the row it posted, and the change to physical reality is a *new*
    row that offsets it. That is why the history of a corrected delivery reads as two things
    that happened rather than as one thing that was always true.
    """
    bound = context.bound
    if bound is None:  # pragma: no cover - the interpreter refuses an unbound correction
        raise IntakeStateError(f"case {case.id} has no bound exception to correct")

    line_ids = [item.commitment_line_id for item in outcome.outcomes]
    current = await _line_states(connection, line_ids)
    changed = [
        item
        for item in outcome.outcomes
        if current.get(item.commitment_line_id) is not item.received_state
    ]

    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_PHYSICAL_FACT_CORRECTED,
        actor=Actor(kind="WORKER", id=context.current.reported_by),
        authority="NONE",
        rule_id=RULE_PHYSICAL_FACT_ATTESTED,
        case_id=case.id,
        before={
            "lines": {
                item.commitment_line_id: (
                    None
                    if current.get(item.commitment_line_id) is None
                    else current[item.commitment_line_id].value
                )
                for item in outcome.outcomes
            }
        },
        after={
            "lines": {
                item.commitment_line_id: item.received_state.value for item in outcome.outcomes
            },
            "changed": [item.commitment_line_id for item in changed],
        },
        provenance={
            "statement": str(context.current.id),
            "raw_utterance": context.current.raw_text,
            "observed_at": context.current.observed_at.isoformat(),
            "corrects_exception": str(bound.id),
        },
        occurred_at=now,
    ) as write:
        facts = await _compensate(
            write,
            exception_id=bound.id,
            changed=changed,
            attestor=context.current.reported_by,
            source=context.current.id,
            now=now,
        )

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        # A correction changes what is physically true, so whatever was concluded from the
        # previous truth has to be concluded again. This is that re-analysis, under the
        # correcting statement's own key so it cannot collide with the first one.
        successors=(
            CreateStep(
                step_key=analysis.analyze_step_key(context.current.id),
                kind=analysis.STEP_ANALYZE_IMPACT,
            ),
        ),
        events=(
            AppendEvent(
                type=EVENT_FACT_CORRECTED,
                payload={"corrected": len(facts)},
                entity_refs=tuple(
                    {"kind": FACT_TARGET_COMMITMENT_LINE, "id": item.commitment_line_id}
                    for item in changed
                )
                or (({"kind": "exception", "id": str(bound.id)},)),
            ),
        ),
        result={
            "outcome": "CORRECTED",
            "ready_for_analysis": True,
            "exception_id": str(bound.id),
            "corrected": {item.commitment_line_id: item.received_state.value for item in changed},
            "facts": [str(item) for item in facts],
        },
    )


async def _compensate(
    write: GovernedWrite,
    *,
    exception_id: UUID,
    changed: Sequence[Any],
    attestor: str,
    source: UUID,
    now: datetime,
) -> list[UUID]:
    """Append the corrective fact, offset what was posted, and move the line to the new truth."""
    facts: list[UUID] = []
    for item in changed:
        line = (
            await write.execute(
                select(CommitmentLine)
                .where(CommitmentLine.id == item.commitment_line_id)
                .with_for_update()
            )
        ).one()
        posted = await _posted_for_line(write, item.commitment_line_id)
        fact_id = fact_id_for(
            exception_id, FACT_TARGET_COMMITMENT_LINE, item.commitment_line_id, source
        )

        delta = _compensating_delta(
            posted=posted, to_state=item.received_state, quantity=line.quantity
        )
        ledger_ids = (
            await _post(
                write,
                LedgerPosting(
                    resource_id=line.resource_id,
                    delta=delta,
                    source_kind=LedgerSourceKind.CORRECTION,
                    source_id=str(fact_id),
                ),
                now,
            )
            if delta is not None and delta != 0
            else []
        )

        await write.execute(
            update(CommitmentLine)
            .where(CommitmentLine.id == item.commitment_line_id)
            .values(
                received_state=item.received_state.value,
                received_qty=None,
                settled_at=now,
                attested_by=attestor,
            )
        )
        facts.append(
            await _fact(
                write,
                exception_id=exception_id,
                target_kind=FACT_TARGET_COMMITMENT_LINE,
                target_id=item.commitment_line_id,
                before={"received_state": line.received_state},
                after={"received_state": item.received_state.value},
                posted=ledger_ids,
                attestor=attestor,
                source=source,
                now=now,
                supersedes=await _latest_fact(write, exception_id, item.commitment_line_id),
                fact_id=fact_id,
            )
        )
    return facts


def _compensating_delta(
    *, posted: Decimal | None, to_state: ReceivedState, quantity: Decimal | None
) -> Decimal | None:
    """What the ledger must move by so that on-hand tells the corrected truth.

    Derived from what was actually posted for this line rather than from what the line says it
    should have been, because the compensation has to cancel the row that exists, not the row
    somebody expected.
    """
    if to_state is ReceivedState.RECEIVED:
        if quantity is None:
            return None
        return quantity - (posted or Decimal("0"))
    if posted is None:
        return None
    return -posted


async def _posted_for_line(write: GovernedWrite, line_id: str) -> Decimal | None:
    """Everything the ledger has already moved on account of this line.

    Read through the facts rather than by guessing at source keys: every posting a fact caused
    is recorded on that fact, so this sum is the net physical effect this line has had on
    on-hand stock, whatever kind of source each movement was filed under. ``None`` if any of
    them is an unknown quantity, because an unknown cannot be cancelled.
    """
    entries = (
        await write.execute(
            select(ExceptionFact.posted_ledger_ids).where(
                ExceptionFact.target_kind == FACT_TARGET_COMMITMENT_LINE,
                ExceptionFact.target_id == line_id,
            )
        )
    ).scalars()
    sequences = sorted({int(item) for entry in entries for item in entry})
    if not sequences:
        return Decimal("0")

    total = Decimal("0")
    deltas = (
        await write.execute(
            select(InventoryLedgerEntry.delta).where(InventoryLedgerEntry.seq.in_(sequences))
        )
    ).scalars()
    for delta in deltas:
        if delta is None:
            return None
        total += delta
    return total


async def _latest_fact(write: GovernedWrite, exception_id: UUID, target_id: str) -> UUID | None:
    return (
        await write.execute(
            select(ExceptionFact.id)
            .where(
                ExceptionFact.exception_id == exception_id,
                ExceptionFact.target_kind == FACT_TARGET_COMMITMENT_LINE,
                ExceptionFact.target_id == target_id,
            )
            .order_by(ExceptionFact.attested_at.desc(), ExceptionFact.id)
            .limit(1)
        )
    ).scalar_one_or_none()


# --------------------------------------------------------------------------------- escalate


async def _escalate(
    connection: AsyncConnection,
    *,
    case: LockedCase,
    context: ObservationContext,
    worker: str,
    outcome: HumanInterpretationRequired,
    now: datetime,
    semantic: Mapping[str, Any] | None = None,
) -> StepOutcome:
    """Stop, write nothing, and say why. The worker's words are already on the case."""
    unit_of_work = UnitOfWork(connection)
    async with unit_of_work.governed(
        event_type=AUDIT_NEEDS_HUMAN_INTERPRETATION,
        actor=Actor(kind="SYSTEM", id=worker),
        authority="NONE",
        case_id=case.id,
        before={"case_state": case.state},
        after={"case_state": CASE_NEEDS_HUMAN, "reason": outcome.reason.value},
        provenance={
            "statement": str(context.current.id),
            "raw_utterance": context.current.raw_text,
            "detail": outcome.detail,
            **_semantic_provenance(semantic),
        },
        occurred_at=now,
    ):
        pass

    return StepOutcome(
        disposition=Disposition.DONE,
        event_type=EVENT_STEP_COMPLETED,
        case_change=CaseChange(state=CASE_NEEDS_HUMAN, needs_owner_attention=True),
        events=(
            AppendEvent(
                type=EVENT_NEEDS_HUMAN,
                payload={"reason": outcome.reason.value},
                entity_refs=({"kind": "case", "id": str(case.id)},),
            ),
        ),
        result={
            "outcome": "NEEDS_HUMAN_INTERPRETATION",
            "reason": outcome.reason.value,
            "detail": outcome.detail,
            **_semantic_provenance(semantic),
        },
    )


# ----------------------------------------------------------------------------------- shared


async def _lock_lines(connection: AsyncConnection, commitment_id: str | None) -> None:
    """Take every line of the delivery for update, in ascending id.

    One order, everywhere, so two transactions settling overlapping deliveries queue rather
    than deadlock. Taken before any write, and after the case row this executor already holds.
    """
    if commitment_id is None:
        return
    await connection.execute(
        select(CommitmentLine.id)
        .where(CommitmentLine.commitment_id == commitment_id)
        .order_by(CommitmentLine.id)
        .with_for_update()
    )


async def _line_states(
    connection: AsyncConnection, line_ids: Sequence[str]
) -> Mapping[str, ReceivedState]:
    rows = (
        await connection.execute(
            select(CommitmentLine.id, CommitmentLine.received_state)
            .where(CommitmentLine.id.in_(list(line_ids)))
            .order_by(CommitmentLine.id)
            .with_for_update()
        )
    ).all()
    return {row.id: ReceivedState(row.received_state) for row in rows}


async def _post(write: GovernedWrite, posting: LedgerPosting, now: datetime) -> list[int]:
    """One physical movement, at most once. The unique index is the guarantee, not the check."""
    seq = (
        await write.execute(
            pg_insert(InventoryLedgerEntry)
            .values(
                resource_id=posting.resource_id,
                delta=posting.delta,
                source_kind=posting.source_kind.value,
                source_id=posting.source_id,
                recorded_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    InventoryLedgerEntry.source_kind,
                    InventoryLedgerEntry.source_id,
                ]
            )
            .returning(InventoryLedgerEntry.seq)
        )
    ).scalar_one_or_none()
    return [] if seq is None else [int(seq)]


async def _fact(
    write: GovernedWrite,
    *,
    exception_id: UUID,
    target_kind: str,
    target_id: str,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    posted: Sequence[int],
    attestor: str,
    source: UUID,
    now: datetime,
    supersedes: UUID | None = None,
    fact_id: UUID | None = None,
) -> UUID:
    """Append one attestation. Append-only: this row is never updated and never deleted."""
    identifier = fact_id or fact_id_for(exception_id, target_kind, target_id, source)
    await write.execute(
        pg_insert(ExceptionFact)
        .values(
            id=identifier,
            exception_id=exception_id,
            target_kind=target_kind,
            target_id=target_id,
            before=None if before is None else dict(before),
            after=None if after is None else dict(after),
            posted_ledger_ids=list(posted),
            supersedes_fact_id=supersedes,
            source_report_id=source,
            attested_by=attestor,
            attested_at=now,
        )
        .on_conflict_do_nothing(index_elements=[ExceptionFact.id])
    )
    return identifier


async def _snapshot(connection: AsyncConnection) -> GraphSnapshot:
    """The slice of the graph settlement arithmetic needs: supply, resources and the ledger.

    Deliberately partial. Orders, recipes and promises decide nothing about whether a crate
    arrived, and a settlement transaction that read them would be holding a view of the order
    book it has no business having.
    """
    resources = [
        EngineResource(id=row.id, kind=ResourceKind(row.kind), name=row.name, unit=row.unit)
        for row in (await connection.execute(select(Resource).order_by(Resource.id))).all()
    ]
    suppliers = [
        EngineSupplier(id=row.id, name=row.name)
        for row in (await connection.execute(select(Supplier).order_by(Supplier.id))).all()
    ]
    lines: dict[str, list[EngineCommitmentLine]] = {}
    for row in (await connection.execute(select(CommitmentLine).order_by(CommitmentLine.id))).all():
        lines.setdefault(row.commitment_id, []).append(
            EngineCommitmentLine(
                id=row.id,
                commitment_id=row.commitment_id,
                resource_id=row.resource_id,
                quantity=row.quantity,
                received_state=ReceivedState(row.received_state),
                received_qty=row.received_qty,
                settled_at=row.settled_at,
                attested_by=row.attested_by,
            )
        )
    commitments = [
        EngineCommitment(
            id=row.id,
            supplier_id=row.supplier_id,
            due_at=row.due_at,
            lines=tuple(lines.get(row.id, ())),
        )
        for row in (
            await connection.execute(select(SupplierCommitment).order_by(SupplierCommitment.id))
        ).all()
    ]
    ledger = [
        EngineLedgerEntry(
            seq=row.seq,
            resource_id=row.resource_id,
            delta=row.delta,
            source_kind=LedgerSourceKind(row.source_kind),
            source_id=row.source_id,
            recorded_at=row.recorded_at,
        )
        for row in (
            await connection.execute(
                select(InventoryLedgerEntry).order_by(InventoryLedgerEntry.seq)
            )
        ).all()
    ]
    return GraphSnapshot.build(
        resources=resources, suppliers=suppliers, commitments=commitments, ledger=ledger
    )


def _text(value: Decimal | None) -> str | None:
    """Quantities reach JSONB as text. A float in the payload would be a float in the record."""
    return None if value is None else str(value)
