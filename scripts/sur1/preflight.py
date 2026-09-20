"""What has to be true before a scored comparative attempt may be bought, checked one at a time.

A scored run of ``SUR-1`` is the headline whatever it says, it may be taken once, and the retry
policy permits no second opinion. So everything that would make the resulting number mean
something other than what it appears to mean is asked **before** an arm is constructed, in one
place, and any failure refuses the run.

Twenty-five checks, and each is a fact rather than a promise:

1. the three frozen identities recompute to their published values;
2. all three bindings say they are real, so a run cannot be driven by a double;
3. the model configuration is the contract's own, and names an explicit region;
4. every credential and address a scored run needs is configured;
5. the workspace origin is set, is well formed, and is one this API actually accepts;
6. every receiver answers, so no scenario is voided for an unreadable source afterwards;
7. the world is installed into the database its evidence is read out of;
8. the running order system publishes the ``E1`` fields an amendment is attributed by;
9. the running PromisePatch is the revision this source tree is about to measure;
10. the durable worker can be stopped while a world is installed, and started afterwards;
11. the world holds a customer-consent door and the API behind it verifies signed links, so a
    stipulated reply reaches the product and not only the channel record;
12. the ``asserts_change`` rule is the declared one and hashes to its published identity;
13. every selected scenario has a world program that builds the world it declares;
14. the nine programs are the frozen nine, at their published hashes, and nothing on their
    preparation path can name a field that says what a correct answer is;
15. the world names the clock its scenarios are installed at;
16. the output directory is new, or is a resumable run of the same experiment;
17. nothing on the scoring path can reach an arm's name;
18. nothing that fires a world event can name an arm, an answer or a scorer's reading;
19. every previously published scored run is byte-identical to what was taken;
20. every spelling of a customer channel the world shows resolves to the identity it places;
21. the frozen report schema yields a report the projection accepts;
22. the worker opens no demo case inside the world an arm is about to act on;
23. the lifecycle re-reads the world after the worker comes back, and refuses a change;
24. the product's own semantic boundary is configured for the model the contract froze;
25. the process deciding revalidation is the one arm C's wrapper is installed in.

Checks 8 to 10 are the three the first scored run was refused by nothing. Each of them asks a
*capability* of a process that is already running -- what it publishes, what it was built for,
whether it can be quiesced -- because reachability passed on all three while the run was lost.
See ``docs/sur1-first-scored-run-defect.md`` and the correction record beside it.

Check 7 is what the *second* scored run was refused by nothing. All seventeen questions passed
while the fixture load was pointed at a hosted database and the receivers at the local one, and
all 27 attempts then failed at the write. See ``docs/sur1-corrected-scored-run-refusal.md``.

Checks 19 to 25 are what the *third* scored run was refused by nothing. All eighteen questions
passed while the baseline's messages were recorded on an address nothing could place, the
worker's own start-up opened a case inside every installed world, the product answered semantic
jobs with the deterministic fake, arm C's ablation reached no evaluator at all, and the report
tool published no fields for the one arm that had to fill them. Five of those are conditions
nothing asked about; one -- ``ablation_reach`` -- refuses every topology that exists today, and
that refusal is the point. See ``docs/sur1-v3-forensic-audit.md`` and
``docs/sur1-parity-correction.md``.

**A preflight reads and never writes.** It opens clients, asks services whether they are ready
and recomputes hashes. It creates no run directory, mints no token, prepares no world and calls
no model -- invoking the model to find out whether the model can be invoked would spend exactly
the thing this exists to protect.

**Failing is the useful outcome.** :func:`require` raises with every failed check named, rather
than returning a boolean somebody has to remember to read.

**Passing is a capability, not a note.** :func:`authorise` turns a passing scored report into a
:class:`~scripts.sur1.authorisation.ScoredAuthorisation` bound to the exact inputs that were
checked, and the driver and the capture layer ask for that object. This is the only place one is
minted, so "the preflight ran" stopped being something a caller could be trusted to have done.

**This preflight has minted three capabilities against real bindings, and every run it
authorised was lost.** All fourteen of its questions passed and ``20260919T2020Z-scored`` was
lost to three conditions none of them asked about; all seventeen passed and
``20260920T1100Z-scored-corrected`` was lost to a split database target none of them asked about
either; all eighteen passed and ``20260920T1215Z-scored-v3`` was lost to five more. Checks 7 to
10 and 19 to 25 are what it asks now, and the pattern is worth naming: each time, the questions
it did ask were true and the run still meant something other than it appeared to. See
``docs/sur1-first-scored-run-defect.md``, ``docs/sur1-corrected-scored-run-refusal.md`` and
``docs/sur1-v3-forensic-audit.md``.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from scripts.sur1 import predeclaration
from scripts.sur1.authorisation import (
    AuthorisationError,
    RunFingerprint,
    ScoredAuthorisation,
    _grant,
    digest_of,
)
from scripts.sur1.bindings import is_real
from scripts.sur1.bindings.config import BindingConfig
from scripts.sur1.bindings.lifecycle import ABSENT, RUNNING, STOPPED
from scripts.sur1.bindings.setup import unprogrammed
from scripts.sur1.capture import RUNS_ROOT, RunDirectory
from scripts.sur1.evidence import UNDETERMINED, OutboundClassifier, blind_bundle
from scripts.sur1.frozen import ARMS, Contract, FrozenIdentityError

SCORED: Final = "scored"

ROOT: Final = Path(__file__).resolve().parents[2]

REQUIRED_ORDER_CAPABILITIES: Final = (
    "admin-events.committed-body",
    "admin-events.command-idempotency-key",
)
"""What the order system has to say it publishes before a scored run reads its event log.

Named rather than imported. ``scripts.sur1`` treats the order system as an external service
and opens none of its code -- :class:`~scripts.sur1.bindings.receivers.OrderSystemReceiver`
reads two endpoints and nothing else -- so a capability the harness depends on is written down
here, and ``test_sur1_harness_correction`` asserts this list against what the simulator
actually declares.
"""

REQUIRED_ORDER_ENTRY_FIELDS: Final = (
    "event",
    "external_order_id",
    "occurred_at",
    "previous_version",
    "source",
    "type",
    "version",
)
"""Every key of an admin event entry that ``receivers.OrderSystemReceiver._event`` reads."""

REQUIRED_ORDER_BODY_FIELDS: Final = ("changed_line_ids", "command", "order")
"""Every key of the committed body that same reader opens, ``command`` above all.

Rule ``B2`` attributes an amendment to an arm by the idempotency key on the order system's own
event. A body with no command cannot serve it, and the reader's tolerance for one -- an event
with no command is read as having none -- is correct for an operator's edit and catastrophic
for a projection that publishes no commands at all.
"""

PUBLISHED_RUNS: Final[dict[str, tuple[int, str]]] = {
    "20260919T2020Z-scored": (
        57,
        "d599d644c6869fe527a32cfe240fe9a20433ed4a07679b02fbb597fecdc746ed",
    ),
    "20260920T1100Z-scored-corrected": (
        57,
        "e2a46c35b53902c817b9602999bb84f3df82cd3c7b425cb813551e7817364bca",
    ),
    "20260920T1215Z-scored-v3": (
        57,
        "403622ecd45a34723517556570d1b154c3f11f0e1fcaf9201856eeff6b9e18ca",
    ),
}
"""Every scored run that has been taken, by file count and digest, so an edit is detectable.

A scored run may be taken once and its headline is whatever it says. All three of these are
published inconclusive or invalid, and **all three stay exactly as they were taken**: the
correct response to one of these digests moving is to restore the run, never to update the
constant. ``20260920T1215Z-scored-v3`` is pinned here for the first time; the other two were
pinned in ``scripts/tests`` and are pinned again here, because the preflight has to be able to
refuse a fourth run whose predecessors have quietly changed.

Hashed the way the freeze hashes a module set: the relative path, a NUL, the bytes with
CRLF normalised to LF, another NUL, over the paths in sorted order. That is the algorithm
``test_sur1_database_target`` pins, restated here rather than imported out of a test.
"""

REQUIRED_CHECKS: Final = (
    "frozen_identities",
    "real_bindings",
    "model_identity",
    "configuration",
    "workspace_origin",
    "receivers",
    "database_identity",
    "order_projection",
    "backend_build",
    "worker_lifecycle",
    "consent_ingress",
    "classifier_identity",
    "world_programs",
    "world_program_freeze",
    "world_clock",
    "output_directory",
    "blinding",
    "event_blinding",
    "historical_runs",
    "channel_transport",
    "report_projection",
    "demo_provisioning",
    "world_integrity",
    "product_model_identity",
    "ablation_reach",
    "build_identity",
    "config_parity",
    "sole_executor",
)
"""Every question a scored run must have been asked, named so a partial report cannot mint.

:func:`authorise` refuses a report that does not carry all of these, which is what stops a
capability being minted from a hand-built report holding one passing check. It is a constant
rather than a count because a report naming eleven checks, one of which is new and two of which
are missing, would pass a count. :func:`preflight` is asserted to produce exactly these names,
so this cannot drift away from what is actually asked.
"""

FORBIDDEN_ON_THE_SCORING_PATH: Final = (
    "promisepatch",
    "promise_graph",
    "scripts.sur1",
)
"""Packages the scorer may not import, because each of them is one arm or the driver of one."""

ARM_FIELD_NAMES: Final = frozenset({"arm", "arm_label", "label", "system", "adapter"})
"""Field names on the scorer's own bundle that would carry an arm's identity if they existed."""

FORBIDDEN_SCENARIO_FIELDS: Final = frozenset(
    {"ground_truth", "the_point", "expected_report", "ablation_target"}
)
"""Frozen scenario fields a world program may not read, because each says what an answer is.

