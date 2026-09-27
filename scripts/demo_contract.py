"""The demo-contract runner: the storyboard, executed as assertions, through the product's doors.

``ARCHITECTURE_PLAN.md`` §3 names this file -- *"Executes the storyboard as assertions, including a
real worker restart"* -- and ``new_roadmap.md`` §11 G8 says what it may and may not be: *"uses the
new transport boundaries; no direct DB consent inserts. Fixture setup and fault injection are
explicit operator actions."* Every choice below follows from those two sentences, and
``docs/g8-demo-contract-runner.md`` records them.

**The storyboard** is the one the five deployed rehearsals were judged against
(``docs/g8-rehearsal-preparation.md`` §3.1) and the one effect-set scenario ``S16`` labels: the
canonical case at ``PLANNED``; a worker's approval carried out; ``pr-a`` amended, ``pr-b`` asked,
``pr-c``/``pr-d`` escalated with their tasks held, ``pr-e``/``pr-f`` untouched; the worker
restarted while the customer is thinking; the customer's ``APPROVE``; ten revalidation checks;
``EXT-B`` amended; the case ``RESOLVED`` -- with the restart invisible in every result and visible
only in the worker identity that produced the second half.

**What it does through a transport, and nothing else:**

- reads the plan the case offers, and carries out a person's approval of it, through the internal
  intent API (``/internal/intents/status`` and ``/internal/intents/confirm``) -- the surface the
  frozen design names for this runner, which under ADR-0018 can *spend* a human approval and has
  no way to write one;
- answers for the customer through the signed approval link (``/api/customer/approval/{token}``),
  with the link taken from the message the customer was actually sent. It never mints one: it
  holds no link secret, so it can answer exactly as far as a customer could and no further;
- reads the External Order System's own store over its HTTP surface, so "the order changed" is
  said by the system of record and not by PromisePatch's mirror of it.

**What it reads from the database, and how.** Evidence -- counts, states, audit rows, digests --
is read in one ``SET TRANSACTION READ ONLY`` transaction per snapshot. That is the database
enforcing that this process cannot insert, update or delete anything, rather than this file
promising not to. A customer's channel address is compared inside SQL and hashed there for the
digest; it never enters this process, and no address, token or link is ever printed.

**What is an operator's, and stays one.** The runner never creates a fixture, never approves a
plan and never touches the worker process:

- the world must already be the restored canonical one (``pp restore-demo-world``); anything else
  is refused with exit code 2, before any transport is called, and nothing is created to fix it;
- the worker's approval is a person's act on a surface where a person authenticates -- their
  browser session or ``pp confirm-plan`` at the console (ADR-0018). The runner asks for it, waits,
  and then checks that exactly that approval exists;
- the restart is the operator's (``docker compose restart worker``). The runner asks for it,
  waits, checks that the restart changed nothing, and later proves it happened: every piece of
  work after it must carry a worker identity no work before it carried. An acknowledgement
  without a restart fails the run.

Exit codes: ``0`` the storyboard held, ``1`` an assertion failed (the failing check is named),
``2`` a prerequisite was not met and nothing was done.

``PP_DATABASE_URL`` comes from ``scripts/with_local_env.py``; the service token is the API's own
and is read from its env file into the environment, never passed as an argument::

    PP_INTERNAL_SERVICE_TOKEN="$(grep '^PP_INTERNAL_SERVICE_TOKEN=' docker/env/api.env \\
        | cut -d= -f2-)" uv run python scripts/with_local_env.py -- \\
        uv run python scripts/demo_contract.py \\
        --api http://127.0.0.1:48000 --order-system http://127.0.0.1:48100
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Protocol, TextIO
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx2
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from promise_graph.examples import hollow_oak as ho
from promise_graph.model import (
    ApprovalDecisionKind,
    ApprovalRequestState,
    Classification,
    ParserKind,
    RuleId,
)
from promisepatch.api.routers.intents import SERVICE_TOKEN_HEADER
from promisepatch.config import Settings
from promisepatch.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    AuditEvent,
    Case,
    Customer,
    DomainEvent,
    FixtureState,
    InboundReply,
    InboxEvent,
    Order,
    OrderConstraint,
    OrderLine,
    OutboxMessage,
    PlanApproval,
    ProductionTask,
    Promise,
    Reservation,
    Track,
)
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.domain import customer_link
from promisepatch.domain.approvals import AUDIT_APPROVAL_DECISION, CUSTOMER_REPLY_SOURCE
from promisepatch.domain.cases import CASE_PLANNED, CASE_RESOLVED, CASE_WAITING
from promisepatch.domain.model import EFFECT_MESSAGE_SEND, EFFECT_ORDER_AMEND
from promisepatch.domain.plan_approval import AUDIT_PLAN_APPROVED, ApprovalChannel
from promisepatch.domain.recovery import (
    AUDIT_PLAN_CONFIRMED,
    AUDIT_RECOVERY_APPLIED,
    AUDIT_RECOVERY_COMPLETED,
    TRACK_ESCALATED,
    TRACK_RECOVERED,
)
from promisepatch.domain.revalidation import AUDIT_REVALIDATION_CHECK, AUDIT_REVALIDATION_PASSED

RUNNER_VERSION: Final = "1.0.0"

EXIT_PASS: Final = 0
EXIT_FAIL: Final = 1
EXIT_REFUSED: Final = 2

FIXTURE_NAME: Final = "hollow-oak"
TRACK_WAITING: Final = "WAITING_FOR_CUSTOMER"
TASK_HELD: Final = "HELD"
HUMAN_APPROVAL: Final = "HUMAN_APPROVAL"
REVALIDATION_CHECKS: Final = 10
CANONICAL_CUSTOMER: Final = "cus-tomas"

UNSETTLED_EFFECT_STATES: Final = frozenset({"PENDING", "IN_FLIGHT", "RETRYING"})
LIVE_CASE_STATES: Final = frozenset({"EXECUTING", CASE_WAITING, "REVALIDATING", "RECONCILING"})

PLANNED_PARTITION: Final[Mapping[str, tuple[str, str]]] = {
    ho.PROMISE_A: (Classification.AUTO_RECOVERABLE.value, RuleId.R_PREAPPROVED.value),
    ho.PROMISE_B: (Classification.APPROVAL_REQUIRED.value, RuleId.R_VISIBLE_ASK.value),
    ho.PROMISE_C: (Classification.BLOCKED.value, RuleId.R_NOSUB.value),
    ho.PROMISE_D: (Classification.BLOCKED.value, RuleId.R_NOSUB.value),
}
"""The threatened set and why, exactly as ``S16``'s ``PLANNED`` checkpoint labels it."""

