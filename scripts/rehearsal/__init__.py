"""The ``SUR-1`` dress rehearsal: the whole execution pipeline, at a scenario that is not ``SUR-1``.

The comparative harness had never been driven. Every part of it was tested -- the ledger, the
retry rule, the capture layout, the blinding, the world programs, the event model -- and the one
thing nobody could say was whether they *compose*: whether an install, an arm, a settle, a
capture, a blind score and a join actually run end to end against the running local stack.

The only way to find out inside ``SUR-1`` is to spend a ``C01``-``C09`` world program and a paid
model call on it, and a first scored run that also happens to be the first integration test is a
first scored run whose failures nobody can tell apart from findings.

So there is ``DR01``: a synthetic rehearsal scenario with its own document, its own scenario
namespace, its own run root and its own scorer, which uses the real driver, the real world
bindings, the real receivers, the real MCP and workspace surfaces, the real order simulator and
the real customer-approval ingress.

**Nothing here is a benchmark and nothing here produces one.**

- The kind is always ``development``. :data:`FORBIDDEN_KIND` is refused by name.
- The run root is :data:`RUNS_ROOT`, which is not ``docs/benchmarks/runs``.
- The contract is :mod:`scripts.rehearsal.contract`, whose ``benchmark_id`` is ``DR-REHEARSAL``.
- No scored authorisation is minted, asked for or held.
- The baseline arm is driven by :class:`~scripts.sur1.doubles.ScriptedModel`, which raises rather
  than reaching a provider.
- The comparative run's paid-inference authorisation phrase appears nowhere in this package,
  which ``test_dress_rehearsal.py`` asserts by searching for the literal. It is deliberately not
  written out here either: a package that quoted it would fail its own check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parent.parent.parent

REHEARSAL_ID: Final = "DR-REHEARSAL"
REHEARSAL_VERSION: Final = "1.0.0"
SCENARIO: Final = "DR01"

CONTRACT_PATH: Final = ROOT / "docs" / "rehearsals" / "dr01.v1.json"
RUNS_ROOT: Final = ROOT / "docs" / "rehearsals" / "runs"
"""Where a rehearsal's artefacts land. Deliberately not the benchmark's run directory."""

FORBIDDEN_KIND: Final = "scored"
"""The one kind a rehearsal may never be driven as.

Refused by name in :mod:`scripts.rehearsal.run`, which offers no other choice on its command line.
"""

NOT_A_BENCHMARK: Final = (
    "This is a DR01 dress rehearsal of the SUR-1 execution pipeline. It is not SUR-1, not a "
    "benchmark and not a comparative result. No C01-C09 world program was executed, no model was "
    "reached, no scored authorisation was minted and no paid inference phrase was spent. Nothing "
    "in this run is evidence about the quality of any system."
)
"""Written into every rehearsal artefact, so a file read on its own says what it is not."""


__all__ = [
    "CONTRACT_PATH",
    "FORBIDDEN_KIND",
    "NOT_A_BENCHMARK",
    "REHEARSAL_ID",
    "REHEARSAL_VERSION",
    "ROOT",
    "RUNS_ROOT",
    "SCENARIO",
]
