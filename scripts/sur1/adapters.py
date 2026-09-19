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
from scripts.sur1.evidence import ReceiverEvidence

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
    """The eleven actions, named and described exactly as the contract describes them."""
    surface = request.contract.document["tool_surface"]
    specifications = []
    for tool in (*surface["reads"], *surface["writes"]):
        name = str(tool["name"])
        specifications.append(
            {
                "name": name,
                "description": str(tool.get("returns") or tool.get("contract") or ""),
                "arguments": ARGUMENTS[name],
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
                request.budget.authorise_tool_call()
                result = request.world.invoke(name, arguments)
                messages.append({"role": "tool", "name": name, "content": result})
                if name == REPORT_TOOL:
                    return ArmAttempt(evidence=request.world.collect())


@dataclass(slots=True)
class PromisePatchArm:
    """Arms B and C: the full system, driven through the surfaces a worker uses.

    The loop is a worker's: say what happened, answer the one thing you are asked, confirm the
    plan that was read back to you, then read the status. Every step is a call the product
    already exposes; none of them is a shortcut opened for this measurement.
    """

    surface: WorkerSurface
    label: str = "PROMISEPATCH"

    def run(self, request: AttemptRequest) -> ArmAttempt:
        return ArmAttempt(evidence=self.drive_through_surface(request))

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
        with ablation() as log:
            evidence = self.inner.drive_through_surface(request)
        return ArmAttempt(
            evidence=evidence,
            diagnostics={"ablation": log.as_payload(), "ablated_check": 5},
        )


def three_arms(*, model: ModelClient, surface: WorkerSurface) -> tuple[ArmAdapter, ...]:
    """The three arms in the order the contract names them, built from two bindings."""
    promisepatch = PromisePatchArm(surface=surface)
    return (BaselineArm(model=model), promisepatch, AblationArm(inner=promisepatch))
