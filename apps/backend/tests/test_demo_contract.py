"""``scripts/demo_contract.py``: the storyboard runner, held to the sentence G8 wrote for it.

*"Demo-contract runner uses the new transport boundaries; no direct DB consent inserts. Fixture
setup and fault injection are explicit operator actions."* (``new_roadmap.md`` §11 G8.)

Each half of that sentence is asserted here against the real thing rather than a stand-in:

- the world is the one ``pp restore-demo-world`` builds, reached through
  :func:`promisepatch.demo_restore.restore_demo_world` -- the operator's fixture action;
- the order system is the real simulator, its own ASGI application over its own SQLite file,
  and PromisePatch's amendments reach it over HTTP;
- the API the runner talks to is the real application, and the worker is the product's own
  :class:`~promisepatch.worker.Worker` running its own loop beside the test;
- the operator is a test double with exactly two powers, the two the runner asks for: approve a
  plan on a surface where a person authenticates, and restart the worker. The runner is given no
  handle on either, which is what makes a runner that "did it itself" impossible rather than
  merely absent.

The runner's own proofs -- a read-only evidence connection, a customer answer that arrives through
the link transport, a restart visible only as a new worker identity -- are asserted from outside
as well, so a runner that printed PASS without them would still fail here.
"""

from __future__ import annotations

import ast
import asyncio
import io
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from _intake_support import Intake
from _intake_support import physical as physical
from _order_system_support import (
    PROMISEPATCH_ORIGIN,
    SIMULATOR_ORIGIN,
    WEBHOOK_PATH,
    WEBHOOK_SECRET,
)
from pydantic import SecretStr
from scripts import demo_contract
from scripts.demo_contract import (
    EXIT_FAIL,
    EXIT_PASS,
    EXIT_REFUSED,
    ConsoleOperator,
    OperatorAction,
    Runner,
    Surfaces,
)
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from test_demo_restore_command import restoring as restoring
from test_demo_restore_command import serving as serving

from order_simulator.app import create_app as create_simulator
from order_simulator.config import Settings as SimulatorSettings
from order_simulator.store import OrderStore
from order_simulator.webhooks import WebhookDispatcher
from promise_graph.examples import hollow_oak as ho
from promisepatch import cli as cli_module
from promisepatch import demo_restore
from promisepatch.api.auth import cookies
from promisepatch.api.routers import auth as login_router
from promisepatch.config import Settings, get_settings
from promisepatch.db.models import Case, OutboxMessage, PlanApproval
from promisepatch.db.runtime import RuntimeDatabase
from promisepatch.domain.adapters import FakeEffectAdapter, RoutedEffectAdapter
from promisepatch.domain.model import EFFECT_ORDER_AMEND
from promisepatch.fixtures import demo
from promisepatch.integrations.order_system import OrderSystemAdapter, OrderSystemClient
from promisepatch.main import create_app as create_promisepatch
from promisepatch.worker import Worker

pytestmark = pytest.mark.integration

LINK_SECRET = "a-local-demo-contract-link-secret"
LINK_BASE_URL = "https://bakery.test/answer"
SERVICE_TOKEN = "a-local-demo-contract-service-token"
RUNNER_SOURCE = Path(demo_contract.__file__)


