"""Liveness behaviour."""

from __future__ import annotations

from starlette.testclient import TestClient

from promisepatch import __version__
from promisepatch.config import Settings
from promisepatch.main import create_app


def test_healthz_reports_liveness(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "api"
    assert body["version"] == __version__


def test_healthz_needs_no_dependencies(client: TestClient) -> None:
    """No database, no provider, no credentials -- so an outage elsewhere cannot kill a task."""
    assert client.get("/healthz").status_code == 200


def test_boot_id_is_stable_within_a_process(client: TestClient) -> None:
    first = client.get("/healthz").json()["boot_id"]
    assert client.get("/healthz").json()["boot_id"] == first


def test_boot_id_differs_across_applications(client: TestClient, settings: Settings) -> None:
    """``boot_id`` is the evidence that a restart really happened."""
    first = client.get("/healthz").json()["boot_id"]
    with TestClient(create_app(settings)) as other:
        assert other.get("/healthz").json()["boot_id"] != first