UNTOUCHED_PROMISES: Final = (ho.PROMISE_E, ho.PROMISE_F)
UNTOUCHED_ORDERS: Final = (ho.ORDER_E, ho.ORDER_F)
UNRELATED_ORDERS: Final = (ho.ORDER_C, ho.ORDER_D, ho.ORDER_E, ho.ORDER_F)
"""The frozen reader's two scopes: outside ``pr-a``/``pr-b``, and outside everything threatened."""

AMENDED: Final[Mapping[str, tuple[str, str]]] = {
    "EXT-A": (ho.LINE_A, ho.RAC_V4),
    "EXT-B": (ho.LINE_B, ho.RRC_V3),
}
"""The two orders a completed story amends, the line each moves and the version it lands on."""

WORKER_IDENTITY: Final = re.compile(r"^.+:\d+:[0-9a-f]{8}$")
"""``WorkerIdentity.create``'s shape, ``host:pid:boot``. It picks out the rows a worker process
wrote from rows written by a person, a customer or a named tool."""


# ================================================================================ outcomes


class Refused(Exception):  # noqa: N818 -- an outcome, named for what the operator reads
    """A prerequisite is not met. Nothing was called and nothing was written."""


class Violation(Exception):  # noqa: N818
    """The storyboard did not hold. ``check`` names the assertion that failed."""

    def __init__(self, check: str, detail: str) -> None:
        super().__init__(f"{check}: {detail}")
        self.check = check
        self.detail = detail


class OperatorAction(StrEnum):
    """The two things the storyboard needs a person to do while it runs."""

    APPROVE_PLAN = "approve-plan"
    RESTART_WORKER = "restart-worker"


class Operator(Protocol):
    """Whoever performs the operator's actions. The runner asks; it never performs one itself."""

    async def perform(self, action: OperatorAction, instruction: str) -> None: ...


@dataclass(slots=True)
class ConsoleOperator:
    """A person at the terminal: shown the instruction, and waited for until they press Enter."""

    out: TextIO
    read_line: Callable[[], str] = input

    async def perform(self, action: OperatorAction, instruction: str) -> None:
        print(f"\nOPERATOR ACTION [{action.value}]\n{instruction}", file=self.out, flush=True)
        print("Press Enter once it is done.", file=self.out, flush=True)
        await asyncio.to_thread(self.read_line)


@dataclass(frozen=True, slots=True)
class Surfaces:
    """Everything the runner reaches: two HTTP surfaces, one credential and a read-only handle."""

    api: httpx2.AsyncClient
    order_system: httpx2.AsyncClient
    service_token: str
    database: RuntimeDatabase


# ================================================================================ evidence


@dataclass(frozen=True, slots=True)
class Effect:
    kind: str
    state: str
    attempts: int
    key: str
    lease_owner: str | None


@dataclass(frozen=True, slots=True)
class AuditRow:
    seq: int
    type: str
    track_promise: str | None
    actor_kind: str
    actor_id: str | None
    authority: str
    worker: str | None
    passed: bool | None