``ground_truth`` and ``the_point`` state the expected disposition outright. ``expected_report``
is one scenario's expected run report and ``ablation_target`` names the check a scenario exists
to remove, both of which a program could shape a world around. They stay in the manifest --
removing them would edit a frozen document -- and nothing on the preparation path may name one.
"""


class PreflightRefusedError(RuntimeError):
    """A scored run was asked for and at least one precondition is not true."""


@dataclass(frozen=True, slots=True)
class Check:
    """One precondition, its answer, and the sentence that says why."""

    name: str
    passed: bool
    detail: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Every check, in the order they were asked. Written into a run's own record."""

    kind: str
    checks: tuple[Check, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if not check.passed)

    def as_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "passed": self.passed,
            "checks": [check.as_payload() for check in self.checks],
        }


def frozen_identities() -> Check:
    try:
        identity = Contract.load().identity
    except FrozenIdentityError as moved:
        return Check("frozen_identities", False, str(moved))
    return Check(
        "frozen_identities",
        True,
        f"manifest {identity.manifest_sha[:8]}, prompt {identity.baseline_prompt_sha[:8]}, "
        f"scorer {identity.scorer_version}",
    )


def real_bindings(*, model: object, world: object, surface: object) -> Check:
    """Every binding declares itself real. A double is refused by value, not by type.

    :func:`~scripts.sur1.bindings.is_real` reads the declared kind rather than checking a
    protocol, because a runtime-checkable protocol only asks whether the members exist and a
    stand-in with the right attribute names satisfies it.
    """
    stand_ins = [
        name
        for name, binding in (("model", model), ("world", world), ("surface", surface))
        if not is_real(binding)
    ]
    if stand_ins:
        return Check(
            "real_bindings",
            False,
            f"a scored run cannot be driven by a stand-in: {', '.join(stand_ins)}",
        )
    return Check("real_bindings", True, "model, world and worker surface are real bindings")


def model_identity(*, model: object, contract: Contract) -> Check:
    """The model a run would call is the one the contract froze, in a named region."""
    identity = getattr(model, "identity", None)
    if not callable(identity):
        return Check("model_identity", False, "this model binding names no identity")
    declared: Mapping[str, Any] = identity()
    configured = contract.model_configuration
    differences = [
        f"{field}: contract {expected!r}, binding {declared.get(field)!r}"
        for field, expected in (
            ("provider", configured.provider),
            ("model_id", configured.model_id),
            ("api", configured.api),
            ("temperature", configured.temperature),
        )
        if declared.get(field) != expected
    ]
    if differences:
        return Check("model_identity", False, "; ".join(differences))
    if not declared.get("region"):
        return Check("model_identity", False, "no region is named, so where it ran is unrecorded")
    return Check(
        "model_identity",
        True,
        f"{declared['model_id']} at temperature {declared['temperature']} in {declared['region']}",
    )


def configuration(config: BindingConfig) -> Check:
    missing = config.missing()
    if missing:
        return Check("configuration", False, f"not configured: {', '.join(missing)}")
    return Check("configuration", True, "every address and credential a scored run needs is set")


def workspace_origin(*, config: BindingConfig, surface: object) -> Check:
    """The origin arms B and C sign in with is one this deployment actually accepts.

    Three questions, and only the running API can answer the third.

    **Set.** There is no default. The obvious one -- the API's own base URL -- is a value the
    product refuses: ``api/routers/auth.py`` matches ``Origin`` against ``PP_CORS_ORIGINS`` by
    exact string and that allowlist names browser origins. Falling back to it silently made the
    failure surface as an unreachable workspace rather than as the missing configuration it was,
    and a worker who cannot sign in can never approve a plan, so ``confirm`` can never spend one
    and every arm-B and arm-C attempt ends ``HARNESS_FAILURE``.

    **Well formed.** An origin is a scheme, a host and an optional port, and nothing else. A
    value carrying a path, a query or a trailing slash is not the string the allowlist holds, so
    it would be refused on a difference nobody could see in a log.

    **Accepted.** Asked of the deployment rather than of a copy of its configuration this
    harness would have to keep, by the surface that would do the signing in. A surface that
    cannot be asked fails the check: a scored run may not proceed on the assumption.
    """
    origin = config.workspace_origin
    if not origin:
        return Check(
            "workspace_origin",
            False,
            "SUR1_WORKSPACE_ORIGIN is unset and there is no default this API accepts; without "
            "it a worker cannot sign in, so no plan can ever be approved or confirmed",
        )
    malformed = _malformed_origin(origin)
    if malformed:
        return Check("workspace_origin", False, f"{origin!r} is not an origin: {malformed}")
    ask = getattr(surface, "origin_probe", None)
    if not callable(ask):
        return Check(
            "workspace_origin",
            False,
            f"this worker surface cannot be asked whether {config.api_base_url} accepts "
            f"{origin}, so whether a worker could sign in at all is unknown",
        )
    probe = ask()
    if not probe.reachable:
        return Check(
            "workspace_origin",
            False,
            f"{probe.detail}; set SUR1_WORKSPACE_ORIGIN to one of the deployment's own "
            "PP_CORS_ORIGINS",
        )
    return Check("workspace_origin", True, probe.detail)


def _malformed_origin(origin: str) -> str:
    """Why this string is not an origin, or the empty string when it is one."""
    from urllib.parse import urlsplit

    parsed = urlsplit(origin)
    if parsed.scheme not in ("http", "https"):
        return "an origin names http or https"
    if not parsed.netloc:
        return "an origin names a host"
    if parsed.path or parsed.query or parsed.fragment:
        return "an origin is a scheme, a host and a port, and carries no path, query or fragment"
    return ""


def receivers(*, world: object, surface: object) -> Check:
    """Ask every source whether it answers. Reads only, and the answers are recorded."""
    probes = []
    for binding in (world, surface):
        every = getattr(binding, "probes", None)
        if callable(every):
            probes.extend(every())
            continue
        one = getattr(binding, "probe", None)
        if callable(one):
            probes.append(one())
    unreachable = [f"{probe.source}: {probe.detail}" for probe in probes if not probe.reachable]
    if unreachable:
        return Check("receivers", False, "; ".join(unreachable))
    return Check(
        "receivers", True, f"reachable: {', '.join(sorted(probe.source for probe in probes))}"
    )


def channel_transport(*, world: object, contract: Contract | None) -> Check:
    """Every spelling the world shows of a customer channel resolves to the identity it places.

    The question that lost the baseline on two scored runs and that nothing asked. ``get_orders``
    is the order system's own snapshot and shows a split ``{"kind": "telegram", "address":
    "1002"}``; ``get_promise_graph`` shows the engine's joined ``tg:1002``. The frozen fixture,
    the arming and ``FixtureMap`` know only the joined one. The harness transport recorded
    whichever string it was handed, so an ask landed under a name no armed event watched, no
    stipulated reply ever fired, and the ``E2`` row was refused at placement. See
    ``docs/sur1-v3-forensic-audit.md`` section 1.

    Three things are required of each of the world's own channels, and a fourth of an address
    that names nobody:

    1. both spellings resolve, through the transport's own resolver, to the joined identity;
    2. ``FixtureMap`` can put that identity on an order;
    3. ``observe`` counts an outbound message on it under that same name, which is what makes a
       declared reply become due;
    4. an address naming no channel in this world is refused rather than recorded.

    Read-only: it resolves strings and reduces synthetic messages. Nothing is sent, no ledger is
    written and the world is not mutated.
    """
    from scripts.sur1.bindings.events import observe
    from scripts.sur1.bindings.receivers import (
        KIND_BY_CHANNEL_PREFIX,
        UnresolvableChannelError,
        resolve_channel_address,
    )
    from scripts.sur1.evidence import OUTBOUND, ChannelMessage, EvidenceMalformedError, FixtureMap

    if contract is None:
        return Check("channel_transport", False, "the frozen contract did not load")
    universe = getattr(world, "channel_universe", None)
    if not callable(universe):
        return Check(
            "channel_transport",
            False,
            "this world cannot say which customer channels it holds, so nothing can check that "
            "the address an arm is shown is the identity its message is placed on",
        )

    known = tuple(universe())
    fixtures = FixtureMap.read(contract.document)
    if sorted(known) != sorted(fixtures.by_channel):
        return Check(
            "channel_transport",
            False,
            f"the world holds {sorted(known)} and the frozen fixture places "
            f"{sorted(fixtures.by_channel)}",
        )

    faults: list[str] = []
    for channel in known:
        prefix, separator, address = channel.partition(":")
        if not separator or prefix not in KIND_BY_CHANNEL_PREFIX:
            faults.append(f"{channel!r} is not a joined channel identity")
            continue
        spellings = (channel, address, f"{KIND_BY_CHANNEL_PREFIX[prefix]}:{address}")
        for spelling in spellings:
            try:
                resolved = resolve_channel_address(spelling, known=known)
            except UnresolvableChannelError as unknown:
                faults.append(f"{spelling!r} does not resolve: {unknown}")
                continue
            if resolved != channel:
                faults.append(f"{spelling!r} resolves to {resolved!r} rather than {channel!r}")
                continue
            try:
                fixtures.order_for_channel(resolved)
            except EvidenceMalformedError as unplaceable:
                faults.append(f"{spelling!r} resolves to a row nothing can place: {unplaceable}")
                continue
            counted = observe(
                [
                    ChannelMessage(
                        channel_address=resolved,
                        direction=OUTBOUND,
                        text="",
                        accepted_at=datetime.now(UTC),
                    )
                ]
            )
            if counted.asks_on(channel) != 1:
                faults.append(f"an ask on {spelling!r} is not counted under {channel!r}")

    stranger = "no-such-address-" + "0" * 4
    try:
        resolve_channel_address(stranger, known=known)
    except UnresolvableChannelError:
        pass
    else:
        faults.append(f"{stranger!r} names no channel here and was accepted anyway")

    if faults:
        return Check("channel_transport", False, "; ".join(faults[:6]))
    return Check(
        "channel_transport",
        True,
        f"{len(known)} channels resolve, place and count identically from every spelling shown",
    )


