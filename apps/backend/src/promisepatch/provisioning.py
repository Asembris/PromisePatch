"""Bring a deployment up with one case already open, and never erase one that exists.

A judge who presses *Look around a real case* reaches a case in one action, and until now the
case had to have been built by hand: ``pp reset-demo-state`` seeds orders, promises, resources
and staff and **no case at all**, so the entry landed on an empty list unless an operator had
run the CLI recipe and nothing had reset the deployment since. That is the defect this module
closes, and closing it is a provisioning question rather than an authority one --
``docs/adr/0016-a-judge-principal-stays-read-only.md`` is why a visitor is never the one who
opens it.

**This is additive, and the distinction is the whole safety argument.** ``reset_demo_state``
replaces every domain row it owns and is therefore something an operator asks for; this runs at
every worker start, so it may only ever *add*. P6.2 records a reboot that silently re-seeded the
database and erased the very cases the deployment exists to prove outlive the host. Nothing here
truncates, deletes or updates a row that was already there:

* it does nothing at all unless ``cases`` is **entirely empty** -- not "no open case", no case,
  which is the strongest form of "never clobber" available and needs no judgement about which
  case matters;
* both statements it makes carry a **fixed command id**, so the case id is derived
  (:func:`~promisepatch.domain.physical.case_id_for`) and a redelivered command is recognised
  by intake rather than opening a second case;
* the whole thing is serialised by a session-level advisory lock taken with
  ``pg_try_advisory_lock``, so a second process that finds it held skips rather than
  queueing behind it.

**It speaks; it does not conclude.** The case is opened by ``maya`` saying the canonical
sentence and answered by ``maya`` answering the one open question, through
:mod:`promisepatch.domain.intake` exactly as the CLI and the MCP surface do. Every state the
case passes through is reached by ordinary worker cycles. There is no privileged path, nothing
is written directly, and if the interpreter asks a question this cannot answer the case is left
sitting on that question rather than guessed at -- a real, truthful state of the product, and
the one the demo sequence's own step 3 describes.

**Why the worker's start rather than a compose service.** The composition that reaches the
deployed host is uploaded to an SSM standard-tier parameter and has 44 bytes of headroom against
its 4096-byte cap, so a new service does not fit without deleting the file's explanation. The
worker is the one process present in both stacks that already holds everything a case needs to
be interpreted -- the database, the effect adapter, the semantic provider, the order client --
and it restarts idempotently. Starting there costs no byte of the composition and no setting.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from sqlalchemy import exists, select, text

from promise_graph.examples import hollow_oak
from promisepatch.config import Settings
from promisepatch.db import RuntimeDatabase
from promisepatch.db.boundary import advisory_lock_key
from promisepatch.db.models import Case, ExceptionClarification
from promisepatch.domain import intake
from promisepatch.domain.cases import CASE_PLANNED
from promisepatch.domain.observation import ClarificationSlot
from promisepatch.observability import get_logger

logger = get_logger(__name__)

ATTESTOR: Final = hollow_oak.BAKER
"""Who says it: the fixture's own baker, read from the dataset rather than typed again.

She is seeded by :data:`promisepatch.fixtures.demo.STAFF` from this same constant and is already
permitted to attest, so the audit row names a worker that exists. A name typed here would be a
second copy of a bakery fact and would go stale the first time the fixture moved.
"""

REPORTED: Final = "today's raspberry delivery didn't arrive"
"""The canonical spoken exception, verbatim, stored byte for byte as any other report is."""

ANSWERED: Final = "just raspberries - the strawberries came"
"""The canonical answer to the scope question, in the words a baker would use.

It is read by :func:`promisepatch.domain.interpretation.read_scope` over the delivery's own
resources rather than matched against an option code, which is why it is a sentence and not an
identifier.
"""

REPORT_COMMAND_ID: Final = UUID("8f1d6a10-3c58-5c7e-9a2f-1b0c4d7e5a90")
ANSWER_COMMAND_ID: Final = UUID("c4b7e2d9-5a31-5f86-8d04-6e9a2c1b3f57")
"""Fixed command identities, so a second run redelivers rather than restates.

