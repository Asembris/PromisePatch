"""Record what unrelated ready work waits while one semantic call is held open.

This is the harness the predeclared protocol names --- see
`docs/g8-head-of-line-predeclaration.md`, which was written and committed before this file
existed. It does three things and refuses a fourth.

It **arranges**: a fixture reset, one case whose sentence the deterministic interpreter cannot
read, staged until its ``INTERPRET_SEMANTICALLY`` step is pending, and then eight unrelated
cases whose first steps queue strictly behind it because ``steps.claim_step`` orders by
``created_at``.

It **injects**: the delay is a subclass of ``FakeSemanticProvider`` handed to ``Worker`` through
the constructor field the product already exposes. Nothing under ``apps/backend/src`` is changed,
and the number of milliseconds is an explicit operator argument rather than a condition anything
fell into. The control arm runs the identical class with the number set to zero.

It **captures**: one JSON file per run, holding every raw instant the database recorded, the
arrangement it asserted, the provider's own hold, the implementation SHA and the environment.

And it **computes no verdict**. There is no wait, no median, no ``H`` and no pass or fail
anywhere in this file. Every subtraction belongs to §9 of the predeclaration, applied by a later
session to captures it did not write. A run labelled ``smoke`` is proof that this harness
executes and is not the measurement: §9 reads captures labelled ``measurement`` and no others.

Nothing here reaches AWS, a model or the deployed host. The provider is the fake plus a sleep.

Check the clone, with no database and no container::

    uv run python scripts/run_head_of_line.py --check

Take the predeclared measurement against the local stack::

    uv run python scripts/with_local_env.py -- uv run python scripts/run_head_of_line.py

Prove the harness runs, without measuring anything::

    uv run python scripts/with_local_env.py -- uv run python scripts/run_head_of_line.py --smoke
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import select

from promisepatch.config import Settings, get_settings
from promisepatch.db.models import AuditEvent, CaseStep
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.domain import intake
from promisepatch.domain.adapters import FakeEffectAdapter
from promisepatch.domain.identity import WorkerIdentity
from promisepatch.domain.model import AUDIT_STEP_EXECUTED
from promisepatch.domain.observation import STEP_INTERPRET_SEMANTICALLY
from promisepatch.semantic import FakeSemanticProvider
from promisepatch.semantic.jobs import JobSpec
from promisepatch.semantic.provider import Attempt
from promisepatch.worker import Worker

ROOT: Final = Path(__file__).resolve().parents[1]

RUNNER_VERSION: Final = "1.0.0"
"""Bumped whenever the harness changes how it arranges or observes. Recorded in every capture."""

PREDECLARATION: Final = "docs/g8-head-of-line-predeclaration.md"
CAPTURE_DIR: Final = ROOT / "docs" / "head-of-line" / "runs"

DELAY_MS: Final = 8000
"""§4.2. Well inside ``steps.LEASE_DURATION`` and eight times §8's threshold."""

REPETITIONS: Final = 3
"""§4.5. Three runs per arm, alternating, so drift falls on both arms equally."""

SMOKE_DELAY_MS: Final = 500
SMOKE_REPETITIONS: Final = 1
"""The shortened shape of §12. Deliberately different numbers, so a smoke capture cannot be
mistaken for a measurement capture by anything that reads only the numbers."""

BOUND_SECONDS: Final = 120.0
"""§9 example C. A tracked step still pending when this elapses has no ``started_at``."""

PREFLIGHT_QUIET_SECONDS: Final = 2.0
"""§7. A live worker container claims a pending step inside its one-second idle interval."""

POLL_SECONDS: Final = 0.2
"""How often the supervisor asks whether the tracked steps are settled. A stop condition only:
no published instant comes from it."""

STAGING_CYCLE_LIMIT: Final = 10
"""§4.4 step 3 needs two cycles. More than this means the arrangement did not form."""

TERMINAL_STEP_STATES: Final[frozenset[str]] = frozenset({"DONE", "FAILED", "SKIPPED"})

