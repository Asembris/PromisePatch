"""One interface, three arms, and the ports that keep the harness out of the world.

The contract's hardest structural requirement is that three systems with no shared internal
vocabulary be driven by one driver and read by one scorer. That works only if the driver's view
of an arm is narrow: hand it a scenario, a budget and a world; get back what the receivers saw.
Everything else -- how many model calls it took, whether it reasoned or looked things up, which
surfaces it went through -- is the arm's business and is never the driver's.

So :class:`ArmAdapter` has one method and no others. An arm cannot write its own capture, cannot
decide its own outcome, cannot read ground truth and cannot widen its own budget, because none
of those is reachable from what it is given.

**The label is on the adapter and never in the result.** ``ArmAdapter.label`` exists so the
driver can mint a token for it and write the token-to-arm map. :class:`ArmAttempt` carries no
label, and the blind bundle the scorer sees has nowhere to put one.

**The world is a port, and the model is a port.** Neither is constructed here. A harness that
built its own Bedrock client would be a harness that could call one by accident, and the two
things this session must not do are call a model and drive a ``SUR-1`` scenario. What is defined
here is the shape the execution session binds: :class:`ScenarioWorld` for the receivers and
:class:`ModelClient` for the one model every arm shares.

**The ceilings reach the arm through the budget and nowhere else.** An arm calls
``budget.authorise_model_call()`` before a provider and ``budget.authorise_tool_call()`` before a
receiver. It does not read a ceiling, does not compare against one and cannot raise one.

**Three terminal signals, and a deliberate absence.** :class:`ArmVoidError` is one of the four
declared void causes -- the world unreachable, the provider silent, a source unreadable, two
receivers disagreeing. :class:`HarnessFailureError` is the harness failing to drive the scenario
at all. Budget exhaustion arrives as ``BudgetExhaustedError`` from the ledger. What is *not* a
signal is a bad answer: an arm that produced no report, a malformed one, or one that did nothing
returns evidence like any other attempt and is scored ``INVALID`` or a nonpass. Letting an arm
raise its way out of a bad result is how attempts disappear.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from scripts.sur1.budget import AttemptBudget
from scripts.sur1.evidence import ReceiverEvidence
from scripts.sur1.frozen import Contract
from scripts.sur1.manifest import AttemptIdentity


class ArmVoidError(RuntimeError):
    """A declared void cause. The attempt could not ask the question at all."""

    def __init__(self, cause: str) -> None:
        super().__init__(cause)
        self.cause = cause


class HarnessFailureError(RuntimeError):
    """The harness could not drive the scenario to any outcome. A nonpass, disclosed by name."""


# ----------------------------------------------------------------------------------- the ports


@dataclass(frozen=True, slots=True)
class ModelReply:
    """One answer from the one model every arm shares."""

    text: str
    tool_calls: tuple[Mapping[str, Any], ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"


@runtime_checkable
class ModelClient(Protocol):
    """The Converse call, as a port.

    Bound by the execution session to ``bedrock-runtime`` at the frozen model id and
    temperature. Nothing in this package constructs one, so nothing in this package can call a
    model by accident.
    """

    def converse(
        self,
        *,
        system: str,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> ModelReply: ...


@runtime_checkable
class ScenarioWorld(Protocol):
    """The order system, the customer channel and the kitchen, as one port.

    The same object serves all three arms, which is what makes "the same world" a fact about the
    harness rather than a claim about three setups. ``prepare`` applies one scenario's stipulated
    facts to a clean fixture; ``collect`` reads the four receivers back; ``tools`` exposes the
    frozen tool surface an agent acts through.
    """

    def prepare(self, scenario: Mapping[str, Any]) -> None:
        """Bring the world to this scenario's stipulated facts, from a clean fixture."""
        ...

    def tools(self) -> Mapping[str, Any]:
        """The eleven frozen actions, by name. No arm has one another arm lacks."""
        ...

    def invoke(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Perform one frozen action and return what the receiver said about it."""
        ...

    def collect(self) -> ReceiverEvidence:
        """Read E1 through E3 back, plus whatever E4 the world was handed."""
        ...

    def settle_durable_work(self) -> str:
        """Wait for the product's durable worker to have nothing outstanding, and say so.

        Asked by arms B and C before their evidence is read, for two reasons that are really
        one. An attempt collected while the worker was mid-step reports a world the arm had not
        finished producing; and arm C's ablation wrapper is installed for the length of the
        arm's call, so a call that returned early would take the wrapper out while the process
        it wraps was still deciding -- ablating a prefix of the work, with nothing in the
        capture to say which part. Both arms ask, identically, so the wait cannot become a
        difference between them. See ADR-0020.

        Returns a sentence for the record and never raises: an attempt whose work did not
        settle is a reading about that attempt, not a reason to end a run.
        """
        ...


@runtime_checkable
class WorkerSurface(Protocol):
    """PromisePatch's ordinary surfaces, as a port, for arms B and C.

    Deliberately the worker's vocabulary and not the harness's: report an exception, answer a
    clarification, confirm a plan that was read out, read the status a worker reads. The
    contract requires arms B and C be driven through the MCP tool surface and the case
    workspace, so the port names those and nothing privileged.
    """

    def report_exception(self, utterance: str) -> Mapping[str, Any]: ...

    def answer_clarification(self, answer: str) -> Mapping[str, Any]: ...

    def confirm_plan(self, plan_id: str) -> Mapping[str, Any]: ...

    def status(self) -> Mapping[str, Any]:
        """The ``promisepatch.domain.status_view`` projection, which is E4 for arms B and C."""
        ...


# ------------------------------------------------------------------------------ the interface


@dataclass(frozen=True, slots=True)
class AttemptRequest:
    """Everything an arm is given, and the whole of it."""

    identity: AttemptIdentity
    scenario: Mapping[str, Any]
    """The frozen scenario, including its stipulated facts. **Not** its ground truth: an arm that
    could read the answer would be measuring itself."""

    contract: Contract
    budget: AttemptBudget
    world: ScenarioWorld

    @property
    def scenario_id(self) -> str:
        return str(self.scenario["id"])

    @property
    def stipulated_facts(self) -> tuple[str, ...]:
        return tuple(str(fact) for fact in self.scenario["stipulated_facts"])


@dataclass(frozen=True, slots=True)
class ArmAttempt:
    """What one arm produced, in receiver terms and with no label on it."""

    evidence: ReceiverEvidence
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    """Arm-specific audit material written into the capture and never into a bundle. Arm C puts
    its ablation log here; the other two put nothing that could identify them in a verdict."""


@runtime_checkable
class ArmAdapter(Protocol):
    """The one interface three arms obey.

    ``label`` is ``BASELINE``, ``PROMISEPATCH`` or ``ABLATION``. It is read exactly once per run,
    by the driver, to write the token map, and never travels with a result.
    """

    label: str

    def run(self, request: AttemptRequest) -> ArmAttempt: ...


def scenario_without_ground_truth(scenario: Mapping[str, Any]) -> dict[str, Any]:
    """The scenario an arm may see: everything except the answer.

    ``ground_truth`` and ``the_point`` are the authored answer and the authored reason for
    asking, and an arm that could read either would be scored against a bound it had been shown.
    The driver strips them before an arm is constructed rather than trusting three arms not to
    look.
    """
    return {
        key: value for key, value in scenario.items() if key not in ("ground_truth", "the_point")
    }
