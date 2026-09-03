"""``GET /api/resources`` against the seeded Hollow Oak fixture.

The central assertion is an equality: every quantity the endpoint serves must equal what
``promise_graph.availability`` returns for the same resource, at the same horizon, from the
same loaded snapshot. That is what "composes engine output" has to mean in practice -- if the
two could differ, the screen would be showing a second, unaudited opinion about inventory.

The other assertions guard the two ways a read model quietly lies about stock: turning unknown
into zero, and clamping a shortfall to zero.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from starlette.testclient import TestClient

from promise_graph.availability import available_by
from promise_graph.model import ResourceKind
from promise_graph.snapshot import GraphSnapshot
from promisepatch.api.schemas.quantity import render_optional
from promisepatch.api.schemas.resources import ResourcesResponse
from promisepatch.api.views import resources as view
from promisepatch.config import Settings
from promisepatch.db import RuntimeDatabase
from promisepatch.graph import load_snapshot, snapshot_session

pytestmark = pytest.mark.integration


def sign_in(api: TestClient) -> None:
    settings = Settings()
    response = api.post(
        "/api/auth/login",
        json={"username": "maya", "password": settings.require_demo_worker_password()},
    )
    assert response.status_code == 200


def resources(api: TestClient, **params: str) -> ResourcesResponse:
    sign_in(api)
    response = api.get("/api/resources", params=params)
    assert response.status_code == 200, response.text
    return ResourcesResponse.model_validate(response.json())


def loaded_snapshot() -> GraphSnapshot:
    """The same snapshot the endpoint reads, loaded directly for comparison."""

    async def load() -> GraphSnapshot:
        database = RuntimeDatabase.from_settings(Settings())
        try:
            async with snapshot_session(database.engine) as session:
                return await load_snapshot(session)
        finally:
            await database.dispose()

    return asyncio.run(load())


# ------------------------------------------------------------------------------------- access


def test_an_unauthenticated_request_is_refused(api: TestClient) -> None:
    response = api.get("/api/resources")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_a_revoked_session_cannot_read_resources(api: TestClient) -> None:
    sign_in(api)
    api.post("/api/auth/logout", headers={"X-CSRF-Token": api.cookies["pp_csrf"]})

    assert api.get("/api/resources").status_code == 401


# ------------------------------------------------------------- agreement with the engine


def test_every_quantity_equals_the_engine_s_own_answer(api: TestClient) -> None:
    """The endpoint may arrange engine output. It may not compute a different number."""
    body = resources(api)
    snapshot = loaded_snapshot()
    horizon = body.at
    now = body.generated_at

    served = {ingredient.id: ingredient for ingredient in body.ingredients}
    assert served

    for resource_id, ingredient in served.items():
        expected = available_by(snapshot, resource_id, horizon, now)
        assert ingredient.on_hand == expected.on_hand, resource_id
        assert ingredient.expected == expected.expected, resource_id
        assert ingredient.reserved == expected.reserved, resource_id
        assert ingredient.available_by == expected.available_by, resource_id
        assert ingredient.unknown == expected.unknown, resource_id
        assert ingredient.overdue_commitment_line_ids == tuple(expected.overdue_line_ids)


def test_every_ingredient_in_the_snapshot_is_served(api: TestClient) -> None:
    body = resources(api)
    snapshot = loaded_snapshot()

    in_snapshot = {
        resource.id
        for resource in snapshot.resources.values()
        if resource.kind is ResourceKind.INGREDIENT
    }
    assert {ingredient.id for ingredient in body.ingredients} == in_snapshot


def test_every_piece_of_equipment_in_the_snapshot_is_served(api: TestClient) -> None:
    body = resources(api)
    snapshot = loaded_snapshot()

    in_snapshot = {
        resource.id
        for resource in snapshot.resources.values()
        if resource.kind is ResourceKind.EQUIPMENT
    }
    assert {item.id for item in body.equipment} == in_snapshot


def test_ingredients_and_equipment_are_not_mixed(api: TestClient) -> None:
    body = resources(api)

    assert {ingredient.id for ingredient in body.ingredients}.isdisjoint(
        {item.id for item in body.equipment}
    )


# ----------------------------------------------------------------------------- honest numbers


def test_unknown_stays_unknown(api: TestClient) -> None:
    """Asserted as a property of the serializer, since the fixture is fully known.

    The dangerous coercion is ``None`` to ``0``: it would turn a promise the engine fails
    closed on into one it believes is satisfiable.
    """
    assert render_optional(None) is None
    assert render_optional(Decimal("0.000")) == "0"

    body = resources(api)
    for ingredient in body.ingredients:
        if ingredient.unknown:
            assert ingredient.available_by is None


def test_an_unknown_quantity_serialises_as_null_and_not_as_zero(api: TestClient) -> None:
    sign_in(api)
    raw = api.get("/api/resources").json()

    for ingredient in raw["ingredients"]:
        for field in ("on_hand", "expected", "reserved", "available_by"):
            value = ingredient[field]
            assert value is None or isinstance(value, str)
            if ingredient["unknown"] and field == "available_by":
                assert value is None


def test_a_shortfall_is_not_clamped_to_zero(api: TestClient) -> None:
    """A negative availability is the condition that makes a promise BLOCKED.

    Asked at a horizon far enough out that every reservation is counted while no further
    delivery is: if any resource is oversubscribed there, the negative number must survive to
    the response exactly as the engine computed it.
    """
    snapshot = loaded_snapshot()
    now = datetime.now(UTC)
    horizon = now + timedelta(days=365)

    engine_values = {
        resource_id: available_by(snapshot, resource_id, horizon, now).available_by
        for resource_id, resource in snapshot.resources.items()
        if resource.kind is ResourceKind.INGREDIENT
    }
    body = resources(api, at=horizon.isoformat())

    for ingredient in body.ingredients:
        assert ingredient.available_by == engine_values[ingredient.id], ingredient.id
        if engine_values[ingredient.id] is not None:
            expected = engine_values[ingredient.id]
            assert expected is not None
            if expected < 0:
                assert ingredient.available_by is not None
                assert ingredient.available_by < 0


def test_negative_values_survive_serialisation() -> None:
    """The rendering itself must not lose a sign or a decimal place."""
    assert render_optional(Decimal("-4.500")) == "-4.5"
    assert render_optional(Decimal("-0.001")) == "-0.001"


# --------------------------------------------------------------------------------- provenance


def test_ledger_provenance_accompanies_every_stock_reading(api: TestClient) -> None:
    """On-hand is a ledger sum, so it comes with the position that sum was taken at."""
    body = resources(api)
    snapshot = loaded_snapshot()

    for ingredient in body.ingredients:
        entries = snapshot.ledger_by_resource.get(ingredient.id, ())
        assert ingredient.ledger.entries == len(entries)
        if entries:
            last = max(entries, key=lambda entry: entry.seq)
            assert ingredient.ledger.last_seq == last.seq
            assert ingredient.ledger.last_recorded_at == last.recorded_at
            assert ingredient.ledger.last_source_kind == str(last.source_kind)
            assert ingredient.ledger.last_source_id == last.source_id
        else:
            assert ingredient.ledger.last_seq is None


def test_aliases_are_served_for_resources_that_have_them(api: TestClient) -> None:
    """Aliases are how a spoken phrase binds to a resource, so a screen has to show them."""
    body = resources(api)
    snapshot = loaded_snapshot()

    for ingredient in body.ingredients:
        assert ingredient.aliases == tuple(snapshot.resources[ingredient.id].aliases)
    assert any(ingredient.aliases for ingredient in body.ingredients)


def test_the_response_states_the_horizon_and_how_current_it_is(api: TestClient) -> None:
    body = resources(api)

    assert body.at.tzinfo is not None
    assert body.generated_at.tzinfo is not None
    assert body.as_of >= 1


def test_the_default_horizon_is_the_end_of_the_order_book(api: TestClient) -> None:
    body = resources(api)
    snapshot = loaded_snapshot()

    latest = max(promise.due_at for promise in snapshot.promises.values())
    assert body.at == max(latest, body.generated_at)


def test_a_caller_may_name_its_own_horizon(api: TestClient) -> None:
    moment = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)

    body = resources(api, at=moment.isoformat())

    assert body.at == moment


def test_a_horizon_without_a_timezone_is_refused(api: TestClient) -> None:
    """A naive instant cannot be compared with a stored timestamp at all."""
    sign_in(api)

    response = api.get("/api/resources", params={"at": "2026-03-04T12:00:00"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


# ---------------------------------------------------------------------------------- equipment


def test_equipment_reports_its_recorded_outages(api: TestClient) -> None:
    body = resources(api)
    snapshot = loaded_snapshot()

    for item in body.equipment:
        outages = snapshot.outages_by_equipment.get(item.id, ())
        assert len(item.outages) == len(outages)
        assert {outage.id for outage in item.outages} == {outage.id for outage in outages}


def test_equipment_status_reads_the_outage_rows(api: TestClient) -> None:
    """A fact about the rows, not the engine's verdict on whether a task can run."""
    body = resources(api)

    for item in body.equipment:
        assert item.status in {"IN_SERVICE", "OUT_OF_SERVICE"}
        if item.status == "OUT_OF_SERVICE":
            assert item.outages