DELAYED_SENTENCE: Final = "the delivery situation is weird"
"""§4.1. ``_intake_support.UNREADABLE``: no supply, stock or equipment marker, so the
deterministic reading cannot conclude and a semantic step is enqueued."""

UNRELATED_SENTENCES: Final[tuple[str, ...]] = (
    "the deck oven is down",
    "the convection oven is down",
    "the butter spoiled",
    "the mascarpone spoiled",
    "the lemon curd spoiled",
    "the dark chocolate spoiled",
    "the ladyfingers spoiled",
    "the cream in the walk-in went off",
)
"""§4.3, in order. Eight sentences the deterministic interpreter resolves outright, naming eight
different resources. The order is fixed because queue position must be comparable across runs."""

REPORTER: Final = "maya"
"""The seeded baker. The measurement makes no claim about who speaks; it needs a principal the
fixture knows."""

STEP_COLUMNS: Final = (
    CaseStep.id,
    CaseStep.case_id,
    CaseStep.step_key,
    CaseStep.kind,
    CaseStep.state,
    CaseStep.attempts,
    CaseStep.created_at,
    CaseStep.started_at,
    CaseStep.done_at,
)


class HarnessRefusalError(RuntimeError):
    """The harness will not produce a record it cannot vouch for. Raised before, never after."""


class StagingProviderCalledError(RuntimeError):
    """A staging cycle reached the provider. Loud, because the delay belongs in the timed window."""


class RefusingProvider(FakeSemanticProvider):
    """The provider staging runs with. Calling it at all is a bug in the arrangement."""

    name = "head-of-line-staging"

    async def invoke(self, spec: JobSpec, content: str, *, correction: str | None) -> Attempt:
        raise StagingProviderCalledError(
            "a staging cycle claimed the semantic step; the delay would have been spent outside "
            "the measured window"
        )


class DelayingProvider(FakeSemanticProvider):
    """``FakeSemanticProvider``, held open for a stated number of milliseconds.

    The answer, the validation path and the stored reading are the unmodified fake's. The only
    difference is the sleep, and in the control arm the number is zero, so the two arms differ
    in one integer and in nothing else.
    """

    name = "head-of-line-harness"

    def __init__(self, delay_ms: int) -> None:
        super().__init__()
        self.delay_ms = delay_ms
        self.holds_ms: list[float] = []

    async def invoke(self, spec: JobSpec, content: str, *, correction: str | None) -> Attempt:
        began = time.perf_counter_ns()
        if self.delay_ms > 0:
            await asyncio.sleep(self.delay_ms / 1000)
        self.holds_ms.append(round((time.perf_counter_ns() - began) / 1_000_000, 1))
        return await super().invoke(spec, content, correction=correction)


@dataclass(frozen=True, slots=True)
class Arm:
    """One run's identity within the alternating sequence."""

    arm: str
    repetition: int
    ordinal: int
    delay_ms: int


@dataclass
class RunRecord:
    """Everything one run observed. Raw instants only; no interval is computed here."""

    arm: Arm
    label: str
    invocation_id: str
    worker_identity: str
    fixture_reset: dict[str, Any] = field(default_factory=dict)
    preflight: dict[str, Any] = field(default_factory=dict)
    arrangement: dict[str, Any] = field(default_factory=dict)
    provider: dict[str, Any] = field(default_factory=dict)
    window: dict[str, Any] = field(default_factory=dict)
    delayed_case: dict[str, Any] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)
    untracked_steps: list[dict[str, Any]] = field(default_factory=list)
    step_executed_actor_ids: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------------ reading


def _moment(value: datetime | None) -> str | None:
    """An instant exactly as the database recorded it, or ``None`` because it recorded none."""
    return None if value is None else value.astimezone(UTC).isoformat()


