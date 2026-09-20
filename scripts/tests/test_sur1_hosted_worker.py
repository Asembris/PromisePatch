"""The hosted worker: what proves arm C was ablated, and what refuses a run that cannot say.

Arm C is PromisePatch with revalidation check 5 dropped. On every topology this benchmark has
run on, the wrapper that drops it was installed in the harness process while the evaluator ran
in the ``worker`` container, so ``diagnostics.ablation`` is empty on all seventeen ablation
captures across two scored runs and **arm C was arm B by construction**. ADR-0020 authorises
running the product's own worker in the harness process for both arms so the rebinding reaches
the process that decides.

Everything below is proved from values and from the product's own audit rows. **No worker is
started, no database is opened, no container is touched, no arm is driven, no model is called
and no ``SUR-1`` scenario is executed.** Where a hosted loop's existence is the fact under test,
it is stood in for explicitly and the stand-in says so.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripts.sur1.ablation import ABLATED_CHECK, ABLATED_MARK
from scripts.sur1.bindings import REAL
from scripts.sur1.bindings.hostedworker import (
    DURABLE_EVALUATOR_MODULE,
    HarnessCompetitionError,
    HostedWorkerControl,
    RevalidationWitness,
)
from scripts.sur1.bindings.lifecycle import ABSENT, RUNNING, STOPPED
from scripts.sur1.driver import executor_evidence

HOSTED = "harness:4242:0badc0de"
CONTAINER = "worker-1:7:deadbeef"
SINCE = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

REAL_NAMES = {
    1: "case is waiting",
    2: "order version unchanged",
    3: "recipe pin unchanged",
    4: "constraint snapshot unchanged",
    5: "substitute still available",
    6: "production task not started and still ahead",
    7: "approval deadline not passed",
    8: "sender is the order's approval channel",
    9: "decision came from the literal parser",
    10: "decision binds this request",
}
"""The ten checks as the evaluator names them, which is what arm B's audit rows carry."""


def audit_rows(*, ablated: bool, worker: str = HOSTED) -> list[tuple[Any, ...]]:
    """One ``REVALIDATION_CHECK`` row per check, exactly as the product writes them.

    ``_record_checks`` writes one governed row per check with the index and the name in
    ``provenance`` and the worker identity beside them. Arm C's check 5 carries the ablation
    mark because the wrapper replaced the check in the tuple the ledger is written from --
    which is the whole of the treatment evidence.
    """
    return [
        (
            str(index),
            ABLATED_MARK if (ablated and index == ABLATED_CHECK) else REAL_NAMES[index],
            worker,
        )
        for index in range(1, 11)
    ]


@dataclass(slots=True)
class LedgerStandIn:
    """A :class:`~scripts.sur1.bindings.receivers.DatabaseReader` made of rows. Opens nothing."""

    checks: list[tuple[Any, ...]] = field(default_factory=list)
    actors: list[tuple[Any, ...]] = field(default_factory=list)
    url: str = "stand-in://rows"
    seen: list[str] = field(default_factory=list)
    unreadable: bool = False

    def rows(self, source: str, statement: str) -> list[tuple[Any, ...]]:
        self.seen.append(statement)
        if self.unreadable:
            raise OSError("the audit ledger could not be read")
        return list(self.checks) if "REVALIDATION_CHECK" in statement else list(self.actors)


@dataclass(slots=True)
class ComposeStandIn:
    """A container worker in a stated state. Nothing here starts or stops anything."""

    reported: str = STOPPED
    service: str = "worker"
    raises: bool = False

    def state(self) -> str:
        if self.raises:
            raise OSError("compose did not answer")
        return self.reported


@dataclass(slots=True)
class WorldStandIn:
    """Only what :func:`~scripts.sur1.driver.executor_evidence` reads off a world."""

    worker: Any
    started_at: datetime = SINCE


def hosted(**overrides: Any) -> HostedWorkerControl:
    """A control with a ledger behind it and, by default, no container worker to compete."""
    control = HostedWorkerControl(
        database=overrides.get("database", LedgerStandIn()),  # type: ignore[arg-type]
        compose=overrides.get("compose", ComposeStandIn()),  # type: ignore[arg-type]
    )
    if "identity" in overrides:
        _pretend_a_worker_is_hosted(control, overrides["identity"])
    return control


def _pretend_a_worker_is_hosted(control: HostedWorkerControl, identity: str) -> None:
    """Stand in for a hosted loop without starting one.

    Starting a real one needs a database, and what these tests are about is what the control
    *says* and *reads back*, not whether a loop can be started -- which is a live-stack
    question and belongs to ``DR01``. The two private values a running life would have set are
    set here, and the test that cares says so in its own name.
    """
    import importlib

    from scripts.sur1.bindings.hostedworker import _Loop

    life = _Loop()
    life.identity = identity
    control._life = life
    control._evaluator_module = importlib.import_module(DURABLE_EVALUATOR_MODULE)


