"""The world-program freeze: what the nine programs are, hashed, in a document beside the code.

The frozen ``SUR-1`` contract was published before this work existed and may not be edited to
carry it. So the program set is its own declaration, with its own version and its own hashes,
and the two are joined by the contract's own manifest hash rather than by an edit to it.

**Three identities, because three different things can move.**

``program_set_sha`` is the hash of what the nine programs declare themselves to be: their steps,
their armed events, their incidents, the frozen fields each one consumed. A step reworded, an
order changed, a quantity retyped -- each moves it.

``world_digests`` is one hash per scenario of the *starting world* those steps produce. Two
programs can differ in how they are written and produce the same world; two that produce
different worlds are different scenarios. This is the identity a run has to quote.

``implementation_sha`` is the hash of the source that computes both. It exists because the first
two are computed by code: a snapshot renderer that quietly stopped including task states would
leave nine digests looking stable while the thing they describe had changed.

**What the declaration is for.** A scored run recomputes all three and refuses if any has moved.
That is the whole mechanism by which "the programs were frozen before the outcome was seen" is a
fact rather than a claim -- the same argument
``docs/benchmarks/sur1-execution-predeclaration.v1.md`` makes about the ``asserts_change`` rule,
for the same reason.

**No arm has been executed.** The declaration says so, the check asserts it says so, and it is
true: this package has driven no arm, called no model, collected no evidence and produced no
comparative result. What *was* run is recorded separately in :data:`REALISATION_EXERCISED`,
because a freeze whose honesty rests on a sentence that is slightly false is not a freeze.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

from scripts.sur1.bindings import clock as clock_module
from scripts.sur1.bindings import consentdoor as consentdoor_module
from scripts.sur1.bindings import database as database_module
from scripts.sur1.bindings import events as events_module
from scripts.sur1.bindings import governed as governed_module
from scripts.sur1.bindings import programs as programs_module
from scripts.sur1.bindings import realisation as realisation_module
from scripts.sur1.bindings import setup as setup_module
from scripts.sur1.bindings import worldsink as worldsink_module
from scripts.sur1.bindings import worldsnapshot as snapshot_module
from scripts.sur1.bindings.programs import (
    PROGRAM_SET_ID,
    PROGRAM_SET_VERSION,
    program_set_sha,
    programs,
)
from scripts.sur1.bindings.worldsnapshot import SNAPSHOT_SCHEMA_VERSION, digests

ROOT: Final = Path(__file__).resolve().parents[3]
DECLARATION_PATH: Final = ROOT / "docs" / "benchmarks" / "sur1-world-programs.v1.json"

NO_ARM_EXECUTED: Final = (
    "No arm was executed to produce this declaration: it is derived from frozen documents and "
    "from the code that reads them, and nothing in it was learned from a run. Two scored runs "
    "have since been driven under it. 20260919T2020Z-scored, on 2026-09-19, is published "
    "inconclusive and unaltered, with 24 of its 27 attempts HARNESS_FAILURE. "
    "20260920T1100Z-scored-corrected, on 2026-09-20, failed in preparation on all 27 of its "
    "attempts, reached no model and spent nothing. No program, program hash or world digest in "
    "this declaration was changed by either run or by the corrections after them."
)
"""The statement the freeze carries, asserted by a test rather than left as a sentence.

It said *no arm has been driven at any SUR-1 scenario* until 2026-09-19, when one was. The
sentence was replaced rather than quietly kept, because a freeze whose honesty rests on a
statement that has become false is not a freeze. What the freeze actually claims -- that the
programs were fixed before any outcome was seen -- is unchanged and is the first sentence."""

REALISATION_EXERCISED: Final = (
    "The realisation path was executed once, unintentionally, while checking a refusal message: "
    "C04's canonical world was installed into the local development PostgreSQL through the "
    "governed fixture load, and the local demo fixture was restored immediately afterwards with "
    "pp reset-demo-state. No arm was driven at it, no order-system change was posted, nothing "
    "was read back from it and no capture exists. It is recorded here because a freeze that "
    "said nothing had ever been run would be a freeze nobody should trust."
)
"""What was actually run, recorded beside what was not. Neither is inferred from the other."""

IMPLEMENTATION_MODULES: Final = (
    programs_module,
    snapshot_module,
    realisation_module,
    setup_module,
    events_module,
    worldsink_module,
    consentdoor_module,
    clock_module,
    governed_module,
    database_module,
)
"""Every module whose source decides what a program is or what its world looks like.

Setup is in the list because it resolves the registry and defines what a step may reach; a
change there can change what a program does without changing a line any program declares.

The event model, the world sink and the consent door are in it for the same reason and one
more: they decide what a declared event observes and what it does, which is the rest of what a
scenario's world is. The door is in the list because it decides whether a stipulated reply
reaches the deciding system at all -- a change there moves what arms with a consent protocol
receive, while every world digest holds still, which is exactly the failure this hash exists
for. They are also the modules the structural blindness checks walk, so listing them here is
what makes a trigger that started reading an arm or an answer a parse failure rather than a
review question.

The governed writer is in it because it is how the world's two writes into PromisePatch's
own tables are authorised. A change there decides whether a stipulated stock movement or a
hold happens at all, while every world digest holds still -- the same failure the sink and
the door are listed for.

The database module is in it because *which database* a world is installed into decides whether
the world an arm acts on is the world the receivers read. A world digest cannot see that either:
it is taken of the canonical snapshot before the write, so a change that quietly pointed the load
somewhere else would leave all nine digests holding still while every reading became a reading
about a world that was never installed. That is what happened to ``20260920T1100Z-scored-
corrected``, and ``docs/sur1-corrected-scored-run-refusal.md`` is the record of it.