def _row(record: Any) -> dict[str, Any]:
    return {
        "step_id": str(record.id),
        "case_id": str(record.case_id),
        "step_key": record.step_key,
        "kind": record.kind,
        "state": record.state,
        "attempts": record.attempts,
        "created_at": _moment(record.created_at),
        "started_at": _moment(record.started_at),
        "done_at": _moment(record.done_at),
    }


async def _steps_of(database: RuntimeDatabase, case_ids: Sequence[UUID]) -> list[Any]:
    async with database.begin() as connection:
        result = await connection.execute(
            select(*STEP_COLUMNS)
            .where(CaseStep.case_id.in_(case_ids))
            .order_by(CaseStep.created_at, CaseStep.id)
        )
        return list(result.all())


async def _first_step(database: RuntimeDatabase, case_id: UUID, kind: str | None = None) -> Any:
    rows = [row for row in await _steps_of(database, [case_id]) if kind is None or row.kind == kind]
    return rows[0] if rows else None


async def _database_now(database: RuntimeDatabase) -> datetime:
    async with database.begin() as connection:
        from promisepatch.db.clock import database_now

        return await database_now(connection)


async def _oldest_claimable(database: RuntimeDatabase) -> Any:
    async with database.begin() as connection:
        result = await connection.execute(
            select(*STEP_COLUMNS)
            .where(CaseStep.state.in_(("PENDING", "RETRYING")))
            .order_by(CaseStep.created_at, CaseStep.id)
            .limit(1)
        )
        return result.first()


async def _executing_actors(database: RuntimeDatabase, case_ids: Sequence[UUID]) -> list[str]:
    """Every principal the audit ledger says executed a step of these cases.

    A second worker process is the condition §10 voids on, and this is where it would show:
    ``steps.execute_step`` attributes the governed write to the worker identity that claimed it.
    """
    async with database.begin() as connection:
        result = await connection.execute(
            select(AuditEvent.actor_id)
            .where(AuditEvent.case_id.in_(case_ids), AuditEvent.type == AUDIT_STEP_EXECUTED)
            .distinct()
        )
        return sorted(str(value) for value in result.scalars() if value is not None)


# ------------------------------------------------------------------------------------ driving


async def _settled(database: RuntimeDatabase, step_ids: Sequence[UUID]) -> bool:
    async with database.begin() as connection:
        result = await connection.execute(select(CaseStep.state).where(CaseStep.id.in_(step_ids)))
        states = list(result.scalars())
    return len(states) == len(step_ids) and all(state in TERMINAL_STEP_STATES for state in states)


async def _await_settled(database: RuntimeDatabase, step_ids: Sequence[UUID]) -> None:
    while not await _settled(database, step_ids):
        await asyncio.sleep(POLL_SECONDS)