@pytest.fixture(autouse=True)
def configured_links(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Links are signed by the worker, from the process's own settings, as a deployment does."""
    monkeypatch.setenv("PP_CUSTOMER_LINK_SECRET", LINK_SECRET)
    monkeypatch.setenv("PP_CUSTOMER_LINK_BASE_URL", LINK_BASE_URL)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def deployed(restoring: Settings) -> Settings:
    """The API's configuration: an intent surface, signed customer links, the order system."""
    return restoring.model_copy(
        update={
            "internal_service_token": SecretStr(SERVICE_TOKEN),
            "surface_worker_id": ho.BAKER,
            "customer_link_secret": SecretStr(LINK_SECRET),
            "customer_link_base_url": LINK_BASE_URL,
            "order_system_webhook_secret": SecretStr(WEBHOOK_SECRET),
        }
    )


# ------------------------------------------------------------------------------ the stack


@dataclass
class Recorded(httpx2.AsyncBaseTransport):
    """An ASGI transport that remembers every request the runner made, by method and path."""

    inner: httpx2.AsyncBaseTransport
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append((request.method, request.url.path))
        return await self.inner.handle_async_request(request)

    def to(self, prefix: str) -> list[tuple[str, str]]:
        return [call for call in self.calls if call[1].startswith(prefix)]


class HostedWorker:
    """The product's worker loop, run beside the test. Only the operator double restarts it."""

    def __init__(self, database: RuntimeDatabase, adapter: Any, fetch: Any) -> None:
        self.database, self.adapter, self.fetch = database, adapter, fetch
        self.identities: list[str] = []
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        worker = Worker(
            database=self.database, adapter=self.adapter, fetch_order=self.fetch, idle_interval=0.05
        )
        self.identities.append(worker.identity.value)
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(worker.run_forever(self._stop))

    async def halt(self) -> None:
        if self._task is not None:
            self._stop.set()
            await self._task
            self._task = None

    async def restart(self) -> None:
        await self.halt()
        self.start()


@dataclass
class Stack:
    physical: Intake
    settings: Settings
    api: httpx2.AsyncClient
    api_calls: Recorded
    orders: httpx2.AsyncClient
    worker: HostedWorker

    def surfaces(self) -> Surfaces:
        return Surfaces(
            api=self.api,
            order_system=self.orders,
            service_token=SERVICE_TOKEN,
            database=self.physical.database,
        )


@asynccontextmanager
async def stack(physical: Intake, settings: Settings, tmp_path: Path) -> AsyncIterator[Stack]:
    """Both applications up and wired to each other both ways, no worker yet.

    PromisePatch's amendments reach the order system over HTTP, and the order system's own
    webhook dispatcher delivers its signed ``order.updated`` events back to PromisePatch's ingress
    -- the convergence a finished recovery waits for. The dispatcher runs as the simulator's
    delivery loop would, on a client of its own, so its traffic is not the runner's.
    """
    simulator_settings = SimulatorSettings(
        database_path=tmp_path / "orders.db",
        webhook_url=f"{PROMISEPATCH_ORIGIN}{WEBHOOK_PATH}",
        webhook_secret=SecretStr(WEBHOOK_SECRET),
        log_level="warning",
    )
    simulator = create_simulator(simulator_settings, deliver=False)
    application = create_promisepatch(settings)
    recorded = Recorded(httpx2.ASGITransport(app=application))
    async with (
        simulator.router.lifespan_context(simulator),
        application.router.lifespan_context(application),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=simulator), base_url=SIMULATOR_ORIGIN
        ) as orders,
        httpx2.AsyncClient(transport=recorded, base_url=PROMISEPATCH_ORIGIN) as api,
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=application)) as webhooks,
    ):
        client = OrderSystemClient(base_url=SIMULATOR_ORIGIN, timeout=5.0, client=orders)
        adapter = RoutedEffectAdapter(
            routes={EFFECT_ORDER_AMEND: OrderSystemAdapter(client)}, default=FakeEffectAdapter()
        )
        hosted = HostedWorker(physical.database, adapter, client.fetch_order)
        courier = asyncio.create_task(
            deliver_forever(
                WebhookDispatcher(OrderStore(tmp_path / "orders.db"), simulator_settings), webhooks
            )
        )
        try:
            yield Stack(physical, settings, api, recorded, orders, hosted)
        finally:
            await hosted.halt()
            courier.cancel()
            with suppress(asyncio.CancelledError):
                await courier


async def deliver_forever(dispatcher: WebhookDispatcher, client: httpx2.AsyncClient) -> None:
    """The order system's delivery loop: one signed event at a time, idling when there is none."""
    while True:
        if not await dispatcher.deliver_one(client):
            await asyncio.sleep(0.05)


