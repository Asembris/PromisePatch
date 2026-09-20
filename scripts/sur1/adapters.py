"""The three arms, behind one interface, differing only where the contract says they differ.

Arm A is a tool-using agent on the one frozen model. Arms B and C are PromisePatch driven
through the surfaces a worker uses. C is B with revalidation check 5 dropped from the outcome
derivation and nothing else changed. Everything else -- the world, the budget, the evidence
collection, the capture, the scoring -- is the driver's and is identical for all three.

**Arm A gets the frozen prompt and the whole of it.** :class:`BaselineArm` hands the model
``docs/benchmarks/baseline-agent-prompt.v1.md`` verbatim, as the bytes on disk, after
:class:`~scripts.sur1.frozen.Contract` has asserted the published hash. It is not summarised,
not excerpted and not supplemented. Cutting the file down to its "System instruction (verbatim)"
section would be a judgement this harness is not entitled to make: choosing where to cut is
choosing what the baseline is, and a benchmark whose baseline is shaped by the winner's authors
is worth exactly as much as that shaping. So the cut is not made.

One thing is structurally required and is therefore declared rather than hidden.
:data:`KICKOFF` is the first user turn, because the Converse API needs one. It is the same three
characters for all nine scenarios, it carries no scenario content, and the agent learns what
happened by calling ``get_incident`` like every other fact it has.

**Arm A's tool schemas are the harness's, and the contract's tool surface is not.** Which actions
exist is frozen; how an agent is told to call one is not, because arms B and C do not call one at
all. The names and the descriptions come straight out of the contract's ``tool_surface`` block --
"the descriptions here are the descriptions the model is given" -- and only the argument shapes
are written here.

**Arms B and C use ordinary surfaces.** :class:`PromisePatchArm` holds a
:class:`~scripts.sur1.arms.WorkerSurface`, which is the MCP tool surface and the case workspace:
report an exception, answer a clarification, confirm a plan that was read out, read the status a
worker reads. There is no benchmark-only read, no privileged write, and nothing that reaches a
row the product would not show a person. Its E4 is the status projection, which the contract
names as the source, and its incident text is the same ``get_incident`` payload arm A works from.

**Arm C is arm B plus one context manager.** :class:`AblationArm` composes rather than
subclasses, so there is exactly one implementation of "drive PromisePatch" and the ablation
cannot drift into being a second one. Its ablation log goes into the attempt's diagnostics,
which are captured and are never an input to a verdict.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from scripts.sur1.ablation import ablation
from scripts.sur1.arms import (
    ArmAdapter,
    ArmAttempt,
    AttemptRequest,
    HarnessFailureError,
    ModelClient,
    WorkerSurface,
)
from scripts.sur1.bindings.bedrock import JSON_TYPES
from scripts.sur1.evidence import ReceiverEvidence
from scripts.sur1.frozen import Contract

KICKOFF: Final = "Begin."
"""The first user turn. Structurally required by the API, identical for every scenario, and
carrying no fact about any of them. The incident arrives through ``get_incident``."""

REPORT_TOOL: Final = "report_outcome"
"""The one write that ends an attempt. Every arm produces exactly one."""

REPORTED: Final = "reported"
CLARIFICATION: Final = "clarification"
ANSWER: Final = "answer"
"""The three field names ``get_incident`` answers with, read here and written by one place.

A world program builds the incident -- see ``programs._incident`` -- and these arms read it.
There is exactly one producer and these are its field names, so they are named as constants
rather than spelled inline twice. An arm that read a field the programs do not write would raise
``HarnessFailureError`` on every scenario, which is not a reading about that arm.
"""

ARGUMENTS: Final[dict[str, dict[str, Any]]] = {
    "get_incident": {},
    "get_orders": {},
    "get_promise_graph": {},
    "get_stock": {},
    "get_tasks": {},
    "read_customer_replies": {},
    "amend_order": {
        "external_id": "string",
        "expected_version": "integer",
        "to_item_id": "string",
        "idempotency_key": "string",
    },
    "send_customer_message": {"channel_address": "string", "text": "string"},
    "hold_task": {"task_id": "string"},
    "release_task": {"task_id": "string"},
    REPORT_TOOL: {"report": "object, the frozen RunReport schema"},
}
"""The argument shape of each frozen action.