def _reset(settings: Settings) -> dict[str, Any]:
    """Run the product's own operator command, unchanged, in its own process."""
    completed = subprocess.run(
        [sys.executable, "-m", "promisepatch.cli", "reset-demo-state"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if completed.returncode != 0:
        raise HarnessRefusalError(
            f"pp reset-demo-state exited {completed.returncode}: {completed.stderr.strip()}"
        )
    return {
        "exit_code": completed.returncode,
        "stdout_lines": [line for line in completed.stdout.splitlines() if line.strip()],
    }


async def _open(database: RuntimeDatabase, sentence: str) -> UUID:
    result = await intake.open_physical_exception(
        database,
        command_id=uuid4(),
        worker_id=REPORTER,
        raw_text=sentence,
        observed_at=datetime.now(UTC),
    )
    return result.case_id


async def _stage_semantic_step(worker: Worker, database: RuntimeDatabase, case_id: UUID) -> Any:
    """Cycle until the semantic step exists and is pending, and never claim it."""
    for _ in range(STAGING_CYCLE_LIMIT):
        row = await _first_step(database, case_id, STEP_INTERPRET_SEMANTICALLY)
        if row is not None and row.state == "PENDING":
            return row
        await worker.run_once()
    raise HarnessRefusalError(
        f"no pending {STEP_INTERPRET_SEMANTICALLY} step formed within "
        f"{STAGING_CYCLE_LIMIT} staging cycles"
    )


async def _one_run(settings: Settings, arm: Arm, *, label: str, invocation_id: str) -> RunRecord:
    """Arrange, time, read. Every instant in the record comes from a column, not from here."""
    identity = WorkerIdentity.create()
    record = RunRecord(
        arm=arm, label=label, invocation_id=invocation_id, worker_identity=identity.value
    )
    record.fixture_reset = _reset(settings)

    worker_database = RuntimeDatabase.from_settings(settings)
    observation = RuntimeDatabase.from_settings(settings)
    provider = DelayingProvider(arm.delay_ms)
    try:
        delayed_case_id = await _open(worker_database, DELAYED_SENTENCE)

        # Preflight: nothing here runs a cycle, so a step that moves was moved by somebody else.
        await asyncio.sleep(PREFLIGHT_QUIET_SECONDS)
        first = await _first_step(observation, delayed_case_id)
        if first is None or first.state != "PENDING" or first.attempts != 0:
            raise HarnessRefusalError(
                "another worker is running against this database: the delayed case's first step "
                f"is {None if first is None else first.state} after "
                f"{PREFLIGHT_QUIET_SECONDS}s of quiet. Stop the compose `worker` container."
            )
        record.preflight = {
            "quiet_seconds": PREFLIGHT_QUIET_SECONDS,
            "state": first.state,
            "attempts": first.attempts,
        }

        staging = Worker(
            database=worker_database,
            adapter=FakeEffectAdapter(),
            identity=identity,
            semantic=RefusingProvider(),
        )
        semantic_step = await _stage_semantic_step(staging, observation, delayed_case_id)

        unrelated: list[tuple[str, UUID]] = []
        for sentence in UNRELATED_SENTENCES:
            unrelated.append((sentence, await _open(worker_database, sentence)))

        tracked: list[tuple[int, str, UUID, Any]] = []
        for ordinal, (sentence, case_id) in enumerate(unrelated, start=1):
            row = await _first_step(observation, case_id)
            if row is None:
                raise HarnessRefusalError(f"case for {sentence!r} enqueued no step")
            tracked.append((ordinal, sentence, case_id, row))

        oldest = await _oldest_claimable(observation)
        record.arrangement = {
            "semantic_step_id": str(semantic_step.id),
            "semantic_step_state": semantic_step.state,
            "oldest_claimable_step_id": None if oldest is None else str(oldest.id),
            "semantic_step_is_oldest_claimable": oldest is not None
            and oldest.id == semantic_step.id,
            "tracked_states": [row.state for _, _, _, row in tracked],
            "tracked_all_pending": all(row.state == "PENDING" for _, _, _, row in tracked),
        }
        if not record.arrangement["semantic_step_is_oldest_claimable"]:
            raise HarnessRefusalError(
                "the semantic step is not the oldest claimable row; there is no head of the "
                "line to block"
            )
        if not record.arrangement["tracked_all_pending"]:
            raise HarnessRefusalError("a tracked step was not PENDING when the window opened")

        tracked_ids = [row.id for _, _, _, row in tracked]
        timed = Worker(
            database=worker_database,
            adapter=FakeEffectAdapter(),
            identity=identity,
            semantic=provider,
        )

        t0_database = await _database_now(observation)
        t0_monotonic = time.perf_counter_ns()
        stop = asyncio.Event()
        loop = asyncio.create_task(timed.run_forever(stop))
        stop_reason = "all-tracked-settled"
        try:
            await asyncio.wait_for(_await_settled(observation, tracked_ids), BOUND_SECONDS)
        except TimeoutError:
            stop_reason = "bound-elapsed"
            record.failures.append(
                f"the {BOUND_SECONDS}s bound elapsed with tracked steps unsettled"
            )
        finally:
            stop.set()
            await loop
        stopped_monotonic = time.perf_counter_ns()
        stopped_database = await _database_now(observation)

        record.window = {
            "t0_database": _moment(t0_database),
            "stopped_database": _moment(stopped_database),
            "t0_monotonic_ns": t0_monotonic,
            "stopped_monotonic_ns": stopped_monotonic,
            "stop_reason": stop_reason,
            "bound_seconds": BOUND_SECONDS,
        }
        record.provider = {
            "name": provider.name,
            "requested_delay_ms": provider.delay_ms,
            "calls": len(provider.holds_ms),
            "holds_ms": list(provider.holds_ms),
        }

        every = {row.id: row for row in await _steps_of(observation, [delayed_case_id])}
        semantic_after = every.get(semantic_step.id)
        record.delayed_case = {
            "sentence": DELAYED_SENTENCE,
            "case_id": str(delayed_case_id),
            "semantic_step": None if semantic_after is None else _row(semantic_after),
        }

        by_case = {
            case_id: {row.id: row for row in rows}
            for case_id, rows in _grouped(
                await _steps_of(observation, [case_id for _, _, case_id, _ in tracked])
            ).items()
        }
        for ordinal, sentence, case_id, row in tracked:
            rows = by_case.get(case_id, {})
            after = rows.get(row.id)
            record.items.append(
                {
                    "ordinal": ordinal,
                    "sentence": sentence,
                    "case_id": str(case_id),
                    "tracked": True,
                    "step": None if after is None else _row(after),
                }
            )
            record.untracked_steps.extend(
                {"sentence": sentence, "tracked": False, "step": _row(other)}
                for identifier, other in rows.items()
                if identifier != row.id
            )

        record.step_executed_actor_ids = await _executing_actors(
            observation, [delayed_case_id, *(case_id for _, _, case_id, _ in tracked)]
        )
        return record
    finally:
        await worker_database.dispose()
        await observation.dispose()


def _grouped(rows: Sequence[Any]) -> dict[UUID, list[Any]]:
    grouped: dict[UUID, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row.case_id, []).append(row)
    return grouped


# ----------------------------------------------------------------------------------- capture


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], capture_output=True, text=True, cwd=ROOT, check=False
    )
    return completed.stdout.strip()


