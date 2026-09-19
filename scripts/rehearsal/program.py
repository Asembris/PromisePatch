"""``DR01``'s world program, and the published world it is checked against before it installs.

The rehearsal reuses the frozen harness's step vocabulary rather than inventing one:
:class:`~scripts.sur1.bindings.programs.AttestCommitmentLine` settles the strawberry line and
posts its receipt, :class:`~scripts.sur1.bindings.programs.ScriptedReply` declares the one
customer answer the world owes, and :func:`~scripts.sur1.bindings.realisation.realise` installs
the canonical graph through the product's own governed fixture load. Everything a scored install
does, ``DR01``'s install does.

**The starting-world check is kept, not dropped.** ``realise`` refuses to install a world whose
digest is not the one a declaration published for that scenario. A rehearsal that skipped the
check would be exercising a path the scored run does not have, so ``DR01`` publishes its own
world digest in ``docs/rehearsals/dr01-world.v1.json`` and the same check runs against that.

**It declares one armed event and no more.** One reply, on one channel, due when the first
outbound ask reaches it. That is the smallest thing that exercises arming, firing, the
observation reduction and the ordering; a rehearsal with a second event would be testing the
event model rather than the pipeline, which ``scripts/tests/test_sur1_world_events.py`` already
does without a database.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from zoneinfo import ZoneInfo

from promise_graph.examples import hollow_oak
from promise_graph.model import ReceivedState
from scripts.rehearsal import ROOT, SCENARIO
from scripts.rehearsal.contract import scenario as rehearsal_scenario
from scripts.sur1.bindings import clock
from scripts.sur1.bindings.programs import AttestCommitmentLine, ScenarioProgram, ScriptedReply
from scripts.sur1.bindings.setup import UnprogrammedScenarioError
from scripts.sur1.bindings.worldsnapshot import digest_of

WORLD_PATH: Final = ROOT / "docs" / "rehearsals" / "dr01-world.v1.json"
"""Where ``DR01``'s starting-world digest is published, so the install check is a real one."""

REPORTED: Final = "today's raspberry delivery didn't arrive"
SCOPE_QUESTION: Final = "the whole delivery, or just the raspberries?"
SCOPE_ANSWER: Final = "just the raspberries -- the strawberries came"
"""The worker's words. The same three sentences every arm reads through ``get_incident``."""

STRAWBERRY_LINE: Final = hollow_oak.VP_TODAY_STRAWBERRY
ARRIVED: Final = Decimal("6.0")

BAKERY_TIMEZONE: Final = ZoneInfo("Africa/Tunis")
"""The calendar the engine buckets a commitment as today or tomorrow against."""

SETTLED_BEFORE: Final = clock.SETTLED_BEFORE
"""How far before the run the world's anchor is placed. The harness's own rule, not a copy.

``DR01`` found the defect this rule closes and stated the rule here first, because what ``SUR-1``
should do about its own clock was not a rehearsal's to decide. `ADR-0019
<../../docs/adr/0019-a-benchmark-world-is-installed-at-a-run-local-anchor.md>`_ decided it, and
decided the same rule, so :mod:`scripts.sur1.bindings.clock` is now the one statement of how a
benchmark world is placed in time and this name points at it. Two copies of that rule, one of
which nobody re-reads, is exactly the drift the rehearsal record kept warning about.
"""


def bakery_anchor(now: datetime) -> datetime:
    """The instant to install ``DR01``'s world from, or a refusal naming why not.

    The hour before the current one. The fixture puts its today delivery at anchor plus sixty
    minutes, so that delivery is between nought and sixty minutes in the past when the run
    starts -- which is what makes the report about a delivery that has already failed to arrive
    -- and every production task except the one the fixture declares ``STARTED`` is still ahead.

    Delegated to :func:`scripts.sur1.bindings.clock.run_anchor`, which asks one question more
    than this used to: that *tomorrow's* delivery has cleared the bakery day as well. A run just
    after midnight passed here and would still have collapsed, because both deliveries then fall
    inside one day and both options carry the same words.
    """
    return clock.run_anchor(now, zone=BAKERY_TIMEZONE)


@dataclass(frozen=True, slots=True)
class RehearsalProgram(ScenarioProgram):
    """``DR01``'s program: a ``SUR-1`` program checked against the rehearsal's own declaration.

    The one overridden member is :meth:`apply`, and it overrides it for one reason: to name the
    published world this install is checked against. Everything else -- the projection, the
    digest, the arming, the governed load -- is the frozen harness's own code path.
    """

    anchor: Any = None
    """The instant this world is installed from. ``None`` is the fixture's own."""

    def apply(self, handles: Any, *, sink: Any = None, anchor: Any = None) -> Any:
        from scripts.sur1.bindings.realisation import realise

        return realise(
            self,
            handles,
            sink=sink,
            published_programs=published(),
            anchor=anchor if anchor is not None else self.anchor,
        )


