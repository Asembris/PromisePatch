"""Asking a model to read a sentence, durably, with no transaction held.

A semantic call is a round trip to somebody else's service, and the one thing it may never be
is a statement inside a database transaction: a connection, its locks and its snapshot held
open for the length of a model's thinking is how a slow provider becomes a stalled kitchen.

So the work is split the way every other provider call in PromisePatch is split, and reuses the
same durable machinery rather than growing another one beside it:

```text
worker claims the INTERPRET_SEMANTICALLY step        (the ordinary claim sweep)
        │
        ├── transaction: hydrate the case, build the candidate set, fingerprint the question
        │   ... commit, hold nothing ...
        ├── the provider call                        (no transaction, no lock, no connection)
        └── transaction: write the reading onto the step row, fenced by the claim
        │
worker executes the step                             (the ordinary execution transaction)
            the case is locked, the fingerprint is rechecked, the reading is consumed
```

Everything that could go wrong leaves correct state:

*The worker dies before the call.* The step is still ``IN_FLIGHT`` with a lease that expires.
Another worker claims it and starts again. Nothing was written, so nothing is undone.

*The worker dies after the call, before the reading is stored.* Same: the lease expires, the
step is reclaimed, and the model is asked again. A model call is not an external effect -- it
moves nothing in anybody's world -- so asking twice costs a fraction of a cent and changes
nothing about what may be concluded from either answer.

*The worker dies after the reading is stored.* The reading is on the row. The next claim finds
it and consumes it without calling anybody, so a crash in this window costs nothing at all.

*The worker dies after consumption commits.* The step is ``DONE`` and is not claimable. There
is no second fact, no second question and no second call.

The reading is stored as the small typed object it is: a category, the identifiers it named,
where in the sentence it saw them. No prompt, no model prose, no reasoning, and nothing a
person said that is not already on the case report.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from promisepatch.db.clock import database_now
from promisepatch.db.models import Case, CaseStep
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.domain import crash, grounding, physical
from promisepatch.domain.observation import CASE_INTERPRETING, statement_id_of
from promisepatch.domain.steps import StepClaim
from promisepatch.observability import get_logger
from promisepatch.semantic import (
    ObservationInterpretation,
    SemanticProvider,
    SemanticProviderError,
    SemanticValidationError,
)

logger = get_logger(__name__)

RESULT_KEY: Final = "semantic"
"""Where a reading lives on ``case_steps.result`` until the transition consumes it.

The step ledger's own column, not a new table. What has to survive a crash here is one small
answer belonging to one step, which is exactly what that column is for -- and a table whose
only purpose was to count model calls would be telemetry pretending to be evidence.
"""

STATUS_READ: Final = "READ"
STATUS_REJECTED: Final = "REJECTED"
STATUS_UNAVAILABLE: Final = "UNAVAILABLE"
STATUS_UNNEEDED: Final = "UNNEEDED"
"""What the preparation found, in the four outcomes the transition has to tell apart.

