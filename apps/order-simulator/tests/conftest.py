"""Fixtures for the order system's own suite.

Every test gets a fresh SQLite file in a temporary directory, because this system's whole job
is to hold durable state and a suite that shared one would be testing the leftovers of the last
test. Nothing here reaches PromisePatch, a PostgreSQL server or the network.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _simulator_support import WEBHOOK_SECRET
from pydantic import SecretStr
from starlette.testclient import TestClient

from order_simulator.app import create_app
from order_simulator.config import Settings
from order_simulator.store import OrderStore


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "order-simulator.sqlite3"


@pytest.fixture
def settings(database_path: Path) -> Settings:
    """Settings built explicitly, never inherited from the developer's environment."""
    return Settings(
        database_path=database_path,
        webhook_url="http://promisepatch.invalid/api/integrations/order-system/events",
        webhook_secret=SecretStr(WEBHOOK_SECRET),
        log_level="warning",
    )


@pytest.fixture
def store(settings: Settings) -> OrderStore:
    created = OrderStore(settings.database_path)
    created.initialize()
    return created


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """The application, with its delivery loop deliberately not running.

    Delivery is exercised directly in ``test_webhooks``; leaving the loop out of the API tests
    keeps them from depending on a background task's timing.
    """
    with TestClient(create_app(settings, deliver=False)) as test_client:
        yield test_client
