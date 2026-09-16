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

## Standalone: from a clean clone to a running example

The engine installs and runs on its own. It needs no database, no service, no network at run
time, no environment variable and **no cloud credentials of any kind** — there is no AWS SDK in
its dependency tree and nothing to configure.

**Local prerequisites.** Python 3.12 (the package declares `>=3.12,<3.13`), `git`, and
[`uv`](https://docs.astral.sh/uv/). Only the install step reaches the network, and only to
PyPI. If you would rather not use `uv`, every command below has a `python -m venv` / `pip`
equivalent and the pinned file is an ordinary requirements file.

```bash
git clone https://github.com/Asembris/PromisePatch.git promisepatch
cd promisepatch/packages/promise-graph
uv venv --python 3.12
uv pip install --requirement requirements-standalone.txt
uv pip install --no-deps .
uv run python examples/one_missing_delivery.py
uv run pytest tests -q
```

`requirements-standalone.txt` is a fully resolved, transitively pinned set — `pydantic`, plus
`pytest` and `hypothesis` for the suite — at the versions this repository itself resolves and
tests against. `--no-deps` on the package install is what makes the pins authoritative rather
than advisory: nothing is re-resolved.

The example prints the four partitions for one missing delivery, counted, with the rule that
decided each one:

```
UNAFFECTED         untouched by this exception  (1 of 4)
    EXT-4  Dev       R-UNREACH  NOT_REACHABLE

AUTO_RECOVERABLE   changed without asking anyone  (1 of 4)
    EXT-1  Amara     R-PREAPPROVED  PREAPPROVAL_COVERS
...
```

`tests/test_example.py` asserts that transcript in full, so a change to propagation, option
enumeration or the rule ladder cannot silently alter what the example claims.

## Tests

From the monorepo:

```bash
uv run pytest packages/promise-graph
```

From a standalone clone, as above:

```bash
uv run pytest tests -q
```

## License

Apache-2.0.