Intake derives a case id from the command id and recognises a redelivered command, so these two
constants are what make "run this at every boot" safe even before the emptiness check refuses
to reach them.
"""

LOCK_NAME: Final = "promisepatch.demo_case_provisioning"
LOCK_KEY: Final = advisory_lock_key(LOCK_NAME)

MAX_CYCLES: Final = 60
"""How many worker cycles provisioning will spend before giving up and letting the loop start.

A bound rather than a guess: the canonical case reaches ``PLANNED`` in well under a dozen, and
what this number really protects is the worker's own start. A provisioning step that could spin
for ever would be a worker that never runs, which is a far worse failure than a missing case.
"""

DEADLINE_SECONDS: Final = 60.0
"""The wall-clock half of the same bound, because a cycle can block on a provider call."""

_TRY_LOCK = text("SELECT pg_try_advisory_lock(:key)")
_UNLOCK = text("SELECT pg_advisory_unlock(:key)")


class Provisioned(StrEnum):
    """What a provisioning run did. Closed, because a caller logs it and a test asserts on it."""

    DISABLED = "DISABLED"
    """This deployment does not offer the judge entry, so it needs nothing to land on."""

    PRESENT = "PRESENT"
    """A case already existed. Nothing was read further, and nothing was touched."""

    CONTENDED = "CONTENDED"
    """Another process holds the lock. It is doing this; doing it twice is not better."""

    OPENED = "OPENED"
    """A case was opened and driven to the state it declares."""

    STOPPED = "STOPPED"
    """A case was opened and could not be carried further. It is left where it stopped."""


@dataclass(frozen=True, slots=True)
class ProvisionOutcome:
    """What happened, in terms an operator reading a log and a test can both check."""

    action: Provisioned
    case_id: UUID | None = None
    state: str | None = None
    detail: str = ""

    @property
    def reached_plan(self) -> bool:
        return self.action is Provisioned.OPENED and self.state == CASE_PLANNED


class Cycles(Protocol):
    """Whatever can run one worker cycle.

    A protocol rather than the class, because :class:`promisepatch.worker.Worker` lives above
    this module and importing it here would invert the layering. What provisioning needs is not
    a worker -- it is the ability to ask the ordinary machinery to make progress.
    """

    async def run_once(self) -> bool: ...


async def ensure_demo_case(
    database: RuntimeDatabase,
    *,
    cycles: Cycles,
    settings: Settings,
    max_cycles: int = MAX_CYCLES,
    deadline_seconds: float = DEADLINE_SECONDS,
) -> ProvisionOutcome:
    """Make sure this deployment has a case to look at, without ever replacing one.

    Gated on :attr:`~promisepatch.config.Settings.demo_session_enabled` on purpose, and not on a
    setting of its own. The defect being fixed is that the judge entry shipped with nothing
    guaranteeing a case for it to land on; two independent switches is exactly how those two
    facts drifted apart, so the deployment that offers the entry is by construction the
    deployment that provisions the case.
    """
    if not settings.demo_session_enabled:
        return ProvisionOutcome(Provisioned.DISABLED, detail="the judge entry is not served here")

    async with database.connect() as connection:
        held = bool((await connection.execute(_TRY_LOCK, {"key": LOCK_KEY})).scalar_one())
        if not held:
            return ProvisionOutcome(
                Provisioned.CONTENDED, detail="another process is provisioning the demo case"
            )
        try:
            return await _provision(
                database,
                cycles=cycles,
                max_cycles=max_cycles,
                deadline_seconds=deadline_seconds,
            )
        finally:
            # Session-level rather than transaction-level, because the work below spans many
            # transactions. A connection handed back to the pool still holding this would lock
            # every later boot out, so the release is a `finally` and not a line at the end.
            await connection.execute(_UNLOCK, {"key": LOCK_KEY})


async def _provision(
    database: RuntimeDatabase,
    *,
    cycles: Cycles,
    max_cycles: int,
    deadline_seconds: float,
) -> ProvisionOutcome:
    """The run itself, with the lock held."""
    async with database.connect() as connection:
        if bool((await connection.execute(select(exists().select_from(Case)))).scalar_one()):
            return ProvisionOutcome(
                Provisioned.PRESENT, detail="a case already exists; nothing was touched"
            )

    opened = await intake.open_physical_exception(
        database,
        command_id=REPORT_COMMAND_ID,
        worker_id=ATTESTOR,
        raw_text=REPORTED,
        observed_at=datetime.now(UTC),
    )
    case_id = opened.case_id
    budget = _Budget(cycles=max_cycles, until=time.monotonic() + deadline_seconds)

    question = await _run_to_question(database, case_id, cycles=cycles, budget=budget)
    if question is None:
        return await _stopped(database, case_id, "no answerable question was reached")
    if question is not ClarificationSlot.SCOPE:
        # The one ambiguity this cannot resolve: near the bakery's midnight both Valley Produce
        # deliveries fall on the same day, the interpreter asks which commitment was meant, and
        # every option carries the same words. Guessing costs an answer and two unmatched
        # answers escalate the case permanently, so it is left on the question -- which is a
        # real state of the product and shows a judge an open question rather than a result.
        return await _stopped(database, case_id, f"the open question is {question.value}")

    await intake.answer_clarification(
        database,
        case_id=case_id,
        command_id=ANSWER_COMMAND_ID,
        worker_id=ATTESTOR,
        raw_text=ANSWERED,
    )
    state = await _run_to_plan(database, case_id, cycles=cycles, budget=budget)
    if state != CASE_PLANNED:
        return await _stopped(database, case_id, f"the case settled at {state}")

    logger.info("provisioning.demo_case.opened", case_id=str(case_id), state=state)
    return ProvisionOutcome(Provisioned.OPENED, case_id=case_id, state=state)


@dataclass(slots=True)
class _Budget:
    """Cycles and wall clock, spent by both drives rather than reset between them."""

    cycles: int
    until: float

    def spend(self) -> bool:
        if self.cycles <= 0 or time.monotonic() >= self.until:
            return False
        self.cycles -= 1
        return True


async def _run_to_question(
    database: RuntimeDatabase, case_id: UUID, *, cycles: Cycles, budget: _Budget
) -> ClarificationSlot | None:
    """Cycle until the case is waiting on an answer, and say which question it is waiting on."""
    while True:
        slot = await _open_question(database, case_id)
        if slot is not None:
            return slot
        if not budget.spend() or not await cycles.run_once():
            return await _open_question(database, case_id)


async def _run_to_plan(
    database: RuntimeDatabase, case_id: UUID, *, cycles: Cycles, budget: _Budget
) -> str:
    """Cycle until the case reaches ``PLANNED``, or until the budget runs out."""
    while True:
        state = await _state(database, case_id)
        if state == CASE_PLANNED:
            return state
        if not budget.spend() or not await cycles.run_once():
            return await _state(database, case_id)


async def _open_question(database: RuntimeDatabase, case_id: UUID) -> ClarificationSlot | None:
    """The slot of the one unanswered clarification on this case, if it is waiting on one."""
    async with database.connect() as connection:
        row = (
            await connection.execute(
                select(ExceptionClarification.slot)
                .where(
                    ExceptionClarification.case_id == case_id,
                    ExceptionClarification.answer_text.is_(None),
                )
                .order_by(ExceptionClarification.ordinal)
                .limit(1)
            )
        ).scalar_one_or_none()
    return None if row is None else ClarificationSlot(row)


async def _state(database: RuntimeDatabase, case_id: UUID) -> str:
    async with database.connect() as connection:
        return str(
            (await connection.execute(select(Case.state).where(Case.id == case_id))).scalar_one()
        )


async def _stopped(database: RuntimeDatabase, case_id: UUID, detail: str) -> ProvisionOutcome:
    """Leave the case where it is and say so. Nothing is withdrawn and nothing is guessed."""
    state = await _state(database, case_id)
    logger.warning(
        "provisioning.demo_case.stopped", case_id=str(case_id), state=state, detail=detail
    )
    return ProvisionOutcome(Provisioned.STOPPED, case_id=case_id, state=state, detail=detail)
