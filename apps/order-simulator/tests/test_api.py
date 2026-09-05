"""The surface PromisePatch and an operator actually talk to."""

from __future__ import annotations

from uuid import uuid4

from starlette.testclient import TestClient

from order_contract import amendments
from order_contract.amendments import AmendmentRequest, AmendmentResult
from order_contract.events import SCHEMA_VERSION, OrderSnapshot
from order_simulator import ui

LENA_ORDER = "EXT-D"
LENA_LINE = "ol-d"
RASPBERRY_LEMON = "rv-raspberry-lemon-2"
LEMON_CURD = "rv-lemon-curd-1"


def an_amendment(**overrides: object) -> AmendmentRequest:
    fields: dict[str, object] = {
        "external_order_id": LENA_ORDER,
        "expected_version": 1,
        "external_line_id": LENA_LINE,
        "from_item_id": RASPBERRY_LEMON,
        "to_item_id": LEMON_CURD,
        "correlation": amendments.AmendmentCorrelation(
            case_id=uuid4(), track_id=uuid4(), option_id=uuid4()
        ),
    }
    fields.update(overrides)
    return AmendmentRequest(**fields)


def post_amendment(
    client: TestClient, request: AmendmentRequest, *, key: str
) -> tuple[int, dict[str, object]]:
    response = client.post(
        f"/orders/{request.external_order_id}/amendments",
        content=request.model_dump_json(),
        headers={"Content-Type": "application/json", amendments.IDEMPOTENCY_HEADER: key},
    )
    return response.status_code, response.json()


# ----------------------------------------------------------------------------------- probes


def test_liveness_answers_without_touching_the_store(client: TestClient) -> None:
    assert client.get("/healthz").json()["service"] == "order-simulator"


def test_readiness_says_the_store_is_open_and_seeded(client: TestClient) -> None:
    body = client.get("/readyz").json()

    assert body["status"] == "ok"
    assert body["seeded"] is True


# --------------------------------------------------------------------------------- reading


def test_the_order_book_is_readable_at_its_current_version(client: TestClient) -> None:
    body = client.get("/orders").json()

    assert body["schema_version"] == SCHEMA_VERSION
    assert [order["external_id"] for order in body["orders"]] == [
        "EXT-A",
        "EXT-B",
        "EXT-C",
        "EXT-D",
        "EXT-E",
        "EXT-F",
    ]


def test_one_order_is_readable_as_the_typed_contract(client: TestClient) -> None:
    """The authoritative fetch a mirror uses to repair itself. Typed, not a database dump."""
    order = OrderSnapshot.model_validate(client.get(f"/orders/{LENA_ORDER}").json())

    assert order.version == 1
    assert order.lines[0].external_item_id == RASPBERRY_LEMON
    assert order.customer.approval_channel.kind == "telegram"


def test_an_unknown_order_is_a_typed_refusal(client: TestClient) -> None:
    response = client.get("/orders/EXT-NOWHERE")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == amendments.ERROR_ORDER_NOT_FOUND


# ---------------------------------------------------------------------------- operator UI


def test_the_screen_says_which_system_it_is(client: TestClient) -> None:
    """A judge must be able to see at a glance that this is not PromisePatch."""
    html = client.get("/").text

    assert ui.SYSTEM_NAME in html
    assert ui.STANDING_NOTICE in html
    assert "not Square" in html
    assert "PromisePatch" in html  # only ever as the thing it is *not*


def test_the_screen_shows_every_order_with_its_version_and_item(client: TestClient) -> None:
    html = client.get("/").text

    assert "Lena Fischer" in html
    assert RASPBERRY_LEMON in html
    assert "Raspberry Lemon Layer v2" in html


def test_one_operator_action_moves_lena_to_the_lemon_curd_variant(client: TestClient) -> None:
    """The Proof A mutation, made here, in this system's own screen."""
    response = client.post(
        f"/ui/orders/{LENA_ORDER}/lines/{LENA_LINE}",
        data={"to_item_id": LEMON_CURD},
        follow_redirects=False,
    )

    assert response.status_code == 303
    order = OrderSnapshot.model_validate(client.get(f"/orders/{LENA_ORDER}").json())
    assert order.version == 2
    assert order.state == "AMENDED"
    assert order.lines[0].external_item_id == LEMON_CURD


