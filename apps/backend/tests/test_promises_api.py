"""``GET /api/promises`` against the seeded Hollow Oak fixture.

The fixture's six promises are the demo's opening shot, so this suite checks the things a
viewer would notice and a client would depend on: that all six are there, in due order, with
the versions they are actually pinned to, with the one task that is already underway shown as
underway, and with nothing on the wire that should not be.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from promise_graph.fingerprint import canonical_json
from promisepatch.api.schemas.promises import PromisesResponse
from promisepatch.api.schemas.quantity import render
from promisepatch.config import Settings
from promisepatch.db import RuntimeDatabase
from promisepatch.graph import load_snapshot, snapshot_session

pytestmark = pytest.mark.integration

EXPECTED_EXTERNAL_IDS = ("EXT-A", "EXT-B", "EXT-C", "EXT-D", "EXT-E", "EXT-F")
"""The fixture's six orders. Named here so a change to the dataset fails loudly."""


def sign_in(api: TestClient) -> None:
    settings = Settings()
    response = api.post(
        "/api/auth/login",
        json={"username": "maya", "password": settings.require_demo_worker_password()},
    )
    assert response.status_code == 200


def promises(api: TestClient) -> PromisesResponse:
    sign_in(api)
    response = api.get("/api/promises")
    assert response.status_code == 200
    return PromisesResponse.model_validate(response.json())


# ------------------------------------------------------------------------------------- access


def test_an_unauthenticated_request_is_refused(api: TestClient) -> None:
    response = api.get("/api/promises")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_a_revoked_session_cannot_read_the_order_book(api: TestClient) -> None:
    sign_in(api)
    api.post("/api/auth/logout", headers={"X-CSRF-Token": api.cookies["pp_csrf"]})

    assert api.get("/api/promises").status_code == 401


def test_the_owner_may_read_the_order_book_too(api: TestClient) -> None:
    """Evidence reads are for both roles; only owner *actions* are role-gated."""
    settings = Settings()
    api.post(
        "/api/auth/login",
        json={"username": "jo", "password": settings.require_demo_owner_password()},
    )

    assert api.get("/api/promises").status_code == 200


# ------------------------------------------------------------------------------------ content


def test_the_fixture_yields_exactly_the_six_promises(api: TestClient) -> None:
    body = promises(api)

    assert len(body.promises) == 6
    assert {promise.external_id for promise in body.promises} == set(EXPECTED_EXTERNAL_IDS)


def test_promises_are_ordered_by_due_time_then_external_id(api: TestClient) -> None:
    """Deterministic order, so a screenshot, a test and a demo all agree."""
    body = promises(api)

    keys = [(promise.due_at, promise.external_id) for promise in body.promises]
    assert keys == sorted(keys)


def test_the_order_is_stable_across_identical_requests(api: TestClient) -> None:
    first = [promise.id for promise in promises(api).promises]
    second = [promise.id for promise in promises(api).promises]

    assert first == second


def test_every_promise_carries_its_order_identity(api: TestClient) -> None:
    for promise in promises(api).promises:
        assert promise.order_id
        assert promise.external_id
        assert promise.external_version >= 1
        assert promise.order_state


def test_every_line_is_pinned_to_an_authored_recipe_version(api: TestClient) -> None:
    """A recovery re-points a line at a version a human authored; nothing derives one."""
    for promise in promises(api).promises:
        assert promise.lines
        for line in promise.lines:
            version = line.recipe_version
            assert version.id
            assert version.recipe_id
            assert version.recipe_name
            assert version.version_no >= 1
            assert version.authored_by
            assert version.authored_at


def test_the_pinned_versions_match_the_loaded_snapshot(api: TestClient) -> None:
    """The API's pinning is the database's pinning, compared against a direct snapshot read."""
    body = promises(api)
    served = {
        line.id: line.recipe_version.id for promise in body.promises for line in promise.lines
    }

    async def from_snapshot() -> dict[str, str]:
        database = RuntimeDatabase.from_settings(Settings())
        try:
            async with snapshot_session(database.engine) as session:
                snapshot = await load_snapshot(session)
        finally:
            await database.dispose()
        return {line_id: line.recipe_version_id for line_id, line in snapshot.order_lines.items()}

    assert served == asyncio.run(from_snapshot())


def test_the_started_task_is_reported_as_started(api: TestClient) -> None:
    """E is already in the oven in the fixture, and the screen has to show that."""
    body = promises(api)
    e = next(promise for promise in body.promises if promise.external_id == "EXT-E")

    states = {line.task.state for line in e.lines if line.task is not None}
    assert "STARTED" in states