@dataclass(frozen=True, slots=True)
class World:
    """One read-only snapshot of everything the storyboard asserts about."""

    fixture_name: str | None
    cases: tuple[tuple[UUID, str], ...]
    tracks: Mapping[str, tuple[str, str | None, str | None]]
    effects: tuple[Effect, ...]
    requests: tuple[tuple[str, str], ...]
    decisions: tuple[tuple[str, str, bool], ...]
    replies: int
    customer_replies: tuple[tuple[str, str | None], ...]
    plan_approvals: tuple[tuple[str, str, str], ...]
    mirror: Mapping[str, tuple[int, str]]
    lines: Mapping[str, str]
    held_tasks: Mapping[str, int]
    audit: tuple[AuditRow, ...]
    untouched_attributed: int
    unrelated_digest: str
    untouched_digest: str

    @property
    def case_state(self) -> str | None:
        return self.cases[0][1] if len(self.cases) == 1 else None

    def outstanding_effects(self) -> int:
        return sum(1 for effect in self.effects if effect.state in UNSETTLED_EFFECT_STATES)

    def durable_facts(self) -> tuple[Any, ...]:
        """What a restart must leave exactly as it found it."""
        return (
            self.cases,
            tuple(sorted(self.tracks.items())),
            tuple(sorted((e.kind, e.state, e.attempts, e.key) for e in self.effects)),
            self.requests,
            self.decisions,
            self.replies,
            self.plan_approvals,
            tuple(sorted(self.mirror.items())),
            tuple(sorted(self.lines.items())),
            tuple(sorted(self.held_tasks.items())),
            self.unrelated_digest,
        )

    def worker_identities(self, *, after: int = 0, through: int | None = None) -> set[str]:
        """Worker processes that wrote an audit row in ``(after, through]``."""
        found: set[str] = set()
        for row in self.audit:
            if row.seq <= after or (through is not None and row.seq > through):
                continue
            for candidate in (row.actor_id if row.actor_kind == "SYSTEM" else None, row.worker):
                if candidate is not None and WORKER_IDENTITY.match(candidate):
                    found.add(candidate)
        return found


def _canon(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canon(value).encode()).hexdigest()


async def _rows(connection: AsyncConnection, statement: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in (await connection.execute(statement)).mappings().all()]


async def _components(connection: AsyncConnection, orders: Sequence[str]) -> dict[str, Any]:
    """The frozen reader's per-order scope: orders, lines, constraints, promises, tracks, tasks,
    reservations and customers, with each customer's address hashed inside the database."""
    lines = select(OrderLine.id).where(OrderLine.order_id.in_(orders))
    return {
        "orders": await _rows(
            connection,
            select(
                Order.id,
                Order.external_id,
                Order.external_version,
                Order.customer_id,
                Order.due_at,
                Order.state,
            )
            .where(Order.id.in_(orders))
            .order_by(Order.id),
        ),
        "lines": await _rows(
            connection,
            select(
                OrderLine.id, OrderLine.order_id, OrderLine.recipe_version_id, OrderLine.quantity
            )
            .where(OrderLine.order_id.in_(orders))
            .order_by(OrderLine.id),
        ),
        "constraints": await _rows(
            connection,
            select(OrderConstraint.id, OrderConstraint.order_id, OrderConstraint.kind)
            .where(OrderConstraint.order_id.in_(orders))
            .order_by(OrderConstraint.id),
        ),
        "promises": await _rows(
            connection,
            select(
                Promise.id,
                Promise.order_id,
                Promise.current_classification,
                Promise.current_track_state,
            )
            .where(Promise.order_id.in_(orders))
            .order_by(Promise.id),
        ),
        "tracks": await _rows(
            connection,
            select(Track.promise_id, Track.state, Track.classification, Track.rule_id)
            .join(Promise, Promise.id == Track.promise_id)
            .where(Promise.order_id.in_(orders))
            .order_by(Track.promise_id, Track.id),
        ),
        "tasks": await _rows(
            connection,
            select(ProductionTask.id, ProductionTask.state, ProductionTask.held_by_case_id)
            .where(ProductionTask.order_line_id.in_(lines))
            .order_by(ProductionTask.id),
        ),
        "reservations": await _rows(
            connection,
            select(Reservation.id, Reservation.resource_id, Reservation.quantity)
            .where(Reservation.order_line_id.in_(lines))
            .order_by(Reservation.id),
        ),
        "customers": await _rows(
            connection,
            select(Customer.id, func.md5(Customer.approval_channel_address).label("h"))
            .where(Customer.id.in_(select(Order.customer_id).where(Order.id.in_(orders))))
            .order_by(Customer.id),
        ),
    }


async def read_world(database: RuntimeDatabase) -> World:
    """One snapshot, in a transaction the database itself holds read-only."""
    async with database.connect() as connection:
        await connection.execute(text("SET TRANSACTION READ ONLY"))
        return await _read(connection)