def test_the_screen_shows_the_event_the_change_raised(client: TestClient) -> None:
    client.post(
        f"/ui/orders/{LENA_ORDER}/lines/{LENA_LINE}",
        data={"to_item_id": LEMON_CURD},
        follow_redirects=False,
    )

    html = client.get("/").text
    assert "order.updated" in html
    assert "operator" in html
    assert "data-delivery-state" in html


def test_the_reset_button_puts_the_order_book_back(client: TestClient) -> None:
    client.post(
        f"/ui/orders/{LENA_ORDER}/lines/{LENA_LINE}",
        data={"to_item_id": LEMON_CURD},
        follow_redirects=False,
    )
    client.post("/ui/reset", follow_redirects=False)

    order = OrderSnapshot.model_validate(client.get(f"/orders/{LENA_ORDER}").json())
    assert order.version == 1
    assert order.lines[0].external_item_id == RASPBERRY_LEMON


# -------------------------------------------------------------------------- the amendment


def test_an_amendment_is_applied_and_answered_with_its_resulting_version(
    client: TestClient,
) -> None:
    status, body = post_amendment(client, an_amendment(), key="pp:amend:one")

    result = AmendmentResult.model_validate(body)
    assert status == 200
    assert result.previous_version == 1
    assert result.external_version == 2
    assert result.item_id == LEMON_CURD
    assert result.provider_ref


def test_a_repeated_key_answers_the_same_thing_without_a_second_mutation(
    client: TestClient,
) -> None:
    """The crash-after-provider-success window, answered honestly by the provider."""
    request = an_amendment()
    _, first = post_amendment(client, request, key="pp:amend:one")
    status, second = post_amendment(client, request, key="pp:amend:one")

    assert status == 200
    assert second["provider_ref"] == first["provider_ref"]
    assert second["external_version"] == first["external_version"]
    assert second["replayed"] is True
    assert OrderSnapshot.model_validate(client.get(f"/orders/{LENA_ORDER}").json()).version == 2
    assert len(client.get("/admin/events").json()["events"]) == 1


def test_an_amendment_without_an_idempotency_key_is_refused(client: TestClient) -> None:
    response = client.post(
        f"/orders/{LENA_ORDER}/amendments",
        content=an_amendment().model_dump_json(),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_an_amendment_for_another_order_than_the_path_is_refused(client: TestClient) -> None:
    response = client.post(
        "/orders/EXT-A/amendments",
        content=an_amendment().model_dump_json(),
        headers={"Content-Type": "application/json", amendments.IDEMPOTENCY_HEADER: "k"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ORDER_MISMATCH"


def test_a_stale_expected_version_is_refused_with_the_current_one(client: TestClient) -> None:
    client.post(
        f"/ui/orders/{LENA_ORDER}/lines/{LENA_LINE}",
        data={"to_item_id": LEMON_CURD},
        follow_redirects=False,
    )

    status, body = post_amendment(client, an_amendment(expected_version=1), key="pp:amend:stale")

    assert status == 409
    assert body["error"]["code"] == amendments.ERROR_VERSION_CONFLICT  # type: ignore[index]
    assert body["error"]["current_version"] == 2  # type: ignore[index]


def test_a_key_reused_for_a_different_amendment_is_refused(client: TestClient) -> None:
    post_amendment(client, an_amendment(), key="pp:amend:one")

    status, body = post_amendment(
        client,
        an_amendment(expected_version=2, from_item_id=LEMON_CURD, to_item_id=RASPBERRY_LEMON),
        key="pp:amend:one",
    )

    assert status == 409
    assert body["error"]["code"] == amendments.ERROR_IDEMPOTENCY_CONFLICT  # type: ignore[index]


def test_recent_events_report_what_left_and_where_it_got_to(client: TestClient) -> None:
    post_amendment(client, an_amendment(), key="pp:amend:one")

    events = client.get("/admin/events").json()["events"]

    assert len(events) == 1
    assert events[0]["external_order_id"] == LENA_ORDER
    assert events[0]["version"] == 2
    assert events[0]["source"] == "amendment"
    assert events[0]["delivery_state"] == "PENDING"


def test_the_admin_reset_restores_the_seeded_book(client: TestClient) -> None:
    post_amendment(client, an_amendment(), key="pp:amend:one")

    assert client.post("/admin/reset").json() == {"reset": True, "orders": 6}
    assert client.get("/admin/events").json()["events"] == []
