"""A socket that leaves this machine fails the test that opened it.

The suites in this directory test the two modules that can spend money, and their central
claim is that running them spends nothing. "We passed a fake provider" is a statement about
intent. This is a statement about the process: every outbound connection is intercepted, and
anything that is not loopback raises instead of connecting.

Loopback is allowed because the test infrastructure itself uses it -- asyncio's event loop
opens a self-pipe on Windows -- and because a connection to this machine is not a provider
call, an AWS call or a data disclosure. Everything else is refused and recorded, so the count
of off-machine connections is a number a test can assert on rather than a hope.

The guard is installed twice, at two scopes, because a scope is exactly what it used to miss.
pytest builds higher-scoped fixtures first, so a module-scoped fixture's setup ran before any
function-scoped ``autouse`` one -- and the module-scoped fixture in this directory opened a
database and dropped things in it. The session-scoped installation covers that window; the
function-scoped one is unchanged, so what a test sees is what it always saw.

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


def _install(patch: pytest.MonkeyPatch) -> None:
    """Wrap the three ways a connection is opened, whatever scope is asking."""
    patch.setattr(socket.socket, "connect", _guard("connect", socket.socket.connect))
    patch.setattr(socket.socket, "connect_ex", _guard("connect_ex", socket.socket.connect_ex))
    patch.setattr(
        socket, "create_connection", _guard("create_connection", socket.create_connection)
    )


@pytest.fixture(scope="session", autouse=True)
def refuse_off_machine_connections_outside_a_test() -> Iterator[None]:
    """The same interception, for everything that happens between tests rather than inside one.

    The fixture below is function-scoped, and pytest builds higher-scoped fixtures first: a
    module-scoped ``setup`` opened its connections before any function-scoped guard existed.
    ``test_sur1_world_lifecycle_postgres`` was the module that had one, and it dropped and
    created a database in it.

    That module now proves its own target local before it connects, which is the protection
    that matters -- it also covers the Alembic child process, which no in-process patch can
    reach. This is the net underneath it, so the next module-scoped fixture in this directory
    does not have to rediscover the gap.
    """
    with pytest.MonkeyPatch.context() as patch:
        _install(patch)
        yield


@pytest.fixture(autouse=True)
def refuse_off_machine_connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Intercept every outbound connection for the duration of one test."""
    _install(monkeypatch)
    yield
