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

* it opens nothing while a live case exists, and nothing while today's own case exists;
* every statement it makes carries a **derived command id**, one identity per bakery day, so
  the case id is derived (:func:`~promisepatch.domain.physical.case_id_for`) and a redelivered
  command -- a second boot, a second host, a retried run -- is recognised by intake rather than
  opening a second case;
* the whole thing is serialised by a session-level advisory lock taken with
  ``pg_try_advisory_lock``, so a second process that finds it held skips rather than
  queueing behind it.

**And it keeps the world it lands on from going stale.** ``docs/demo-fixture-anchoring.md``
measured the decay: the seed is a point-in-time world written once per instance, so a case
opened on any later day resolves *today's raspberry delivery* to tomorrow's delivery, which no
promise is waiting on, and the two bands the product exists to show disappear without anything
reporting an error. Opening a fresh case is not a repair for that, and the code says why:
``promisepatch.domain.analysis``'s ``_live_tracks_elsewhere`` gives every promise another live
case already holds the ``LINKED`` state, so a second case opened beside the first shows six
linked tracks and no authority bands at all. The world itself has to move, and the case that
was holding it has to be concluded first.

So a run whose world no longer tells the story concludes the untouched case it opened -- through
the domain's own bounded withdrawal, which reverses nothing physical because there is nothing to
reverse -- moves every fixture instant forward with
:func:`promisepatch.fixtures.reanchor.reanchor_world`, and opens today's case against it.
**It refuses to do any of that if anything would be lost**: one dispatched effect, one customer
reply, one approval request or decision, or one live case this module did not open is enough to
leave the world exactly where it is and say so in the log. A stale demo is a bad demo; a demo
that ate somebody's work is a broken product, and P6.2 records what that costs.

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
from typing import Any, Final, Protocol
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.examples import hollow_oak
from promisepatch.config import Settings
from promisepatch.db import RuntimeDatabase
from promisepatch.db.boundary import advisory_lock_key
from promisepatch.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    Case,
    CaseReport,
    CommitmentLine,
    ExceptionClarification,
    FixtureState,
    InboundReply,
    OutboxMessage,
    Promise,
    SupplierCommitment,
)
from promisepatch.db.uow import Actor
from promisepatch.domain import intake, withdrawal
from promisepatch.domain.cases import CASE_PLANNED
from promisepatch.domain.model import TERMINAL_CASE_STATES
from promisepatch.domain.observation import ClarificationSlot
from promisepatch.domain.physical import bakery_day, case_id_for
from promisepatch.fixtures import demo, reanchor
from promisepatch.fixtures.reset import FIXTURE_STATE_ID
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
"""The namespaces a world's command identities are derived in, not the identities themselves.

Intake derives a case id from the command id and recognises a redelivered command. One fixed
identity would make "run this at every boot" safe and "run this again after the world moved"
impossible: the second report would be read as a redelivery of the first and answered with the
case it already opened -- which, after a roll, is the very case the roll just concluded.

So the identity is derived from **the anchor the world is loaded at**, and it changes exactly
when the world does. Two boots against one world produce one case; a roll produces a new world
and therefore a new case; and nothing about either depends on what the wall clock calls today.
"""

ROLL_ACTOR: Final = Actor(kind="SYSTEM", id="promisepatch.provisioning")
"""Who the audit row names when the demo world is moved. Nothing human authorised it."""


def report_command_id(anchor: datetime) -> UUID:
    """The identity of the report that opens the demo case for the world at ``anchor``."""
    return uuid5(REPORT_COMMAND_ID, f"report:{anchor.isoformat()}")


def answer_command_id(anchor: datetime) -> UUID:
    """The identity of the answer to that case's one open question."""
    return uuid5(ANSWER_COMMAND_ID, f"answer:{anchor.isoformat()}")


def withdraw_command_id(case_id: UUID) -> UUID:
    """The identity of the withdrawal that concludes one superseded demo case.

    Derived from the case rather than minted, so a roll interrupted after the withdrawal and
    retried redelivers that withdrawal instead of failing against a case it already concluded.
    """
    return uuid5(REPORT_COMMAND_ID, f"withdraw:{case_id}")


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

    REFUSED = "REFUSED"
    """The world no longer tells the story and was left exactly as it is, because moving it
    would have moved rows under something somebody is using. Nothing was written."""