# --------------------------------------------------------------- the treatment, per arm


def test_arm_b_s_own_audit_rows_show_the_full_ten_check_revalidation() -> None:
    control = hosted(database=LedgerStandIn(checks=audit_rows(ablated=False)))

    witnesses = control.revalidation_witnesses(SINCE)

    assert [witness.check for witness in witnesses] == list(range(1, 11))
    assert not any(witness.ablated for witness in witnesses)
    assert witnesses[4].name == REAL_NAMES[ABLATED_CHECK]


def test_arm_c_s_own_audit_rows_show_check_five_ablated_and_nothing_else_moved() -> None:
    """The arm's whole definition, read out of the system under test rather than the harness."""
    control = hosted(database=LedgerStandIn(checks=audit_rows(ablated=True)))

    witnesses = control.revalidation_witnesses(SINCE)

    assert [witness.check for witness in witnesses] == list(range(1, 11))
    assert [witness.check for witness in witnesses if witness.ablated] == [ABLATED_CHECK]
    assert [witness.name for witness in witnesses if witness.check != ABLATED_CHECK] == [
        REAL_NAMES[index] for index in range(1, 11) if index != ABLATED_CHECK
    ]


def test_the_two_arms_audit_rows_differ_only_at_check_five() -> None:
    full = hosted(database=LedgerStandIn(checks=audit_rows(ablated=False)))
    ablated = hosted(database=LedgerStandIn(checks=audit_rows(ablated=True)))

    before = full.revalidation_witnesses(SINCE)
    after = ablated.revalidation_witnesses(SINCE)

    differing = [b.check for b, a in zip(before, after, strict=True) if b != a]
    assert differing == [ABLATED_CHECK]


def test_the_ablation_mark_is_the_one_the_wrapper_writes_and_not_a_second_spelling() -> None:
    """A copy of the mark here would let the proof pass while the wrapper wrote something else."""
    assert RevalidationWitness(check=5, name=ABLATED_MARK, worker=HOSTED).ablated
    assert not RevalidationWitness(check=5, name=REAL_NAMES[5], worker=HOSTED).ablated


# ------------------------------------------------------------------- the sole executor


def test_an_attempt_the_hosted_worker_executed_alone_carries_its_proof_and_no_fault() -> None:
    control = hosted(
        database=LedgerStandIn(checks=audit_rows(ablated=True), actors=[(HOSTED,)]),
        identity=HOSTED,
    )

    payload, fault = executor_evidence(WorldStandIn(worker=control))  # type: ignore[arg-type]

    assert fault == ""
    assert payload["worker"] == HOSTED
    assert payload["foreign_workers"] == []
    assert [row["check"] for row in payload["revalidation"]] == list(range(1, 11))


def test_an_attempt_a_second_worker_touched_fails_closed() -> None:
    """Part of an ablated attempt executed where the wrapper does not reach is no arm at all."""
    control = hosted(
        database=LedgerStandIn(checks=audit_rows(ablated=True), actors=[(HOSTED,), (CONTAINER,)]),
        identity=HOSTED,
    )

    payload, fault = executor_evidence(WorldStandIn(worker=control))  # type: ignore[arg-type]

    assert CONTAINER in fault
    assert "a reading of no declared arm" in fault
    assert payload["foreign_workers"] == [CONTAINER]


def test_an_unreadable_ledger_is_a_refusal_rather_than_a_passing_proof() -> None:
    """*Nobody else did the work* and *nobody could tell* are different facts."""
    control = hosted(database=LedgerStandIn(unreadable=True), identity=HOSTED)

    payload, fault = executor_evidence(WorldStandIn(worker=control))  # type: ignore[arg-type]

    assert "could not be read" in fault
    assert "unreadable" in payload


def test_a_control_that_tracks_no_executor_yields_no_proof_and_no_fault() -> None:
    """Every run taken so far. The preflight refuses it; this function does not invent one."""

    class Untracked:
        pass

    payload, fault = executor_evidence(
        WorldStandIn(worker=Untracked())  # type: ignore[arg-type]
    )

    assert (payload, fault) == ({}, "")


def test_a_running_container_worker_refuses_to_let_a_hosted_one_start() -> None:
    control = hosted(compose=ComposeStandIn(reported=RUNNING))

    with pytest.raises(HarnessCompetitionError, match="without arm C's wrapper"):
        control.require_no_competing_worker()