async def restore_world(ready: Stack) -> None:
    """The operator's fixture action: ``pp restore-demo-world``, through its own function."""
    outcome = await demo_restore.restore_demo_world(
        ready.physical.database,
        cycles=ready.physical.worker(),
        settings=ready.settings,
        confirmation=demo_restore.CONFIRMATION,
        order_client=ready.orders,
    )
    assert outcome.action is demo_restore.Restored.RESTORED


# ------------------------------------------------------------------------------ the operator


Handler = Callable[[str], Awaitable[None]]


@dataclass
class ScriptedOperator:
    """Performs what it is asked, by the handler a test chose. Records what it was asked."""

    handlers: dict[OperatorAction, Handler]
    asked: list[OperatorAction] = field(default_factory=list)

    async def perform(self, action: OperatorAction, instruction: str) -> None:
        self.asked.append(action)
        await self.handlers[action](instruction)


def quoted(instruction: str, flag: str) -> str:
    """What a person reads off the instruction they were shown."""
    found = re.search(rf"{flag} (\S+)", instruction)
    assert found is not None, instruction
    return found.group(1)


def approve_in_the_browser(ready: Stack) -> Handler:
    """The worker signs in and presses Approve: ``BROWSER_SESSION``, recorded, not carried out."""

    async def handler(instruction: str) -> None:
        origin = ready.settings.cors_origin_list[0]
        app = create_promisepatch(ready.settings)
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url=origin, headers={"Origin": origin}
            ) as browser,
        ):
            login_router._limiter.reset()
            signed_in = await browser.post(
                "/api/auth/login",
                json={
                    "username": ho.BAKER,
                    "password": ready.settings.require_demo_worker_password(),
                },
            )
            assert signed_in.status_code == 200, signed_in.text
            approved = await browser.post(
                "/api/conversation/approve",
                json={
                    "case_id": quoted(instruction, "--case"),
                    "plan_id": quoted(instruction, "--plan"),
                },
                headers={cookies.CSRF_HEADER: browser.cookies[cookies.CSRF_COOKIE]},
            )
            assert approved.status_code in (200, 201, 202), approved.text

    return handler


def confirm_at_the_console(ready: Stack) -> Handler:
    """``pp confirm-plan``: ``OPERATOR_CONSOLE``, recorded and carried out in one command."""

    async def handler(instruction: str) -> None:
        await cli_module._confirm(
            ready.settings,
            UUID(quoted(instruction, "--case")),
            ho.BAKER,
            quoted(instruction, "--plan"),
            uuid4(),
        )

    return handler


def restart_the_worker(ready: Stack) -> Handler:
    async def handler(_: str) -> None:
        await ready.worker.restart()

    return handler


async def acknowledge_only(_: str) -> None:
    """An operator who says "done" and did nothing."""


async def run(ready: Stack, operator: ScriptedOperator) -> tuple[int, str]:
    out = io.StringIO()
    runner = Runner(ready.surfaces(), operator, out=out, timeout=60.0, poll=0.05)
    code = await runner.run()
    return code, out.getvalue()


async def count(database: RuntimeDatabase, model: Any) -> int:
    async with database.connect() as connection:
        return len((await connection.execute(select(model))).all())


# ============================================================ the fixture is the operator's


async def test_a_world_nobody_restored_is_refused_and_nothing_is_created(
    physical: Intake, deployed: Settings, tmp_path: Path
) -> None:
    """Hollow Oak seeded, no case: the runner says so and stops, before any transport is called."""
    async with stack(physical, deployed, tmp_path) as ready:
        operator = ScriptedOperator({})
        code, output = await run(ready, operator)

        assert code == EXIT_REFUSED, output
        assert "REFUSED" in output and "restore-demo-world" in output
        assert operator.asked == []
        assert ready.api_calls.calls == [], "a refused run called a transport"
        assert await count(physical.database, Case) == 0, "the runner created a case"
        assert await count(physical.database, OutboxMessage) == 0