def database_identity(*, world: object, config: BindingConfig) -> Check:
    """The world is installed into the database its evidence is read out of. One target.

    The question the second scored run needed and nobody asked. Seventeen checks passed while the
    governed fixture load was pointed at a hosted database by the repository's ``.env`` and the
    receivers were pointed at the local one by ``SUR1_DATABASE_URL``; all 27 attempts then failed
    in preparation, at the write, which is far too late to be a gate. See
    ``docs/sur1-corrected-scored-run-refusal.md`` §3.

    **Three readings, because three objects could disagree and any two agreeing proves nothing.**
    The scored configuration says which database this run is *for*; the world's own receivers say
    which one they will actually read; and the installer target says which one the fixture load
    will actually write to. All three have to name one database.

    **It opens nothing.** Every value here is parsed from a string or read from settings, which is
    what lets this refuse before authorisation, before a run directory exists, before a connection
    is dialled and before a model is reached -- rather than after a ``TRUNCATE`` has been aimed.

    **Unknown is a refusal.** A URL this package cannot read is not a URL whose target can be
    compared with another, so a malformed or unrecognised one fails rather than being treated as
    agreement.
    """
    from scripts.sur1.bindings.database import (
        DatabaseIdentityError,
        InstallerTarget,
        disagreement,
        identity_of,
        receiver_identity,
    )

    reader = getattr(world, "database", None)
    if reader is None or not isinstance(getattr(reader, "url", None), str):
        return Check(
            "database_identity",
            False,
            "this world does not say which database its receivers read, so nothing can be "
            "checked against the database its world would be installed into",
        )
    target = getattr(world, "installer", None)
    if not isinstance(target, InstallerTarget):
        return Check(
            "database_identity",
            False,
            "this world carries no installer target, so the fixture load has no database it was "
            "handed and no run may be driven at it",
        )

    try:
        scored = receiver_identity(config.database_url)
        observed = identity_of(reader.url, what="the world's own receiver database URL")
        installing = target.identity()
    except DatabaseIdentityError as failure:
        return Check("database_identity", False, str(failure))

    if scored != observed:
        return Check(
            "database_identity",
            False,
            f"this run is configured for {scored} and its receivers would read {observed}",
        )
    split = disagreement(installing, observed)
    if split:
        return Check("database_identity", False, split)
    return Check(
        "database_identity",
        True,
        f"the world installs into and is read out of {observed}; the load resolves it from "
        f"{target.source}",
    )


def order_projection(*, world: object) -> Check:
    """The running order system publishes the ``E1`` fields rule ``B2`` attributes by.

    :func:`receivers` asks whether the order system *answers*. This asks what it answers
    *with*, and the two are not the same question: a container four days behind the commit
    that added the committed event body answered ``/readyz``, ``/orders`` and ``/admin/events``
    perfectly and published no ``event`` key at all. Twenty of the first scored run's
    twenty-seven attempts died on that, downstream, one at a time, after the model had been
    paid. See ``docs/sur1-first-scored-run-defect.md`` §2.1 and §3.

    **Capability rather than a build date.** The order system is asked what it publishes and
    has to say so; an image timestamp would be a proxy for the thing, and a proxy is what this
    check exists to stop relying on. A build too old to answer the question fails here, which
    is before anything is spent.

    **Nothing downstream is relaxed to accommodate an old build.** ``receivers._event`` still
    reads an event with no command as having none, and ``replay._text`` still refuses an empty
    idempotency key. Those two are right as they are; what was missing was a question asked
    early enough for the disagreement between them never to arise.
    """
    reader = getattr(world, "orders", None)
    ask = getattr(reader, "published_projection", None)
    if not callable(ask):
        return Check(
            "order_projection",
            False,
            "this world's E1 reader cannot be asked what the order system publishes, so "
            "whether an amendment could be attributed to an arm at all is unknown",
        )
    try:
        published: Mapping[str, Any] = ask()
    except Exception as failure:
        detail = getattr(failure, "detail", None) or f"{type(failure).__name__}: {failure}"
        return Check("order_projection", False, str(detail))

    declared = set(published.get("capabilities") or ())
    entry = set(published.get("entry_fields") or ())
    body = set(published.get("body_fields") or ())
    observed = published.get("observed_entry_fields")

    faults = [
        f"capability {name!r} is not declared"
        for name in REQUIRED_ORDER_CAPABILITIES
        if name not in declared
    ]
    faults += [
        f"an event entry does not carry {name!r}"
        for name in REQUIRED_ORDER_ENTRY_FIELDS
        if name not in entry
    ]
    faults += [
        f"a committed event body does not carry {name!r}"
        for name in REQUIRED_ORDER_BODY_FIELDS
        if name not in body
    ]
    if isinstance(observed, Sequence) and not isinstance(observed, str):
        faults += [
            f"the entry this log actually published does not carry {name!r}"
            for name in REQUIRED_ORDER_ENTRY_FIELDS
            if name not in set(observed)
        ]
    if faults:
        return Check(
            "order_projection",
            False,
            "the running order system cannot serve rule B2: " + "; ".join(faults),
        )
    seen = "no event on the log yet" if observed is None else "checked against a published entry"
    return Check("order_projection", True, f"E1 publishes the committed body; {seen}")


def report_projection(*, contract: Contract | None) -> Check:
    """A report built only from the schema arm A is given survives the whole projection.

    ``E4`` came back with no promises on every baseline attempt of two scored runs. The Converse
    tool published ``report`` as a bare object with no properties and the frozen prompt names no
    field, so nothing told arm A what to fill. See ``docs/sur1-v3-forensic-audit.md`` section 5,
    F6.

    The check is the whole path taken dry: derive the schema from the frozen manifest, build one
    report *by walking that schema and nothing else*, read it with the same ``_report_row`` an
    arm's call is read with, project it through ``blind_bundle``, and require what comes out to
    satisfy the frozen ``invalid_report_rule`` -- one entry per order in the case universe, every
    enumerated value drawn from the frozen enumerations.

    The rule is read out of the frozen document rather than out of the scorer. The scorer is
    reached through one blind seam and a preflight that opened its internals would be a second
    copy of the metric. ``scripts/tests/test_sur1_report_contract.py`` is where the agreement
    between the two is proved.

    No model, no socket, no write: the report is synthetic, ``_report_row`` is pure, and no
    world's own report field is touched.
    """
    from scripts.sur1.adapters import ReportSchemaError, run_report_schema
    from scripts.sur1.bindings.world import _report_row
    from scripts.sur1.evidence import EvidenceMalformedError, FixtureMap, ReceiverEvidence

    if contract is None:
        return Check("report_projection", False, "the frozen contract did not load")

    scenario = contract.scenario_ids[0] if contract.scenario_ids else "C01"
    try:
        schema = run_report_schema(contract)
    except ReportSchemaError as unreadable:
        return Check(
            "report_projection", False, f"the frozen report schema is unreadable: {unreadable}"
        )

    entry = schema["properties"].get("promises", {}).get("items", {}).get("properties")
    if not entry:
        return Check(
            "report_projection",
            False,
            "the published report schema describes no promise entry, which is the shape arm A "
            "was given when it filled none",
        )

    universe = contract.case_universe
    synthetic = {
        "scenario_id": scenario,
        "exception_recorded": True,
        "promises": [
            {
                "order": order,
                "outcome": entry["outcome"]["enum"][0],
                "recovered_to_version": None,
                "work_state": entry["work_state"]["enum"][0],
                "claimed_stopped": False,
                "reason": "preflight projection, never scored",
            }
            for order in universe
        ],
    }

    try:
        projected = _report_row(synthetic, scenario_id=scenario)
        bundle = blind_bundle(
            ReceiverEvidence(report=projected),
            run_id="preflight",
            scenario_id=scenario,
            arm_token="preflight",
            fixtures=FixtureMap.read(contract.document),
        )
    except EvidenceMalformedError as malformed:
        return Check(
            "report_projection", False, f"the projection refused its own report: {malformed}"
        )

    report = bundle.report
    if report is None:
        return Check("report_projection", False, "the projection produced no report at all")
    reported = sorted(promise.order for promise in report.promises)
    if reported != sorted(universe):
        return Check(
            "report_projection",
            False,
            f"the projected report names {reported} and the case universe is {sorted(universe)}",
        )
    outcomes = set(entry["outcome"]["enum"])
    states = set(entry["work_state"]["enum"])
    strays = [
        f"{promise.order}: {promise.outcome}/{promise.work_state}"
        for promise in report.promises
        if promise.outcome not in outcomes or promise.work_state not in states
    ]
    if strays:
        return Check("report_projection", False, "; ".join(strays))
    return Check(
        "report_projection",
        True,
        f"the published schema yields a report of {len(reported)} promises the projection accepts",
    )