def test_the_outage_interval_is_half_open() -> None:
    """Pinned explicitly, because it is the one interval rule this module restates."""
    snapshot = loaded_snapshot()
    equipment = next(
        resource
        for resource in snapshot.resources.values()
        if resource.kind is ResourceKind.EQUIPMENT
    )
    start = datetime(2026, 3, 4, 8, 0, tzinfo=UTC)
    end = start + timedelta(hours=2)
    with_outage = snapshot.replace(
        outages=(
            *snapshot.outages,
            _outage(equipment.id, start, end),
        )
    )

    assert view._status(with_outage, equipment.id, start) == "OUT_OF_SERVICE"
    assert view._status(with_outage, equipment.id, end - timedelta(seconds=1)) == "OUT_OF_SERVICE"
    assert view._status(with_outage, equipment.id, end) == "IN_SERVICE"
    assert view._status(with_outage, equipment.id, start - timedelta(seconds=1)) == "IN_SERVICE"


def test_an_open_ended_outage_never_ends() -> None:
    snapshot = loaded_snapshot()
    equipment = next(
        resource
        for resource in snapshot.resources.values()
        if resource.kind is ResourceKind.EQUIPMENT
    )
    start = datetime(2026, 3, 4, 8, 0, tzinfo=UTC)
    with_outage = snapshot.replace(outages=(*snapshot.outages, _outage(equipment.id, start, None)))

    assert view._status(with_outage, equipment.id, start + timedelta(days=400)) == "OUT_OF_SERVICE"


def test_equipment_shows_what_is_booked_on_it(api: TestClient) -> None:
    body = resources(api)
    snapshot = loaded_snapshot()

    for item in body.equipment:
        booked = snapshot.tasks_by_equipment.get(item.id, ())
        assert {task.id for task in item.scheduled_tasks} == set(booked)
    assert any(item.scheduled_tasks for item in body.equipment)


# ------------------------------------------------------------------------------------ hygiene


def test_the_typed_response_model_validates_the_served_body(api: TestClient) -> None:
    sign_in(api)

    validated = ResourcesResponse.model_validate(api.get("/api/resources").json())

    assert validated.ingredients
    assert validated.equipment


def test_the_read_endpoint_is_get_only(api: TestClient) -> None:
    for method in ("post", "put", "patch", "delete"):
        assert getattr(api, method)("/api/resources").status_code == 405


def _outage(equipment_id: str, starts_at: datetime, ends_at: datetime | None) -> object:
    from promise_graph.model import EquipmentOutage

    return EquipmentOutage(
        id=f"outage-test-{equipment_id}",
        equipment_id=equipment_id,
        starts_at=starts_at,
        ends_at=ends_at,
    )