def program(*, anchor: datetime | None = None) -> RehearsalProgram:
    """``DR01``, built from the rehearsal document's own stipulated facts and consent fact."""
    document = rehearsal_scenario()
    return RehearsalProgram(
        anchor=anchor,
        scenario_id=str(document["id"]),
        slug=str(document["slug"]),
        dimension=str(document["dimension"]),
        steps=(
            AttestCommitmentLine(
                name="the strawberry line is attested received",
                line_id=STRAWBERRY_LINE,
                state=ReceivedState.RECEIVED,
                arrived=ARRIVED,
            ),
        ),
        armed=tuple(
            ScriptedReply(
                name=f"reply {position} on {fact['channel']}",
                trigger=f"an ask reaches {fact['channel']} about {fact['order']}",
                effect="the customer's words arrive on the channel, uninterpreted",
                order=str(fact["order"]),
                channel=str(fact["channel"]),
                text=str(fact["text"]),
                literal=bool(fact.get("literal", False)),
                authorising=bool(fact.get("authorising", False)),
                deliveries=1,
            )
            for position, fact in enumerate(document["consent_facts"], start=1)
        ),
        incident={
            "reported": REPORTED,
            "clarification": {"question": SCOPE_QUESTION, "answer": SCOPE_ANSWER},
        },
        consumed=("stipulated_facts", "consent_facts"),
    )


def registry(*, anchor: datetime | None = None) -> Callable[[str], RehearsalProgram]:
    """The rehearsal's world-program registry, bound to one anchor for the whole run.

    Handed to :class:`~scripts.sur1.bindings.world.LiveScenarioWorld` in place of the frozen
    ``program_for``. A rehearsal world asked to prepare ``C04`` refuses here, which is what keeps
    a rehearsal from reaching a benchmark scenario even by mistake. The anchor is captured in the
    closure rather than read per call, so the retry of an attempt installs the same world.
    """

    def lookup(scenario_id: str) -> RehearsalProgram:
        if scenario_id != SCENARIO:
            raise UnprogrammedScenarioError(
                f"{scenario_id} is not the dress rehearsal scenario. This registry holds "
                f"{SCENARIO} and nothing else; a SUR-1 scenario is prepared by the frozen "
                "registry, under a scored preflight, and never here."
            )
        return program(anchor=anchor)

    return lookup


lookup: Final = registry()
"""The registry at the fixture's own anchor, for a caller that needs no other."""


def declaration() -> dict[str, Any]:
    """What ``DR01``'s starting world is, recomputed from the program right now."""
    built = program()
    return {
        "rehearsal_id": "DR-REHEARSAL",
        "not_a_benchmark": (
            "DR01's starting world. This is a rehearsal declaration and is not part of the "
            "SUR-1 world-program freeze in docs/benchmarks/sur1-world-programs.v1.json."
        ),
        "fixture": "promise_graph.examples.hollow_oak",
        "program_sha": built.identity(),
        "programs": {SCENARIO: {"world_digest": digest_of(built)}},
    }


def published() -> dict[str, Any]:
    """The published ``programs`` block ``realise`` checks an install against."""
    if not WORLD_PATH.is_file():
        raise UnprogrammedScenarioError(
            f"{WORLD_PATH} does not exist; DR01's starting world has not been published and the "
            "install check has nothing to check against"
        )
    loaded: dict[str, Any] = json.loads(WORLD_PATH.read_text(encoding="utf-8"))
    return dict(loaded["programs"])


def differences() -> tuple[str, ...]:
    """Every field on which the published world and the built one disagree."""
    was = json.loads(WORLD_PATH.read_text(encoding="utf-8")) if WORLD_PATH.is_file() else {}
    now = declaration()
    found = []
    for key in ("program_sha", "programs"):
        if was.get(key) != now[key]:
            found.append(f"{key}: published {was.get(key)!r}, now {now[key]!r}")
    return tuple(found)


def write() -> str:
    """Publish ``DR01``'s starting world. Run once, by hand, and never from a run."""
    WORLD_PATH.parent.mkdir(parents=True, exist_ok=True)
    WORLD_PATH.write_text(json.dumps(declaration(), indent=2, sort_keys=True) + "\n", "utf-8")
    return str(WORLD_PATH)


def main() -> int:
    """``uv run python -m scripts.rehearsal.program [--write]``: check, or publish once."""
    import sys

    if "--write" in sys.argv[1:]:
        print(f"wrote {write()}")
        return 0
    found = differences()
    for difference in found:
        print(f"  - {difference}")
    print("DR01's published world matches the program" if not found else "MISMATCH")
    return 1 if found else 0


if __name__ == "__main__":  # pragma: no cover - a command line, exercised through main()
    raise SystemExit(main())


__all__ = [
    "WORLD_PATH",
    "RehearsalProgram",
    "declaration",
    "differences",
    "lookup",
    "main",
    "program",
    "published",
    "write",
]