def backend_build(*, surface: object) -> Check:
    """The running PromisePatch is the revision the harness is about to measure.

    Two facts, because two different processes are involved and each can be wrong on its own.

    **The served API.** ``/readyz`` names the migration revision the *running image's own code*
    was built for and whether the database is at it. A deployment serving an older build says
    so here, in a value it computes from its own bytes rather than from a tag anybody chose. It
    is asked of the worker surface, which already owns the API's address and its transport, for
    the reason :func:`workspace_origin` asks that surface too.

    **The in-process fixture load.** The harness does not install a world over HTTP: it imports
    :func:`~promisepatch.fixtures.reset.reset_demo_state` and runs it in this process, so the
    capability that matters is whether *the code on this path* takes a stated snapshot and
    fixture name. That is asked of the function's own signature, and the package is required to
    resolve inside this repository -- a harness running against an installed wheel of some
    other revision would pass every HTTP check and install a world nobody declared.

    **What it does not prove**, said plainly because the gap is real: an image stale only in
    code that no migration accompanied reports the same revision as the source tree and passes.
    Migration head is the strongest identity the product publishes about itself today, and it
    is a capability claim rather than a timestamp, which is the property that matters here.
    """
    import inspect

    faults: list[str] = []
    detail = []

    try:
        from promisepatch import fixtures
        from promisepatch.db import HEAD_REVISION
        from promisepatch.fixtures.reset import reset_demo_state
    except Exception as failure:
        return Check(
            "backend_build",
            False,
            f"the product's own fixture load could not be imported: "
            f"{type(failure).__name__}: {failure}",
        )

    accepted = set(inspect.signature(reset_demo_state).parameters)
    missing = sorted({"snapshot", "fixture_name"} - accepted)
    if missing:
        faults.append(
            f"reset_demo_state on this path takes no {missing}; a scenario's canonical world "
            "cannot be installed through the governed fixture load"
        )
    here = Path(fixtures.__file__ or "").resolve()
    if ROOT not in here.parents:
        faults.append(f"promisepatch resolves to {here}, which is outside this repository")

    served = _served_readiness(surface, faults)
    migrations: Mapping[str, Any] = (served or {}).get("migrations") or {}
    if served is not None:
        expected = str(migrations.get("expected_revision", ""))
        if expected != HEAD_REVISION:
            faults.append(
                f"the running API was built for migration {expected or 'nothing'} and this "
                f"source is at {HEAD_REVISION}; it is not the revision being measured"
            )
        elif not migrations.get("at_head"):
            faults.append(
                f"the database is at {migrations.get('actual_revision')} and the running API "
                f"expects {expected}"
            )
        else:
            detail.append(f"API and source both at migration {expected}")

    if faults:
        return Check("backend_build", False, "; ".join(faults))
    detail.append("the governed fixture load takes a stated world")
    return Check("backend_build", True, "; ".join(detail))


def _served_readiness(surface: object, faults: list[str]) -> Mapping[str, Any] | None:
    """What the running API says about itself, or ``None`` and a named reason it could not say.

    A surface that cannot be asked and a surface that refused are two different failures and
    both are recorded, because a caller repairing a refused run needs to know which it has.
    """
    ask = getattr(surface, "readiness", None)
    if not callable(ask):
        faults.append("this worker surface cannot be asked what the running API was built for")
        return None
    try:
        served: Mapping[str, Any] = ask()
    except Exception as failure:
        faults.append(f"the running API could not be read: {type(failure).__name__}: {failure}")
        return None
    return served


def worker_lifecycle(*, world: object) -> Check:
    """The durable worker can be put down while a world is installed, and brought back.

    ``reset_demo_state`` empties forty-two tables and takes an exclusive lock on each; the
    worker's cycle holds shared locks on several of them in a different order. One attempt of
    the first scored run died of exactly that deadlock. A run that cannot stop the worker
    cannot remove the race, so it is refused rather than driven and hoped over.

    Asked of the control the world actually holds, and refused for a stand-in by declared kind
    -- the same rule :func:`real_bindings` and :func:`consent_ingress` use, for the same reason:
    a protocol check only asks whether the methods exist.
    """
    control = getattr(world, "worker", None)
    if control is None:
        return Check(
            "worker_lifecycle",
            False,
            "this world carries no worker control, so a fixture load would be issued beside a "
            "live worker and can deadlock against it",
        )
    if not is_real(control):
        return Check(
            "worker_lifecycle",
            False,
            "a scored run cannot install its worlds beside a worker it only pretends to control",
        )
    probe = control.probe()
    if not probe.reachable:
        return Check("worker_lifecycle", False, probe.detail)
    return Check("worker_lifecycle", True, probe.detail)


def consent_ingress(*, world: object) -> Check:
    """The world can deliver a stipulated reply to the product, not only to the record.

    Without this, a run takes every reading it would otherwise take and the customer replies
    reach a Python list: no approval request is bound, no sender is compared against the channel
    the request was sent to, no deadline is checked and the literal parser never runs. The
    baseline is unaffected -- it has no consent protocol and needs the reply only to exist -- so
    the damage is arm-correlated and invisible in the numbers. That is what makes this a refusal
    rather than a warning.

    Asked in two parts, because two different things can be wrong. A world carrying no door
    cannot deliver at all. A process that mints no customer link signs nothing and therefore
    verifies nothing, and answers ``503`` to every token -- so the probe presents a token that
    cannot verify and requires the surface to say ``404``, which is the answer of a surface that
    read a link and refused it. Nothing is written by either part.
    """
    door = getattr(world, "consent_door", None)
    if door is None:
        return Check(
            "consent_ingress",
            False,
            "this world carries no customer-consent door, so a stipulated reply would reach the "
            "channel record and never reach PromisePatch; every scenario needing a literal yes "
            "would understate recovery, and only for the arms that have a consent protocol",
        )
    if not is_real(door):
        return Check(
            "consent_ingress",
            False,
            "a scored run cannot deliver consent through a stand-in door",
        )
    answer = door.probe()
    if not answer.reachable:
        return Check("consent_ingress", False, answer.detail)
    return Check("consent_ingress", True, answer.detail)


def classifier_identity(classifier: OutboundClassifier) -> Check:
    """The ``asserts_change`` rule is declared, and is the one whose identity was published."""
    if classifier is UNDETERMINED:
        return Check(
            "classifier_identity",
            False,
            "the harness's undetermined default decides nothing; a scored run needs the rule "
            "declared in the execution predeclaration",
        )
    if classifier is not predeclaration.asserts_change:
        return Check(
            "classifier_identity",
            False,
            f"this run would use {getattr(classifier, '__qualname__', classifier)!r}, which is "
            "not the declared rule",
        )
    recomputed = predeclaration.identity_sha()
    if recomputed != predeclaration.PREDECLARATION_SHA:
        return Check(
            "classifier_identity",
            False,
            f"the declared rules have moved: published {predeclaration.PREDECLARATION_SHA}, "
            f"recomputed {recomputed}",
        )
    return Check(
        "classifier_identity",
        True,
        f"{predeclaration.ASSERTS_CHANGE_RULE} at {recomputed[:8]}",
    )


def world_programs(scenario_ids: Sequence[str]) -> Check:
    """Every selected scenario has a program, and every program builds the world it declares.

    Building it is the check. A program that names a version the fixture does not have, or
    stipulates a task state the fixture contradicts, raises while it is projected -- and it has
    to raise here, before an attempt is bought, rather than inside the preparation of the third
    arm's second scenario.
    """
    missing = unprogrammed(scenario_ids)
    if missing:
        return Check(
            "world_programs",
            False,
            f"no world program for {', '.join(missing)}; their stipulated facts are prose in the "
            "frozen contract and nobody has authored them into world steps",
        )
    from scripts.sur1.bindings.setup import program_for
    from scripts.sur1.bindings.worldsnapshot import digest_of

    unprepared = []
    for scenario_id in scenario_ids:
        try:
            digest_of(program_for(scenario_id))
        except Exception as failure:  # a program that cannot build a world prepares nothing
            unprepared.append(f"{scenario_id}: {type(failure).__name__}: {failure}")
    if unprepared:
        return Check("world_programs", False, "; ".join(unprepared))
    return Check("world_programs", True, f"{len(scenario_ids)} scenarios can be prepared")


def world_program_freeze(contract: Contract | None) -> Check:
    """The nine programs are the frozen nine, and nothing on their path can read an answer.

    Four facts in one check because they fail together and are useless apart: a hash that
    matches a declaration listing eight scenarios says nothing, and nine matching hashes
    computed by code that had started branching on the expected disposition say less.
    """
    if contract is None:
        return Check("world_program_freeze", False, "the frozen contract did not load")
    from scripts.sur1.bindings.declaration import differences
    from scripts.sur1.bindings.programs import programs

    try:
        built = programs()
    except Exception as failure:
        return Check("world_program_freeze", False, f"{type(failure).__name__}: {failure}")

    expected = tuple(contract.scenario_ids)
    if tuple(sorted(built)) != tuple(sorted(expected)):
        return Check(
            "world_program_freeze",
            False,
            f"the program set is {sorted(built)} and the contract's scenarios are "
            f"{sorted(expected)}",
        )

    reachable = ground_truth_reachable()
    if reachable:
        return Check(
            "world_program_freeze",
            False,
            f"a world program could read what a correct answer is: {'; '.join(reachable)}",
        )

    moved = differences()
    if moved:
        return Check("world_program_freeze", False, "; ".join(moved))
    return Check(
        "world_program_freeze",
        True,
        f"{len(built)} programs frozen at the published set and world digests",
    )