def _endpoint(url: str) -> str:
    """Host, port and database name. Never the credential that precedes them."""
    split = urlsplit(url)
    host = split.hostname or "?"
    port = "" if split.port is None else f":{split.port}"
    return f"{host}{port}{split.path}"


async def _postgres_version(settings: Settings) -> str:
    database = RuntimeDatabase.from_settings(settings)
    try:
        async with database.begin() as connection:
            from sqlalchemy import text

            value = await connection.scalar(text("SELECT version()"))
            return str(value)
    finally:
        await database.dispose()


def _environment(settings: Settings, postgres: str) -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "postgres": postgres,
        "database_endpoint": _endpoint(settings.require_database_url()),
        "log_level": "WARNING",
        "model_calls": 0,
        "aws_calls": 0,
        "order_system_used": False,
        "worker_processes": 1,
    }


def _capture(
    record: RunRecord, *, environment: dict[str, Any], sha: str, dirty: list[str]
) -> dict[str, Any]:
    return {
        "runner_version": RUNNER_VERSION,
        "invocation_id": record.invocation_id,
        "label": record.label,
        "protocol": (
            f"the measurement predeclared in {PREDECLARATION}"
            if record.label == "measurement"
            else (
                f"NOT the measurement predeclared in {PREDECLARATION}. A smoke run: one run per "
                f"arm and a shortened delay, taken only as evidence that the harness executes. "
                f"Its numbers are interpreted nowhere."
            )
        ),
        "predeclaration": PREDECLARATION,
        "computed": (
            "nothing. This harness records instants. Every wait, median, added delay and verdict "
            f"belongs to §9 of {PREDECLARATION}."
        ),
        "written_at": datetime.now(UTC).isoformat(),
        "implementation_sha": sha,
        "working_tree_clean": not dirty,
        "working_tree_dirty": dirty,
        "environment": environment,
        "arm": record.arm.arm,
        "repetition": record.arm.repetition,
        "ordinal": record.arm.ordinal,
        "delay_ms": record.arm.delay_ms,
        "worker_identity": record.worker_identity,
        "fixture_reset": record.fixture_reset,
        "preflight": record.preflight,
        "arrangement": record.arrangement,
        "provider": record.provider,
        "window": record.window,
        "delayed_case": record.delayed_case,
        "items": record.items,
        "untracked_steps": record.untracked_steps,
        "step_executed_actor_ids": record.step_executed_actor_ids,
        "failures": record.failures,
    }