``READ`` is an answer to consume. ``REJECTED`` is a model that answered something PromisePatch
will not accept, which asking again does not fix. ``UNAVAILABLE`` is a provider that could not
be reached, which asking again might. ``UNNEEDED`` is nobody having been asked: either the
deterministic reading resolved in the meantime, or the statement is not one a second reading
may be put to at all.
"""


@dataclass(frozen=True, slots=True)
class PreparedReading:
    """One question put to a model, and what came back, on its way to the step row."""

    status: str
    payload: dict[str, Any]


async def prepare(
    database: RuntimeDatabase,
    provider: SemanticProvider,
    *,
    claim: StepClaim,
) -> PreparedReading | None:
    """Fetch this step's reading, if it needs one, and store it. ``None`` when nothing was done.

    Called by the worker between claiming the step and executing it, which is the only place in
    the cycle where a provider call can be made with no transaction open. It writes nothing a
    transition depends on except the reading itself, and it decides nothing: the answer it
    stores is still a proposal when the transaction that consumes it starts.
    """
    async with database.begin() as connection:
        existing = await _stored(connection, claim.step_id)
        if existing is not None and existing.get("status") == STATUS_READ:
            return None
        if await _case_state(connection, claim.case_id) != CASE_INTERPRETING:
            # A case that is no longer trying to understand its sentence has no use for a
            # reading of it. Checked before the call rather than after, because the cheapest
            # semantic call is the one nobody makes.
            return None
        context = await physical.hydrate(
            connection,
            case_id=claim.case_id,
            statement_id=statement_id_of(claim.step_key),
            now=await database_now(connection),
        )
        # One pure decision, and it settles both halves at once: whether a model is asked at
        # all, and what it would be asked. Asked in that order rather than built first and
        # gated afterwards, because a statement no reading may be put to must not reach the
        # request that would refuse to carry it.
        question = grounding.question_for(context, case_id=claim.case_id)

    if question is None:
        return await _store(
            database,
            claim=claim,
            prepared=PreparedReading(
                status=STATUS_UNNEEDED,
                payload={
                    "status": STATUS_UNNEEDED,
                    "detail": (
                        "no model was asked: the deterministic reading resolved, or this "
                        "statement is not one a second reading may be put to"
                    ),
                },
            ),
        )

    request = question.request
    common: dict[str, Any] = {
        "request_hash": question.fingerprint,
        "reason": question.reason.value,
        "provider": provider.name,
        "candidates": {
            "resources": len(request.resources),
            "commitments": len(request.commitments),
            "commitment_lines": sum(len(item.lines) for item in request.commitments),
            "equipment": len(request.equipment),
        },
    }

    crash.at(crash.BEFORE_SEMANTIC_CALL)
    try:
        result = await provider.run(request)
    except SemanticValidationError as rejected:
        prepared = PreparedReading(
            status=STATUS_REJECTED,
            payload={
                **common,
                "status": STATUS_REJECTED,
                "failure": rejected.category.value,
                "detail": str(rejected),
            },
        )
    except SemanticProviderError as unavailable:
        prepared = PreparedReading(
            status=STATUS_UNAVAILABLE,
            payload={
                **common,
                "status": STATUS_UNAVAILABLE,
                "retryable": unavailable.retryable,
                "detail": str(unavailable),
            },
        )
    else:
        telemetry = result.telemetry
        prepared = PreparedReading(
            status=STATUS_READ,
            payload={
                **common,
                "status": STATUS_READ,
                "model_id": telemetry.model_id,
                "provider_attempts": telemetry.attempts,
                "input_tokens": telemetry.usage.input_tokens,
                "output_tokens": telemetry.usage.output_tokens,
                "latency_ms": telemetry.usage.latency_ms,
                # The typed reading, and nothing around it. Identifiers, a category and the
                # spans of the sentence they were seen in -- the evidence somebody reviewing
                # this case needs, and none of the material that produced it.
                "reading": result.value.model_dump(mode="json"),
            },
        )

    crash.at(crash.AFTER_SEMANTIC_CALL)
    return await _store(database, claim=claim, prepared=prepared)


async def _store(
    database: RuntimeDatabase, *, claim: StepClaim, prepared: PreparedReading
) -> PreparedReading | None:
    """Write the reading onto the claimed row, or discover the claim is no longer ours.

    Fenced by ``(state, lease_owner, attempts)`` like every other write this claim makes, so a
    worker that stalled past its lease and woke up holding an answer cannot put that answer on
    a row another worker is already executing.
    """
    async with database.begin() as connection:
        affected = (
            await connection.execute(
                update(CaseStep)
                .where(
                    CaseStep.id == claim.step_id,
                    CaseStep.state == "IN_FLIGHT",
                    CaseStep.lease_owner == claim.lease_owner,
                    CaseStep.attempts == claim.attempts,
                )
                .values(result={RESULT_KEY: prepared.payload})
            )
        ).rowcount
    if affected != 1:
        logger.info(
            "worker.semantic.claim_lost",
            step_id=str(claim.step_id),
            step_key=claim.step_key,
            attempt=claim.attempts,
        )
        return None
    logger.info(
        "worker.semantic.prepared",
        step_id=str(claim.step_id),
        step_key=claim.step_key,
        attempt=claim.attempts,
        status=prepared.status,
        provider=prepared.payload.get("provider"),
        model_id=prepared.payload.get("model_id"),
    )
    return prepared


async def _case_state(connection: AsyncConnection, case_id: UUID) -> str | None:
    """The case's state, read without a lock: this is a decision about whether to spend money.

    The authoritative check is the one the consuming transaction makes under the case lock. A
    race here can only cause a reading nobody needed, which is a fraction of a cent and no
    correctness at all.
    """
    state = await connection.scalar(select(Case.state).where(Case.id == case_id))
    return None if state is None else str(state)


async def _stored(connection: AsyncConnection, step_id: UUID) -> dict[str, Any] | None:
    result = await connection.scalar(select(CaseStep.result).where(CaseStep.id == step_id))
    if not isinstance(result, dict):
        return None
    stored = result.get(RESULT_KEY)
    return stored if isinstance(stored, dict) else None


def stored_reading(result: object) -> dict[str, Any] | None:
    """The reading a previous preparation left on a step row, if there is one."""
    if not isinstance(result, dict):
        return None
    stored = result.get(RESULT_KEY)
    return stored if isinstance(stored, dict) else None


def reading_of(payload: dict[str, Any]) -> ObservationInterpretation | None:
    """Rebuild the typed reading from what was persisted, or ``None`` if there is not one.

    Validated on the way back out as well as on the way in, and through the same strict model:
    a row edited by hand, or written by a build that shaped this payload differently, is refused
    here rather than becoming a binding nobody checked. A row carrying no reading at all is that
    same refusal and not an exception -- the caller's answer to both is the sentence going to a
    person, and a payload shape is not worth crashing a worker over. The consent protocol reads
    its own stored label the same way.
    """
    reading = payload.get("reading")
    if not isinstance(reading, dict):
        return None
    return ObservationInterpretation.model_validate(reading)


__all__: Sequence[str] = [
    "RESULT_KEY",
    "STATUS_READ",
    "STATUS_REJECTED",
    "STATUS_UNAVAILABLE",
    "STATUS_UNNEEDED",
    "PreparedReading",
    "prepare",
    "reading_of",
    "stored_reading",
]
