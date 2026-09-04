"""The ``pp`` operator CLI.

Everything an operator does to a running PromisePatch — serve the API, reset the demo
fixture, replay an inbox row — is a subcommand here rather than a script, so each one is
typed, testable and discoverable.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer

from promisepatch.config import Settings, get_settings
from promisepatch.db import RuntimeDatabase, build_engine
from promisepatch.db.uow import Actor
from promisepatch.domain import analysis, intake
from promisepatch.fixtures import demo
from promisepatch.fixtures.reset import ResetOutcome, ensure_reset_allowed, reset_demo_state

app = typer.Typer(
    name="pp",
    help="PromisePatch operator commands.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    """Group callback.

    Without it Typer collapses a single-command application into the bare ``pp`` command,
    which would break the moment a second subcommand is added.
    """


@app.command()
def api(
    host: str = typer.Option("127.0.0.1", help="Interface to bind."),
    port: int = typer.Option(8000, help="Port to bind."),
    reload: bool = typer.Option(False, "--reload", help="Reload on source changes."),
) -> None:
    """Run the HTTP API."""
    import uvicorn

    uvicorn.run("promisepatch.main:app", host=host, port=port, reload=reload)


@app.command()
def worker() -> None:
    """Run the durable workflow worker.

    Connects as ``promisepatch_app`` like every other runtime process. Stop it with Ctrl+C or a
    ``SIGTERM``; killing it outright is also fine, because everything it was doing is a row and
    every claim it held expires.
    """
    from promisepatch import worker as worker_module

    settings = get_settings()
    try:
        asyncio.run(worker_module.run(settings))
    except RuntimeError as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error


@app.command(name="reset-demo-state")
def reset_demo_state_command(
    anchor: str = typer.Option(
        "",
        help=(
            "Reset instant as ISO-8601. Naive values are read in the bakery's timezone; "
            "omit it to anchor on now."
        ),
    ),
) -> None:
    """Reload the demo fixture, replacing every domain row PromisePatch owns.

    The audit ledger and the event spine are untouched: they record that this happened, and a
    reset that could erase its own trace would not be a reset worth trusting.
    """
    settings = get_settings()
    try:
        ensure_reset_allowed(settings)
        resolved_anchor = resolve_anchor(anchor, settings)
        outcome = asyncio.run(_run_reset(settings, resolved_anchor))
    except (RuntimeError, ValueError) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    local = outcome.anchor.astimezone(ZoneInfo(settings.bakery_tz))
    typer.echo(f"fixture:  {outcome.fixture_name}")
    typer.echo(f"anchor:   {outcome.anchor.isoformat()} ({local.isoformat()} {settings.bakery_tz})")
    typer.echo(f"digest:   {outcome.digest}")
    typer.echo(f"rows:     {outcome.rows_written}")
    typer.echo(f"audit:    seq {outcome.audit_seq}")
    typer.echo(f"event:    seq {outcome.domain_event_seq}")


def resolve_anchor(given: str, settings: Settings) -> datetime:
    """Turn the operator's ``--anchor`` into one unambiguous UTC instant.

    A naive value is read in the bakery's timezone rather than the server's, because "seven in
    the morning" is a claim about the kitchen, and the machine running this command may be
    nowhere near it. An aware value is taken as given.
    """
    if not given:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(given)
    except ValueError as error:
        raise ValueError(f"--anchor {given!r} is not an ISO-8601 datetime") from error
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    try:
        zone = ZoneInfo(settings.bakery_tz)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError(
            f"PP_BAKERY_TZ names an unknown timezone: {settings.bakery_tz!r}"
        ) from error
    return parsed.replace(tzinfo=zone).astimezone(UTC)


# --------------------------------------------------------------------------- intake commands
#
# Three thin wrappers, and thin is the requirement rather than the style. Each one parses a
# couple of arguments, calls the reusable service in `promisepatch.domain.intake`, and prints
# what came back. Not one line of what may be said, by whom, or what it means lives here --
# that all lives in the domain, where the MCP tools and the voice orchestrator will find it
# unchanged when they arrive.
#
# Nothing here interprets anything either. These commands only make a statement durable; the
# worker reads it, and until a worker runs, the case sits exactly where the command left it.


@app.command(name="report-exception")
def report_exception_command(
    text: str = typer.Argument(..., help="What the worker said, verbatim."),
    worker: str = typer.Option(..., "--worker", help="The staff id attesting the observation."),
    command_id: str = typer.Option(
        "", "--command-id", help="Stable command identity; a retry must reuse it."
    ),
) -> None:
    """Open a case for a spoken physical exception."""
    _intake(
        lambda database: intake.open_physical_exception(
            database,
            command_id=_command_id(command_id),
            worker_id=worker,
            raw_text=text,
            observed_at=datetime.now(UTC),
        )
    )


@app.command(name="answer-clarification")
def answer_clarification_command(
    text: str = typer.Argument(..., help="The worker's answer, verbatim."),
    case: str = typer.Option(..., "--case", help="The case awaiting an answer."),
    worker: str = typer.Option(..., "--worker", help="The staff id answering."),
    command_id: str = typer.Option(
        "", "--command-id", help="Stable command identity; a retry must reuse it."
    ),
) -> None:
    """Answer the open clarification on a case."""
    _intake(
        lambda database: intake.answer_clarification(
            database,
            case_id=_uuid(case, "--case"),
            command_id=_command_id(command_id),
            worker_id=worker,
            raw_text=text,
        )
    )


@app.command(name="correct-physical-fact")
def correct_physical_fact_command(
    text: str = typer.Argument(..., help="The correction, verbatim."),
    case: str = typer.Option(..., "--case", help="The case whose facts are being corrected."),
    worker: str = typer.Option(..., "--worker", help="The staff id making the correction."),
    command_id: str = typer.Option(
        "", "--command-id", help="Stable command identity; a retry must reuse it."
    ),
) -> None:
    """Attest a correction to a physical fact this case already recorded.

    A correction is never an undo. The original attestation stays, and the ledger movement that
    cancels it is appended beside the one it cancels.
    """
    _intake(
        lambda database: intake.correct_physical_fact(
            database,
            case_id=_uuid(case, "--case"),
            command_id=_command_id(command_id),
            worker_id=worker,
            raw_text=text,
        )
    )


# --------------------------------------------------------------------------- case commands


@app.command(name="case-status")
def case_status_command(
    case: str = typer.Option(..., "--case", help="The case to describe."),
) -> None:
    """Show what analysis and planning concluded for one case.

    Read-only. It runs no step, enqueues nothing and changes nothing: the worker is what moves
    a case, and an operator command that quietly did the work would make the durable engine
    optional. Everything printed comes from :func:`promisepatch.domain.analysis.read_case_status`.
    """
    settings = get_settings()
    try:
        status = asyncio.run(_read_case_status(settings, _uuid(case, "--case")))
    except (RuntimeError, ValueError) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"case:      {status.case_id}")
    typer.echo(f"state:     {status.state}")
    typer.echo(f"exception: {status.exception_id or '-'} ({status.category or '-'})")
    typer.echo(f"attention: {'yes' if status.needs_owner_attention else 'no'}")
    for track in status.tracks:
        typer.echo("")
        typer.echo(f"  {track.promise_id}  {track.customer_name} / {track.order_external_id}")
        typer.echo(
            f"    {track.classification or '-'} via {track.rule_id or '-'} "
            f"({track.reason_detail or '-'})"
        )
        typer.echo(
            f"    track {track.state}, priority {track.priority}, "
            f"{track.paths} path(s), {track.watched_entities} watched"
        )
        if track.fingerprint:
            typer.echo(f"    fingerprint {track.fingerprint}")
        if track.linked_track_id:
            typer.echo(f"    linked to track {track.linked_track_id}")
        if track.deadline_at:
            typer.echo(f"    approval window closes {track.deadline_at.isoformat()}")
        for option in track.options:
            marker = "*" if option.chosen else " "
            typer.echo(
                f"   {marker}option {option.kind} {option.from_version_id or '-'} -> "
                f"{option.to_version_id or '-'} "
                f"({'approval required' if option.requires_approval else 'no approval'})"
            )
        if not track.options:
            typer.echo("     no recovery option")


async def _read_case_status(settings: Settings, case_id: UUID) -> analysis.CaseStatus:
    database = RuntimeDatabase.from_settings(settings)
    try:
        return await analysis.read_case_status(database, case_id=case_id)
    finally:
        await database.dispose()


def _uuid(value: str, flag: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise ValueError(f"{flag} {value!r} is not a UUID") from error


def _command_id(value: str) -> UUID:
    """The caller's identity for this statement, or a fresh one if they have none.

    Minting one is right for a person at a terminal: they are not retrying anything, and a new
    identity is exactly what they mean. A transport that can redeliver must supply its own.
    """
    return _uuid(value, "--command-id") if value else intake.new_command_id()


def _intake(operation: Callable[[RuntimeDatabase], Awaitable[intake.IntakeResult]]) -> None:
    """Run one intake command against the runtime connection and report what it did."""
    settings = get_settings()
    try:
        outcome = asyncio.run(_with_database(settings, operation))
    except (RuntimeError, ValueError) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    typer.echo(f"case:      {outcome.case_id}")
    typer.echo(f"statement: {outcome.statement_id}")
    typer.echo(f"state:     {outcome.state}")
    typer.echo(f"accepted:  {'now' if outcome.created else 'already (retry)'}")


async def _with_database(
    settings: Settings, operation: Callable[[RuntimeDatabase], Awaitable[intake.IntakeResult]]
) -> intake.IntakeResult:
    database = RuntimeDatabase.from_settings(settings)
    try:
        return await operation(database)
    finally:
        await database.dispose()


async def _run_reset(settings: Settings, anchor: datetime) -> ResetOutcome:
    """One connection, one transaction: the reset commits whole or not at all."""
    passwords = {
        demo.BAKER_ROLE: settings.require_demo_worker_password(),
        demo.OWNER_ROLE: settings.require_demo_owner_password(),
    }
    engine = build_engine(settings.require_migration_database_url(), pool_size=1)
    try:
        async with engine.begin() as connection:
            return await reset_demo_state(
                connection,
                anchor=anchor,
                now=datetime.now(UTC),
                passwords=passwords,
                actor=Actor(kind="SYSTEM", id="pp reset-demo-state"),
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    app()