async def _read(connection: AsyncConnection) -> World:
    fixture = (await connection.execute(select(FixtureState.fixture_name))).scalars().first()
    cases = tuple(
        (row.id, row.state)
        for row in (await connection.execute(select(Case.id, Case.state).order_by(Case.opened_at)))
    )
    case_ids = [case_id for case_id, _ in cases]
    tracks = {
        row.promise_id: (row.state, row.classification, row.rule_id)
        for row in await connection.execute(
            select(Track.promise_id, Track.state, Track.classification, Track.rule_id).where(
                Track.case_id.in_(case_ids)
            )
        )
    }
    effects = tuple(
        Effect(row.kind, row.state, row.attempts, row.idempotency_key, row.lease_owner)
        for row in await connection.execute(
            select(
                OutboxMessage.kind,
                OutboxMessage.state,
                OutboxMessage.attempts,
                OutboxMessage.idempotency_key,
                OutboxMessage.lease_owner,
            ).order_by(OutboxMessage.created_at)
        )
    )
    requests = tuple(
        (row.state, row.promise_id)
        for row in await connection.execute(
            select(ApprovalRequest.state, ApprovalRequest.promise_id).order_by(
                ApprovalRequest.sent_at
            )
        )
    )
    decisions = tuple(
        (row.decision, row.parser, bool(row.same_channel))
        for row in await connection.execute(
            select(
                ApprovalDecision.decision,
                ApprovalDecision.parser,
                (ApprovalDecision.sender_identity == ApprovalRequest.customer_channel).label(
                    "same_channel"
                ),
            ).join(ApprovalRequest, ApprovalRequest.id == ApprovalDecision.request_id)
        )
    )
    replies = int(
        (await connection.execute(select(func.count()).select_from(InboundReply))).scalar_one()
    )
    customer_replies = tuple(
        (row.state, (row.raw_headers or {}).get("transport"))
        for row in await connection.execute(
            select(InboxEvent.state, InboxEvent.raw_headers).where(
                InboxEvent.source == CUSTOMER_REPLY_SOURCE
            )
        )
    )
    plan_approvals = tuple(
        (row.plan_id, row.channel, row.approved_by)
        for row in await connection.execute(
            select(PlanApproval.plan_id, PlanApproval.channel, PlanApproval.approved_by)
        )
    )
    mirror = {
        row.external_id: (row.external_version, row.state)
        for row in await connection.execute(
            select(Order.external_id, Order.external_version, Order.state)
        )
    }
    lines = {
        row.id: row.recipe_version_id
        for row in await connection.execute(select(OrderLine.id, OrderLine.recipe_version_id))
    }
    held_tasks = {
        row.order_id: int(row.held)
        for row in await connection.execute(
            select(OrderLine.order_id, func.count().label("held"))
            .join(ProductionTask, ProductionTask.order_line_id == OrderLine.id)
            .where(ProductionTask.state == TASK_HELD, ProductionTask.held_by_case_id.is_not(None))
            .group_by(OrderLine.order_id)
        )
    }
    audit = tuple(
        AuditRow(
            seq=row.seq,
            type=row.type,
            track_promise=row.promise_id,
            actor_kind=row.actor_kind,
            actor_id=row.actor_id,
            authority=row.authority,
            worker=(row.provenance or {}).get("worker"),
            passed=(row.after or {}).get("passed"),
        )
        for row in await connection.execute(
            select(
                AuditEvent.seq,
                AuditEvent.type,
                Track.promise_id,
                AuditEvent.actor_kind,
                AuditEvent.actor_id,
                AuditEvent.authority,
                AuditEvent.provenance,
                AuditEvent.after,
            )
            .outerjoin(Track, Track.id == AuditEvent.track_id)
            .where(AuditEvent.case_id.in_(case_ids))
            .order_by(AuditEvent.seq)
        )
    )
    unrelated = await _components(connection, UNRELATED_ORDERS)
    untouched = await _components(connection, UNTOUCHED_ORDERS)
    return World(
        fixture_name=fixture,
        cases=cases,
        tracks=tracks,
        effects=effects,
        requests=requests,
        decisions=decisions,
        replies=replies,
        customer_replies=customer_replies,
        plan_approvals=plan_approvals,
        mirror=mirror,
        lines=lines,
        held_tasks=held_tasks,
        audit=audit,
        untouched_attributed=await _untouched_attribution(connection, untouched),
        unrelated_digest=_digest(unrelated),
        untouched_digest=_digest(untouched),
    )


async def _untouched_attribution(connection: AsyncConnection, untouched: dict[str, Any]) -> int:
    """The frozen reader's four structural counts for ``pr-e``/``pr-f``, since the fixture loaded:
    audit rows on their tracks, domain events naming any of their ids, outbox payloads naming
    them, and approval requests on their promises. Every one must be zero."""
    loaded = (await connection.execute(select(FixtureState.loaded_at))).scalars().first()
    ids = set(UNTOUCHED_ORDERS)
    for part in ("lines", "promises", "tasks", "customers"):
        ids |= {str(row["id"]) for row in untouched[part]}
    ids |= {str(row["external_id"]) for row in untouched["orders"]}
    track_ids = [
        row.id
        for row in await connection.execute(
            select(Track.id).where(Track.promise_id.in_(UNTOUCHED_PROMISES))
        )
    ]
    ids |= {str(track_id) for track_id in track_ids}
    audit = (
        await connection.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.occurred_at >= loaded, AuditEvent.track_id.in_(track_ids))
        )
    ).scalar_one()
    events = sum(
        1
        for refs in (
            await connection.execute(
                select(DomainEvent.entity_refs).where(DomainEvent.occurred_at >= loaded)
            )
        ).scalars()
        if any(isinstance(ref, dict) and str(ref.get("id")) in ids for ref in refs or ())
    )
    outbox = sum(
        1
        for payload in (await connection.execute(select(OutboxMessage.payload))).scalars()
        if any(f'"{identifier}"' in _canon(payload) for identifier in ids)
    )
    requests = (
        await connection.execute(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(ApprovalRequest.promise_id.in_(UNTOUCHED_PROMISES))
        )
    ).scalar_one()
    return int(audit) + events + outbox + int(requests)


async def delivered_link(database: RuntimeDatabase) -> str | None:
    """The approval link in the message the customer was sent -- the customer's device, read.

    Under the fake provider the delivered outbox payload *is* the message; ``approval_url`` is the
    only place the link exists (``test_the_message_carries_a_link_to_the_customers_own_channel``).
    Returned to the caller and never printed.
    """
    async with database.connect() as connection:
        await connection.execute(text("SET TRANSACTION READ ONLY"))
        payload = (
            (
                await connection.execute(
                    select(OutboxMessage.payload).where(
                        OutboxMessage.kind == EFFECT_MESSAGE_SEND,
                        OutboxMessage.state == "DELIVERED",
                    )
                )
            )
            .scalars()
            .first()
        )
    url = None if payload is None else payload.get("approval_url")
    return url if isinstance(url, str) else None


