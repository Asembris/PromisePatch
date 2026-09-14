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


WRITEABLE_PREFIXES = ("/api/auth", "/api/conversation", "/api/integrations")
"""The only three families of route in this application that a caller may write to.

``/api/auth`` is a person signing in or out. ``/api/integrations`` is another *system* handing
us something it has already done -- authenticated with a shared secret rather than a session,
and storing the delivery rather than acting on it.

``/api/conversation`` is the third, added deliberately and not by accident: it is a person
**saying something**, which is the only way a worker has ever been able to move a case. What was
new was the transport, not the authority -- the same three application services the MCP tools
reach, over a session instead of a service token, with the actor read off the session row.

None of the three is an order editor, and the test below says so about this one specifically
rather than trusting the prefix: what a caller may state is a sentence, a case and a plan
identity the server itself handed out. There is no field naming an order, a line, a quantity or
a recipe version, so there is nothing here that could be talked into editing one. The external
order system remains the system of record, and PromisePatch still writes to an order only as a
governed recovery amendment raised by the worker process.
"""

CONVERSATION_FIELDS: dict[str, frozenset[str]] = {
    "ReportTurn": frozenset({"command_id", "text"}),
    "ClarifyTurn": frozenset({"command_id", "case_id", "text"}),
    "ConfirmTurn": frozenset({"command_id", "case_id", "plan_id"}),
    "WithdrawTurn": frozenset({"command_id", "case_id"}),
}
"""Every field a browser may put in a conversation request. Stated whole, not sampled.

Written out so that a field added to one of these models fails here rather than passing a test
that only looked for the words somebody thought to forbid.
"""


def test_no_write_route_exists_for_orders_or_promises(api: TestClient) -> None:
    """The external order system is the system of record; there is no order editor."""
    schema = api.get("/openapi.json").json()

    for path, operations in schema["paths"].items():
        if not path.startswith("/api"):
            continue
        methods = {method.upper() for method in operations}
        mutating = methods & {"POST", "PUT", "PATCH", "DELETE"}
        assert not mutating or path.startswith(WRITEABLE_PREFIXES), (path, mutating)


def test_the_conversation_routes_are_not_an_order_editor(api: TestClient) -> None:
    """The third writeable family states words, never a change to somebody's order.

    The prefix allowlist above says these routes may write. This says what they may write *about*:
    a sentence, a case, and an opaque plan identity the server handed out. There is no field for
    an order, a line, a quantity, a resource or a recipe version, so no caller -- and no model
    behind one -- has anything to fill in that could reach the order book. What actually amends an
    order is a governed recovery amendment raised by the worker process, and nothing on this
    surface can name one.
    """
    schema = api.get("/openapi.json").json()
    models = schema["components"]["schemas"]

    for model, expected in CONVERSATION_FIELDS.items():
        assert frozenset(models[model]["properties"]) == expected, model
        # `extra="forbid"`: a field a caller invented is refused rather than ignored.
        assert models[model]["additionalProperties"] is False, model


def test_no_conversation_request_carries_an_actor_or_a_clock(api: TestClient) -> None:
    """Who is speaking and when they spoke are the server's, and there is no field to say otherwise.

    Asserted over the published schema rather than over the source, because the schema is what a
    caller reads: if any of these names appeared here, somebody would reasonably try to set it.
    """
    schema = api.get("/openapi.json").json()
    models = schema["components"]["schemas"]
    forbidden = {
        "worker_id",
        "worker",
        "actor",
        "attested_by",
        "reported_by",
        "confirmed_by",
        "role",
        "observed_at",
        "recorded_at",
        "now",
        "timestamp",
    }

    for model in CONVERSATION_FIELDS:
        assert not (frozenset(models[model]["properties"]) & forbidden), model


def test_every_conversation_route_is_a_session_mutation(api: TestClient) -> None:
    """Four POSTs and nothing else: no read, no delete, no route that skipped the list."""
    schema = api.get("/openapi.json").json()

    conversation = {
        path: set(operations)
        for path, operations in schema["paths"].items()
        if path.startswith("/api/conversation")
    }

    assert conversation == {
        "/api/conversation/report": {"post"},
        "/api/conversation/clarify": {"post"},
        "/api/conversation/confirm": {"post"},
        "/api/conversation/withdraw": {"post"},
    }


def test_the_integration_ingress_is_the_only_route_an_order_can_arrive_through(
    api: TestClient,
) -> None:
    """And it is not an editor: it takes an event from the system of record, not a command.

    The distinction matters more than the count. A route that let a caller *state* what an
    order should say would be an order editor whatever it was called; this one accepts only
    what the order system has already committed, proves it with a signature over the exact
    bytes, and changes no order in the request that answers -- which is asserted directly in
    ``test_order_mirror``.
    """
    schema = api.get("/openapi.json").json()

    integrations = {path for path in schema["paths"] if path.startswith("/api/integrations")}

    assert integrations == {"/api/integrations/order-system/events"}
    assert set(schema["paths"]["/api/integrations/order-system/events"]) == {"post"}


def test_the_read_endpoints_are_get_only(api: TestClient) -> None:
    for method in ("post", "put", "patch", "delete"):
        response = getattr(api, method)("/api/promises")
        assert response.status_code == 405
