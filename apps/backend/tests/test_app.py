"""Application factory behaviour: exposure, correlation and CORS."""

from __future__ import annotations

from starlette.testclient import TestClient

from promisepatch.api.middleware import CORRELATION_HEADER
from promisepatch.config import Environment, Settings
from promisepatch.main import create_app


def test_docs_are_open_locally(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 200


def test_docs_are_closed_in_a_deployed_environment() -> None:
    """An unauthenticated schema browser is not something a deployment should offer."""
    with TestClient(create_app(Settings(env=Environment.AWS))) as deployed:
        assert deployed.get("/docs").status_code == 404
        assert deployed.get("/openapi.json").status_code == 404
        assert deployed.get("/healthz").status_code == 200


def test_correlation_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.headers[CORRELATION_HEADER]


def test_inbound_correlation_id_is_honoured(client: TestClient) -> None:
    response = client.get("/healthz", headers={CORRELATION_HEADER: "corr-1234"})
    assert response.headers[CORRELATION_HEADER] == "corr-1234"


def test_cors_allows_the_configured_origin_with_credentials(client: TestClient) -> None:
    response = client.get("/healthz", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_rejects_an_unconfigured_origin(client: TestClient) -> None:
    response = client.get("/healthz", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers
