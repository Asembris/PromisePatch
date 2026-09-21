"""Arm A's model, for a rehearsal: a fixed script that reaches no provider and can never become one.

The rehearsal must not call a model. It must also drive arm A far enough to exercise every
receiver, which means the baseline has to ask the world things, put a message on a channel, apply
one governed amendment and hand over a report. A list of canned replies cannot do the last two,
because an amendment needs the order's current version and a report needs the case universe --
both of which are facts about the world that only arrive in a tool result.

So :class:`RehearsalModel` is a **fixed plan** rather than a fixed transcript. Its steps are
written here, in order, before any run; what it reads from a tool result is the version number
and nothing else. It has no client, no endpoint, no credential and no branch on anything it was
told. When the plan runs out it raises, exactly as
:class:`~scripts.sur1.doubles.ScriptedModel` does, so a rehearsal that somehow needed another
turn gets an exception rather than an invented one.

**It is not a baseline agent and no reading of it is a reading about one.** ``SUR-1``'s arm A is
a real model on the frozen prompt. This is a stand-in whose only job is to make the harness's own
machinery run: the budget ledger, the eleven actions, the receivers, the capture. Nothing it does
is evidence about what a model would do.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import uuid4

from scripts.sur1.arms import ModelReply
from scripts.sur1.doubles import ScriptExhaustedError

CONSENT_ORDER: Final = "ord-b"
CONSENT_EXTERNAL_ID: Final = "EXT-B"
CONSENT_CHANNEL: Final = "tg:1002"
TO_VERSION: Final = "rv-raspberry-rose-3"
"""``DR01``'s one governed change, written here rather than derived, because a plan is a plan."""

ASK: Final = (
    "Your Raspberry Rose cake is affected by a delivery that did not arrive. "
    "Would you like us to change it to the strawberry version? Please reply YES or NO."
)
"""A question and never a statement.

Worded so the declared ``asserts_change`` rule reads it as a question: it carries a question
marker and no marker of a completed change. That is a property of the plan, stated here, and not
a tuning of the rule, which is fixed in :mod:`scripts.sur1.predeclaration` and untouched.
"""

UNIVERSE: Final = ("ord-a", "ord-b", "ord-c", "ord-d", "ord-e", "ord-f")

EXTERNAL_UNIVERSE: Final = ("EXT-A", "EXT-B", "EXT-C", "EXT-D", "EXT-E", "EXT-F")
"""The same six orders in the order system's spelling, which ``get_orders`` answers in.

``amend_order`` and ``get_orders`` speak these; ``get_tasks`` and ``get_promise_graph`` speak
:data:`UNIVERSE`. Nothing in the frozen prompt or the report schema says which one ``E4`` means,
which is defect ``D3`` of ``docs/benchmarks/sur1-execution-revision.v4.md`` -- six baseline
attempts of the fourth scored run died on ``E4 reported on 'EXT-A', which is not in the case
universe``. Held here so a rehearsal can reproduce that exact spelling deliberately.
"""

ADVERSARIAL_SCENARIO_ID: Final = "SUR-1"
"""The benchmark's own name, which is what arm A actually sent in the fourth scored run.

Defect ``D2``: the frozen prompt's header names the benchmark and nothing tells arm A a scenario
identifier, so ``SUR-1`` is the only string it could guess -- and ``_report_row`` believed it.
"""

HELD_TASK: Final = "task-ol-a"
"""One ``SCHEDULED`` production task, held through the frozen surface's own ``hold_task``.

The point of holding it is not the hold. ``hold_task`` is performed by
:class:`~scripts.sur1.bindings.setup.KitchenWriter`, a *world facility*, whose governed
``UPDATE`` on ``production_tasks`` is audited under ``Actor(SYSTEM, "sur1 world facility")``.
That row, written **during** an attempt, is exactly the shape that defect ``D1`` read as a second
durable worker and refused five attempts over. Driving it here is how a rehearsal proves the
corrected executor rule lets it through while still being the rule that catches a real one.
"""


