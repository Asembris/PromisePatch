"""A socket that leaves this machine fails the test that opened it.

The suites in this directory test the two modules that can spend money, and their central
claim is that running them spends nothing. "We passed a fake provider" is a statement about
intent. This is a statement about the process: every outbound connection is intercepted, and
anything that is not loopback raises instead of connecting.

Loopback is allowed because the test infrastructure itself uses it -- asyncio's event loop
opens a self-pipe on Windows -- and because a connection to this machine is not a provider
call, an AWS call or a data disclosure. Everything else is refused and recorded, so the count
of off-machine connections is a number a test can assert on rather than a hope.

Nothing here grants a spend authorisation, and nothing here is ``autouse`` except the guard.
That is deliberate and is checked by :func:`test_no_fixture_here_authorises_spending`: a
fixture that quietly authorised paid inference for every test in the directory would recreate,
one layer down, exactly the accident this whole slice exists to prevent.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

OFF_MACHINE_CONNECTIONS: list[str] = []
"""Every non-loopback address a test tried to reach. Expected to stay empty for ever."""

LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost", "0.0.0.0", ""})


class OffMachineConnectionError(RuntimeError):
    """A test tried to open a connection off this machine. No test here has any reason to."""


def _host_of(address: Any) -> str | None:
    if isinstance(address, tuple) and address:
        return str(address[0])
    return None


def _guard(name: str, original: Any) -> Any:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        address = args[1] if name != "create_connection" else args[0]
        host = _host_of(address)
        if host is not None and host not in LOOPBACK:
            OFF_MACHINE_CONNECTIONS.append(f"{name} -> {host}")
            raise OffMachineConnectionError(
                f"a test opened a connection to {host!r}. Nothing in this directory calls a "
                f"provider, an AWS endpoint or any other host: every answer comes from a "
                f"fake handed in as a parameter, or from a file somebody already paid for."
            )
        return original(*args, **kwargs)

    return wrapper


@pytest.fixture(autouse=True)
def refuse_off_machine_connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Intercept every outbound connection for the duration of one test."""
    monkeypatch.setattr(socket.socket, "connect", _guard("connect", socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", _guard("connect_ex", socket.socket.connect_ex))
    monkeypatch.setattr(
        socket, "create_connection", _guard("create_connection", socket.create_connection)
    )
    yield
