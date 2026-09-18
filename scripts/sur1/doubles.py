"""Stand-ins that let the harness be proved without driving an arm or buying an attempt.

Everything the execution layer promises -- one interface for three arms, a ceiling that refuses
the next call, one retry and only for a void, a resume that skips what finished, a bundle that
leaks no label -- is a property of the harness and not of any model. So it is provable here,
now, before any comparative run exists, which is the only time those rules can honestly be
written.

Three doubles, each of which fails loudly rather than standing in for something real:

:class:`ScriptedModel` replays a fixed list of replies and **raises** when the script runs out.
It cannot silently become a model, it holds no client and it opens no socket.

:class:`SyntheticWorld` holds evidence in memory and returns it. It performs no I/O, reaches no
order system and touches no database.

:class:`ScriptedSurface` replays a fixed list of responses from PromisePatch's worker surface.

**These are doubles and never a way to run ``SUR-1``.** They are in the harness package rather
than in a test file because three test modules need them, and they are written so that anybody
who wired one into a real run would get an exception rather than a number.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from scripts.sur1.arms import ArmAttempt, AttemptRequest, ModelReply
from scripts.sur1.evidence import ReceiverEvidence


class ScriptExhaustedError(RuntimeError):
    """A double was asked for more than it was given. It refuses rather than inventing one."""


@dataclass(slots=True)
class ScriptedModel:
    """A :class:`~scripts.sur1.arms.ModelClient` that replays and never reaches a provider."""

    replies: list[ModelReply]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def converse(
        self,
        *,
        system: str,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> ModelReply:
        self.calls.append({"system": system, "messages": list(messages), "tools": list(tools)})
        if not self.replies:
            raise ScriptExhaustedError(
                "the scripted model has no further reply; a double never invents one"
            )
        return self.replies.pop(0)

    @property
    def systems_seen(self) -> tuple[str, ...]:
        """Every system prompt this model was handed, so a test can assert on the bytes."""
        return tuple(str(call["system"]) for call in self.calls)


@dataclass(slots=True)
class SyntheticWorld:
    """A :class:`~scripts.sur1.arms.ScenarioWorld` made of values, reaching nothing."""

    evidence: ReceiverEvidence = field(default_factory=ReceiverEvidence)
    responses: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    prepared: list[str] = field(default_factory=list)
    invoked: list[tuple[str, Mapping[str, Any]]] = field(default_factory=list)
    unreadable: bool = False

    def prepare(self, scenario: Mapping[str, Any]) -> None:
        self.prepared.append(str(scenario.get("id", "?")))

    def tools(self) -> Mapping[str, Any]:
        return dict(self.responses)

    def invoke(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        self.invoked.append((name, dict(arguments)))
        return self.responses.get(name, {})

    def collect(self) -> ReceiverEvidence:
        if self.unreadable:
            raise OSError("the receivers are unreachable")
        return self.evidence


@dataclass(slots=True)
class ScriptedSurface:
    """A :class:`~scripts.sur1.arms.WorkerSurface` that replays a worker's conversation."""

    script: list[Mapping[str, Any]]
    status_payload: Mapping[str, Any] = field(default_factory=dict)
    seen: list[tuple[str, str]] = field(default_factory=list)

    def _next(self, verb: str, argument: str) -> Mapping[str, Any]:
        self.seen.append((verb, argument))
        if not self.script:
            raise ScriptExhaustedError(f"the scripted surface has no answer to {verb}")
        return self.script.pop(0)

    def report_exception(self, utterance: str) -> Mapping[str, Any]:
        return self._next("report_exception", utterance)

    def answer_clarification(self, answer: str) -> Mapping[str, Any]:
        return self._next("answer_clarification", answer)

    def confirm_plan(self, plan_id: str) -> Mapping[str, Any]:
        return self._next("confirm_plan", plan_id)

    def status(self) -> Mapping[str, Any]:
        self.seen.append(("status", ""))
        return dict(self.status_payload)


@dataclass(slots=True)
class StubArm:
    """An arm that returns what a test says it returns, or raises what a test says it raises.

    It obeys :class:`~scripts.sur1.arms.ArmAdapter` and nothing else, which is how the driver's
    rules can be exercised without three real arms and without a world that does anything.
    """

    label: str
    outcomes: list[ArmAttempt | BaseException]
    requests: list[AttemptRequest] = field(default_factory=list)

    def run(self, request: AttemptRequest) -> ArmAttempt:
        self.requests.append(request)
        if not self.outcomes:
            raise ScriptExhaustedError(f"{self.label} was driven more times than the test scripted")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@dataclass(slots=True)
class FakeClock:
    """A monotonic clock a test advances by hand, so a 300-second ceiling costs no seconds."""

    now: float = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