The clock is in it because *where in time* a world is installed decides whether its commitments
fall inside the bakery day, and therefore which clarification a scenario asks and whether any
answer can resolve it. A world digest cannot see that -- it is rendered as offsets from the
anchor and is invariant under it by design -- so a change to the anchor rule would otherwise
move what every scenario does while all nine digests held still. That is exactly the failure
this hash exists for. See ADR-0019.
"""


class DeclarationMismatchError(RuntimeError):
    """The code and the published world-program declaration no longer agree."""


def implementation_sha() -> str:
    """The hash of the source that computes the program set and its snapshots.

    Over the file bytes, named in a fixed order, exactly as ``verify_effect_set_manifest``
    hashes a document: a hash over behaviour would need the behaviour to be exercised, and this
    has to be checkable without running anything.
    """
    hasher = hashlib.sha256()
    for module in IMPLEMENTATION_MODULES:
        path = Path(module.__file__ or "")
        hasher.update(path.name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes().replace(b"\r\n", b"\n"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def declaration() -> dict[str, Any]:
    """The whole freeze, recomputed from the code that is on disk right now."""
    from scripts.sur1.frozen import Contract

    contract = Contract.load()
    built = programs()
    world = digests(built)
    return {
        "program_set_id": PROGRAM_SET_ID,
        "program_set_version": PROGRAM_SET_VERSION,
        "benchmark_id": contract.identity.benchmark_id,
        "manifest_version": contract.identity.manifest_version,
        "manifest_sha": contract.identity.manifest_sha,
        "fixture": "promise_graph.examples.hollow_oak",
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "program_set_sha": program_set_sha(),
        "implementation_sha": implementation_sha(),
        "allowed_frozen_fields": list(_allowed_frozen_fields()),
        "programs": {
            scenario_id: {
                "slug": built[scenario_id].slug,
                "dimension": built[scenario_id].dimension,
                "program_sha": built[scenario_id].identity(),
                "world_digest": world[scenario_id],
                "steps": [step.name for step in built[scenario_id].steps],
                "armed_events": [event.name for event in built[scenario_id].armed],
                "consumed_fields": list(built[scenario_id].consumed),
            }
            for scenario_id in sorted(built)
        },
        "no_arm_executed": NO_ARM_EXECUTED,
        "realisation_exercised": REALISATION_EXERCISED,
    }


def _allowed_frozen_fields() -> tuple[str, ...]:
    """The five consumable fields, plus identity, read off the view rather than retyped."""
    return programs_module.StipulatedFacts.ALLOWED


def published() -> dict[str, Any]:
    """The declaration as committed. A missing one is a refusal, never an empty default."""
    if not DECLARATION_PATH.is_file():
        raise DeclarationMismatchError(
            f"{DECLARATION_PATH} does not exist; the world programs are not frozen and a scored "
            "run has nothing to check itself against"
        )
    loaded: dict[str, Any] = json.loads(DECLARATION_PATH.read_text(encoding="utf-8"))
    return loaded


def differences() -> tuple[str, ...]:
    """Every way the code and the published declaration disagree, named one at a time."""
    try:
        was = published()
    except DeclarationMismatchError as missing:
        return (str(missing),)
    now = declaration()
    found: list[str] = []
    for field in (
        "program_set_id",
        "program_set_version",
        "manifest_sha",
        "snapshot_schema_version",
        "program_set_sha",
        "implementation_sha",
    ):
        if was.get(field) != now[field]:
            found.append(f"{field}: declared {was.get(field)!r}, recomputed {now[field]!r}")
    declared = was.get("programs") or {}
    for scenario_id in sorted(set(declared) | set(now["programs"])):
        if scenario_id not in declared:
            found.append(f"{scenario_id} is programmed and is not in the declaration")
            continue
        if scenario_id not in now["programs"]:
            found.append(f"{scenario_id} is declared and has no program")
            continue
        for field in ("program_sha", "world_digest"):
            if declared[scenario_id].get(field) != now["programs"][scenario_id][field]:
                found.append(
                    f"{scenario_id} {field}: declared "
                    f"{declared[scenario_id].get(field)!r}, recomputed "
                    f"{now['programs'][scenario_id][field]!r}"
                )
    if was.get("no_arm_executed") != NO_ARM_EXECUTED:
        found.append("the declaration no longer carries the statement that no arm was executed")
    if was.get("realisation_exercised") != REALISATION_EXERCISED:
        found.append("the declaration no longer records what was actually run")
    return tuple(found)


def write(path: Path = DECLARATION_PATH) -> Path:
    """Write the declaration. Run once, at the freeze, and never as part of a run.

    Deliberately not called by anything in the harness. A run that rewrote its own declaration
    when it disagreed with it would be a run with no freeze at all.
    """
    path.write_text(json.dumps(declaration(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    """``uv run python -m scripts.sur1.bindings.declaration [--write]``: check, or freeze once."""
    import sys

    if "--write" in sys.argv[1:]:
        print(f"wrote {write()}")
        return 0
    found = differences()
    for difference in found:
        print(f"  - {difference}")
    print("the world-program declaration matches the code" if not found else "MISMATCH")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DECLARATION_PATH",
    "NO_ARM_EXECUTED",
    "REALISATION_EXERCISED",
    "DeclarationMismatchError",
    "declaration",
    "differences",
    "implementation_sha",
    "published",
    "write",
]