def world_clock(*, world: object) -> Check:
    """This run is placed in time by a declared rule, and the capture will say which.

    The check a scored run needs and the one the dress rehearsal's §13 showed was missing: a
    world installed at the fixture's own March 2026 anchor is months in the past, both Valley
    Produce deliveries fall outside the bakery day, the clarification collapses into two options
    carrying the same words and every scenario ends ``NEEDS_HUMAN_INTERPRETATION``. That failure
    produces a full set of numbers and none of them is about a scenario, which is exactly the
    kind of failure a preflight exists to turn into a refusal.

    So the question is not *is the anchor sensible* --
    :func:`scripts.sur1.bindings.clock.run_anchor` already refuses an unusable one at the moment
    it is chosen -- but *was any declared rule used at all*. An unrecognised strategy is refused
    rather than trusted, because a world carrying a string nobody recognised is a world placed in
    time by something this package did not write. See ADR-0019.
    """
    from scripts.sur1.bindings.clock import FIXTURE_ANCHOR, KNOWN_STRATEGIES, RunClock

    clock = getattr(world, "clock", None)
    if clock is None:
        return Check(
            "world_clock",
            False,
            "this world carries no run clock, so it would be installed at the fixture's own "
            f"anchor ({FIXTURE_ANCHOR}). Every commitment would then fall outside the bakery day "
            "and every scenario would end NEEDS_HUMAN_INTERPRETATION",
        )
    if not isinstance(clock, RunClock):
        return Check(
            "world_clock",
            False,
            f"a run clock is a RunClock, not a {type(clock).__name__}",
        )
    if not clock.declared:
        return Check(
            "world_clock",
            False,
            f"{clock.strategy!r} is not a declared clock strategy; this run may be driven under "
            f"{sorted(KNOWN_STRATEGIES)} and nothing else",
        )
    return Check(
        "world_clock",
        True,
        f"{clock.strategy}/{clock.version} at {clock.anchor.isoformat()} ({clock.timezone})",
    )


EVENT_MODULES: Final = ("events", "worldsink", "consentdoor")
"""The modules that decide when a declared world event fires and what it does.

Named here rather than inferred, because the whole value of the check below is that adding a
module to the firing path and forgetting to list it is itself visible in a diff.
"""

SCORING_MODULE: Final = "scripts.score_safe_useful_recovery"
"""What event code may never import. A trigger that could read a reading is not a trigger."""


def event_blinding() -> Check:
    """Nothing that fires a world event can name an arm, an answer or a scorer's reading.

    The same argument :func:`blinding` makes about the scoring path, made about the firing path,
    and for a sharper reason: a world whose events fired differently depending on which arm was
    driving would make every later number a comparison between three different worlds, and the
    failure would be invisible in all of them.

    Three structural facts. What a trigger is allowed to read carries no field an arm label
    could travel in; no module on the firing path names an arm, an expected disposition or a
    scorer's own vocabulary as code; and none of them can import the scorer at all.
    """
    from scripts.sur1.bindings.events import Observation

    leaking = sorted(set(Observation.__dataclass_fields__) & ARM_FIELD_NAMES)
    if leaking:
        return Check("event_blinding", False, f"a trigger's observation carries {leaking}")

    forbidden = FORBIDDEN_SCENARIO_FIELDS | ARM_FIELD_NAMES | frozenset(ARMS)
    found: list[str] = []
    for path in _event_sources():
        for name in sorted(_names_in(path, forbidden)):
            found.append(f"{path.name} names {name!r}")
        imported = _imports_of(path)
        if any(
            name == SCORING_MODULE or name.startswith(f"{SCORING_MODULE}.") for name in imported
        ):
            found.append(f"{path.name} imports the scorer")
    if found:
        return Check("event_blinding", False, "; ".join(found))
    return Check(
        "event_blinding",
        True,
        f"{len(EVENT_MODULES)} firing modules name no arm, no answer and no reading",
    )


def _event_sources() -> tuple[Path, ...]:
    """The files the firing path is made of, resolved from the modules themselves."""
    from scripts.sur1.bindings import consentdoor as consentdoor_module
    from scripts.sur1.bindings import events as events_module
    from scripts.sur1.bindings import worldsink as worldsink_module

    by_name = {
        "events": events_module,
        "worldsink": worldsink_module,
        "consentdoor": consentdoor_module,
    }
    return tuple(Path(by_name[name].__file__ or "") for name in EVENT_MODULES)


def ground_truth_reachable() -> tuple[str, ...]:
    """Whether any module on the world-program path can name what a correct answer is.

    Read from the syntax rather than from behaviour, the way :func:`blinding` reads the
    scorer's imports. A program that branched on the expected disposition would produce a world
    built towards its own answer, and the failure would be invisible in every number afterwards
    -- so the guard is the one thing here that must not depend on a program choosing to be
    honest at runtime.
    """
    from scripts.sur1.bindings import declaration as declaration_module

    found: list[str] = []
    for module in declaration_module.IMPLEMENTATION_MODULES:
        path = Path(module.__file__ or "")
        for name in sorted(_forbidden_names_in(path)):
            found.append(f"{path.name} names {name!r}")
    return tuple(found)


def _forbidden_names_in(path: Path) -> set[str]:
    """Every forbidden field name this file mentions, as an attribute, a key or a literal."""
    return _names_in(path, FORBIDDEN_SCENARIO_FIELDS)