@dataclass(frozen=True, slots=True)
class ProvisionOutcome:
    """What happened, in terms an operator reading a log and a test can both check."""

    action: Provisioned
    case_id: UUID | None = None
    state: str | None = None
    detail: str = ""
    rolled: bool = False
    """Whether this run moved the demo world forward before it opened anything."""

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
                settings=settings,
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
    settings: Settings,
    max_cycles: int,
    deadline_seconds: float,
) -> ProvisionOutcome:
    """The run itself, with the lock held."""
    now = datetime.now(UTC)
    rolled = False

    async with database.connect() as connection:
        anchor = await _world_anchor(connection)
        if anchor is None:
            return ProvisionOutcome(
                Provisioned.REFUSED, detail="no demo world is loaded; a seed has never run here"
            )
        current = await _world_tells_the_story(connection, now)
        live = await _live_cases(connection)
        blocker = None if current else await _what_would_be_lost(connection, live, anchor)

    if not current:
        if blocker is not None:
            logger.warning("provisioning.demo_world.refused", detail=blocker)
            return ProvisionOutcome(Provisioned.REFUSED, detail=blocker)
        await _conclude(database, live)
        anchor = demo.resolve_demo_anchor(now, settings.bakery_tz)
        async with database.begin() as connection:
            await reanchor.reanchor_world(connection, anchor=anchor, now=now, actor=ROLL_ACTOR)
        rolled = True
        live = ()

    command_id = report_command_id(anchor)
    identity = case_id_for(command_id)
    async with database.connect() as connection:
        if await _case_exists(connection, identity):
            return ProvisionOutcome(
                Provisioned.PRESENT,
                case_id=identity,
                detail="this world's case already exists; nothing was touched",
                rolled=rolled,
            )
    if live:
        return ProvisionOutcome(
            Provisioned.PRESENT, detail="a case already exists; nothing was touched", rolled=rolled
        )

    opened = await intake.open_physical_exception(
        database,
        command_id=command_id,
        worker_id=ATTESTOR,
        raw_text=REPORTED,
        observed_at=now,
    )
    case_id = opened.case_id
    budget = _Budget(cycles=max_cycles, until=time.monotonic() + deadline_seconds)

    question = await _run_to_question(database, case_id, cycles=cycles, budget=budget)
    if question is None:
        return await _stopped(database, case_id, "no answerable question was reached", rolled)
    if question is not ClarificationSlot.SCOPE:
        # The one ambiguity this cannot resolve: near the bakery's midnight both Valley Produce
        # deliveries fall on the same day, the interpreter asks which commitment was meant, and
        # every option carries the same words. Guessing costs an answer and two unmatched
        # answers escalate the case permanently, so it is left on the question -- which is a
        # real state of the product and shows a judge an open question rather than a result.
        return await _stopped(database, case_id, f"the open question is {question.value}", rolled)

    await intake.answer_clarification(
        database,
        case_id=case_id,
        command_id=answer_command_id(anchor),
        worker_id=ATTESTOR,
        raw_text=ANSWERED,
    )
    state = await _run_to_plan(database, case_id, cycles=cycles, budget=budget)
    if state != CASE_PLANNED:
        return await _stopped(database, case_id, f"the case settled at {state}", rolled)

    logger.info("provisioning.demo_case.opened", case_id=str(case_id), state=state, rolled=rolled)
    return ProvisionOutcome(Provisioned.OPENED, case_id=case_id, state=state, rolled=rolled)


# ------------------------------------------------------- does the world still tell the story


async def _world_anchor(connection: AsyncConnection) -> datetime | None:
    """The instant this world's fixture is loaded at, or ``None`` if no seed has ever run here.

    It is what the demo case's identity is derived from, so it is read once and carried rather
    than asked for twice: a value that changed between the two reads would mint a second case
    for one world.
    """
    if not await connection.scalar(
        select(SupplierCommitment.id).where(SupplierCommitment.id == hollow_oak.VP_TODAY)
    ):
        return None
    anchor = await connection.scalar(
        select(FixtureState.anchor_at).where(FixtureState.id == FIXTURE_STATE_ID)
    )
    return None if anchor is None else anchor


async def _world_tells_the_story(connection: AsyncConnection, now: datetime) -> bool:
    """Two measurements over the durable rows, both of them the decay this exists to stop.

    The first is the interpreter's own question, asked of the database rather than of a stored
    anchor: does exactly one raspberry-bearing delivery fall in the bakery day a report made now
    would be narrowed against? ``docs/demo-fixture-anchoring.md`` measured what the other
    answers cost -- two of them means the case stops to ask which delivery was meant and every
    option carries the same words, and one *wrong* one means it resolves confidently to
    tomorrow's delivery, which no promise is waiting on, and every reached promise falls to
    ``BLOCKED`` with nothing reporting an error.

    The second is cheaper and just as fatal to a demo: a promise whose deadline has passed reads
    as a missed one whatever the case says about it.
    """
    start, end = bakery_day(now)
    today = await connection.scalar(
        select(func.count(func.distinct(SupplierCommitment.id)))
        .select_from(SupplierCommitment)
        .join(CommitmentLine, CommitmentLine.commitment_id == SupplierCommitment.id)
        .where(
            CommitmentLine.resource_id == hollow_oak.RASPBERRIES,
            SupplierCommitment.due_at >= start,
            SupplierCommitment.due_at < end,
        )
    )
    if int(today or 0) != 1:
        return False
    overdue = await connection.scalar(
        select(func.count()).select_from(Promise).where(Promise.due_at <= now)
    )
    return int(overdue or 0) == 0


