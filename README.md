# PromisePatch

[![product gate](https://github.com/Asembris/PromisePatch/actions/workflows/pr.yml/badge.svg?branch=main)](https://github.com/Asembris/PromisePatch/actions/workflows/pr.yml)
[![effect sets: 11/16, red on purpose](https://github.com/Asembris/PromisePatch/actions/workflows/effect-sets.yml/badge.svg?branch=main)](docs/effect-set-first-scored-run.md)

Two badges, because they answer two different questions, and the second one needs reading before
it is wondered about.

The **first** is the product gate: thirteen jobs, ruff through the whole-stack browser suite.
Its red means a regression, and that is the only thing it means.

The **second is red on purpose and is meant to stay red.** It runs the sixteen frozen effect-set
scenarios, whose [first scored run](docs/effect-set-first-scored-run.md) is published at
**11/16**. Five of the sixteen disagreed with labels written by hand before the runner existed;
four of those five — S08, then S06, S07 and S13 — have since been repaired, each with its own fix
SHA, and **S12 stays committed *failing*** with its exact diffs published, because its label
applies a manifest-wide rule that is false for work the kitchen had already started
([`docs/started-work-contract.md`](docs/started-work-contract.md)). No repaired run has been
scored; a development run is not a score.
`docs/effect-set-run-protocol.md` forbids weakening, skipping,
deselecting, removing or marking any of them expected-to-fail — so this badge goes green only
when the remaining disagreements are repaired, and a green tick before then would mean a scenario
had been quietly weakened. **11/16 is the permanent headline**: it is never replaced by a
repaired score, and the denominator is never smaller than sixteen.

When a delivery does not arrive, the expensive problem is not the inventory — it is the
customer promises somebody already made. PromisePatch lets a frontline bakery worker report
one physical-world exception by voice, then identifies every accepted customer promise that
exception threatens, coordinates bounded recovery, obtains customer approval through the
customer's own channel where that order's recorded constraints require it, resumes
asynchronously, revalidates against the current state, and reconciles the affected systems —
while leaving every unaffected promise untouched.

## Status

An active hackathon build. What exists today is the deterministic engine
(`packages/promise-graph`), the backend with its audited PostgreSQL write boundary, the durable
case engine, the Live Operations screen, the external order-system integration — a separate
order system that owns order state, a signed event ingress, and governed recovery amendments
pushed back at it — the semantic boundary an Amazon Bedrock model answers through, now wired
into exception intake, an authenticated **MCP Streamable HTTP endpoint** carrying all five
intent tools -- report, clarify, confirm, withdraw and status -- and the case workspace a
worker and a judge read a case on.

**It is deployed.** `https://184.194.40.87.sslip.io` serves the single-page application and the
same API, event stream and MCP endpoint over TLS on one `t4g.small` in `us-east-1b`, against a
private encrypted RDS PostgreSQL. Twelve deployment smoke checks pass, five of them asserting a
refusal. See [`docs/p6.2-first-deployment.md`](docs/p6.2-first-deployment.md) and
[`docs/p7.3-deployed-judge-surface.md`](docs/p7.3-deployed-judge-surface.md). The Telegram
customer channel is **not built**; the customer channel in this build is simulated.

**The measured voice number.** Ten predeclared voice turns were recorded, and **9 of 10 started a
truthful spoken response within four seconds of speech ending** — the gate is 9, so it passes by
exactly one turn, with the failing turn missing the threshold by 807.8 ms. A first run is
published void, in full, with its `K = 1/10`. Both runs, every timing, the failures and the
conditions — including that the measurement ran on the local stack and so carries no
public-internet round trip — are in
[`docs/g7-ten-turn-voice-measurement.md`](docs/g7-ten-turn-voice-measurement.md), against the
setup fixed beforehand in
[`docs/g7-ten-turn-voice-predeclaration.md`](docs/g7-ten-turn-voice-predeclaration.md). This is a
usability gate, not a production latency SLA.

## The frozen effect-set manifest

Sixteen scenarios, hand-labelled from stipulated facts, committed before the runner that
executes them existed. Each declares the orders it expects in each partition at each ordered
checkpoint, and the exact operational effects and refusals it expects — including the zeros.

| | |
|---|---|
| Manifest | `promisepatch-effect-sets` v1.0.0, 16 scenarios |
| File | [`docs/effect-sets/scenarios.v1.json`](docs/effect-sets/scenarios.v1.json) |
| **Manifest SHA** | `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` |
| Frozen at commit | `9a7f4a899ade132507f015f65688c8be8b373827` |

Recompute that hash and check the manifest's coherence with no database, no credential and no
network:

```bash
uv run python scripts/verify_effect_set_manifest.py
```

The labels are **not** derived from PromisePatch's own output, and the verifier is structural
only — it never asks the engine what it would classify. All sixteen scenarios are now wired to
an executable runner that performs their stipulated facts against the real system.

**The first scored run is 11/16**, taken at implementation SHA
`e81b5aa3af101847fdceb0f0af6cb515909d40b2` against that manifest SHA, with every diff published
and nothing repaired: [`docs/effect-set-first-scored-run.md`](docs/effect-set-first-scored-run.md).
Five scenarios failed — S06, S07, S08, S12, S13 — every difference an effect count lower than the
label, with no order misclassified anywhere in the sixteen and no extra, unauthorized or
duplicate effect. That headline is immutable: a later repaired run is published beside it, never
over it, and 16/16 is a separate release condition. Read
[`docs/effect-set-manifest.md`](docs/effect-set-manifest.md) for the method, the partition
algebra, the pass rule and the disclosure that these labels are developer-authored and finite.

## What integrating this would actually require

[`docs/prerequisites-integration-cost-and-limitations.md`](docs/prerequisites-integration-cost-and-limitations.md)
is the honest version: which data has to be accurate and who maintains it, what an order system
must satisfy to talk to this one, what the real deployment cost and found, what is simulated and
what is not built at all — and what this repository does **not** establish. Every prerequisite
there names the file, table or decision record that imposes it, and every figure is labelled
measured, estimated or not measured.

## The deterministic engine

`promise_graph` is a separate, pure package on purpose. It owns reachability, temporal
availability, allocation, impact classification, recovery-option validation, snapshot
fingerprinting and the revalidation checklist. It performs no I/O, reads no environment, and
never calls the wall clock — time is passed in explicitly — so every decision that could
affect a customer is testable with zero cloud access.

## The semantic boundary

The model understands; the deterministic protocol authorizes. `promisepatch.semantic` is the
narrow, pure boundary a model answers through: three bounded jobs, strict schemas, and a check
that every identifier in an answer came from the candidates PromisePatch supplied. A model can
propose a reading; it cannot write a row, record a consent decision, attest a physical fact or
select a recovery — the import graph forbids it, not a convention.

The default provider is a deterministic fake, so the suites, the local stack and CI all run
with **no AWS credentials of any kind**. Switching to Amazon Bedrock is an environment change
plus whatever the AWS SDK already uses to authenticate on that machine; PromisePatch holds no
AWS key in any environment.

One workflow uses it. When the deterministic interpreter cannot read a worker's report — "the
deck oven packed up", "Valley only brought part of the raspberries today" — a model is asked
which of the bakery's own things the sentence was about, and nothing else. It contributes a
category and one identity; which delivery, what arrived and how much stay with deterministic
code and the worker's answers. An identity is accepted only when the worker's sentence contains
that resource's stored name or one of its aliases, so a model may parse a phrasing but may not
supply vocabulary the bakery never authored. The canonical raspberry report is understood by
the lexicon and costs **zero** model calls, which is asserted rather than assumed.

The worker remains the physical attestor throughout: `PHYSICAL_FACT_RECORDED` names the person
who spoke, and the model appears only as provenance beside it.

Explanations are the same rule pointed the other way: the deterministic engine establishes the
facts, and the model verbalises them. A settled outcome is projected into a bounded set of
named facts -- the classification, the cited rule, the shortfall, the pre-authored variant, the
constraint and who recorded it -- and a passage is accepted only if it stays inside its word
limit, refers to nothing PromisePatch did not supply, and accounts for the causes the
application marked required. The same facts render PromisePatch's own sentence, which is what
gets shown when the provider is down, the answer will not parse, a reference is invented or the
outcome moved while the model was writing. **Explanation output is never parsed back into
workflow authority**, and no explanation call gates an external effect.

[docs/semantic-boundary.md](docs/semantic-boundary.md) has the trust line, the fallback
condition, the failure semantics, the prompt-injection posture and the opt-in live acceptance.

How well that boundary reads a sentence is measured rather than asserted. `evals/` holds a
hand-authored gold dataset, deterministic scorers, hard safety gates and the spend controls a
live benchmark will run under; `python -m evals replay` scores the whole thing with **zero
provider calls**, and no command there can reach Bedrock. [evals/README.md](evals/README.md)
has the methodology, the thresholds and the cost policy.

How well it *says* an outcome out loud is measured separately, because that answer is a matter of
opinion where the other two are not. The explanation gate has its own thirty-five-case dataset
checked against the production projection, structural gates computed by the application's own
validator, and exactly **one** structured judge call per accepted passage — never one per quality
dimension. `python -m evals explanation-plan` prints what a live run would spend and constructs no
client to do it; `python -m evals explanation-replay` scores the whole thing offline.
[docs/explanation-quality-gate.md](docs/explanation-quality-gate.md) has the protocol, the
thresholds, the two separate cost accountings and the holdout rules.

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker with Compose v2, for the local stack
- Node.js 24, for the frontend

## Run the local stack

The stack is a disposable PostgreSQL 16 in a Docker volume, the repository's own migrations,
the Hollow Oak fixture, the API, the durable workflow worker, the MCP endpoint, the frontend
and the External Order System simulator. It needs no hosted database and no cloud account.

```bash
uv run python scripts/bootstrap_local_env.py
```

That generates `docker/env/*.env` with fresh credentials. The files are never committed, and
there are no default passwords: read the seeded demo logins out of `docker/env/migrate.env`.

```bash
docker compose up --detach --wait
```

`--wait` returns only once PostgreSQL is healthy, the migrations have exited zero, the fixture
has loaded, `/readyz` reports ready and the frontend is serving. Then open
<http://localhost:55173> and sign in as `maya` with `PP_DEMO_WORKER_PASSWORD`.

```bash
docker compose run --rm seed        # reload the fixture
docker compose restart worker       # restart the worker; outstanding work resumes
docker compose down                 # stop, keeping the database
docker compose down --volumes       # stop and discard the database
```

| Service | On the host | Inside the network |
|---|---|---|
| frontend | <http://localhost:55173> | `frontend:5173` |
| api | <http://localhost:58000> | `api:8000` |
| worker | no port; `docker compose logs worker` | -- |
| mcp | <http://localhost:58001/mcp> | `mcp:8001` |
| order-simulator | <http://localhost:58100> | `order-simulator:8100` |
| postgres | `127.0.0.1:55432` | `postgres:5432` |

The host ports are deliberately not 5173, 8000 and 5432: those are usually already taken on a
machine that develops this project, and a stack that quietly attached to something else would
be a confusing way to find out.

A few properties are worth knowing before you use it:

- **Neither the API nor the worker holds an administrative credential.** Both connect as
  `promisepatch_app`, which owns nothing, migrates nothing and cannot truncate a table.
  Migrations and `pp reset-demo-state` run in separate containers with the administrative
  connection. That is why there is no HTTP reset endpoint.
- **The worker is stateless, so restarting it is the recovery mechanism.** Every piece of
  outstanding work is a row and everything the process holds is a lease; `docker compose
  restart worker` -- or killing it outright -- loses nothing, and the work resumes as the
  leases expire. Several workers can run at once without coordinating.
- **`pp reset-demo-state` recreates the fixture workers, so it signs everyone out.** It is an
  operator command that replaces every domain row PromisePatch owns, and the sessions go with
  them. A browser watching the live feed will see the resulting domain event, refetch, be told
  its session is gone, and return to the sign-in screen. That is current, intended behaviour.
- **The MCP endpoint is a separate process, and cannot reach the database.** It is the surface
  a third-party MCP client is pointed at, and it reaches a case the way any other client would:
  an authenticated HTTP call to the API's `/internal/intents`. An import-linter contract stops
  the code in it from importing the domain or the database at all, so that boundary is checked
  rather than intended. It speaks protocol revision **2025-11-25** over Streamable HTTP, refuses
  an unauthenticated caller before the protocol layer, and rejects an unlisted `Origin`. Point a
  client at it with the bearer token from `docker/env/mcp.env`;
  [docs/p5.1-mcp-transport-spine.md](docs/p5.1-mcp-transport-spine.md) is the transport contract
  and [docs/p5.2-mcp-clarification-and-confirmation.md](docs/p5.2-mcp-clarification-and-confirmation.md)
  is the current tool contract, including why a confirmation has to quote back the identity of
  the plan it is confirming.
- **The order system is a different system, and is meant to look like one.** It runs in its
  own process, over its own SQLite volume, on its own port, with its own UI. PromisePatch
  mirrors it and pushes governed amendments at it; neither reads the other's storage. It is a
  simulator — not Square, not a production point of sale — and
  [docs/order-system.md](docs/order-system.md) says exactly what it does and does not prove.

Behind an antivirus or corporate proxy that terminates TLS, put that root certificate in
`docker/env/extra-ca.crt` before building; the file is created empty and is otherwise ignored.

## Choosing a database for the repository tooling

`.env` at the repository root points Alembic, the CLI and the integration suite at whichever
database you configured — typically a hosted developer project. `docker/env/host.env` points
them at the disposable local one instead, and `scripts/with_local_env.py` runs a single command
with it, so switching to the local stack never means editing `.env`:

```bash
uv run python scripts/with_local_env.py -- uv run pytest apps/backend
```

## Tests

The engine suite needs nothing at all:

```bash
uv run pytest packages/promise-graph
```

The backend suite needs a database. With the local stack running:

```bash
uv run python scripts/with_local_env.py -- uv run pytest apps/backend
```

Stop the worker first, though — it and the suite share the local database, and a running worker
will claim the steps a workflow test just enqueued and finish them out from under it:

```bash
docker compose stop worker
```

The order-system integration runs both applications against each other, and the acceptance
proof for the whole boundary is one file:

```bash
uv run python scripts/with_local_env.py -- uv run pytest apps/backend/tests/test_order_system_boundary.py
```

The semantic boundary needs neither a database nor an AWS account:

```bash
uv run pytest apps/backend/tests/test_semantic_contracts.py \
  apps/backend/tests/test_semantic_provider.py \
  apps/backend/tests/test_semantic_grounding.py \
  apps/backend/tests/test_explanations.py \
  apps/backend/tests/test_bedrock_semantic.py
```

The MCP protocol suite needs no database, no credential and no model. It starts the real server
on a loopback socket and drives it with the official SDK's client, so what it checks is the
protocol -- initialization, negotiation, discovery, framing, the bearer challenge, the `Origin`
and `Host` rejections, the JSON-RPC error codes and the absence of a session to resume:

```bash
uv run pytest apps/backend/tests/test_mcp_protocol.py apps/backend/tests/test_status_view.py \
  apps/backend/tests/test_plan_identity.py
```

What a tool call *causes* needs the database. That suite drives the whole chain end to end --
SDK client, Streamable HTTP, MCP server, the service-token hop, the intent API, the domain and
PostgreSQL -- and then asserts the rows:

```bash
uv run python scripts/with_local_env.py -- uv run pytest apps/backend/tests/test_intent_api.py
```

The semantic intake workflow needs the database but still no AWS account — every one of its
scenarios runs against a scripted model:

```bash
uv run python scripts/with_local_env.py -- uv run pytest apps/backend/tests/test_semantic_intake.py
```

The tests that call Amazon Bedrock for real are marked `bedrock_live` and are deselected by
default. They need credentials available to the AWS SDK and access to the configured model:

```bash
PP_LLM_PROVIDER=bedrock uv run pytest -m bedrock_live
AWS_PROFILE=promisepatch PP_LLM_PROVIDER=bedrock \
  uv run python scripts/with_local_env.py -- uv run pytest -m "bedrock_live and integration"
```

The order system's own suite needs nothing but Python:

```bash
uv run pytest apps/order-simulator packages/order-contract
```

The frozen effect-set manifest's identity and coherence are checked with nothing at all:

```bash
uv run pytest scripts/tests/test_effect_set_manifest.py
```

The effect-set harness executes scenarios from that manifest against the real system. From a
fresh clone it verifies its own prerequisites with no database, no container and no credential —
this is the command to run first, because it proves the clone is complete and the frozen
identity intact before anything heavier is attempted:

```bash
uv run python scripts/run_effect_sets.py --check
```

With the local stack up and the worker stopped, it runs the scenarios. All sixteen are wired, so
this form is a harness-development run that computes no score, and adding `--scored` reproduces
the measurement:

```bash
uv run python scripts/with_local_env.py -- uv run python scripts/run_effect_sets.py
```

The judge and the runner's own suites need nothing at all:

```bash
uv run pytest apps/backend/tests/test_effect_set_judge.py scripts/tests/test_run_effect_sets.py
```

[docs/effect-set-run-protocol.md](docs/effect-set-run-protocol.md) fixes, in advance, what counts
as a scored run and what may never happen to its result;
[docs/effect-set-harness.md](docs/effect-set-harness.md) describes the machinery and the
disagreements building it surfaced;
[docs/effect-set-first-scored-run.md](docs/effect-set-first-scored-run.md) publishes the first
scored run, its per-scenario table and every diff.

The frontend gates:

```bash
cd apps/frontend && npm ci && npm run typecheck && npm run lint && npm test && npm run build
```

The browser suite runs against the local stack, not against mocks. It reloads the fixture, so
expect the stack's demo data to be replaced:

```bash
cd apps/frontend && npx playwright install chromium && npm run e2e
```

## License

Apache-2.0. See [LICENSE](LICENSE).

---

The full product is under active hackathon development; this repository grows one phase at a
time.