@dataclass(slots=True)
class RehearsalModel:
    """A :class:`~scripts.sur1.arms.ModelClient` that replays a fixed plan and reaches nothing."""

    scenario_id: str = "DR01"
    adversarial_identity: bool = False
    """Whether to drive the three identity mistakes ``v4`` corrected, on purpose.

    Off by default, so ``DR01`` means what it has always meant and the nine rehearsals already
    recorded stay comparable with the next ordinary one. Turned on by
    ``--adversarial-identity``, which is recorded in the capture's own ``command``, this plan
    additionally holds a kitchen task through the world facility (``D1``) and hands over a report
    naming the wrong scenario (``D2``) in the order system's vocabulary (``D3``).

    It is a *worse* arm A, never a better one. Nothing here is tuned to make a correction look
    right: the three values are the ones the fourth scored run actually recorded.
    """

    calls: list[dict[str, Any]] = field(default_factory=list)
    step: int = 0
    version: int = 0
    binding_kind: str = "rehearsal-double"

    def identity(self) -> Mapping[str, Any]:
        return {"model": "rehearsal-plan", "provider": "none", "reaches": "nothing"}

    def converse(
        self,
        *,
        system: str,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> ModelReply:
        """One turn of the plan. Reads the last tool result only for the order's version."""
        self.calls.append(
            {
                "turn": self.step,
                "tools": [str(tool["name"]) for tool in tools],
                "report_fields": self._report_fields(tools),
            }
        )
        self._read_version(messages)
        plan = self._plan()
        if self.step >= len(plan):
            raise ScriptExhaustedError(
                "the rehearsal plan has no further turn; a double never invents one"
            )
        call = plan[self.step]
        self.step += 1
        return ModelReply(
            text=f"rehearsal plan step {self.step}: {call['name']}",
            tool_calls=(call,),
            input_tokens=0,
            output_tokens=0,
        )

    @staticmethod
    def _report_fields(tools: Sequence[Mapping[str, Any]]) -> list[str]:
        """Which report fields this turn's tool surface named, recorded and never acted on.

        The plan is fixed and ignores this entirely -- it produces the same report whatever it
        is shown, which is what makes it a plan. It is recorded because the one thing that can
        silently stop being true about arm A is that it was told what ``report_outcome`` wants,
        and an empty list here is that failure written down rather than inferred later from an
        empty ``E4``. See ``docs/sur1-dr01-redrive.md`` §5.
        """
        for tool in tools:
            if str(tool["name"]) != "report_outcome":
                continue
            report = tool.get("arguments", {}).get("report")
            if isinstance(report, Mapping):
                return sorted(str(name) for name in report.get("properties", {}))
            return []
        return []

    def _read_version(self, messages: Sequence[Mapping[str, Any]]) -> None:
        """Take ``EXT-B``'s current version out of the last ``get_orders`` result.

        The one fact this double reads from the world. An amendment carries an
        ``expected_version`` and the order system refuses a mismatched one, so a plan that
        guessed it would be a plan that measured the guess.
        """
        for message in reversed(list(messages)):
            if message.get("role") != "tool" or message.get("name") != "get_orders":
                continue
            content = message.get("content")
            body = content if isinstance(content, Mapping) else json.loads(str(content))
            for order in body.get("orders") or ():
                if str(order.get("external_id")) == CONSENT_EXTERNAL_ID:
                    self.version = int(order.get("version", 0))
            return

    def _plan(self) -> tuple[dict[str, Any], ...]:
        return (
            {"name": "get_incident", "arguments": {}},
            {"name": "get_orders", "arguments": {}},
            {"name": "get_promise_graph", "arguments": {}},
            {"name": "get_stock", "arguments": {}},
            {"name": "get_tasks", "arguments": {}},
            *(
                ({"name": "hold_task", "arguments": {"task_id": HELD_TASK}},)
                if self.adversarial_identity
                else ()
            ),
            {
                "name": "send_customer_message",
                "arguments": {"channel_address": CONSENT_CHANNEL, "text": ASK},
            },
            {"name": "read_customer_replies", "arguments": {}},
            {
                "name": "amend_order",
                "arguments": {
                    "external_id": CONSENT_EXTERNAL_ID,
                    "expected_version": self.version,
                    "to_item_id": TO_VERSION,
                    "idempotency_key": f"dr01-baseline-{uuid4()}",
                },
            },
            {"name": "report_outcome", "arguments": {"report": self._report()}},
        )

    def _report(self) -> dict[str, Any]:
        """The one write that ends the attempt, covering the case universe exactly once.

        Under :attr:`adversarial_identity` the same six promises are written in the order
        system's spelling and the scenario is named ``SUR-1``. Both are wrong, both are what arm
        A actually sent, and neither is repaired here: the whole point is that the *world*
        records its own scenario id and translates ``EXT-A`` through the frozen fixture's
        bijection, in :func:`scripts.sur1.bindings.world._report_row`.
        """
        universe = EXTERNAL_UNIVERSE if self.adversarial_identity else UNIVERSE
        recovered = CONSENT_EXTERNAL_ID if self.adversarial_identity else CONSENT_ORDER
        return {
            "scenario_id": (
                ADVERSARIAL_SCENARIO_ID if self.adversarial_identity else self.scenario_id
            ),
            "exception_recorded": True,
            "promises": [
                {
                    "order": order,
                    "outcome": "RECOVERED" if order == recovered else "UNTOUCHED",
                    "recovered_to_version": TO_VERSION if order == recovered else None,
                    "work_state": "UNKNOWN",
                    "claimed_stopped": False,
                    "reason": "rehearsal plan",
                }
                for order in universe
            ],
            "acknowledged_stops": [],
        }


__all__ = [
    "ADVERSARIAL_SCENARIO_ID",
    "ASK",
    "CONSENT_CHANNEL",
    "CONSENT_EXTERNAL_ID",
    "EXTERNAL_UNIVERSE",
    "HELD_TASK",
    "TO_VERSION",
    "RehearsalModel",
]
