"""The ``pp`` operator CLI."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from promisepatch.cli import app

runner = CliRunner()


def test_api_is_a_subcommand_not_the_root_command() -> None:
    """``pp`` stays a command group, so later subcommands do not change its shape."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "api" in result.stdout


def test_bare_invocation_shows_help() -> None:
    assert runner.invoke(app, []).exit_code != 0


def test_api_serves_the_application_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_run(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr("uvicorn.run", fake_run)

    result = runner.invoke(app, ["api", "--host", "0.0.0.0", "--port", "9001", "--reload"])

    assert result.exit_code == 0, result.output
    assert calls == [
        (("promisepatch.main:app",), {"host": "0.0.0.0", "port": 9001, "reload": True})
    ]