Not frozen by the contract, because arms B and C never see one. Written here so that the one
arm that does see them sees the same set on every scenario and on every run.
"""


ARRAY_MEMBER: Final = "[]."
"""How the frozen ``run_report_schema`` spells one entry of an array field, ``promises[].order``."""

ONE_OF: Final = "one of "
STRING_OR_NULL: Final = "string or null"
FREE_TEXT: Final = "free text"
AT_MOST: Final = "at most "


class ReportSchemaError(RuntimeError):
    """A frozen ``run_report_schema`` field shape this reader cannot turn into a JSON schema."""


def run_report_schema(contract: Contract) -> dict[str, Any]:
    """The frozen ``RunReport``, as the JSON schema the one arm that sees a schema is given.

    **Why this exists.** ``report_outcome`` was published to Converse as a bare
    ``{"type": "object"}`` with no properties, and the frozen prompt names the outcomes without
    naming a single field. So nothing anywhere told arm A that the array is called ``promises``,
    that an entry names an ``order``, or that there is a ``work_state`` at all -- and ``E4`` came
    back with no promises on 18 of 18 baseline attempts across two scored runs. See
    ``docs/sur1-v3-forensic-audit.md`` §5, F6.

    **Derived, never restated.** Every property, every enumeration and every description is read
    out of ``run_report_schema.fields`` in the frozen manifest after its hash has been asserted.
    A schema written out here would be a second copy of a frozen document, and the first time the
    two disagreed arm A would be answering a question the scorer is not asking.

    **It adds no field the other arms cannot produce.** Only the frozen fields are published.
    ``acknowledged_stops`` is read by the harness and scored, and is *not* in the frozen field
    list -- the predeclaration records it as empty for arms B and C -- so publishing it here
    would hand arm A a field its comparators structurally cannot fill.

    **A shape this reader cannot read is refused rather than defaulted**, because a field
    published as the wrong type is a question arm A would answer wrongly through no fault of
    its own.
    """
    fields: Mapping[str, Any] = contract.document["run_report_schema"]["fields"]
    top: dict[str, Any] = {}
    members: dict[str, dict[str, dict[str, Any]]] = {}
    for name, shape in fields.items():
        prefix, marker, member = str(name).partition(ARRAY_MEMBER)
        if marker:
            members.setdefault(prefix, {})[member] = _property(str(name), str(shape))
        else:
            top[str(name)] = _property(str(name), str(shape))

    for array, properties in members.items():
        if array not in top:
            raise ReportSchemaError(f"{array}[] has entries and {array} is not a declared field")
        if top[array].get("type") != "array":
            raise ReportSchemaError(f"{array} carries entries and is declared {top[array]!r}")
        top[array]["items"] = {
            "type": "object",
            "properties": properties,
            "required": sorted(properties),
        }

    unshaped = sorted(
        name for name, shape in top.items() if shape.get("type") == "array" and "items" not in shape
    )
    if unshaped:
        raise ReportSchemaError(
            f"{', '.join(unshaped)} is an array whose entries nothing describes; an arm told only "
            "that a field is a list is told nothing about what belongs in it"
        )

    return {
        "type": "object",
        "properties": top,
        "required": sorted(top),
    }


def _property(name: str, shape: str) -> dict[str, Any]:
    """One frozen field shape, as one JSON-schema property carrying the frozen words verbatim.

    The manifest writes a shape as prose because it is documentation first. Four forms appear in
    it and each is read literally: ``one of A, B, C`` is an enumeration, ``string or null`` is a
    nullable string, ``free text, at most N characters`` is a bounded string, and anything else
    names its JSON type in the word before the comma.
    """
    described = {"description": shape}
    body = shape.strip()
    if body.startswith(ONE_OF):
        options = [word.strip() for word in body[len(ONE_OF) :].split(",") if word.strip()]
        if not options:
            raise ReportSchemaError(f"{name} is declared {shape!r} and enumerates nothing")
        return {"type": "string", "enum": options, **described}
    if body.startswith(STRING_OR_NULL):
        return {"type": ["string", "null"], **described}
    if body.startswith(FREE_TEXT):
        bounded: dict[str, Any] = {"type": "string", **described}
        _, marker, rest = body.partition(AT_MOST)
        if marker:
            digits = rest.split()[0]
            if not digits.isdigit():
                raise ReportSchemaError(f"{name} bounds its length with {digits!r}")
            bounded["maxLength"] = int(digits)
        return bounded
    word = body.split(",")[0].strip()
    if word not in JSON_TYPES:
        raise ReportSchemaError(f"{name} is declared {shape!r}, which names no JSON type")
    return {"type": JSON_TYPES[word], **described}


TEXT_CEILING: Final = 400
WIDTH_CEILING: Final = 32
DEPTH_CEILING: Final = 6
"""How much of one tool argument a capture keeps. Bounded so a diagnostic cannot become a blob.