def _names_in(path: Path, forbidden: frozenset[str]) -> set[str]:
    """Which of these names this file uses as code: a literal, an attribute or a name.

    Exact equality, and never a substring of prose. A module that explains in its docstring why
    a trigger must not consult an arm is doing the right thing; one with ``PROMISEPATCH`` in an
    expression is not, and only the second is a name in the syntax.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found |= {name for name in forbidden if name == node.value}
        elif isinstance(node, ast.Attribute) and node.attr in forbidden:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in forbidden:
            found.add(node.id)
    return found


def output_directory(run_id: str, *, root: Path = RUNS_ROOT, contract: Contract | None) -> Check:
    """A new run, or a resumable one that is the same experiment. Never a third thing.

    A directory holding a run started against different frozen identities is refused here for the
    same reason :func:`~scripts.sur1.capture.open_run` refuses it later: two contracts in one
    summary is two experiments.
    """
    directory = RunDirectory(root / run_id)
    if not directory.path.exists():
        return Check("output_directory", True, f"{directory.path} is new")
    if not directory.run_file.exists():
        return Check(
            "output_directory",
            False,
            f"{directory.path} exists and holds no run manifest, so it is neither new nor "
            "resumable",
        )
    started = json.loads(directory.run_file.read_text(encoding="utf-8"))
    if contract is not None and started.get("manifest_sha") != contract.identity.manifest_sha:
        return Check(
            "output_directory",
            False,
            f"{run_id} was started against manifest {started.get('manifest_sha')!r} and this "
            f"run pins {contract.identity.manifest_sha!r}",
        )
    if not directory.arm_map_file.exists():
        return Check("output_directory", False, f"{run_id} has no token map and cannot be resumed")
    completed = len(directory.completed_attempts())
    return Check("output_directory", True, f"{run_id} resumes with {completed} attempts captured")


def historical_runs(*, root: Path = RUNS_ROOT) -> Check:
    """Every previously published scored run is byte-identical to what was taken.

    Reads :data:`~scripts.sur1.capture.RUNS_ROOT` rather than the run's own output root: the
    published runs are history and live in the tree, wherever this run happens to be writing.

    A comparative benchmark whose earlier runs can be edited publishes a number about a history
    that no longer exists. Three runs have been taken, none of them conclusive, and each is
    evidence about this harness rather than about the product -- which is exactly why a later
    session correcting the harness is the moment one of them is most likely to be tidied.

    Asked in the preflight rather than only in the test suite because this is the last gate
    before spend, and because a run taken against a rewritten history would be uncheckable
    afterwards.
    """
    moved = []
    for run_id, (expected_files, expected_digest) in sorted(PUBLISHED_RUNS.items()):
        directory = root / run_id
        if not directory.is_dir():
            moved.append(f"{run_id} is missing from the tree")
            continue
        files = sorted(path for path in directory.rglob("*") if path.is_file())
        if len(files) != expected_files:
            moved.append(f"{run_id} holds {len(files)} files rather than {expected_files}")
            continue
        found = _run_digest(directory, files)
        if found != expected_digest:
            moved.append(f"{run_id} hashes to {found[:12]} rather than {expected_digest[:12]}")
    if moved:
        return Check(
            "historical_runs",
            False,
            "a published scored run has been edited: "
            + "; ".join(moved)
            + ". Restore it; never update the pin",
        )
    return Check(
        "historical_runs",
        True,
        f"{len(PUBLISHED_RUNS)} published scored runs are byte-identical to what was taken",
    )


def _run_digest(directory: Path, files: Sequence[Path]) -> str:
    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.relative_to(directory).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes().replace(b"\r\n", b"\n"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def _worker_control(world: object) -> object | None:
    """The thing that puts the durable worker down, if this world holds one."""
    return getattr(world, "worker", None)


def _published_runtime_identity(world: object) -> tuple[Mapping[str, Any] | None, str]:
    """What the worker process says it is configured to do, and why if it said nothing."""
    control = _worker_control(world)
    ask = getattr(control, "runtime_identity", None)
    if not callable(ask):
        return None, "this world's worker control cannot be asked what it is configured for"
    try:
        published = ask()
    except Exception as failure:
        return None, f"the worker could not be asked: {type(failure).__name__}: {failure}"
    if not published:
        return None, (
            "the worker published no runtime identity; a scored run may not proceed on the "
            "assumption that it holds the configuration the contract froze"
        )
    return published, ""


def product_model_identity(*, world: object, contract: Contract | None) -> Check:
    """The product's own semantic boundary is configured for the model the contract froze.

    The constraint is the contract's own: *its semantic boundary calls the same model, with the
    same parameters, as the baseline arm*, applying to all three arms. Nothing asked. All three
    scored runs were driven at ``api``, ``worker`` and ``mcp`` containers carrying no
    ``PP_LLM_PROVIDER``, no ``PP_BEDROCK_*`` and no AWS variable at all, so the product resolved
    the deterministic fake while arm A called Nova. ``run.json`` did record a
    ``model_provider_configured`` flag -- read in the **harness** process, about the wrong
    process, gated on by nothing. See ``docs/sur1-v3-forensic-audit.md`` section 3.

    Asked of the process that executes semantic jobs, in the words that process computes from
    its own settings, and compared with the frozen block. A credential is reported as a boolean
    by that process and never read here.
    """
    if contract is None:
        return Check("product_model_identity", False, "the frozen contract did not load")
    published, why = _published_runtime_identity(world)
    if published is None:
        return Check("product_model_identity", False, why)

    configured = contract.model_configuration
    faults = [
        f"{field}: contract {expected!r}, product {published.get(key)!r}"
        for field, key, expected in (
            ("provider", "llm_provider", configured.provider),
            ("model_id", "model_id", configured.model_id),
            ("api", "api", configured.api),
            ("temperature", "temperature", configured.temperature),
        )
        if published.get(key) != expected
    ]
    if not published.get("region"):
        faults.append("no region is named, so where a semantic job would run is unrecorded")
    if published.get("credential_resolves") is not True:
        faults.append(
            "no credential resolves in that process, so a semantic job would fail rather than "
            "reach the model the contract froze"
        )
    if faults:
        return Check("product_model_identity", False, "; ".join(faults))
    return Check(
        "product_model_identity",
        True,
        f"the worker calls {published['model_id']} at temperature {published['temperature']} "
        f"in {published['region']}, and a credential resolves there",
    )


def demo_provisioning(*, world: object) -> Check:
    """The scored stack's worker does not open a demo case inside the world it was handed.

    ``provisioning.ensure_demo_case`` runs at every worker start, gated only on
    ``PP_DEMO_SESSION_ENABLED``. The per-attempt worker lifecycle restarts the worker around
    every install, so on all 27 attempts of the third scored run it opened a case in the
    freshly installed world and attested today's raspberry line ``NOT_RECEIVED`` *before the arm
    reported anything*. The arm's identical report then bound to the wrong delivery and every
    raspberry scenario stopped at a clarification. See ``docs/sur1-v3-forensic-audit.md``
    section 2.

    The product behaves as documented and needs no change. What is refused is a **scored stack**
    configured to do it.
    """
    published, why = _published_runtime_identity(world)
    if published is None:
        return Check("demo_provisioning", False, why)
    if published.get("demo_session_enabled") is not False:
        return Check(
            "demo_provisioning",
            False,
            "the worker has PP_DEMO_SESSION_ENABLED on, so ensure_demo_case opens a case inside "
            "every installed world before any arm acts; set it false for a scored stack and "
            "recreate the container",
        )
    return Check(
        "demo_provisioning", True, "the worker opens no demo case inside an installed world"
    )


class _SchemaCheckedReader:
    """A stand-in database that answers from values and refuses a column the product lacks.

    The stand-in this replaced could not fail on a real column name. It matched statements on
    substrings, so ``SELECT id, state FROM commitment_lines`` -- a column that table does not
    have -- was answered as happily as the correct one, and ``world_integrity`` passed while
    every scored attempt would have died at its first install. See
    ``docs/sur1-dr01-hosted-worker-rehearsal.md`` §4.

    So this one parses the statement and checks every table and column it names against the
    product's **own** table definitions, which is what Alembic migrates the database from. A
    statement the schema cannot satisfy raises the same refusal a real database raises, phrased
    the way PostgreSQL phrases it, and the lifecycle fails the check rather than passing it.

    Statements it cannot parse are refused too, rather than waved through: a fingerprint that
    grew a form this cannot check would otherwise go back to being unchecked, quietly.
    """

    url = "preflight://in-memory"

    _SELECT: Final = re.compile(
        r"^SELECT\s+(?P<columns>.+?)\s+FROM\s+(?P<table>[a-z_]+)"
        r"(?:\s+ORDER BY\s+(?P<order>[a-z_,\s]+))?$",
        re.IGNORECASE,
    )

    def __init__(self, installed: str) -> None:
        self.installed = installed
        self.cases = 0
        self.seen: list[str] = []

    def rows(self, source: str, statement: str) -> list[tuple[Any, ...]]:
        from scripts.sur1.bindings.receivers import ReceiverUnreadableError

        self.seen.append(statement)
        match = self._SELECT.match(statement.strip())
        if match is None:
            raise ReceiverUnreadableError(
                source,
                f"this check cannot verify the statement {statement!r} against the product's "
                "schema, so it cannot say the fingerprint would run",
            )
        table = match.group("table")
        columns = [name.strip() for name in match.group("columns").split(",")]
        if match.group("order"):
            columns += [name.strip() for name in match.group("order").split(",")]
        self._require_schema(source, table, columns)

        if table == "fixture_state":
            return [(self.installed, "a-digest")]
        if table == "cases" and "count(*)" in columns:
            return [(self.cases,)]
        if "count(*)" in columns:
            return [(0,)]
        return []

    @staticmethod
    def _require_schema(source: str, table: str, columns: Sequence[str]) -> None:
        """Every name the statement uses, against the declarations Alembic migrates from."""
        import promisepatch.db.models  # noqa: F401  populates the registry
        from promisepatch.db.base import SCHEMA, metadata
        from scripts.sur1.bindings.receivers import ReceiverUnreadableError

        defined = metadata.tables.get(f"{SCHEMA}.{table}")
        if defined is None:
            raise ReceiverUnreadableError(source, f'UndefinedTableError: relation "{table}"')
        for column in columns:
            if column == "count(*)":
                continue
            if column not in defined.columns:
                raise ReceiverUnreadableError(
                    source, f'UndefinedColumnError: column "{column}" does not exist'
                )


def world_integrity(*, world: object) -> Check:
    """The installation lifecycle reads the world again *after* the worker comes back.

    Proved by driving it, not by reading it. A stand-in worker whose own resume writes into the
    world is handed to a real :class:`~scripts.sur1.bindings.lifecycle.InstallationLifecycle`,
    and the lifecycle has to refuse. A lifecycle that verified once, before ``resume``, passes
    every other question in this file and is exactly what drove 27 attempts at a world nobody
    declared.

    **Two halves, because the ordering was never the only thing that could be wrong.** The
    lifecycle is driven in-process against :class:`_SchemaCheckedReader`, which refuses a column
    the product does not declare; and then, when this machine's database answers at all, the
    fingerprint's real statements are executed against it. The first half cannot be skipped and
    catches the statement defect anywhere, including in CI. The second is the live reading
    ``DR01`` had to be driven to get, and it is read-only: four ``SELECT``\\ s, no install, no
    write, nothing created.

    **A database that cannot be reached is not a failure here.** Reachability is
    :func:`receivers`' and :func:`database_identity`' question, and answering it twice in
    different words would make one defect refuse a run for two reasons. What fails is a database
    that *answers* and then refuses one of the fingerprint's statements.
    """
    from scripts.sur1.bindings.lifecycle import InstallationLifecycle
    from scripts.sur1.bindings.setup import PreparationError

    reader = _SchemaCheckedReader("hollow-oak+sur1-preflight")

    class _WritesOnResume:
        binding_kind = "stand-in"

        def state(self) -> str:
            return "running"

        def quiesce(self) -> str:
            return "worker:stopped"

        def resume(self) -> str:
            reader.cases += 1
            return "worker:running"

        def probe(self) -> Any:
            raise NotImplementedError

    lifecycle = InstallationLifecycle(
        worker=_WritesOnResume(),  # type: ignore[arg-type]
        database=reader,  # type: ignore[arg-type]
    )
    try:
        lifecycle.around("preflight", lambda: "installed")
    except PreparationError:
        pass
    except Exception as failure:
        return Check(
            "world_integrity",
            False,
            f"the lifecycle could not be exercised: {type(failure).__name__}: {failure}",
        )
    else:
        return Check(
            "world_integrity",
            False,
            "the lifecycle accepted a world that changed while the worker was coming back; an "
            "attempt driven here would measure a world nobody declared",
        )

    driven = (
        "the lifecycle re-reads the world after the worker returns and refuses an undeclared change"
    )
    executed, why = _fingerprint_against_the_database(world)
    if executed is False:
        return Check("world_integrity", False, f"{driven}, but {why}")
    return Check("world_integrity", True, f"{driven}, and {why}")


def _fingerprint_against_the_database(world: object) -> tuple[bool | None, str]:
    """Run the fingerprint's own statements at this machine's world database, read-only.

    ``None`` is *the database did not answer*, which this check does not own. ``False`` is a
    database that answered and then refused a statement -- which is the defect ``DR01`` found,
    and is fatal to every attempt of a scored run.
    """
    from scripts.sur1.bindings.lifecycle import InstallationLifecycle, UncontrolledWorker
    from scripts.sur1.bindings.receivers import ReceiverUnreadableError

    reader = getattr(world, "database", None)
    if reader is None or not isinstance(getattr(reader, "url", None), str):
        return None, (
            "this world names no database, so the fingerprint's statements were not executed "
            "against one here"
        )
    try:
        reader.rows("WORLD", "SELECT 1")
    except Exception:
        return None, (
            "this machine's world database did not answer, so the fingerprint's statements were "
            "not executed against one here; receivers and database_identity own reachability"
        )
    try:
        InstallationLifecycle(worker=UncontrolledWorker(), database=reader).fingerprint()
    except ReceiverUnreadableError as refused:
        return False, (
            "the world database refuses one of the fingerprint's own statements, so every "
            f"install of a scored run would fail after the world was written: {refused.detail}"
        )
    except Exception as failure:
        return False, (
            "the fingerprint could not be taken of this machine's world database: "
            f"{type(failure).__name__}: {failure}"
        )
    return True, "its statements are the ones this machine's world database actually answers"


def _stack(world: object) -> object | None:
    """The other containers of this stack, if this world can reach them. Reads only."""
    return getattr(world, "stack", None)


def _stack_identities(world: object, services: Sequence[str]) -> dict[str, Mapping[str, Any]]:
    """What each named container says it is, or an empty mapping where it said nothing."""
    stack = _stack(world)
    ask = getattr(stack, "identities", None)
    if not callable(ask):
        return {}
    try:
        answered: Mapping[str, Mapping[str, Any]] = ask(services)
    except Exception:
        return {}
    return {name: dict(published or {}) for name, published in answered.items()}


PARITY_SERVICES: Final = ("api", "mcp")
"""The containers that serve a scored run beside the worker, and must match it.

