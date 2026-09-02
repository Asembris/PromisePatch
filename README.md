# PromisePatch

When a delivery does not arrive, the expensive problem is not the inventory — it is the
customer promises somebody already made. PromisePatch lets a frontline bakery worker report
one physical-world exception by voice, then identifies every accepted customer promise that
exception threatens, coordinates bounded recovery, obtains customer approval through the
customer's own channel where that order's recorded constraints require it, resumes
asynchronously, revalidates against the current state, and reconciles the affected systems —
while leaving every unaffected promise untouched.

## Status

Phase 0 of an active hackathon build. Only the deterministic engine
(`packages/promise-graph`) exists. There is no backend, frontend, database or deployment yet.

## The deterministic engine

`promise_graph` is a separate, pure package on purpose. It owns reachability, temporal
availability, allocation, impact classification, recovery-option validation, snapshot
fingerprinting and the revalidation checklist. It performs no I/O, reads no environment, and
never calls the wall clock — time is passed in explicitly — so every decision that could
affect a customer is testable with zero cloud access.

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

## Install

```bash
uv sync
```

## Run the engine tests

```bash
uv run pytest packages/promise-graph
```

## License

Apache-2.0. See [LICENSE](LICENSE).

---

The full product is under active hackathon development; this repository grows one phase at a
time.