The depth is six because the deepest thing a frozen action carries is a ``report_outcome``
argument -- arguments, report, ``promises``, one entry, one field -- which is five, and a
ceiling that cut the field a report is diagnosed by would defeat the point of keeping it.
"""


def sanitised(value: Any, *, depth: int = 0) -> Any:
    """One tool argument, as the bounded structure a capture keeps beside the attempt.

    **Diagnostic, never scored.** :class:`~scripts.sur1.arms.ArmAttempt` diagnostics are written
    into the capture and are structurally unreachable from an evidence bundle, which is what lets
    an arm-identifying record like this one exist at all. Arm C's ablation log already lives
    there; arm A's tool calls did not, and the consequence was that the report mechanism behind
    18 empty ``E4`` rows could not be shown from the artefacts at all -- only guessed at. See
    ``docs/sur1-v3-forensic-audit.md`` §5, F6.

    **Bounded rather than complete.** The structure is kept, because the structure is the thing
    a later reader has to see: which fields arm A sent and which it did not. Strings are cut at
    :data:`TEXT_CEILING`, collections at :data:`WIDTH_CEILING` and nesting at
    :data:`DEPTH_CEILING`, so one long message cannot turn a capture into a transcript dump.

    Nothing here reads a value for meaning. A cut is marked in the text rather than done
    silently, so a reader can tell a short field from a truncated one.
    """
    if depth >= DEPTH_CEILING:
        return "[... nested past the diagnostic depth ceiling]"
    if isinstance(value, Mapping):
        kept = sorted(value)[:WIDTH_CEILING]
        body = {str(key): sanitised(value[key], depth=depth + 1) for key in kept}
        if len(value) > len(kept):
            body["..."] = f"[{len(value) - len(kept)} more keys]"
        return body
    if isinstance(value, str):
        return value if len(value) <= TEXT_CEILING else f"{value[:TEXT_CEILING]}[... cut]"
    if isinstance(value, list | tuple):
        kept_items = [sanitised(item, depth=depth + 1) for item in value[:WIDTH_CEILING]]
        if len(value) > WIDTH_CEILING:
            kept_items.append(f"[{len(value) - WIDTH_CEILING} more entries]")
        return kept_items
    if isinstance(value, bool | int | float) or value is None:
        return value
    return sanitised(str(value), depth=depth)


def clarification_answer(incident: Mapping[str, Any]) -> str:
    """The answer the worker gave, or nothing, from the shape a world program writes.

    ``clarification`` is ``None`` where the report was not ambiguous and is otherwise the
    question and the answer together. Only the answer is said back: the question is the
    product's own to ask, and repeating it to a clarification endpoint would be answering with
    a question.
    """
    block = incident.get(CLARIFICATION)
    if not isinstance(block, Mapping):
        return ""
    return str(block.get(ANSWER, ""))


def tool_specifications(request: AttemptRequest) -> tuple[Mapping[str, Any], ...]:
    """The eleven actions, named and described exactly as the contract describes them.

    The one argument that is a structure rather than a scalar -- ``report_outcome``'s report --
    carries the frozen ``RunReport`` schema itself, derived by :func:`run_report_schema`, so the
    arm that has to produce it can see which fields it has.
    """
    surface = request.contract.document["tool_surface"]
    report_schema = run_report_schema(request.contract)
    specifications = []
    for tool in (*surface["reads"], *surface["writes"]):
        name = str(tool["name"])
        arguments: dict[str, Any] = dict(ARGUMENTS[name])
        if name == REPORT_TOOL:
            arguments["report"] = report_schema
        specifications.append(
            {
                "name": name,
                "description": str(tool.get("returns") or tool.get("contract") or ""),
                "arguments": arguments,
            }
        )
    return tuple(specifications)


@dataclass(slots=True)
class BaselineArm:
    """Arm A: a competent tool-using agent on the one frozen model.

    It is denied PromisePatch's private deterministic machinery and nothing else. Its loop is
    the ordinary one -- ask, act, ask again -- bounded by the shared ledger rather than by any
    number this class holds.
    """

    model: ModelClient
    label: str = "BASELINE"

    def run(self, request: AttemptRequest) -> ArmAttempt:
        system = request.contract.baseline_prompt()
        tools = tool_specifications(request)
        messages: list[dict[str, Any]] = [{"role": "user", "content": KICKOFF}]
        calls: list[Mapping[str, Any]] = []

        while True:
            request.budget.authorise_model_call()
            reply = self.model.converse(system=system, messages=messages, tools=tools)
            request.budget.record_tokens(
                input_tokens=reply.input_tokens, output_tokens=reply.output_tokens
            )
            messages.append({"role": "assistant", "content": reply.text, "tools": reply.tool_calls})

            if not reply.tool_calls:
                # Nothing was asked of the world. The model-call ceiling is what ends this, and
                # ending it here instead would be the harness deciding the attempt was over.
                messages.append({"role": "user", "content": KICKOFF})
                continue

            for call in reply.tool_calls:
                name = str(call["name"])
                arguments = dict(call.get("arguments", {}))
                calls.append({"name": name, "arguments": sanitised(arguments)})
                request.budget.authorise_tool_call()
                result = request.world.invoke(name, arguments)
                messages.append({"role": "tool", "name": name, "content": result})
                if name == REPORT_TOOL:
                    return ArmAttempt(
                        evidence=request.world.collect(),
                        diagnostics={"tool_calls": tuple(calls)},
                    )


@dataclass(slots=True)
class PromisePatchArm:
    """Arms B and C: the full system, driven through the surfaces a worker uses.

    The loop is a worker's: say what happened, answer the one thing you are asked, confirm the
    plan that was read back to you, then read the status. Every step is a call the product
    already exposes; none of them is a shortcut opened for this measurement.
    """

    surface: WorkerSurface
    label: str = "PROMISEPATCH"
    settled: str = ""
    """What the last attempt's wait for durable quiescence reported. Diagnostic, never scored.

    Written by :meth:`drive_through_surface` and read by :class:`AblationArm`, which is the one
    caller that needs to say in its capture whether the wrapper was still installed when the
    work finished. One field on the one object both arms share, so neither can record a
    different answer than the other would have.
    """

    def run(self, request: AttemptRequest) -> ArmAttempt:
        evidence = self.drive_through_surface(request)
        return ArmAttempt(evidence=evidence, diagnostics={"settled": self.settled})

    def drive_through_surface(self, request: AttemptRequest) -> ReceiverEvidence:
        """A worker's loop: say what happened, answer the one thing you are asked, confirm.

        **The one thing you are asked, once.** The worker has exactly one answer -- the one they
        already gave, which arrives with the incident -- and a product that asks again has not
        accepted it. Saying the same words a second time is not a worker answering; it is a
        client hammering, and the product's own answer ceiling turns a repeated answer into
        ``NEEDS_HUMAN_INTERPRETATION``. So the answer is given once and a second request ends the
        loop, with the status read as it stands. The attempt is scored on what the receivers saw,
        which is the honest reading of a case the product could not resolve.
        """
        incident = self._incident(request)
        request.budget.authorise_tool_call()
        response: Mapping[str, Any] = self.surface.report_exception(str(incident[REPORTED]))

        answered = False
        confirmed: set[str] = set()
        while True:
            request.budget.checkpoint()
            needs = response.get("needs")
            if needs == "clarification" and not answered:
                answered = True
                request.budget.authorise_tool_call()
                response = self.surface.answer_clarification(clarification_answer(incident))
            elif needs == "confirmation" and str(response["plan_id"]) not in confirmed:
                # A plan id is confirmed once. A product that reads the same plan back after it
                # was confirmed is not asking for a second yes, and sending one would be spending
                # an approval twice on one agreement.
                plan_id = str(response["plan_id"])
                confirmed.add(plan_id)
                request.budget.authorise_tool_call()
                response = self.surface.confirm_plan(plan_id)
            else:
                break

        request.budget.authorise_tool_call()
        self.surface.status()
        # Let the product's durable worker finish before anything is read back. Two reasons,
        # and they are the same reason: an attempt collected mid-step reports a world the arm
        # had not finished producing, and arm C's wrapper is installed around *this call*, so
        # returning while the deciding process was still deciding would ablate a prefix of the
        # work with nothing in the capture to say which part. Arms B and C both wait, here, in
        # the one method both of them run. See ADR-0020.
        self.settled = request.world.settle_durable_work()
        return request.world.collect()

    def _incident(self, request: AttemptRequest) -> Mapping[str, Any]:
        """The same words arm A reads, from the same read, so the facts are identical."""
        request.budget.authorise_tool_call()
        incident = request.world.invoke("get_incident", {})
        if not str(incident.get(REPORTED, "")).strip():
            raise HarnessFailureError(
                f"get_incident returned no {REPORTED!r} for {request.scenario_id}; no arm can be "
                "driven from an incident nobody reported"
            )
        return incident


@dataclass(slots=True)
class AblationArm:
    """Arm C: arm B, with revalidation check 5 dropped from the outcome derivation.

    Composition rather than inheritance, so that "drive PromisePatch" has one implementation
    and the ablated arm cannot quietly become a second one.
    """

    inner: PromisePatchArm
    label: str = "ABLATION"

    def run(self, request: AttemptRequest) -> ArmAttempt:
        # The wrapper spans the wait for quiescence as well as the surface loop, because
        # ``drive_through_surface`` ends by waiting for the durable worker. Taking the wrapper
        # out before that would ablate only the part of the attempt that happened to finish
        # inside the arm's own call. See ADR-0020.
        with ablation() as log:
            evidence = self.inner.drive_through_surface(request)
        return ArmAttempt(
            evidence=evidence,
            diagnostics={
                "ablation": log.as_payload(),
                "ablated_check": 5,
                "settled": self.inner.settled,
            },
        )


def three_arms(*, model: ModelClient, surface: WorkerSurface) -> tuple[ArmAdapter, ...]:
    """The three arms in the order the contract names them, built from two bindings."""
    promisepatch = PromisePatchArm(surface=surface)
    return (BaselineArm(model=model), promisepatch, AblationArm(inner=promisepatch))