def token_of(url: str) -> str | None:
    values = parse_qs(urlsplit(url).query).get(customer_link.PARAM)
    return values[0] if values else None


# ================================================================================ the contract


@dataclass(slots=True)
class Contract:
    """Prints each assertion as it passes and raises on the first that does not."""

    out: TextIO
    passed: list[str] = field(default_factory=list)

    def expect(self, check: str, holds: bool, detail: str = "") -> None:
        if not holds:
            raise Violation(check, detail or "did not hold")
        self.passed.append(check)
        print(f"PASS  {check}", file=self.out, flush=True)

    def note(self, line: str) -> None:
        print(f"      {line}", file=self.out, flush=True)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise Refused(reason)


def prerequisite(world: World) -> UUID:
    """The world an operator restored, or a refusal. Checks only; creates nothing."""
    _require(world.fixture_name == FIXTURE_NAME, "the database does not hold the demo fixture")
    _require(len(world.cases) == 1, f"expected exactly one case, found {len(world.cases)}")
    case_id, state = world.cases[0]
    _require(state == CASE_PLANNED, f"the case is {state}, not {CASE_PLANNED}")
    threatened = {
        promise: (classification, rule)
        for promise, (_, classification, rule) in world.tracks.items()
        if promise in PLANNED_PARTITION
    }
    _require(threatened == dict(PLANNED_PARTITION), "the case is not the canonical partition")
    _require(
        all(world.tracks.get(p, ("UNAFFECTED",))[0] == "UNAFFECTED" for p in UNTOUCHED_PROMISES),
        "an untouched promise carries a live track",
    )
    for name, count in (
        ("outbox rows", len(world.effects)),
        ("approval requests", len(world.requests)),
        ("customer decisions", len(world.decisions)),
        ("customer replies", world.replies),
        ("plan approvals", len(world.plan_approvals)),
    ):
        _require(count == 0, f"{name} already exist ({count}); the world is not freshly restored")
    _require(
        all(version == 1 for version, _ in world.mirror.values()),
        "an order is past external version 1",
    )
    return case_id


