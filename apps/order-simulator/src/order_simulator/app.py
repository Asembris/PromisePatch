"""The External Order System simulator: a separate process with its own database and UI.

It answers three audiences and keeps them apart.

* **An operator**, through the HTML screen. This is where the Proof A mutation is made on
  camera, in a window that is visibly not PromisePatch.
* **PromisePatch**, through the typed API: read an order's authoritative state, and push one
  governed recovery amendment with an idempotency key and the version it was planned against.
* **A container runtime**, through liveness and readiness.

**Nothing here mutates in the request that answers.** A mutation is committed by the store in
one transaction that also records the event and its delivery row; the HTTP handler's job ends
at translating an error into a status code. The webhook that tells PromisePatch about it leaves
through the delivery loop, afterwards, from durable state.

**There is no fault-injection endpoint.** The awkward orderings a test needs -- a lost response,
a delayed webhook -- are produced by the test's own transport, not by a control this application
exposes. An operator screen with a "lose the next response" button would be a way to make the
demo lie.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import FastAPI, Form, Header, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from order_contract.amendments import (
    AmendmentRequest,
    AmendmentResult,
    ContractError,
    ErrorResponse,
)
from order_contract.events import SCHEMA_VERSION, OrderSnapshot
from order_simulator import capabilities, ui
from order_simulator.config import Settings, get_settings
from order_simulator.observability import configure_logging, get_logger
from order_simulator.store import EVENT_PAGE, OrderStore, SimulatorError
from order_simulator.webhooks import WebhookDispatcher

logger = get_logger(__name__)


def _error(error: SimulatorError) -> JSONResponse:
    """One shape for every refusal, with the code the contract names."""
    body = ErrorResponse(
        error=ContractError(
            code=error.code, message=error.message, current_version=error.current_version
        )
    )
    return JSONResponse(status_code=error.status, content=body.model_dump(mode="json"))


def create_app(settings: Settings | None = None, *, deliver: bool = True) -> FastAPI:
    """Build the simulator. ``deliver=False`` leaves the delivery loop unstarted for tests."""
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)
    store = OrderStore(resolved.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store.initialize()
        stop = asyncio.Event()
        task: asyncio.Task[None] | None = None
        if deliver:
            task = asyncio.create_task(WebhookDispatcher(store, resolved).run_forever(stop))
        logger.info(
            "simulator.start",
            database=str(resolved.database_path),
            webhook_configured=bool(resolved.webhook_url and resolved.webhook_secret),
            undelivered=store.undelivered_count(),
        )
        try:
            yield
        finally:
            stop.set()
            if task is not None:
                await task
            logger.info("simulator.stop")

    app = FastAPI(
        title=ui.SYSTEM_NAME,
        version="0.1.0",
        summary=ui.STANDING_NOTICE,
        lifespan=lifespan,
    )
    app.state.store = store
    app.state.settings = resolved

    # ------------------------------------------------------------------------- operator UI

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def operator_screen() -> HTMLResponse:
        return HTMLResponse(
            ui.render(
                orders=store.list_orders(),
                catalogue=store.catalogue(),
                deliveries=store.latest_deliveries(),
            )
        )

    @app.post("/ui/orders/{external_id}/lines/{line_id}", include_in_schema=False)
    async def operator_change(
        external_id: str,
        line_id: str,
        to_item_id: Annotated[str, Form()],
        quantity: Annotated[int | None, Form(gt=0)] = None,
    ) -> Response:
        """One operator edit. The change is this system's own; nobody asked its permission."""
        try:
            mutation = store.operator_change(
                external_order_id=external_id,
                external_line_id=line_id,
                to_item_id=to_item_id,
                quantity=quantity,
            )
        except SimulatorError as error:
            return _error(error)
        logger.info(
            "simulator.order.changed",
            external_order_id=external_id,
            external_version=mutation.result.external_version,
            event_id=str(mutation.event.event_id),
            operation="operator_change",
        )
        return RedirectResponse("/", status_code=303)

    @app.post("/ui/reset", include_in_schema=False)
    async def operator_reset() -> Response:
        store.reset()
        return RedirectResponse("/", status_code=303)

    # -------------------------------------------------------------------------- the API

    @app.get("/orders", summary="Every order this system holds, at its current version")
    async def list_orders() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "orders": [order.model_dump(mode="json") for order in store.list_orders()],
        }

    @app.get("/orders/{external_id}", summary="One order's authoritative current state")
    async def read_order(external_id: str) -> Response:
        """The authoritative snapshot, for repairing a mirror that has fallen behind."""
        try:
            order: OrderSnapshot = store.read_order(external_id)
        except SimulatorError as error:
            return _error(error)
        return JSONResponse(content=order.model_dump(mode="json"))

    @app.post("/orders/{external_id}/amendments", summary="Apply one governed amendment")
    async def amend(
        external_id: str,
        request: AmendmentRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> Response:
        if idempotency_key is None or not idempotency_key.strip():
            return _error(
                SimulatorError(
                    "IDEMPOTENCY_KEY_REQUIRED",
                    "an Idempotency-Key header is required for an amendment",
                    status=400,
                )
            )
        if request.external_order_id != external_id:
            return _error(
                SimulatorError(
                    "ORDER_MISMATCH",
                    "the amendment names a different order from the path",
                    status=400,
                )
            )
        try:
            mutation = store.amend(request, idempotency_key=idempotency_key)
        except SimulatorError as error:
            return _error(error)

        result: AmendmentResult = mutation.result
        logger.info(
            "simulator.order.amended",
            external_order_id=external_id,
            external_version=result.external_version,
            event_id=str(mutation.event.event_id),
            idempotency_key=idempotency_key,
            operation="amendment",
            replayed=result.replayed,
        )
        return JSONResponse(content=result.model_dump(mode="json"))

    @app.get("/admin/events", summary="The committed event log and each event's delivery state")
    async def recent_events(since: str | None = None, limit: int = EVENT_PAGE) -> Response:
        """Every committed event, oldest first, each carrying the message that left this system.

        ``event`` is the published :class:`~order_contract.events.OrderEvent` itself, read out
        of the row it was committed on. It is the same document a webhook subscriber is handed,
        so an auditor reading this system's own log sees what its subscribers saw -- including
        the command that caused a change, which is the only thing that says whose amendment it
        was rather than merely that the order moved.

        ``since`` is an ISO-8601 instant and ``limit`` a window; ``truncated`` says whether more
        events matched than were returned, because a log that stopped early and looked complete
        would let a reader conclude something never happened.
        """
        moment: datetime | None = None
        if since is not None:
            try:
                moment = datetime.fromisoformat(since.replace("Z", "+00:00"))
            except ValueError:
                return _error(
                    SimulatorError(
                        "SINCE_NOT_AN_INSTANT",
                        "since must be an ISO-8601 instant",
                        status=400,
                    )
                )
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
        events, truncated = store.events(since=moment, limit=limit)
        return JSONResponse(
            content={
                "schema_version": SCHEMA_VERSION,
                "since": None if moment is None else moment.isoformat(),
                "truncated": truncated,
                "events": [
                    capabilities.event_entry(event, body=json.loads(event.body)) for event in events
                ],
            }
        )

    @app.get("/admin/capabilities", summary="What this build of the order system publishes")
    async def admin_capabilities() -> dict[str, Any]:
        """The shape of the admin projection, so a reader can ask instead of assuming.

        A build that predates this route answers ``404``, which is a usable answer: it says the
        process is older than the projection the caller is about to depend on. See
        :mod:`order_simulator.capabilities`.
        """
        return capabilities.declaration()

    @app.post("/admin/reset", summary="Put the demo order book back to its seeded state")
    async def reset() -> dict[str, Any]:
        store.reset()
        return {"reset": True, "orders": len(store.list_orders())}

    # ------------------------------------------------------------------------- probes

    @app.get("/healthz", summary="Liveness")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "order-simulator"}

    @app.get("/readyz", summary="Readiness: the store is open and seeded")
    async def readyz(response: Response) -> dict[str, Any]:
        ready = store.is_ready()
        response.status_code = 200 if ready else 503
        return {
            "status": "ok" if ready else "not-ready",
            "service": "order-simulator",
            "database": str(resolved.database_path),
            "seeded": ready,
        }

    return app