def test_task_scheduling_and_equipment_are_present_where_the_fixture_has_them(
    api: TestClient,
) -> None:
    body = promises(api)
    tasks = [line.task for promise in body.promises for line in promise.lines if line.task]

    assert tasks
    assert any(task.scheduled_start is not None for task in tasks)
    assert any(task.equipment_id is not None for task in tasks)
    for task in tasks:
        if task.equipment_id is not None:
            assert task.equipment_name


def test_reservations_are_reported_with_their_source_version(api: TestClient) -> None:
    body = promises(api)
    reservations = [
        reservation
        for promise in body.promises
        for line in promise.lines
        for reservation in line.reservations
    ]

    assert reservations
    for reservation in reservations:
        assert reservation.resource_id
        assert reservation.resource_name
        assert reservation.source_recipe_version_id


def test_constraint_provenance_is_served_with_the_constraint(api: TestClient) -> None:
    """A rule nobody can attribute cannot justify a substitution to a customer."""
    body = promises(api)
    constraints = [constraint for promise in body.promises for constraint in promise.constraints]

    assert constraints
    for constraint in constraints:
        assert constraint.kind
        assert constraint.recorded_by
        assert constraint.recorded_at


def test_a_promise_with_no_open_case_has_no_classification(api: TestClient) -> None:
    """``None`` rather than UNAFFECTED: the engine's verdict is about a specific exception."""
    body = promises(api)

    for promise in body.promises:
        assert promise.classification is None
        assert promise.track_state is None
        assert promise.case_id is None
        assert promise.track_id is None


def test_the_response_is_stamped_with_how_current_it_is(api: TestClient) -> None:
    body = promises(api)

    assert body.as_of >= 1
    assert body.generated_at.tzinfo is not None


# ------------------------------------------------------------------------------------- hygiene


def test_the_typed_response_model_validates_the_served_body(api: TestClient) -> None:
    """``extra="forbid"`` throughout, so an unexpected field is a failure and not a leak."""
    sign_in(api)
    body = api.get("/api/promises").json()

    validated = PromisesResponse.model_validate(body)
    assert len(validated.promises) == 6


def test_the_customer_approval_channel_is_never_served(api: TestClient) -> None:
    """It is a real person's chat id and the thing consent is authenticated against."""
    sign_in(api)
    raw = api.get("/api/promises").text

    assert "approval_channel" not in raw
    assert "telegram" not in raw.lower()
    for promise in promises(api).promises:
        assert set(promise.customer.model_dump()) == {"id", "name"}


def test_decimal_quantities_are_strings_matching_the_engine_convention(api: TestClient) -> None:
    """A JSON number would reintroduce binary float at the last possible moment."""
    sign_in(api)
    raw = api.get("/api/promises").json()

    quantities = [
        reservation["quantity"]
        for promise in raw["promises"]
        for line in promise["lines"]
        for reservation in line["reservations"]
    ]
    assert quantities
    for quantity in quantities:
        assert quantity is None or isinstance(quantity, str)

    # The rendering is the engine's own canonical form, not merely "a string".
    assert render(Decimal("2.000")) == canonical_json(Decimal("2.000")).strip('"')
    assert render(Decimal("0.500")) == canonical_json(Decimal("0.500")).strip('"')
    assert render(Decimal("12.345")) == canonical_json(Decimal("12.345")).strip('"')


def test_line_quantities_are_whole_units(api: TestClient) -> None:
    """An order line is a count of items, stored as an integer, and served as one."""
    for promise in promises(api).promises:
        for line in promise.lines:
            assert isinstance(line.quantity, int)
            assert line.quantity > 0


def test_no_write_route_exists_for_orders_or_promises(api: TestClient) -> None:
    """The external order system is the system of record; there is no order editor."""
    schema = api.get("/openapi.json").json()

    for path, operations in schema["paths"].items():
        if not path.startswith("/api"):
            continue
        methods = {method.upper() for method in operations}
        mutating = methods & {"POST", "PUT", "PATCH", "DELETE"}
        assert not mutating or path.startswith("/api/auth"), (path, mutating)


def test_the_read_endpoints_are_get_only(api: TestClient) -> None:
    for method in ("post", "put", "patch", "delete"):
        response = getattr(api, method)("/api/promises")
        assert response.status_code == 405