The ``worker`` service is deliberately not here: a scored run does not have one. Its work is
done by the hosted worker in the harness process, and its container must be down --
:func:`sole_executor` is what requires that.
"""

BUILD_KEYS: Final = ("source_digest", "migration_revision")
"""What *running the same revision* means, as the product computes it about itself."""

CONFIGURATION_KEYS: Final = (
    "llm_provider",
    "demo_session_enabled",
    "explanation_verbalisation",
    "bakery_tz",
    "model_id",
    "region",
    "temperature",
    "api",
)
"""What *configured the same way* means, restricted to the settings that change behaviour.

Addresses are absent on purpose and are compared separately: a container on the compose network
and a process on the host legitimately spell the same database and the same order system
differently, and requiring string equality there would refuse a correct stack while saying
nothing true.
"""


def build_identity(*, world: object) -> Check:
    """Every process serving this run is running the revision the harness is measuring.

    ``backend_build`` asks the API which *migration* its code expects, and says plainly that an
    image stale only in code no migration accompanied reports the same revision and passes. That
    gap is not hypothetical: the first scored run was driven against a container built before the
    code it was measuring, and the local containers have no bind mounts, so they serve the image
    and never the working tree.

    This asks a stronger question of a stronger fact. Each process publishes a ``source_digest``
    it computes over the bytes of the three packages it actually imported, and they all have to
    be one digest -- including the harness's own, because the harness imports the same product
    source and is where arm C's wrapper and the governed fixture load run.
    """
    try:
        from promisepatch.runtime_identity import behavioural_differences, source_digest

        here = source_digest()
    except Exception as failure:
        return Check(
            "build_identity",
            False,
            f"this process could not compute a source digest: {type(failure).__name__}: {failure}",
        )

    published, why = _published_runtime_identity(world)
    if published is None:
        return Check("build_identity", False, why)

    identities: dict[str, Mapping[str, Any]] = {"hosted worker": published}
    identities.update(_stack_identities(world, PARITY_SERVICES))
    missing = [name for name in PARITY_SERVICES if not identities.get(name)]
    if missing:
        return Check(
            "build_identity",
            False,
            f"{', '.join(missing)} published no runtime identity, so whether the stack serving "
            "this run is one revision is unknown; a container built before the code being "
            "measured has served a scored run before",
        )

    mine = {"source_digest": here, "migration_revision": published.get("migration_revision")}
    faults = [
        f"{name} differs from this source tree on " + "; ".join(differences)
        for name, found in sorted(identities.items())
        if (differences := behavioural_differences(mine, found, keys=BUILD_KEYS))
    ]
    if faults:
        return Check("build_identity", False, "; ".join(faults))
    return Check(
        "build_identity",
        True,
        f"the harness, the hosted worker and {', '.join(PARITY_SERVICES)} all run source "
        f"{here[:12]} at migration {published.get('migration_revision')}",
    )


def config_parity(*, world: object, config: BindingConfig) -> Check:
    """Every process serving this run is configured the same way in the ways that matter.

    Two comparisons, because two kinds of value are involved.

    **Settings are compared by equality.** The provider, the model, the Region, the temperature,
    the bakery timezone, demo provisioning and explanation verbalisation mean the same thing in
    every process, so they must be the same value in every process. A split stack -- one process
    on Bedrock and another quietly on the fake -- is the defect that made all three scored runs
    unusable, and nothing asked.

    **Addresses are compared by target.** A container reaches the order system at
    ``order-simulator:8100`` and a host process reaches it on the published port; both are
    correct and they are different strings. So the hosted worker, which is the process that does
    the work, must name exactly the systems the harness's own receivers read -- and the
    containers must name the service whose published port is the one the harness named.
    ``docker/env/host.env`` says ``58100`` while this machine publishes ``48100``; a hosted
    worker configured from it would push every governed amendment into a closed socket, and the
    receivers would read an order system nothing had written to.
    """
    try:
        from promisepatch.runtime_identity import behavioural_differences, database_target
    except Exception as failure:
        return Check(
            "config_parity", False, f"the product could not be imported: {type(failure).__name__}"
        )

    published, why = _published_runtime_identity(world)
    if published is None:
        return Check("config_parity", False, why)

    identities: dict[str, Mapping[str, Any]] = dict(_stack_identities(world, PARITY_SERVICES))
    missing = [name for name in PARITY_SERVICES if not identities.get(name)]
    if missing:
        return Check(
            "config_parity",
            False,
            f"{', '.join(missing)} published no runtime identity, so whether the stack is "
            "configured one way is unknown",
        )

    faults = [
        f"{name} differs from the hosted worker on " + "; ".join(differences)
        for name, found in sorted(identities.items())
        if (differences := behavioural_differences(published, found, keys=CONFIGURATION_KEYS))
    ]

    wanted_database = database_target(config.database_url)
    if not wanted_database:
        faults.append("SUR1_DATABASE_URL names no database this comparison could be made against")
    elif published.get("database_target") != wanted_database:
        faults.append(
            f"the hosted worker writes to {published.get('database_target')!r} and the receivers "
            f"read {wanted_database!r}; the work and the evidence would be two databases"
        )

    wanted_orders = config.order_system_base_url.rstrip("/")
    if published.get("order_system_base_url") != wanted_orders:
        faults.append(
            f"the hosted worker amends orders at {published.get('order_system_base_url')!r} and "
            f"E1 is read from {wanted_orders!r}; a governed amendment would land where nothing "
            "reads it"
        )

    faults.extend(_service_reaches_the_harness_order_system(world, identities, wanted_orders))

    if faults:
        return Check("config_parity", False, "; ".join(faults))
    return Check(
        "config_parity",
        True,
        f"the hosted worker and {', '.join(PARITY_SERVICES)} share one configuration, one "
        f"database ({wanted_database}) and one order system ({wanted_orders})",
    )


ORDER_SIMULATOR_SERVICE: Final = "order-simulator"
ORDER_SIMULATOR_PORT: Final = 8100
"""The compose service the order system runs as, and the port it listens on inside the network."""


def _service_reaches_the_harness_order_system(
    world: object, identities: Mapping[str, Mapping[str, Any]], wanted: str
) -> list[str]:
    """Whether each container's order-system address is the system the harness named.

    Asked of compose's own port map rather than of a convention. A container naming the service
    is correct exactly when that service is published on the port the harness reads E1 from; a
    container naming a loopback address is correct exactly when the port matches. Anything this
    cannot establish is a fault, because an unestablished address is how two systems of record
    came to be in one run.
    """
    stack = _stack(world)
    ask = getattr(stack, "published_port", None)
    if not callable(ask):
        return ["this world cannot ask compose where the order system is published"]
    try:
        port = str(ask(ORDER_SIMULATOR_SERVICE, ORDER_SIMULATOR_PORT))
    except Exception as failure:
        return [f"compose could not be asked for the order system's port: {failure}"]
    if not port:
        return [f"compose publishes no host port for {ORDER_SIMULATOR_SERVICE}"]
    if not wanted.endswith(f":{port}"):
        return [
            f"compose publishes {ORDER_SIMULATOR_SERVICE} on port {port} and the harness reads "
            f"E1 from {wanted!r}; those are two order systems"
        ]
    faults = []
    for name, found in sorted(identities.items()):
        address = str(found.get("order_system_base_url", ""))
        if not address:
            faults.append(f"{name} names no order system")
        elif ORDER_SIMULATOR_SERVICE not in address and not address.endswith(f":{port}"):
            faults.append(
                f"{name} amends orders at {address!r}, which is neither the "
                f"{ORDER_SIMULATOR_SERVICE} service nor the port it is published on"
            )
    return faults


def sole_executor(*, world: object) -> Check:
    """Exactly one worker can execute this run's benchmark work, and it is the hosted one.

    A second durable worker would claim steps and execute them **without** arm C's wrapper. The
    ablation would then cover whichever fraction of an attempt the hosted worker happened to
    claim, arm C would be part arm B, and no artefact would say which part. That is not a weaker
    reading; it is an unreadable one, so it is refused before a run rather than noted in it.

    Three facts, each read rather than assumed: the control can say whether a container worker
    is running and it is not; the hosted worker has an identity that governed writes will carry;
    and the control can read the product's own audit ledger back to prove, after each attempt,
    that nothing else did the work.
    """
    control = _worker_control(world)
    competing = getattr(control, "competing_worker_state", None)
    if not callable(competing):
        return Check(
            "sole_executor",
            False,
            "this world's worker control cannot say whether a second worker could claim this "
            "run's steps, so whether arm C's wrapper covered the whole of an attempt is unknown",
        )
    try:
        state = str(competing())
    except Exception as failure:
        return Check("sole_executor", False, f"{type(failure).__name__}: {failure}")
    if state == RUNNING:
        return Check(
            "sole_executor",
            False,
            "the containerised worker is running beside the hosted one; it would claim "
            "benchmark steps and execute them without arm C's wrapper, so part of every "
            "ablated attempt would silently be arm B. Stop it before a scored run",
        )
    if state not in {STOPPED, ABSENT}:
        return Check(
            "sole_executor",
            False,
            f"the containerised worker is {state!r}, which is neither stopped nor absent; a "
            "scored run may not proceed on an unestablished answer to who executes its work",
        )

    prove = getattr(control, "executed_only_by_the_hosted_worker", None)
    if not callable(prove):
        return Check(
            "sole_executor",
            False,
            "this world's worker control cannot read back which worker did the governed work, "
            "so the sole-executor claim would be an assertion rather than a reading",
        )
    identity = str(getattr(control, "worker_identity", lambda: "")() or "")
    if not identity:
        return Check(
            "sole_executor",
            False,
            "no hosted worker is running, so there is no identity for this run's governed "
            "writes to carry and nothing to compare a foreign one against",
        )
    return Check(
        "sole_executor",
        True,
        f"the containerised worker is {state} and the hosted worker {identity} is the only "
        "process that can execute this run's durable work",
    )


def ablation_reach(*, world: object) -> Check:
    """Arm C's wrapper is reached by the process that decides revalidation.

    Arm C is defined as PromisePatch with revalidation check 5 dropped and nothing else, removed
    by rebinding ``promisepatch.domain.revalidation.revalidate`` at the benchmark boundary. The
    rebinding happens in the harness process. When the durable worker is a separate process, the
    evaluator that decides runs over there and the wrapper is never called: ``diagnostics
    .ablation`` is empty on all nine third-run ablation captures and all eight of the first
    run's, and arm C is arm B by construction. That is unmeasurable rather than merely
    unmeasured, so it refuses the run rather than being noted in it. See
    ``docs/sur1-v3-forensic-audit.md`` section 5 and ``docs/sur1-parity-correction.md``.
    """
    control = _worker_control(world)
    ask = getattr(control, "evaluates_in_process", None)
    if not callable(ask):
        return Check(
            "ablation_reach",
            False,
            "this world's worker control cannot say which process decides revalidation, so "
            "whether arm C differs from arm B at all is unknown",
        )
    try:
        reached = bool(ask())
    except Exception as failure:
        return Check("ablation_reach", False, f"{type(failure).__name__}: {failure}")
    if not reached:
        return Check(
            "ablation_reach",
            False,
            "the durable worker that decides revalidation is a separate process, and arm C's "
            "wrapper is installed in this one; arm C would be arm B and the ablation would "
            "measure nothing. See docs/sur1-parity-correction.md and ADR-0020",
        )

    # Reaching the evaluator is necessary and is not sufficient. The rebinding could reach a
    # module in this process while the work is done by a worker that is not running, or by one
    # the wrapper was installed after. So the same control must also be able to show, from the
    # product's own ledger, which checks actually ran -- and a hosted worker must be up now.
    witnesses = getattr(control, "revalidation_witnesses", None)
    if not callable(witnesses):
        return Check(
            "ablation_reach",
            False,
            "the wrapper reaches the evaluator in this process, but nothing can read the "
            "product's own record of which checks ran; the treatment would be asserted by the "
            "harness about itself rather than proved from the system under test",
        )
    if str(getattr(control, "worker_identity", lambda: "")() or "") == "":
        return Check(
            "ablation_reach",
            False,
            "the wrapper reaches the evaluator in this process and no worker is running in it; "
            "an attempt driven now would decide nothing to ablate",
        )
    return Check(
        "ablation_reach",
        True,
        "the process that decides revalidation is the one arm C's wrapper is installed in, and "
        "the product's own audit rows can be read back to show which checks ran",
    )


def blinding() -> Check:
    """Nothing on the scoring path can reach an arm's name.

    Two structural facts rather than a review. The scorer's bundle has no field an arm label
    could travel in -- ``arm_token`` is opaque and is minted per run -- and the scorer's own
    import surface is parsed, so a module that started importing an arm fails here rather than
    being trusted not to.
    """
    from scripts.score_safe_useful_recovery import EvidenceBundle

    fields = set(EvidenceBundle.__dataclass_fields__)
    leaking = sorted(fields & ARM_FIELD_NAMES)
    if leaking:
        return Check("blinding", False, f"the scorer's bundle carries {leaking}")

    source = Path(__file__).resolve().parent.parent / "score_safe_useful_recovery.py"
    imported = _imports_of(source)
    forbidden = sorted(
        name
        for name in imported
        if any(
            name == banned or name.startswith(f"{banned}.")
            for banned in FORBIDDEN_ON_THE_SCORING_PATH
        )
    )
    if forbidden:
        return Check("blinding", False, f"the scorer imports {forbidden}")

    text = source.read_text(encoding="utf-8")
    named = sorted(arm for arm in ARMS if arm in text)
    if named:
        return Check("blinding", False, f"the scorer names {named}")
    return Check("blinding", True, "no arm name is reachable from a bundle or from the scorer")


def _imports_of(path: Path) -> tuple[str, ...]:
    """Every module one file imports, read from its syntax rather than from its behaviour."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return tuple(sorted(set(found)))