async def test_a_world_with_a_plan_already_approved_is_refused(
    physical: Intake, deployed: Settings, tmp_path: Path
) -> None:
    """A used world is not a clean fixture. The runner refuses it rather than working around it."""
    async with stack(physical, deployed, tmp_path) as ready:
        await restore_world(ready)
        case_id = (await demo_contract.read_world(physical.database)).cases[0][0]
        status = await ready.api.post(
            "/internal/intents/status",
            json={"case_id": str(case_id)},
            headers={"X-Service-Token": SERVICE_TOKEN},
        )
        await cli_module._confirm(deployed, case_id, ho.BAKER, status.json()["plan_id"], uuid4())

        operator = ScriptedOperator({})
        code, output = await run(ready, operator)

        assert code == EXIT_REFUSED, output
        assert "not PLANNED" in output, output
        assert operator.asked == []
        assert await count(physical.database, PlanApproval) == 1, "the refusal wrote something"


# ============================================================ the storyboard, through transports


async def test_the_storyboard_holds_with_a_browser_approval_and_a_real_restart(
    physical: Intake, deployed: Settings, tmp_path: Path
) -> None:
    async with stack(physical, deployed, tmp_path) as ready:
        await restore_world(ready)
        ready.worker.start()
        operator = ScriptedOperator(
            {
                OperatorAction.APPROVE_PLAN: approve_in_the_browser(ready),
                OperatorAction.RESTART_WORKER: restart_the_worker(ready),
            }
        )

        code, output = await run(ready, operator)

        assert code == EXIT_PASS, output
        assert "DEMO CONTRACT PASS" in output
        assert operator.asked == [OperatorAction.APPROVE_PLAN, OperatorAction.RESTART_WORKER]
        assert len(set(ready.worker.identities)) == 2, "the operator restarted the worker once"
        # The runner's writes are transport calls and nothing else: it carried out the person's
        # approval through the intent API, and the customer answered through the link.
        assert ready.api_calls.to("/internal/intents/confirm") == [
            ("POST", "/internal/intents/confirm")
        ]
        assert [m for m, _ in ready.api_calls.to("/api/customer/approval/")] == ["GET", "POST"]
        assert not ready.api_calls.to("/api/conversation/"), "the runner spoke as the worker"
        # No output line carries the link, its token or the customer's address.
        assert LINK_BASE_URL not in output and "tg:" not in output