def write_capture(capture: dict[str, Any], *, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f%z")
    name = f"{stamp}-{capture['label']}-{capture['arm']}-{capture['repetition']}.json"
    path = directory / name
    path.write_text(json.dumps(capture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def sequence(*, repetitions: int, delay_ms: int) -> tuple[Arm, ...]:
    """``C T C T C T``: alternating, so drift over the invocation falls on both arms equally."""
    arms: list[Arm] = []
    ordinal = 0
    for repetition in range(1, repetitions + 1):
        for name, delay in (("control", 0), ("treatment", delay_ms)):
            ordinal += 1
            arms.append(Arm(arm=name, repetition=repetition, ordinal=ordinal, delay_ms=delay))
    return tuple(arms)


# -------------------------------------------------------------------------------------- entry


async def _run_all(arms: Sequence[Arm], *, label: str, directory: Path) -> int:
    settings = get_settings().model_copy(update={"log_level": "WARNING"})
    from promisepatch.observability import configure_logging

    configure_logging(settings)

    sha = _git("rev-parse", "HEAD")
    dirty = [line for line in _git("status", "--porcelain").splitlines() if line.strip()]
    environment = _environment(settings, await _postgres_version(settings))
    invocation_id = str(uuid4())

    print(f"runner {RUNNER_VERSION}  label {label}  invocation {invocation_id}")
    print(f"implementation {sha}  working tree {'clean' if not dirty else 'DIRTY'}")
    print(f"predeclaration {PREDECLARATION}")
    for arm in arms:
        print(
            f"  run {arm.ordinal}/{len(arms)}  {arm.arm} {arm.repetition}  delay {arm.delay_ms}ms"
        )
        record = await _one_run(settings, arm, label=label, invocation_id=invocation_id)
        path = write_capture(
            _capture(record, environment=environment, sha=sha, dirty=dirty), directory=directory
        )
        print(f"    captured {path.relative_to(ROOT).as_posix()}")
        if record.failures:
            for failure in record.failures:
                print(f"    failure: {failure}")
    print("no wait, no median and no verdict was computed. That is §9's work, not this file's.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run the shortened shape that proves the harness executes; not the measurement",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the clone can run this, touching no database and no container",
    )
    parser.add_argument(
        "--out",
        default=str(CAPTURE_DIR),
        help="directory the per-run captures are written to",
    )
    arguments = parser.parse_args(argv)

    if arguments.check:
        print(f"runner {RUNNER_VERSION}")
        print(f"predeclaration {PREDECLARATION}")
        print(f"delayed sentence {DELAYED_SENTENCE!r}")
        print(f"unrelated sentences {len(UNRELATED_SENTENCES)}")
        print(f"measurement: delay {DELAY_MS}ms, {REPETITIONS} runs per arm")
        print(f"smoke: delay {SMOKE_DELAY_MS}ms, {SMOKE_REPETITIONS} run per arm")
        print("imports resolved; no database was opened and no container was required")
        return 0

    label = "smoke" if arguments.smoke else "measurement"
    arms = sequence(
        repetitions=SMOKE_REPETITIONS if arguments.smoke else REPETITIONS,
        delay_ms=SMOKE_DELAY_MS if arguments.smoke else DELAY_MS,
    )
    try:
        return asyncio.run(_run_all(arms, label=label, directory=Path(arguments.out)))
    except HarnessRefusalError as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
