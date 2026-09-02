"""The ``pp`` operator CLI.

Everything an operator does to a running PromisePatch — serve the API, reset the demo
fixture, replay an inbox row — is a subcommand here rather than a script, so each one is
typed, testable and discoverable. Only ``pp api`` exists so far.
"""

from __future__ import annotations

import typer

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


if __name__ == "__main__":  # pragma: no cover
    app()
