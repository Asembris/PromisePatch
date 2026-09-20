# CLAUDE.md — PromisePatch operating contract

This file is the standing contract for every session. It holds what is true now and the rules
that never change. It is **not** a project journal: completed work lives in `docs/`, and the
links at the bottom are the authoritative record. Do not grow this file with narrative.

## Purpose

PromisePatch turns one spoken physical-world exception ("today's raspberry delivery didn't
arrive") into a correct, consent-respecting, selectively-applied set of customer-promise
recoveries, with the reasoning visible. Made-to-order bakery vertical.

## Core rule

**The model understands; the deterministic protocol authorizes.**

## Authority invariants

These are load-bearing. Never weaken one to make something work; amend the ADR first.

- **Model output is never authority.** The LLM never authorizes a write, never produces a
  consent decision, and never produces a physical attestation. A reading that arrives inside its
  schema authorizes exactly as much as one that never arrives: nothing.
- **Worker plan approval and customer consent are wholly distinct**, with distinct parsers,
  distinct records and distinct vocabulary. Never merge them.
- **Customer consent** is only a literal `YES` / option code / `NO`. Free text is at most a
  non-authoritative apparent intent that can trigger one confirmation prompt.
- **Service authentication is not human consent.** Holding the MCP bearer token or the internal
  service secret proves a *process*, never a person. No request field on any transport can name
  an actor, a clock, a reason or a physical claim; the actor is server-derived.
- **MCP `confirm` spends a durable human approval it cannot write.** `plan_approvals` is
  governed and append-only, unique on `(case_id, plan_id)`, and `ApprovalChannel` has no member
  a service surface could name. See ADR-0018.
- A confirmation binds to a **`plan_id`** — the derived, opaque identity of the plan that was
  read out. Stale, wrong-case, replayed and repeated confirmations fail closed.
- Recovery selects only pre-authored `RecipeVersion`s named by `SubstitutionPolicy`. Nothing at
  runtime creates, derives or synthesizes a version.
- The external order system is the system of record for orders. PromisePatch has no order
  editor; it writes to an order only as a governed recovery amendment.
- **Physical facts** (received / not received / spoiled / equipment out) are authoritative
  independently of recovery authorization. Declining a plan never un-spoils anything; only an
  explicit correcting attestation reverses a fact.
- **Work that has started is never reported as stopped.** Scheduled work on a blocked promise is
  held so it cannot begin; started work is escalated to its owner and never held, because release
  restores the literal `SCHEDULED` and would assert that begun work never began. See ADR-0017 and
  [started-work-contract.md](docs/started-work-contract.md).
- A commitment line is open (`EXPECTED`) or settled. Settlement posts its physical outcome to
  the ledger exactly once; a settled line contributes zero to expected supply. Received supply
  is never also counted as expected.
- Unknown or conflicting state **fails closed to `BLOCKED`** — never `UNAFFECTED`, never
  `AUTO_RECOVERABLE`.
- Promises not reachable from the exception are **untouched**: no message, no write, no
  reservation change, no task hold, no audit event.
- A withdrawal stops future work and is **never an undo**: it reverses no physical fact, unsays
  no customer decision and rewrites no delivered effect.
- **Frozen and historical evidence is never silently rewritten.** Manifests, published run
  captures, measurements and closeout documents are read-only history. A later truth is recorded
  beside them, never edited into them.

## Architecture

One Python backend (`api`, `worker`, `mcp` entrypoints, plus the `converse` client), one pure
engine package (`promise_graph`), one React evidence UI, one separate External Order System
simulator, PostgreSQL as the single store, a persisted case state machine with a step ledger,
Bedrock for understanding only, MCP for the five intent tools, Telegram for the customer channel.

`promise_graph` depends on the standard library and Pydantic only, does no I/O, reads no
environment, and never calls the wall clock — time is passed in explicitly. Import-linter
contracts in `pyproject.toml` enforce every boundary: engine purity, the semantic boundary,
consent isolation, the MCP client's separation from the domain and database, and the
orchestrator's separation from everything authoritative.

## Current state

Phase 4, the G5 deployment-entry subset and the first deployment are closed in their committed
records. **G7 is closed with one criterion deliberately not performed** — the demo-narrative
comprehension check, declined by the project owner. **G8 is the open gate.**

- **Deployed** at `https://184.194.40.87.sslip.io` — one EC2 host, private encrypted RDS, Caddy
  with a real Let's Encrypt certificate. See [p6.2-first-deployment.md](docs/p6.2-first-deployment.md).
- **The effect-set benchmark headline is `11/16` and is immutable.** The denominator is
  permanently sixteen; a repaired score never replaces it, and `16/16` is a separate release
  condition published beside it. Failing scenarios stay committed failing.
  See [effect-set-first-scored-run.md](docs/effect-set-first-scored-run.md) and
  [effect-set-run-protocol.md](docs/effect-set-run-protocol.md) before touching anything here.
- **The manifest is frozen**: `docs/effect-sets/scenarios.v1.json`,
  `promisepatch-effect-sets` v1.0.0, content hash
  `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc`, checked by
  `scripts/verify_effect_set_manifest.py`. Never edit a label.
- **Both evaluation holdouts remain sealed.** Do not open one.
- **`SUR-1` has been taken three times and none of the three is a result.** All three are
  preserved byte-identical and pinned in two places; the correct response to a digest moving is to
  restore the run, never to update the pin. The third, `20260920T1215Z-scored-v3`, is **invalid** —
  five arm-correlated defects were proved in it afterwards. All five are now corrected and the
  preflight asks 28 questions rather than 18. The last of them — arm C's ablation reaching no
  evaluator, which made the ablated arm unmeasurable rather than unmeasured — is closed by
  [ADR-0020](docs/adr/0020-a-scored-benchmark-hosts-the-product-s-own-worker.md): the product's
  own durable worker runs inside the harness process for **both** arms B and C, and the
  containerised worker is down for the run. **A fourth run is still not taken and is not this
  session's to take.** `DR01` through the corrected seam, against the live local stack, is owed
  before any spend. See [sur1-v3-forensic-audit.md](docs/sur1-v3-forensic-audit.md),
  [sur1-parity-correction.md](docs/sur1-parity-correction.md) and
  [sur1-hosted-worker.md](docs/sur1-hosted-worker.md) before touching anything here.
- **Telegram is unbuilt**, deferred into G8's deployed rehearsals. Correcting a physical fact is
  CLI-only. A customer answers on the web, through a signed possession link carried in the
  outbound message's payload — a transport into the unchanged consent protocol, never a second
  one. See [customer-approval-link.md](docs/customer-approval-link.md).

`new_roadmap.md` is the authority on what is open and what each gate requires. Read it before
deciding what to build. Do not restate its contents here.

## Repository map

| Path | What it is |
|---|---|
| `packages/promise-graph/` | The pure deterministic engine. No I/O, no clock, no environment. |
| `packages/order-contract/` | The shared order-system contract types. |
| `apps/backend/src/promisepatch/domain/` | Case state machine, consent, recovery, plan approval, withdrawal, status rendering. The authority lives here. |
| `apps/backend/src/promisepatch/semantic/` | The model boundary. Understanding only. |
| `apps/backend/src/promisepatch/api/` | HTTP surface: `routers/conversation.py` (browser), `routers/intents.py` (internal), workspace reads. |
| `apps/backend/src/promisepatch/mcp/` | The MCP transport. Forbidden the domain, the database and SQLAlchemy. |
| `apps/backend/src/promisepatch/orchestrator/` | The conversational client. Holds no authority. |
| `apps/backend/src/promisepatch/worker.py` | The durable workflow worker. |
| `apps/frontend/` | The case workspace. Renders; never decides. |
| `apps/order-simulator/` | The External Order System, a separate application. |
| `evals/` | The measurement surface. Never becomes production. |
| `scripts/` | Harnesses: effect sets, benchmarks, deployment smoke, AWS preflight, local env. |
| `deploy/` | CloudFormation, compose files, IAM policies. |
| `docs/` | The authoritative record. ADRs in `docs/adr/`. |

## Local environment

Full instructions are in [README.md](README.md) (*Prerequisites*, *Run the local stack*,
*Tests*). The rules that bite:

- **Stop the compose `worker` before running the backend suite** — it shares the local database
  and will claim the steps a workflow test just enqueued. Stop `api` and `mcp` too, or the
  suite's `TRUNCATE` waits on their connector locks forever.
- Local containers have **no bind mounts**: they serve the image, not the working tree. Rebuild
  after editing source, and run Vite on the port the allowlist expects.
- `boto3` here needs `AWS_CA_BUNDLE` pointing at the local root, or every AWS call fails TLS.
- Never commit `docker/env/*.env`, `.env`, tokens or credentials.

## Validation

- **Use the `fast-validate` skill.** Run the smallest correct validation for what changed, and
  say what you skipped. `.claude/skills/fast-validate/SKILL.md`.
- **GitHub CI is the broad regression authority.** A green local run never means "validated".
- The full gates are: pytest with the coverage floor, the Hypothesis CI profile, mypy in its
  three separate groups, `ruff check`, `ruff format`, and import-linter.
- Do not run the full backend suite for a small change — it is roughly an hour, fully buffered.
- **Never weaken, skip, delete or deselect a test to make code pass.** Fix the code or fix the
  fixture data, and say which.
- The effect-set scenarios run in their own CI job and are **expected red until 16/16**. "The
  release SHA passes required CI" means the product gate, not that job. Do not touch the
  effect-set workflow merely because it is red.
- For a live evaluation run, a budget or a split, use the `eval-runbook` skill. Never improvise
  a live model invocation.

## AWS and deployment

- **Never mutate an AWS resource unless the task explicitly requires it.** Reads and the
  read-only preflight are fine; creating, updating or deleting is not.
- Never broaden IAM to get around a denial without saying so; prefer removing the dependency on
  the permission. The account owner grants deltas, not this session.
- IMDSv2 stays required, TLS verification stays on everywhere, the database stays private.
- `scripts/aws_preflight.py` is read-only by construction and aborts on an unlisted API.

## Git

- One-line Conventional Commit subjects. **No body, no bullets, no trailers, no co-author line,
  no generated-by line, no emoji.** Example: `feat(engine): propagation`.
- **Never push unless explicitly asked.**
- **Never run a destructive git operation** — no `reset --hard`, no `checkout --`, no `clean`,
  no force push, no history rewrite. Preserve the user's untracked and uncommitted work.

### Staging discipline

- **NEVER `git add .` and NEVER `git add -A`.** Stage explicit paths only.
- Before every commit, inspect what is actually staged:

```bash
git diff --cached --name-only
```

```bash
git diff --cached --stat
```

- Never sweep unrelated or untracked files into a commit. Untracked run captures, local
  assessments and scratch files stay untracked unless the user asks for them.

## Development rules

- One gate at a time. Never build the next gate's artifacts while the current one is open.
- Do not redesign frozen architecture; amend the ADR first if a decision must change.
- No synthetic validation, no invented metrics, no performance or impact claims.
- State what was not done as plainly as what was.

## Authoritative documents

`PROMISEPATCH_PRODUCT_SPEC.md`, `ARCHITECTURE_PLAN.md` and `new_roadmap.md` are frozen,
gitignored, local-only and **authoritative whenever present**. Read them before deciding
anything they cover. Never modify them unless explicitly asked. Never commit them.

`docs/adr/` holds every architectural decision, `0001` through `0020`. The ones that constrain
day-to-day work most: [0008](docs/adr/0008-remove-runtime-customer-intent-classifier.md) (no
runtime intent classifier), [0011](docs/adr/0011-conversational-orchestrator-authority.md) (the
orchestrator holds no authority), [0013](docs/adr/0013-read-only-observer-principal.md) and
[0016](docs/adr/0016-a-judge-principal-stays-read-only.md) (a judge principal stays read-only),
[0015](docs/adr/0015-a-spoken-yes-checked-by-the-server.md) (a spoken yes is checked by the
server), [0018](docs/adr/0018-a-plan-confirmation-spends-a-human-approval.md) (a plan
confirmation spends a human approval), and
[0019](docs/adr/0019-a-benchmark-world-is-installed-at-a-run-local-anchor.md) (a benchmark world
is installed at a run-local anchor; production keeps the ordinary clock), and
[0020](docs/adr/0020-a-scored-benchmark-hosts-the-product-s-own-worker.md) (a scored benchmark
hosts the product's own worker; no deployed process ever learns the benchmark exists).

## Historical record

Completed work is recorded in `docs/` and is not summarized here. When you need the detail,
read the source document rather than a paraphrase of it.

| Area | Document |
|---|---|
| Semantic boundary and its hardening | [semantic-boundary.md](docs/semantic-boundary.md), [p4.9-semantic-failure-hardening.md](docs/p4.9-semantic-failure-hardening.md) |
| Explanation quality gate (closed) | [explanation-quality-gate.md](docs/explanation-quality-gate.md) |
| Product contract and MCP surface | [p5-product-contract.md](docs/p5-product-contract.md), [p5.1-mcp-transport-spine.md](docs/p5.1-mcp-transport-spine.md), [p5.2-mcp-clarification-and-confirmation.md](docs/p5.2-mcp-clarification-and-confirmation.md) |
| Orchestrator, recovery and workspace | [p5.3-conversational-orchestrator.md](docs/p5.3-conversational-orchestrator.md), [p5.4-truthful-recovery-and-case-workspace.md](docs/p5.4-truthful-recovery-and-case-workspace.md), [case-workspace-closeout.md](docs/case-workspace-closeout.md) |
| Deployment | [p6.1-deployment-preflight.md](docs/p6.1-deployment-preflight.md), [p6.2-first-deployment.md](docs/p6.2-first-deployment.md), [head-redeploy-2026-09-16.md](docs/head-redeploy-2026-09-16.md), [non-destructive-release.md](docs/non-destructive-release.md) |
| Judge-facing UX | [p7.1-judge-ux-contract.md](docs/p7.1-judge-ux-contract.md), [p7.1-design-handoff.md](docs/p7.1-design-handoff.md), [p7.3-deployed-judge-surface.md](docs/p7.3-deployed-judge-surface.md) |
| Effect sets | [effect-set-manifest.md](docs/effect-set-manifest.md), [effect-set-harness.md](docs/effect-set-harness.md), [effect-set-run-protocol.md](docs/effect-set-run-protocol.md), [effect-set-first-scored-run.md](docs/effect-set-first-scored-run.md), [effect-set-failure-diagnosis.md](docs/effect-set-failure-diagnosis.md) |
| Comparative benchmark (`SUR-1`, frozen, run once) | [safe-useful-recovery-benchmark.md](docs/safe-useful-recovery-benchmark.md), [sur1-execution-harness.md](docs/sur1-execution-harness.md), [sur1-execution-bindings.md](docs/sur1-execution-bindings.md), [sur1-execution-predeclaration.v1.md](docs/benchmarks/sur1-execution-predeclaration.v1.md), [sur1-world-programs.md](docs/sur1-world-programs.md), [sur1-world-events.md](docs/sur1-world-events.md), [sur1-scored-authorisation.md](docs/sur1-scored-authorisation.md), [sur1-pre-run-audit.md](docs/sur1-pre-run-audit.md), [sur1-consent-ingress.md](docs/sur1-consent-ingress.md) |
| G7 and G8 | [g7-closeout.md](docs/g7-closeout.md), [g8-adversarial-proof-map.md](docs/g8-adversarial-proof-map.md), [g8-head-of-line-measurement.md](docs/g8-head-of-line-measurement.md), [g8-head-of-line-disposition.md](docs/g8-head-of-line-disposition.md), [head-of-line-correction.md](docs/head-of-line-correction.md), [adversarial-race-proofs.md](docs/adversarial-race-proofs.md) |
| Started work and the hold contract | [started-work-contract.md](docs/started-work-contract.md) |
| SUR-1 hosted worker (arm C reaches an evaluator, unrun) | [sur1-hosted-worker.md](docs/sur1-hosted-worker.md) |
| SUR-1 dress rehearsal (`DR01`, not a benchmark) | [sur1-dress-rehearsal.md](docs/sur1-dress-rehearsal.md) |
| SUR-1 scored environment | [sur1-scored-environment.md](docs/sur1-scored-environment.md) |
| SUR-1 phase 3 closeout (harness scope-frozen) | [sur1-phase3-closeout.md](docs/sur1-phase3-closeout.md) |
| SUR-1 first scored run (taken once, inconclusive) | [sur1-first-scored-run-defect.md](docs/sur1-first-scored-run-defect.md) |
| SUR-1 execution revision `v2` (harness corrected, unrun) | [sur1-execution-revision.v2.md](docs/benchmarks/sur1-execution-revision.v2.md) |
| SUR-1 `v2` validated live (one defect found and fixed, still unrun) | [sur1-revision-v2-live-validation.md](docs/benchmarks/sur1-revision-v2-live-validation.md) |
| SUR-1 second scored run (taken once, refused before any arm acted, zero spend) | [sur1-corrected-scored-run-refusal.md](docs/sur1-corrected-scored-run-refusal.md) |
| SUR-1 execution revision `v3` (one database target, gated, unrun) | [sur1-execution-revision.v3.md](docs/benchmarks/sur1-execution-revision.v3.md) |
| SUR-1 third scored run (taken once, **invalid**, preserved) | [sur1-v3-scored-run.md](docs/sur1-v3-scored-run.md), [sur1-v3-forensic-audit.md](docs/sur1-v3-forensic-audit.md) |
| SUR-1 parity correction (five defects closed, ablation reach open) | [sur1-parity-correction.md](docs/sur1-parity-correction.md) |
| Consent, withdrawal and confirmation | [a-spoken-yes.md](docs/a-spoken-yes.md), [bounded-withdrawal.md](docs/bounded-withdrawal.md), [mcp-human-confirmation-boundary.md](docs/mcp-human-confirmation-boundary.md), [customer-intent-classifier-removal.md](docs/customer-intent-classifier-removal.md) |
| Customer approval transport | [customer-approval-link.md](docs/customer-approval-link.md) |
| Demo world and seeded case | [seeded-demo-case.md](docs/seeded-demo-case.md), [demo-fixture-anchoring.md](docs/demo-fixture-anchoring.md), [demo-world-roll.md](docs/demo-world-roll.md) |
| Order system | [order-system.md](docs/order-system.md) |
| Claims against their evidence | [claims-audit.md](docs/claims-audit.md) |
