"""The ``pp`` operator CLI.

Everything an operator does to a running PromisePatch — serve the API, reset the demo
fixture, replay an inbox row — is a subcommand here rather than a script, so each one is
typed, testable and discoverable.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer

from promisepatch.config import Settings, get_settings
from promisepatch.db import build_engine
from promisepatch.db.uow import Actor
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