async def test_an_approval_already_carried_out_at_the_console_is_observed_not_repeated(
    physical: Intake, deployed: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Twice, at one anchor -- what every restore in the hour either side of local midnight gets.

    The second restore re-derives the same case, so the preserved ledger already holds a finished
    incarnation of it. Neither the worker nor the runner may read that one as this one's.
    """
    pinned = demo.resolve_demo_anchor(datetime.now(UTC), deployed.bakery_tz)
    monkeypatch.setattr(demo, "resolve_demo_anchor", lambda now, timezone: pinned)
    async with stack(physical, deployed, tmp_path) as ready:
        cases = []
        for _ in range(2):
            await ready.worker.halt()
            await restore_world(ready)
            cases.append((await demo_contract.read_world(physical.database)).cases[0][0])
            ready.worker.start()
            ready.api_calls.calls.clear()
            operator = ScriptedOperator(
                {
                    OperatorAction.APPROVE_PLAN: confirm_at_the_console(ready),
                    OperatorAction.RESTART_WORKER: restart_the_worker(ready),
                }
            )

            code, output = await run(ready, operator)

            assert code == EXIT_PASS, output
            assert ready.api_calls.to("/internal/intents/confirm") == []
            assert "already carried the approval out" in output
        assert cases[0] == cases[1], "the second restore did not re-derive the same case"


# ============================================================ a fault the operator did not inject


async def test_a_restart_acknowledged_but_never_performed_fails_the_run(
    physical: Intake, deployed: Settings, tmp_path: Path
) -> None:
    """The restart is proved by the worker identity on the second half, never by the say-so."""
    async with stack(physical, deployed, tmp_path) as ready:
        await restore_world(ready)
        ready.worker.start()
        operator = ScriptedOperator(
            {
                OperatorAction.APPROVE_PLAN: approve_in_the_browser(ready),
                OperatorAction.RESTART_WORKER: acknowledge_only,
            }
        )

        code, output = await run(ready, operator)

        assert code == EXIT_FAIL, output
        assert "FAIL  RESTART: the work after the restart carries no identity" in output
        assert "same worker process did work on both sides" in output
        assert "DEMO CONTRACT PASS" not in output


async def test_an_approval_acknowledged_but_never_given_fails_and_confirms_nothing(
    physical: Intake, deployed: Settings, tmp_path: Path
) -> None:
    """The runner cannot supply the missing approval: it fails, and the case stays PLANNED."""
    async with stack(physical, deployed, tmp_path) as ready:
        await restore_world(ready)
        ready.worker.start()
        operator = ScriptedOperator(
            {
                OperatorAction.APPROVE_PLAN: acknowledge_only,
                OperatorAction.RESTART_WORKER: restart_the_worker(ready),
            }
        )

        code, output = await run(ready, operator)

        assert code == EXIT_FAIL, output
        assert "FAIL  CONFIRMED: exactly one human approval of this plan exists" in output
        assert operator.asked == [OperatorAction.APPROVE_PLAN]
        assert ready.api_calls.to("/internal/intents/confirm") == []
        assert await count(physical.database, PlanApproval) == 0
        world = await demo_contract.read_world(physical.database)
        assert world.case_state == "PLANNED"
        assert world.effects == ()


# ============================================================ no direct write, by construction


async def test_the_evidence_connection_refuses_a_write(
    physical: Intake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever the runner's reader tried, the database would refuse it: the transaction is
    ``READ ONLY`` before the first statement runs."""

    async def a_reader_that_writes(connection: Any) -> Any:
        await connection.execute(update(Case).values(state="RESOLVED"))

    monkeypatch.setattr(demo_contract, "_read", a_reader_that_writes)
    with pytest.raises(DBAPIError, match="read-only transaction"):
        await demo_contract.read_world(physical.database)


def test_the_runner_holds_no_writer_no_signer_and_no_process_control() -> None:
    """Read from the runner's own source: nothing in it can write a row, mint a link, record an
    approval or a consent, or reach the worker process."""
    tree = ast.parse(RUNNER_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported |= {f"{node.module}.{alias.name}" for alias in node.names}
        elif isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)

    assert {name for name in imported if name.startswith("sqlalchemy.")} <= {
        "sqlalchemy.func",
        "sqlalchemy.select",
        "sqlalchemy.text",
        "sqlalchemy.ext.asyncio.AsyncConnection",
    }
    for forbidden in ("subprocess", "docker", "os", "promisepatch.worker"):
        assert not any(name == forbidden or name.startswith(f"{forbidden}.") for name in imported)
    assert not {name for name in imported if name.endswith((".record", ".ingest", ".mint"))}
    assert not called & {"record", "ingest", "mint", "confirm_plan", "begin", "insert", "delete"}
    # The only statement text it ever sends is the one that makes its transaction read-only.
    texts = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "text"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]
    assert texts and set(texts) == {"SET TRANSACTION READ ONLY"}


# ============================================================ the operator is a person, waited for


async def test_the_console_operator_shows_the_instruction_and_waits_for_the_person() -> None:
    out = io.StringIO()
    pressed = asyncio.Event()
    loop = asyncio.get_running_loop()

    def enter() -> str:
        loop.call_soon_threadsafe(pressed.set)
        return ""

    operator = ConsoleOperator(out, read_line=enter)
    await operator.perform(
        OperatorAction.RESTART_WORKER, "restart it: docker compose restart worker"
    )

    assert pressed.is_set(), "perform returned before the person pressed Enter"
    shown = out.getvalue()
    assert "OPERATOR ACTION [restart-worker]" in shown
    assert "docker compose restart worker" in shown
    assert "Press Enter" in shown