class Runner:
    """The storyboard, step by step. Holds the surfaces, the operator and the contract."""

    def __init__(
        self,
        surfaces: Surfaces,
        operator: Operator,
        *,
        out: TextIO,
        timeout: float = 120.0,
        poll: float = 0.5,
    ) -> None:
        self.surfaces = surfaces
        self.operator = operator
        self.out = out
        self.timeout = timeout
        self.poll = poll
        self.contract = Contract(out)

    # ------------------------------------------------------------------------ transports

    async def _intent(self, verb: str, body: Mapping[str, Any]) -> httpx2.Response:
        return await self.surfaces.api.post(
            f"/internal/intents/{verb}",
            json=dict(body),
            headers={SERVICE_TOKEN_HEADER: self.surfaces.service_token},
        )

    async def _order_book(self) -> dict[str, tuple[int, str, dict[str, str]]]:
        response = await self.surfaces.order_system.get("/orders")
        self.contract.expect(
            "order system answers its own read", response.status_code == 200, response.text[:200]
        )
        return {
            order["external_id"]: (
                int(order["version"]),
                str(order["state"]),
                {
                    str(line["external_line_id"]): str(line["external_item_id"])
                    for line in order.get("lines", ())
                },
            )
            for order in response.json()["orders"]
        }

    async def _until(self, checkpoint: str, reached: Callable[[World], bool]) -> World:
        deadline = asyncio.get_running_loop().time() + self.timeout
        while True:
            world = await read_world(self.surfaces.database)
            if reached(world):
                return world
            if asyncio.get_running_loop().time() >= deadline:
                raise Violation(
                    f"{checkpoint} reached",
                    f"not reached within {self.timeout:.0f}s; case {world.case_state}, "
                    f"tracks {dict(world.tracks)}, "
                    f"{world.outstanding_effects()} effects outstanding",
                )
            await asyncio.sleep(self.poll)

    # ------------------------------------------------------------------------ the story

    async def run(self) -> int:
        print(f"demo-contract runner {RUNNER_VERSION}", file=self.out, flush=True)
        try:
            await self._story()
        except Refused as refusal:
            print(f"REFUSED  {refusal}", file=self.out, flush=True)
            print(
                "Nothing was called and nothing was written. Restore the canonical world first:\n"
                "  uv run pp restore-demo-world --confirm destroy-and-restore",
                file=self.out,
                flush=True,
            )
            return EXIT_REFUSED
        except Violation as violation:
            print(f"FAIL  {violation.check}: {violation.detail}", file=self.out, flush=True)
            print("DEMO CONTRACT FAIL", file=self.out, flush=True)
            return EXIT_FAIL
        print(
            f"DEMO CONTRACT PASS ({len(self.contract.passed)} assertions)",
            file=self.out,
            flush=True,
        )
        return EXIT_PASS

    async def _story(self) -> None:
        planned = await read_world(self.surfaces.database)
        case_id = prerequisite(planned)
        plan_id = await self._planned(case_id, planned)
        confirmed = await self._confirmed(case_id, plan_id, planned)
        restarted = await self._restart(confirmed)
        answered_after = await self._answer()
        settled = await self._settled(answered_after)
        await self._exactly_once_and_untouched(planned, confirmed, settled)
        self._restart_was_real(confirmed, restarted, answered_after, settled)

    async def _planned(self, case_id: UUID, planned: World) -> str:
        c = self.contract
        c.note(f"case {case_id}")
        response = await self._intent("status", {"case_id": str(case_id)})
        c.expect("PLANNED: intent status answers", response.status_code == 200, response.text[:200])
        status = response.json()
        plan_id = status.get("plan_id")
        c.expect("PLANNED: a plan is on offer", bool(plan_id) and status["awaiting_confirmation"])
        c.expect(
            "PLANNED: status names the threatened four",
            sorted(p["promise_id"] for p in status["threatened"]) == sorted(PLANNED_PARTITION),
            str([p["promise_id"] for p in status["threatened"]]),
        )
        c.expect(
            "PLANNED: status names pr-e and pr-f untouched",
            {p["promise_id"] for p in status["untouched"]} >= set(UNTOUCHED_PROMISES),
        )
        book = await self._order_book()
        c.expect(
            "PLANNED: every order is at version 1 in the order system",
            all(version == 1 for version, _, _ in book.values())
            and set(book) == set(planned.mirror),
        )
        c.note(f"plan {plan_id}")
        return str(plan_id)

    async def _confirmed(self, case_id: UUID, plan_id: str, planned: World) -> World:
        c = self.contract
        await self.operator.perform(
            OperatorAction.APPROVE_PLAN,
            "Approve this plan as yourself, on a surface where you authenticate "
            "(ADR-0018). Either press Approve on the case in your own workspace, or run:\n"
            f"  uv run pp confirm-plan --case {case_id} --worker {ho.BAKER} --plan {plan_id}\n"
            "The runner never approves a plan; it carries out the approval you leave.",
        )
        approved = await read_world(self.surfaces.database)
        human = {channel.value for channel in ApprovalChannel}
        c.expect(
            "CONFIRMED: exactly one human approval of this plan exists",
            len(approved.plan_approvals) == 1
            and approved.plan_approvals[0][0] == plan_id
            and approved.plan_approvals[0][1] in human,
            f"plan approvals: {[(p, ch) for p, ch, _ in approved.plan_approvals]}",
        )
        _, channel, approver = approved.plan_approvals[0]
        c.note(f"approved by {approver} via {channel}")
        if approved.case_state == CASE_PLANNED:
            response = await self._intent(
                "confirm",
                {"case_id": str(case_id), "plan_id": plan_id, "command_id": str(uuid4())},
            )
            c.expect(
                "CONFIRMED: the intent API carries out the person's approval",
                response.status_code == 202,
                response.text[:200],
            )
            body = response.json()
            c.expect(
                "CONFIRMED: the confirmation names the approver and channel, not the service",
                body["confirmed_by"] == approver and body["approved_via"] == channel,
                f"confirmed_by={body['confirmed_by']} approved_via={body['approved_via']}",
            )
        else:
            c.note("the operator's own surface already carried the approval out")

        confirmed = await self._until(
            "CONFIRMED",
            lambda w: (
                w.case_state == CASE_WAITING
                and w.outstanding_effects() == 0
                and len(w.effects) >= 2
            ),
        )
        tracks = confirmed.tracks
        c.expect("CONFIRMED: case is WAITING", confirmed.case_state == CASE_WAITING)
        c.expect(
            "CONFIRMED: pr-a recovered without asking anyone",
            tracks[ho.PROMISE_A][0] == TRACK_RECOVERED,
            str(tracks[ho.PROMISE_A]),
        )
        c.expect(
            "CONFIRMED: pr-b waits for its customer",
            tracks[ho.PROMISE_B][0] == TRACK_WAITING,
            str(tracks[ho.PROMISE_B]),
        )
        c.expect(
            "CONFIRMED: pr-c and pr-d escalated to the owner",
            tracks[ho.PROMISE_C][0] == TRACK_ESCALATED
            and tracks[ho.PROMISE_D][0] == TRACK_ESCALATED,
        )
        c.expect(
            "CONFIRMED: the tasks of pr-c and pr-d are held, and only theirs",
            dict(confirmed.held_tasks) == {ho.ORDER_C: 1, ho.ORDER_D: 1},
            str(dict(confirmed.held_tasks)),
        )
        c.expect(
            "CONFIRMED: one request SENT on pr-b",
            confirmed.requests == ((ApprovalRequestState.SENT.value, ho.PROMISE_B),),
            str(confirmed.requests),
        )
        kinds = sorted((e.kind, e.state, e.attempts) for e in confirmed.effects)
        c.expect(
            "CONFIRMED: one amendment and one message, each delivered at attempt 1",
            kinds == [(EFFECT_MESSAGE_SEND, "DELIVERED", 1), (EFFECT_ORDER_AMEND, "DELIVERED", 1)],
            str(kinds),
        )
        approvals = [
            r for r in confirmed.audit if r.type in (AUDIT_PLAN_APPROVED, AUDIT_PLAN_CONFIRMED)
        ]
        c.expect(
            "CONFIRMED: approval and confirmation are HUMAN_APPROVAL by the person who approved",
            sorted(r.type for r in approvals) == sorted((AUDIT_PLAN_APPROVED, AUDIT_PLAN_CONFIRMED))
            and all(
                r.authority == HUMAN_APPROVAL
                and r.actor_kind == "WORKER"
                and r.actor_id == approver
                for r in approvals
            ),
            str([(r.type, r.authority, r.actor_kind, r.actor_id) for r in approvals]),
        )
        book = await self._order_book()
        c.expect(
            "CONFIRMED: the order system itself holds EXT-A at v2 on the authored version",
            book["EXT-A"][0] == 2 and AMENDED["EXT-A"][1] in book["EXT-A"][2].values(),
            str(book["EXT-A"][:2]),
        )
        c.expect(
            "CONFIRMED: EXT-B is untouched until its customer answers",
            book["EXT-B"][0] == 1 and confirmed.lines[ho.LINE_B] == ho.RRC_V2,
        )
        c.expect(
            "CONFIRMED: plan approvals are still exactly one",
            len(confirmed.plan_approvals) == 1,
        )
        return confirmed

    async def _restart(self, confirmed: World) -> World:
        c = self.contract
        before = confirmed.worker_identities()
        c.expect(
            "RESTART: the work so far was done by a worker process",
            bool(before),
            "no worker identity on any audit row",
        )
        await self.operator.perform(
            OperatorAction.RESTART_WORKER,
            "Restart the worker process now, while the customer has not answered:\n"
            "  docker compose restart worker\n"
            "The runner does not restart anything; it checks afterwards that a different "
            "worker process did the rest.",
        )
        restarted = await read_world(self.surfaces.database)
        c.expect(
            "RESTART: the restart itself changed nothing durable",
            restarted.durable_facts() == confirmed.durable_facts(),
            "a case, track, effect, request, decision, approval, order or task moved",
        )
        return restarted

    async def _answer(self) -> int:
        """The customer answers, through the link in their message. Returns the audit seq before."""
        c = self.contract
        seq = max((row.seq for row in (await read_world(self.surfaces.database)).audit), default=0)
        url = await delivered_link(self.surfaces.database)
        token = None if url is None else token_of(url)
        c.expect("CONSENT: the delivered message carries an approval link", token is not None)
        assert token is not None
        opened = await self.surfaces.api.get(f"/api/customer/approval/{token}")
        c.expect("CONSENT: the link opens the question", opened.status_code == 200)
        pressed = await self.surfaces.api.post(
            f"/api/customer/approval/{token}", json={"answer": "APPROVE"}
        )
        c.expect(
            "CONSENT: the customer's APPROVE is stored by the link transport",
            pressed.status_code == 202,
            f"HTTP {pressed.status_code}",
        )
        return seq

    async def _settled(self, answered_after: int) -> World:
        c = self.contract
        settled = await self._until(
            "SETTLED",
            lambda w: w.case_state not in LIVE_CASE_STATES and w.outstanding_effects() == 0,
        )
        c.expect(
            "SETTLED: case is RESOLVED", settled.case_state == CASE_RESOLVED, str(settled.cases)
        )
        c.expect(
            "CONSENT: one decision, APPROVE, by the literal parser, from the asked channel",
            settled.decisions
            == ((ApprovalDecisionKind.APPROVE.value, ParserKind.LITERAL.value, True),),
            str([(d, p) for d, p, _ in settled.decisions]),
        )
        c.expect(
            "CONSENT: the answer arrived through the customer link and was processed",
            settled.customer_replies == (("PROCESSED", "customer-link"),) and settled.replies == 1,
            str(settled.customer_replies),
        )
        decided = [r for r in settled.audit if r.type == AUDIT_APPROVAL_DECISION]
        c.expect(
            "CONSENT: the decision is HUMAN_APPROVAL by the customer",
            len(decided) == 1
            and decided[0].actor_kind == "CUSTOMER"
            and decided[0].actor_id == CANONICAL_CUSTOMER
            and decided[0].authority == HUMAN_APPROVAL,
            str([(r.actor_kind, r.actor_id, r.authority) for r in decided]),
        )
        checks = [r for r in settled.audit if r.type == AUDIT_REVALIDATION_CHECK]
        c.expect(
            "CONSENT: ten revalidation checks, all passed, written after the decision",
            len(checks) == REVALIDATION_CHECKS
            and all(r.passed is True for r in checks)
            and all(r.seq > decided[0].seq for r in checks),
            f"{len(checks)} checks, passed={[r.passed for r in checks]}",
        )
        applied = {
            r.type
            for r in settled.audit
            if r.track_promise == ho.PROMISE_B and r.authority == HUMAN_APPROVAL
        }
        c.expect(
            "CONSENT: pr-b revalidated, applied and completed under HUMAN_APPROVAL",
            {AUDIT_REVALIDATION_PASSED, AUDIT_RECOVERY_APPLIED, AUDIT_RECOVERY_COMPLETED}
            <= applied,
            str(sorted(applied)),
        )
        c.expect(
            "SETTLED: pr-a and pr-b recovered, pr-c and pr-d escalated",
            [settled.tracks[p][0] for p in PLANNED_PARTITION]
            == [TRACK_RECOVERED, TRACK_RECOVERED, TRACK_ESCALATED, TRACK_ESCALATED],
            str(dict(settled.tracks)),
        )
        c.expect(
            "SETTLED: the request is ANSWERED",
            settled.requests == ((ApprovalRequestState.ANSWERED.value, ho.PROMISE_B),),
            str(settled.requests),
        )
        c.expect(
            "SETTLED: a customer's yes spent no worker approval",
            len(settled.plan_approvals) == 1,
        )
        return settled

    async def _exactly_once_and_untouched(
        self, planned: World, confirmed: World, settled: World
    ) -> None:
        c = self.contract
        kinds = sorted((e.kind, e.state, e.attempts) for e in settled.effects)
        c.expect(
            "EXACTLY ONCE: three effects, two amendments and one message, all at attempt 1",
            kinds
            == [
                (EFFECT_MESSAGE_SEND, "DELIVERED", 1),
                (EFFECT_ORDER_AMEND, "DELIVERED", 1),
                (EFFECT_ORDER_AMEND, "DELIVERED", 1),
            ],
            str(kinds),
        )
        c.expect(
            "EXACTLY ONCE: three distinct idempotency keys",
            len({e.key for e in settled.effects}) == 3,
        )
        c.expect(
            "EXACTLY ONCE: one case, one request, one decision, one reply",
            (len(settled.cases), len(settled.requests), len(settled.decisions), settled.replies)
            == (1, 1, 1, 1),
        )
        book = await self._order_book()
        for external, (line, version) in AMENDED.items():
            c.expect(
                f"SETTLED: the order system holds {external} at v2 on the authored version",
                book[external][0] == 2 and version in book[external][2].values(),
                str(book[external][:2]),
            )
            c.expect(
                f"SETTLED: the mirror agrees on {external}",
                settled.mirror[external] == book[external][:2] and settled.lines[line] == version,
                f"mirror {settled.mirror[external]} vs store {book[external][:2]}",
            )
        c.expect(
            "UNTOUCHED: EXT-C to EXT-F at v1, in the order system and in the mirror",
            all(
                book[e][0] == 1 and settled.mirror[e][0] == 1
                for e in ("EXT-C", "EXT-D", "EXT-E", "EXT-F")
            ),
        )
        c.expect(
            "UNTOUCHED: no message, write, hold or audit event is attributed to pr-e or pr-f",
            settled.untouched_attributed == 0,
            f"{settled.untouched_attributed} attributed rows",
        )
        c.expect(
            "UNTOUCHED: pr-e and pr-f are byte-identical to PLANNED",
            settled.untouched_digest == planned.untouched_digest,
        )
        c.expect(
            "UNTOUCHED: everything outside pr-a and pr-b is identical from CONFIRMED to SETTLED",
            settled.unrelated_digest == confirmed.unrelated_digest,
        )

    def _restart_was_real(
        self, confirmed: World, restarted: World, answered_after: int, settled: World
    ) -> None:
        c = self.contract
        restart_seq = max((row.seq for row in restarted.audit), default=0)
        before = settled.worker_identities(through=restart_seq)
        after = settled.worker_identities(after=answered_after)
        revalidators = {r.worker for r in settled.audit if r.type == AUDIT_REVALIDATION_CHECK}
        c.expect(
            "RESTART: every check was run by one worker process",
            len(revalidators) == 1 and after >= revalidators - {None},
        )
        c.expect(
            "RESTART: the work after the restart carries no identity the work before it carried",
            bool(after) and not (after & before),
            "the same worker process did work on both sides of the restart"
            if after & before
            else "no worker identity after the restart",
        )
        c.note(f"{len(before)} worker identity before the restart, {len(after)} after, disjoint")