def preflight(
    *,
    kind: str,
    run_id: str,
    model: object,
    world: object,
    surface: object,
    config: BindingConfig,
    classifier: OutboundClassifier = UNDETERMINED,
    scenarios: Sequence[str] = (),
    root: Path = RUNS_ROOT,
) -> PreflightReport:
    """Ask every precondition once and report all the answers, failures included.

    Deliberately not short-circuiting. A caller fixing a run wants every reason it was refused,
    not the first one, and a report that stopped at the first failure would be found out one
    correction at a time.
    """
    identities = frozen_identities()
    contract = Contract.load() if identities.passed else None
    selected = tuple(scenarios) or (contract.scenario_ids if contract is not None else ())

    checks = [
        identities,
        real_bindings(model=model, world=world, surface=surface),
        (
            model_identity(model=model, contract=contract)
            if contract is not None
            else Check("model_identity", False, "the frozen contract did not load")
        ),
        configuration(config),
        workspace_origin(config=config, surface=surface),
        receivers(world=world, surface=surface),
        database_identity(world=world, config=config),
        order_projection(world=world),
        backend_build(surface=surface),
        worker_lifecycle(world=world),
        consent_ingress(world=world),
        classifier_identity(classifier),
        world_programs(selected),
        world_program_freeze(contract),
        world_clock(world=world),
        output_directory(run_id, root=root, contract=contract),
        blinding(),
        event_blinding(),
        historical_runs(),
        channel_transport(world=world, contract=contract),
        report_projection(contract=contract),
        demo_provisioning(world=world),
        world_integrity(world=world),
        product_model_identity(world=world, contract=contract),
        ablation_reach(world=world),
        build_identity(world=world),
        config_parity(world=world, config=config),
        sole_executor(world=world),
    ]
    return PreflightReport(kind=kind, checks=tuple(checks))


def require(report: PreflightReport) -> PreflightReport:
    """Refuse a scored run that failed any check, naming every one of them.

    A development run is reported and permitted: it produces no comparative number, it voids the
    scenarios whose evidence it could not read, and refusing it would make the harness unusable
    during the work that prepares a scored one.
    """
    if report.kind != SCORED or report.passed:
        return report
    raise PreflightRefusedError(
        "a scored SUR-1 run was refused:\n"
        + "\n".join(f"  - {check.name}: {check.detail}" for check in report.failures)
    )


def authorise(report: PreflightReport, fingerprint: RunFingerprint) -> ScoredAuthorisation:
    """Mint the capability a scored run is driven under. The only way one comes into existence.

    Three refusals, and each closes a different way of arriving here without having asked the
    questions. The report has to *be* a :class:`PreflightReport` rather than an object shaped
    like one. It has to name every check in :data:`REQUIRED_CHECKS`, so a report carrying a
    single passing check cannot mint. And every check it names has to have passed, which is
    :func:`require`'s rule restated as a precondition on authority rather than on proceeding.

    The fingerprint is the caller's observation of the run it is about to drive, and the
    capability binds it. Nothing here re-observes it: the recomputation that matters happens in
    :func:`~scripts.sur1.driver.drive`, against the objects the driver was actually handed, which
    is the only place where a substitution between the preflight and the run would show up.
    """
    if not isinstance(report, PreflightReport):
        raise AuthorisationError(
            f"a scored authorisation is minted from a preflight report, not from "
            f"{type(report).__name__}"
        )
    if report.kind != SCORED or fingerprint.kind != SCORED:
        raise AuthorisationError(
            f"only a scored preflight authorises a scored run: report {report.kind!r}, "
            f"fingerprint {fingerprint.kind!r}"
        )
    missing = tuple(name for name in REQUIRED_CHECKS if name not in {c.name for c in report.checks})
    if missing:
        raise AuthorisationError(
            f"this report did not ask every question a scored run is gated on: {list(missing)}"
        )
    if not report.passed:
        raise PreflightRefusedError(
            "a scored SUR-1 run cannot be authorised:\n"
            + "\n".join(f"  - {check.name}: {check.detail}" for check in report.failures)
        )
    return _grant(fingerprint, digest_of(report.as_payload()))


__all__ = [
    "EVENT_MODULES",
    "FORBIDDEN_SCENARIO_FIELDS",
    "REQUIRED_CHECKS",
    "REQUIRED_ORDER_BODY_FIELDS",
    "REQUIRED_ORDER_CAPABILITIES",
    "REQUIRED_ORDER_ENTRY_FIELDS",
    "SCORED",
    "Check",
    "PreflightRefusedError",
    "PreflightReport",
    "authorise",
    "backend_build",
    "blinding",
    "classifier_identity",
    "configuration",
    "consent_ingress",
    "database_identity",
    "event_blinding",
    "frozen_identities",
    "ground_truth_reachable",
    "model_identity",
    "order_projection",
    "output_directory",
    "preflight",
    "real_bindings",
    "receivers",
    "require",
    "worker_lifecycle",
    "world_clock",
    "world_program_freeze",
    "world_programs",
]