def test_a_container_whose_state_cannot_be_established_refuses_too() -> None:
    """An unestablished second worker is not an absent one."""
    control = hosted(compose=ComposeStandIn(raises=True))

    with pytest.raises(HarnessCompetitionError, match="could not be established"):
        control.require_no_competing_worker()

    assert control.competing_worker_state() == "unknown"


def test_a_stopped_container_worker_is_what_a_scored_run_needs() -> None:
    control = hosted(compose=ComposeStandIn(reported=STOPPED))

    control.require_no_competing_worker()

    assert control.competing_worker_state() == STOPPED


def test_a_control_holding_no_container_reports_absent_rather_than_stopped() -> None:
    control = HostedWorkerControl(database=LedgerStandIn(), compose=None)  # type: ignore[arg-type]

    assert control.competing_worker_state() == ABSENT


# ------------------------------------------------------------------- reach and identity


def test_a_control_that_has_hosted_nothing_cannot_claim_the_evaluator_runs_here() -> None:
    assert hosted().evaluates_in_process() is False
    assert hosted().worker_identity() == ""


def test_a_hosted_worker_makes_the_rebinding_reach_the_deciding_name() -> None:
    """Both halves: the wrapper reaches the name, and a worker was built against that module."""
    control = hosted(identity=HOSTED)

    assert control.evaluates_in_process() is True
    assert control.worker_identity() == HOSTED


def test_the_rebinding_is_taken_back_out_by_the_question_that_asked_about_it() -> None:
    from scripts.sur1.ablation import installed_evaluator

    before = installed_evaluator()
    hosted(identity=HOSTED).evaluates_in_process()

    assert installed_evaluator() is before


def test_the_hosted_worker_publishes_the_product_s_own_runtime_identity() -> None:
    """Computed here, by the product's own module, about the process that does the work.

    Not a copy of a container's answer. Three scored runs recorded a provider flag read in the
    harness process about the wrong process, gated on by nothing.
    """
    published = hosted().runtime_identity()

    assert published["service"] == "promisepatch"
    assert published["process"] == "hosted-worker"
    assert len(str(published["source_digest"])) == 64
    assert "migration_revision" in published
    assert "bakery_tz" in published


def test_the_published_identity_carries_no_credential_value() -> None:
    """A run manifest is committed, so a value that could be a secret may not appear in one."""
    published = hosted().runtime_identity()

    assert set(published) >= {"database_target", "order_system_base_url"}
    assert not any("password" in str(value).lower() for value in published.values())
    # ``database_target`` is built from the URL's parts rather than rendered from the URL, so
    # there is no masked password in it to carry a length or a position.
    assert ":" not in str(published["database_target"]).partition("@")[0]


def test_the_control_declares_itself_a_real_binding() -> None:
    assert hosted().binding_kind == REAL


def test_a_hosted_worker_that_is_not_running_settles_immediately_and_says_so() -> None:
    assert "no hosted worker" in hosted().await_quiescence()
    assert hosted().state() == STOPPED


# --------------------------------------------------- the production worker is unchanged


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_the_hosted_worker_reaches_no_provisioning_of_its_own() -> None:
    """The contamination that bound 24 arm reports to the wrong delivery cannot happen here.

    ``ensure_demo_case`` is called by ``promisepatch.worker.run``'s ``_DemoCaseKeeper``, which
    is the deployment's judge-entry convenience and lives outside the worker. A hosted worker
    builds the worker and runs its loop, and there is no import by which it could call the
    other thing.
    """
    imported = _imported_names(
        Path(__file__).resolve().parents[1] / "sur1" / "bindings" / "hostedworker.py"
    )

    assert "promisepatch.worker" in imported
    assert "promisepatch.worker.built" in imported
    assert not any("provisioning" in name for name in imported)


def test_the_hosted_worker_adds_no_benchmark_branch_to_the_product() -> None:
    """Nothing under ``apps/`` or ``packages/`` learns that ``SUR-1`` exists.

    The frozen contract's ``what_is_not_touched`` says so, and an ablation seam inside the
    product would be the one repair it rules out. This asserts the absence rather than
    reviewing for it.
    """
    roots = (
        Path(__file__).resolve().parents[2] / "apps" / "backend" / "src" / "promisepatch",
        Path(__file__).resolve().parents[2] / "packages",
    )
    offending = [
        path
        for root in roots
        for path in root.rglob("*.py")
        if "sur1" in path.read_text(encoding="utf-8").lower()
    ]

    assert offending == []


def test_the_deployment_worker_still_installs_its_demo_keeper() -> None:
    """The hosted topology is a benchmark topology and changes no deployment."""
    import inspect

    from promisepatch import worker as product

    source = inspect.getsource(product.run)
    assert "_DemoCaseKeeper" in source
    assert "when_idle=keeper.check_if_the_day_turned" in source


