# promise-graph

The deterministic engine behind PromisePatch: given a physical-world exception and an
immutable snapshot of commitments, resources, recipe versions, orders, constraints, tasks and
reservations, it decides which customer promises are threatened, which recoveries are
permitted, and whether an approval taken earlier is still valid.

Pure Python. Standard library and Pydantic only. No I/O, no environment reads, no wall clock.

## Modules

| Module | Responsibility |
|---|---|
| `model` | Frozen typed records and the closed vocabularies (rule ids, classifications, constraint kinds). |
| `snapshot` | `GraphSnapshot`: immutable, indexed graph plus its structural transformations. |
| `availability` | `ON_HAND` / `EXPECTED` / `RESERVED` / `AVAILABLE_BY`, deterministic allocation, commitment settlement. |
| `propagation` | Directional reachability with role-carrying paths, then quantification. |
| `options` | Substitution policy x order constraints x stock, and equipment reassignment. |
| `classification` | `UNAFFECTED` / `AUTO_RECOVERABLE` / `APPROVAL_REQUIRED` / `BLOCKED` with cited rules. |
| `fingerprint` | Track-scoped snapshot fingerprint and its diff. |
| `revalidation` | The ten-check evaluator run before any write on resume. |
| `evidence` | One rendering of an analysis for UI, audit and narration. |

## Usage

```python
from datetime import UTC, datetime

from promise_graph.availability import apply_exception_facts
from promise_graph.classification import analyze
from promise_graph.evidence import build_case_evidence

now = datetime(2026, 3, 4, 7, 0, tzinfo=UTC)

settled = apply_exception_facts(snapshot, exception, now)  # returns the intended postings
analysis = analyze(settled.snapshot, exception, now)
evidence = build_case_evidence(settled.snapshot, analysis, now)

analysis.classification_of(promise_id)
```

## Invariants

1. A `RecipeVersion` is immutable and human-authored. A recovery **selects** a pre-authored
   variant named by the substitution policy; it never creates, derives or synthesizes one.
2. Reachability alone does not make a promise affected. The quantified shortfall must leave a
   reservation unsatisfiable before the relevant task's scheduled start.
3. Allocation is greedy and strictly ordered by `(task start, order external id, claim id)`.
   A partially served claim still consumes what it took. A rejected candidate consumes nothing.
4. A commitment line is open or settled. Settlement posts its physical outcome once and the
   line contributes zero to expected supply thereafter, in every settled state.
5. Unknown or conflicting state fails closed to `BLOCKED` — never `UNAFFECTED`, never
   `AUTO_RECOVERABLE`.
6. Order-scoped constraints govern resource substitution only. Equipment reassignment does not
   change the product and never requires customer approval.
7. Time is a parameter. No function reads the clock, the environment, the filesystem or the
   network.

## Tests

```bash
uv run pytest packages/promise-graph
```

## License

Apache-2.0.