# --------------------------------------------------------------- what a roll would cost, first


async def _live_cases(connection: AsyncConnection) -> tuple[Any, ...]:
    """Every case that has not finished. A terminal case is history and moves under nothing."""
    rows = (
        await connection.execute(
            select(Case.id, Case.state, Case.opened_by, Case.opened_at)
            .where(Case.state.not_in(sorted(TERMINAL_CASE_STATES)))
            .order_by(Case.opened_at)
        )
    ).all()
    return tuple(rows)


async def _what_would_be_lost(
    connection: AsyncConnection, live: tuple[Any, ...], anchor: datetime
) -> str | None:
    """The reason a roll must not happen, or ``None`` if nothing here belongs to anybody.

    Four questions, in the order that makes the answer cheapest to read in a log. The first
    three are asked of the whole database rather than of one case on purpose: an effect that
    reached the External Order System, or a customer who replied, means this deployment is no
    longer a world nobody has used, and which case it happened on does not change that. It also
    means the order mirror and the simulator have diverged from a fresh seed, which is the state
    ``docs/demo-fixture-anchoring.md`` records spoiling run 1 of the voice measurement.
    """
    if await _any(connection, OutboxMessage):
        return "an operational effect has been queued; this world is no longer untouched"
    if await _any(connection, InboundReply):
        return "a customer has replied; nothing here may move under that"
    if await _any(connection, ApprovalRequest) or await _any(connection, ApprovalDecision):
        return "an approval has been asked for or answered; nothing here may move under that"
    for case in live:
        if not await _is_provisioning_case(connection, case, anchor):
            return f"case {case.id} is {case.state} and was not opened by provisioning"
    return None


async def _any(connection: AsyncConnection, model: Any) -> bool:
    return bool(await connection.scalar(select(func.count()).select_from(model)))


async def _is_provisioning_case(connection: AsyncConnection, case: Any, anchor: datetime) -> bool:
    """Whether this is the case this module opened against the world as it stands now.

    The identity check is what makes it exact rather than a guess about intent: the case id is
    derived from the command id and the command id from the anchor, so a case somebody opened by
    hand with the very same sentence still has a different id and is protected -- and so is one
    this module opened against an older world, which is a case whose history nobody here can
    account for.
    """
    if case.opened_by != ATTESTOR or case.id != case_id_for(report_command_id(anchor)):
        return False
    said = list(
        (
            await connection.execute(
                select(CaseReport.raw_text)
                .where(CaseReport.case_id == case.id)
                .order_by(CaseReport.ordinal)
            )
        ).scalars()
    )
    return said in ([REPORTED], [REPORTED, ANSWERED])


async def _conclude(database: RuntimeDatabase, live: tuple[Any, ...]) -> None:
    """Hand every superseded demo case to the domain's own bounded withdrawal.

    Not a delete, and not an update of a case row from here. ``withdraw_exception`` is the one
    operation in this system that concludes a case a worker no longer wants, it refuses a
    terminal one, and with no dispatched effect and no production hold to reverse it settles at
    ``CANCELLED`` with every track ``WITHDRAWN`` -- which is what releases those promises, since
    ``WITHDRAWN`` is terminal and a terminal track is not one a later case has to link to.
    """
    for case in live:
        result = await withdrawal.withdraw_exception(
            database,
            case_id=case.id,
            command_id=withdraw_command_id(case.id),
            worker_id=ATTESTOR,
        )
        logger.info("provisioning.demo_case.concluded", case_id=str(case.id), state=result.state)


async def _case_exists(connection: AsyncConnection, case_id: UUID) -> bool:
    return bool(await connection.scalar(select(Case.id).where(Case.id == case_id)))


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


async def _stopped(
    database: RuntimeDatabase, case_id: UUID, detail: str, rolled: bool = False
) -> ProvisionOutcome:
    """Leave the case where it is and say so. Nothing is withdrawn and nothing is guessed."""
    state = await _state(database, case_id)
    logger.warning(
        "provisioning.demo_case.stopped", case_id=str(case_id), state=state, detail=detail
    )
    return ProvisionOutcome(
        Provisioned.STOPPED, case_id=case_id, state=state, detail=detail, rolled=rolled
    )