def test_the_hosted_worker_uses_the_product_s_own_wiring_and_loop() -> None:
    """One implementation of *what a worker is*, and the hosted one does not hold a second."""
    import inspect

    from scripts.sur1.bindings import hostedworker

    source = inspect.getsource(hostedworker.HostedWorkerControl._run)
    assert "async with built(get_settings())" in source
    assert "await worker.run_forever(life.stop, when_idle=mark_idle)" in source


def test_the_quiescence_hook_is_the_loop_s_own_idle_hook_and_takes_no_other_action() -> None:
    """``when_idle`` is a production hook. What is passed to it here only counts."""
    import inspect

    from scripts.sur1.bindings import hostedworker

    source = inspect.getsource(hostedworker.HostedWorkerControl._run)
    body = source.split("async def mark_idle")[1].split("async with built")[0]
    assert "life.idle_marks += 1" in body
    assert "worker.deferred == 0" in body
    for forbidden in ("ensure_demo_case", "revalidate", "execute", "commit"):
        assert forbidden not in body


def test_the_witnesses_query_asks_for_the_product_s_own_event_type() -> None:
    """A different event type would read a ledger nothing writes and prove nothing quietly."""
    from scripts.sur1.bindings.hostedworker import REVALIDATION_CHECK_EVENT

    from promisepatch.domain.revalidation import AUDIT_REVALIDATION_CHECK

    assert REVALIDATION_CHECK_EVENT == AUDIT_REVALIDATION_CHECK

    ledger = LedgerStandIn(checks=audit_rows(ablated=False))
    hosted(database=ledger).revalidation_witnesses(SINCE)

    assert AUDIT_REVALIDATION_CHECK in ledger.seen[0]
    assert SINCE.isoformat() in ledger.seen[0]


def test_every_service_the_parity_checks_ask_about_is_one_compose_declares() -> None:
    """A check that asked about a service nobody runs would pass by never finding a difference."""
    from scripts.sur1.preflight import ORDER_SIMULATOR_SERVICE, PARITY_SERVICES

    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    for service in (*PARITY_SERVICES, ORDER_SIMULATOR_SERVICE):
        assert f"\n  {service}:" in compose


def _order_simulator_published_port(compose: str) -> str:
    for line in compose.splitlines():
        if "PROMISEPATCH_ORDER_SIMULATOR_PUBLISHED_PORT" in line:
            return line.split(":-")[1].split("}")[0]
    return ""


def test_the_harness_default_order_system_port_is_the_one_compose_defaults_to() -> None:
    """The two defaults must be one value, and the *published* one is what a run must use.

    On a machine that moved the port they are both wrong together, which is what
    ``config_parity`` asks compose about rather than reading a file. Here the point is narrower:
    the harness and the compose file may not disagree before anybody has moved anything.
    """
    from scripts.sur1.bindings.config import DEFAULT_PORTS

    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert _order_simulator_published_port(compose) == str(DEFAULT_PORTS["order_system"])


def test_a_moved_order_system_port_is_followed_into_the_host_environment() -> None:
    """``host.env`` named 58100 on a machine publishing 48100, and nothing followed it."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from with_local_env import repoint

    moved = repoint(
        {
            "PP_DATABASE_URL": "postgresql+asyncpg://app:pw@127.0.0.1:55432/promisepatch",
            "PP_ORDER_SYSTEM_BASE_URL": "http://127.0.0.1:58100",
        },
        "45432",
        "48100",
    )

    assert moved["PP_ORDER_SYSTEM_BASE_URL"] == "http://127.0.0.1:48100"
    assert "@127.0.0.1:45432/" in moved["PP_DATABASE_URL"]


def test_an_order_system_somewhere_other_than_loopback_is_left_alone() -> None:
    """A deployed address is not this machine's published port and is not repointed."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from with_local_env import repoint

    moved = repoint({"PP_ORDER_SYSTEM_BASE_URL": "https://orders.example:443"}, "45432", "48100")

    assert moved["PP_ORDER_SYSTEM_BASE_URL"] == "https://orders.example:443"


def test_the_required_checks_name_the_three_questions_the_hosted_topology_added() -> None:
    from scripts.sur1.preflight import REQUIRED_CHECKS

    assert {"build_identity", "config_parity", "sole_executor"} <= set(REQUIRED_CHECKS)


def test_the_driver_version_names_the_hosted_topology() -> None:
    """A topology change that did not move the recorded driver version would be undisclosed."""
    from scripts.sur1 import DRIVER_VERSION

    assert DRIVER_VERSION == "1.4.0"