# ================================================================================ command line


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute the demo storyboard as assertions through PromisePatch's transports. "
            "Requires a freshly restored canonical world; asks the operator to approve the plan "
            "and to restart the worker, and performs neither."
        )
    )
    parser.add_argument("--api", required=True, help="PromisePatch's HTTP API base URL.")
    parser.add_argument(
        "--order-system", required=True, help="The External Order System's base URL."
    )
    parser.add_argument(
        "--timeout", type=float, default=120.0, help="Seconds to wait for each checkpoint."
    )
    return parser


async def _main(args: argparse.Namespace, out: TextIO) -> int:
    settings = Settings()
    if settings.database_url is None or settings.internal_service_token is None:
        print(
            "REFUSED  PP_DATABASE_URL (scripts/with_local_env.py sets it) and "
            "PP_INTERNAL_SERVICE_TOKEN (the API's own, from its env file) must be set",
            file=out,
        )
        return EXIT_REFUSED
    database = RuntimeDatabase.from_settings(settings)
    try:
        async with (
            httpx2.AsyncClient(base_url=args.api, timeout=30.0) as api,
            httpx2.AsyncClient(base_url=args.order_system, timeout=30.0) as orders,
        ):
            surfaces = Surfaces(
                api=api,
                order_system=orders,
                service_token=settings.internal_service_token.get_secret_value(),
                database=database,
            )
            runner = Runner(surfaces, ConsoleOperator(out), out=out, timeout=args.timeout)
            return await runner.run()
    finally:
        await database.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return asyncio.run(_main(args, sys.stdout))


if __name__ == "__main__":
    raise SystemExit(main())
