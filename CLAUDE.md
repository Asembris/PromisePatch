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
- **A customer's channel address is kept where it is used and masked where it is read out.** The
  outbox row, the approval request, the decision row and the audit ledger hold it whole, because
  addressing a message, comparing a reply's sender to the channel a request was sent to (§14.3
  check 8) and saying afterwards what those values were all need it. A log, a terminal, an HTTP
  response and a rendered page get the channel kind and nothing else. Masked, never hashed: a
  ten-digit chat id is a space a GPU walks in seconds, so a digest would publish it while looking
  careful. See ADR-0021.

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
  **The deployed image is `4529a802e34e`**, the approval-log privacy repair, released 2026-09-24 by
  the same parameter-only change set (`Changes: []`), the host rebooted and never replaced; see
  [phase7-approval-log-privacy-repair.md](docs/phase7-approval-log-privacy-repair.md). The Phase 7
  RC `abbbd11006f7` before it is [phase7-rc-deployment.md](docs/phase7-rc-deployment.md).
  The `931a296decad` release of 2026-09-23 could not go through `deploy.sh stack` — measured again, live: the
  deployed stack's template predates the channel block, so submitting it reports
  `Replacement: Conditional` on `Host` and `ElasticIpAssociation` and the guard refuses,
  correctly, deleting its change set unexecuted. It was carried the way `4cfb74de7cc2` was, by a
  parameter-only change set against the *previously deployed* template, authorised explicitly and
  gated on an empty resource change list. **That is a documented one-off, not a release path**, and
  [non-destructive-release.md](docs/non-destructive-release.md) §10.1's gap is unchanged: the
  stack's recorded template can only be moved by replacing the host. **Smoke is `9/12` from this
  operator machine and the three gaps are not the deployment**: `mcp-requires-bearer`,
  `origin-refused` and `host-refused` time out in the client while Caddy's own log shows `401` and
  `403` answered in milliseconds, and the same three probes run *on the host* answer `401`, `403`
  and `421` in ~20 ms. The local TLS-intercepting antivirus proxy truncates small non-2xx bodies.
  Do not read those three as a broken deployment, and do not claim `12/12` from here.
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
- **`SUR-1` has been taken five times. The first four are not comparative results; the fifth is
  comparative on outcomes and still says nothing about models.** The first four are preserved
  byte-identical and pinned in two places; the correct response to a digest
  moving is to restore the run, never to update the pin. The third, `20260920T1215Z-scored-v3`, is **invalid** —
  five arm-correlated defects were proved in it afterwards. All five are now corrected and the
  preflight asks 28 questions rather than 18. The last of them — arm C's ablation reaching no
  evaluator, which made the ablated arm unmeasurable rather than unmeasured — is closed by
  [ADR-0020](docs/adr/0020-a-scored-benchmark-hosts-the-product-s-own-worker.md): the product's
  own durable worker runs inside the harness process for **both** arms B and C, and the
  containerised worker is down for the run. The scored preflight passes **28/28** against a
  Bedrock-configured local stack. **The fourth run, `20260921T0910Z-scored-v4`, has now been
  taken** at `DRIVER_VERSION` `1.4.3` and is preserved exactly as it came out: 27 attempts, 0
  retries, arm A unscored on all nine, arms B and C scored on eight of nine having called the
  model zero times, and every safety counter `0`. **It says nothing comparative.** It is the
  first run in which arm C's ablation reached the evaluator, and on `C06` the dropped check is
  recorded changing a decision inside an attempt that failed closed. See
  [sur1-fourth-scored-run.md](docs/sur1-fourth-scored-run.md). **All three defects that run
  recorded unpatched are now closed**, harness-only, at `DRIVER_VERSION` `1.5.0`: the executor
  evidence reads the product's four durable-execution audit rows instead of every `SYSTEM` actor,
  so the harness's own world facility is no longer a competing worker (arm-blind); the baseline's
  `scenario_id` is the world's and not the model's; and the baseline's `promises[].order` is
  translated through the frozen fixture's own bijection, the one `E1` has always used. The last
  two affect arm A only and **both flatter it**. Arms B and C reaching no model is unchanged and
  stays a disclosed limitation. `20260921T0910Z-scored-v4` is now pinned in `PUBLISHED_RUNS` and
  all four runs recompute byte-identical. `implementation_sha`, `PREDECLARATION_SHA`,
  `SCORER_VERSION`, the manifest, the prompt, the world programs, the ground truth, the budgets
  and the retry policy are unmoved, and `REQUIRED_CHECKS` is still 28. **The fifth run,
  `20260921T1420Z-scored-v5`, is the first taken under `1.5.0`** and is preserved exactly as it
  came out: 28 attempts (27 plus one in-policy retry of the single `VOID`), arm A at 124 model
  calls scoring 5 `DISQUALIFIED` / 2 `BUDGET_EXHAUSTED` / 1 each safe-complete and
  safe-incomplete with 12 safety violations, arms B and C both 8 `SAFE_AND_COMPLETE` + 1
  `SAFE_AND_INCOMPLETE` with every safety counter `0` — **having called the model zero times**.
  Arm C's ablation reached the evaluator on six attempts and on `C06` is recorded changing a
  decision, without changing the verdict or raising a counter. **It is not a model comparison**,
  and arm C is identical to arm B on all nine scenarios. It is **now pinned in
  `PUBLISHED_RUNS`**, by a later session that scored nothing; **all five published runs are
  pinned and recompute byte-identical**, and the `scripts/sur1/` scope-freeze tree moved solely
  for that pin. See [sur1-fifth-scored-run.md](docs/sur1-fifth-scored-run.md) and the fifth
  later-truth note in [sur1-phase3-closeout.md](docs/sur1-phase3-closeout.md) section 8. One
  focused rehearsal preceded it: `dr01-v150-focused` drove all three
  corrections live at `DR01`, reaching no model and minting no authorisation, and each behaved as
  the revision claims. See
  [sur1-execution-revision.v4.md](docs/benchmarks/sur1-execution-revision.v4.md) and
  [sur1-v150-focused-rehearsal.md](docs/sur1-v150-focused-rehearsal.md). `DR01`
  **completed with all three arms whole** at
  `DRIVER_VERSION` `1.4.3`, and proved what ADR-0020 was written for: arm B's revalidation check
  5 carries the evaluator's own name, arm C's carries `ABLATED_MARK` exactly, checks 1–4 and 6–10
  are identical, and one hosted worker executed every governed write with no foreign worker in
  any row. Arm A's own defect is **closed**: the rehearsal contract declared a `report_outcome`
  write and no `run_report_schema`, so `adapters.tool_specifications` died on a `KeyError` — a
  rehearsal-only failure since `1.2.0`, harmless to a scored run because the frozen manifest
  carries the block. The rehearsal document now shapes its own report, a contract that shapes
  none is refused by name rather than defaulted, and the rehearsal's readiness builds arm A's
  actions before an arm is driven. **Nothing here is comparative**: a rehearsal measures whether
  the pipeline composed. See [sur1-v3-forensic-audit.md](docs/sur1-v3-forensic-audit.md),
  [sur1-parity-correction.md](docs/sur1-parity-correction.md),
  [sur1-hosted-worker.md](docs/sur1-hosted-worker.md),
  [sur1-dr01-hosted-worker-rehearsal.md](docs/sur1-dr01-hosted-worker-rehearsal.md),
  [sur1-dr01-redrive.md](docs/sur1-dr01-redrive.md) and
  [sur1-dr01-final-rehearsal.md](docs/sur1-dr01-final-rehearsal.md) before touching anything here.
- **Telegram outbound is built, the deployed transport is switched on, and on 2026-09-22 one
  real approval message was delivered to a phone.** One adapter behind the existing provider
  boundary sends the frozen message and
  its signed link, selected by `PP_CUSTOMER_CHANNEL_PROVIDER=telegram`; the fake provider remains
  the default everywhere and is what CI, every test and the local stack use. On **2026-09-22 the
  existing host was migrated in place** through `ssm:StartSession`, without a release, a reboot,
  a host replacement or an IAM change: the committed `converge.sh` channel block was reproduced
  on the host, which read every value from SSM with its **own instance role**, so no credential
  passed through the operator's shell. The deployed `api` and `worker` now report
  `provider: telegram`, a forged approval link moved from `503 CUSTOMER_LINKS_NOT_CONFIGURED` to
  `404 LINK_NOT_FOUND`, and smoke is 12/12. That migration produced a configured transport that
  still reached nobody, because no chat id was bound until the delivery below. The host's
  `converge.sh` is still the stale one, so
  `env/channel.env` is hand-written rather than derived and a rotated token would not be picked
  up until the migration is re-run or the host is replaced. See
  [deployed-customer-channel.md](docs/deployed-customer-channel.md) section 8, which also records
  why `deploy.sh config` must not be used to carry this: it rewrites `image-tag` from HEAD and
  would name an image no `images` stage ever built.
  **The first real delivery was taken on 2026-09-22.** The stale world that blocked it was
  repaired with the documented destructive reset, authorised by the project owner, which cost
  the four deployed cases and preserved both ledgers of record — `audit_events` and
  `domain_events` only grew. The fresh provisioned case restores the canonical partition, the
  canonical demo customer alone was bound to a verified private chat through
  `pp channel bind-demo-customer`, and one plan confirmation on the operator console queued
  exactly one customer approval, which the durable worker dispatched. Telegram answered
  `200 OK`, the `provider_ref` is persisted, the `MESSAGE_SEND` row is `DELIVERED` at one
  attempt, and the operator confirmed exactly one message on the device. The ordering is
  load-bearing and is not negotiable — **reseed, then bind, then propose** — because the reset
  truncates `customers` and erases a binding taken before it. See
  [deployed-customer-channel.md](docs/deployed-customer-channel.md) section 10.
  **The customer then answered that message on the web, and the loop closed.** The signed
  possession link was opened on the phone and `APPROVE` chosen; exactly one
  `approval_decisions` row exists, `APPROVE` via the `LITERAL` parser, bound to the existing
  `pr-b` request, which moved `SENT` → `ANSWERED`. The durable worker wrote all ten
  `REVALIDATION_CHECK` rows against a **fresh** snapshot — `_revalidate` calls
  `analysis.fresh_snapshot`, never the one planning or the approval used — every check passed,
  and only then did `APPLY_RECOVERY` run. `EXT-B` went `ACCEPTED @ v1` → `AMENDED @ v2`, `ol-b`
  `rv-raspberry-rose-2` → `rv-raspberry-rose-3`, `pr-b` settled `RECOVERED`, and the case left
  `WAITING` for `RESOLVED`. `plan_approvals` stayed `1`: a customer's yes spends no worker
  approval. No refusal path was exercised live and no drift was manufactured, so `STALE`,
  `EXPIRED`, `UNAUTHORIZED` and `NOOP` remain proved only by their tests. **The chat id reaches
  the operator read surface too** — `pp case-status` prints it inside `provider_ref`, and the
  decision and reply rows carry it as `sender_identity` — which widens the known logging defect
  and is recorded, not fixed. See
  [deployed-customer-channel.md](docs/deployed-customer-channel.md) section 11.
  **The message no longer tells the customer to reply, and their chat id no longer leaves the
  database.** ADR-0021 amends §13.6's frozen literal: the instruction names the signed link,
  because the link is the only door that opens. The chat id was reaching five read surfaces, two
  of them public — the `GET /api/cases/{id}` response and the deployed SPA's evidence drawer both
  rendered `provider_ref` verbatim — and all five are masked at the boundary. **The host's
  `converge.sh` is no longer stale**: the committed script is installed, and the release's own
  reboot proved it regenerates `env/channel.env` from SSM under the instance role, byte-identical
  to the hand-written file. Two limitations stand: no refusal path has been exercised live, and
  CloudWatch still holds the lines written before the redaction. See
  [customer-disclosure-hardening.md](docs/customer-disclosure-hardening.md).
  **Telegram inbound stays unbuilt and deliberately so**: a second route for the word `YES`
  would be a second consent parser. That is now measured rather than asserted — after the
  delivery above, and **before** the web approval, the operator typed a literal `YES` into the
  bot's own chat and it reached nothing: `inbound_replies` 0, `approval_decisions` 0, the
  request still `SENT` at that point, and zero `getUpdates` calls ever made. The single
  `inbound_replies` row this deployment now holds came from the signed link, not from Telegram. The Bot API offers no idempotency key, so a retry in the
  uncertain window is a real duplicate *message* and never a duplicate effect; that is the
  at-least-once case `outbox.py` already names, and it is disclosed rather than engineered
  around. Correcting a physical fact is CLI-only. A customer answers on the web, through a
  signed possession link carried in the outbound message's payload — a transport into the
  unchanged consent protocol, never a second one. See
  [customer-message-transport.md](docs/customer-message-transport.md) and
  [customer-approval-link.md](docs/customer-approval-link.md).
- **The four-step destructive demo repair is one command, and it has now been run on the deployed
  host.** `pp restore-demo-world --confirm destroy-and-restore` sequences the repair
  `docs/demo-fixture-anchoring.md` wrote down and section 10 above performed: reseed at
  `resolve_demo_anchor(now)`, reset the External Order System, provision the canonical case,
  rebind. **Every refusal is taken before the first destructive statement** — a world that is not
  the demo fixture by name, a customer topology this did not create, a `PENDING` or `IN_FLIGHT`
  outbox row, an unreachable order system, or a bound destination the provider will not confirm.
  A binding is **carried in memory and written back through `bind_demo_customer_channel`**, the
  one binding mechanism there is; nothing is persisted anywhere new and the address reaches no
  output, no log and no `repr`. It confirms no plan, creates no approval request or decision and
  sends no message; `_what_would_be_lost` and the world roll are untouched and unreachable from
  it. Local proof on 2026-09-23: the canonical partition restored, ledgers `176825 → 176838` and
  `227944 → 227962`, every authority counter `0`, 316 related tests green with
  `test_demo_world_roll` unchanged. **The deployed proof was taken on 2026-09-23**, once, carrying
  the real Telegram binding across: exit `0`, `binding: restored`, a fresh anchor, one canonical
  `PLANNED` case, the order book reset to version 1, ledgers `219 → 233` and `279 → 298` with
  `seq` contiguous from `1`, outbox and every authority counter `0`, exactly one customer bound
  and five back at placeholders — and **zero `sendMessage`, zero `worker.telegram.sent`** across
  the whole run. The restored destination still verifies: `returned_id_matches_stored=True`,
  `chat_type=private`, no message sent, and **the chat id reached no output, log or transcript** —
  measured, not asserted. The restore rebooted nothing: host `boot_id` unchanged across it, no
  stack update, no volume removed, certificate and RDS untouched. **Two things it does not say**:
  no refusal path was exercised live, and **no deployed container holds the settings the command
  needs** — the reseed's four live in `env/migrate.env` while provisioning and the channel live in
  `env/api.env`, so the run needed them supplied on the host. That is a defect recorded unfixed.
  See [demo-world-restore.md](docs/demo-world-restore.md).
- **The deployed RC has run the real customer loop once, end to end** (2026-09-24): restore, plan
  confirmation, one Telegram delivery, a real web `APPROVE`, ten revalidation checks, `EXT-B` v1 → v2,
  case `RESOLVED`, `HUMAN_APPROVAL` throughout. **It found a P1, recorded and not fixed**: the
  approval-link token, whose payload base64-encodes the customer's chat id, is logged verbatim by the
  `api` and `caddy` access logs, which ship to CloudWatch. A plaintext address scan cannot see it. See
  [phase7-deployed-behavioral-proof.md](docs/phase7-deployed-behavioral-proof.md).
  **That P1 is closed on `4529a802e34e`**: every backend log line and both Caddy loggers redact the
  link in both URL forms, and the real loop was re-proved with zero recoverable token in any
  container log or in CloudWatch. Two spent, non-actionable tokens remain in CloudWatch history
  until retention expires them; see
  [phase7-approval-log-privacy-repair.md](docs/phase7-approval-log-privacy-repair.md).

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
| `apps/backend/src/promisepatch/demo_restore.py` | The guarded destructive demo repair. Demo tooling, never a general reset. |
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

`docs/adr/` holds every architectural decision, `0001` through `0026`. The ones that constrain
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
hosts the product's own worker; no deployed process ever learns the benchmark exists), and
[0021](docs/adr/0021-a-customer-answers-on-the-web-and-their-address-stays-in-the-database.md)
(a customer answers on the web, and their address stays in the database), and
[0022](docs/adr/0022-an-approval-episode-is-opened-by-the-confirmation-that-asks.md) (an
approval episode is one track asked under one confirmed plan; a re-ask is a new request), and
[0023](docs/adr/0023-a-re-plan-returns-the-case-to-planned-for-that-track-only.md) (a re-plan
returns the case to `PLANNED` for that track only; a revalidation round ends once), and
[0024](docs/adr/0024-freshness-is-judged-where-the-effect-is-committed.md) (the approval deadline
governs the answer; the production start is re-judged in the transaction that commits the
amendment), and
[0025](docs/adr/0025-an-answer-is-revalidated-when-it-arrives.md) (an answer is revalidated when
it arrives, not when a silent sibling's window closes; `RECONCILING` finishes its change first and
may be entered more than once), and
[0026](docs/adr/0026-a-first-dispatch-that-provably-sends-nothing-is-judged-again.md) (an
amendment's first dispatch claim, `attempts == 1`, re-judges the production start and refuses
unsent; from the second claim nothing refuses it).

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
| SUR-1 `DR01` through the hosted worker (incomplete, one defect found) | [sur1-dr01-hosted-worker-rehearsal.md](docs/sur1-dr01-hosted-worker-rehearsal.md) |
| SUR-1 `DR01` re-driven (B/C proved, arm A blocked on a second defect) | [sur1-dr01-redrive.md](docs/sur1-dr01-redrive.md) |
| SUR-1 `DR01` final rehearsal (all three arms whole, no new defect) | [sur1-dr01-final-rehearsal.md](docs/sur1-dr01-final-rehearsal.md) |
| SUR-1 `1.5.0` focused rehearsal (the three `v4` corrections, driven live) | [sur1-v150-focused-rehearsal.md](docs/sur1-v150-focused-rehearsal.md) |
| SUR-1 scored environment | [sur1-scored-environment.md](docs/sur1-scored-environment.md) |
| SUR-1 phase 3 closeout (harness scope-frozen) | [sur1-phase3-closeout.md](docs/sur1-phase3-closeout.md) |
| SUR-1 first scored run (taken once, inconclusive) | [sur1-first-scored-run-defect.md](docs/sur1-first-scored-run-defect.md) |
| SUR-1 execution revision `v2` (harness corrected, unrun) | [sur1-execution-revision.v2.md](docs/benchmarks/sur1-execution-revision.v2.md) |
| SUR-1 `v2` validated live (one defect found and fixed, still unrun) | [sur1-revision-v2-live-validation.md](docs/benchmarks/sur1-revision-v2-live-validation.md) |
| SUR-1 second scored run (taken once, refused before any arm acted, zero spend) | [sur1-corrected-scored-run-refusal.md](docs/sur1-corrected-scored-run-refusal.md) |
| SUR-1 execution revision `v3` (one database target, gated, unrun) | [sur1-execution-revision.v3.md](docs/benchmarks/sur1-execution-revision.v3.md) |
| SUR-1 third scored run (taken once, **invalid**, preserved) | [sur1-v3-scored-run.md](docs/sur1-v3-scored-run.md), [sur1-v3-forensic-audit.md](docs/sur1-v3-forensic-audit.md) |
| SUR-1 fourth scored run (taken once, comparatively empty, preserved) | [sur1-fourth-scored-run.md](docs/sur1-fourth-scored-run.md) |
| SUR-1 execution revision `v4` (three defects closed, harness-only, unrun) | [sur1-execution-revision.v4.md](docs/benchmarks/sur1-execution-revision.v4.md) |
| SUR-1 fifth scored run (taken once, comparative on outcomes, not on models, preserved) | [sur1-fifth-scored-run.md](docs/sur1-fifth-scored-run.md) |
| SUR-1 parity correction (five defects closed, ablation reach open) | [sur1-parity-correction.md](docs/sur1-parity-correction.md) |
| Consent, withdrawal and confirmation | [a-spoken-yes.md](docs/a-spoken-yes.md), [bounded-withdrawal.md](docs/bounded-withdrawal.md), [mcp-human-confirmation-boundary.md](docs/mcp-human-confirmation-boundary.md), [customer-intent-classifier-removal.md](docs/customer-intent-classifier-removal.md) |
| Customer approval transport | [customer-approval-link.md](docs/customer-approval-link.md), [customer-message-transport.md](docs/customer-message-transport.md) |
| Deployed customer channel (switched on, one real delivery, one real web approval) | [deployed-customer-channel.md](docs/deployed-customer-channel.md) |
| Customer copy and address disclosure (both closed, deployed) | [customer-disclosure-hardening.md](docs/customer-disclosure-hardening.md) |
| Phase 7 local release-candidate gate (closed locally) | [phase7-local-rc-correctness.md](docs/phase7-local-rc-correctness.md), [phase7-local-rc-final.md](docs/phase7-local-rc-final.md) |
| Phase 7 RC deployment (`abbbd11006f7` deployed, demo world restored once, not pushed) | [phase7-rc-deployment.md](docs/phase7-rc-deployment.md) |
| Phase 7 deployed behavioural proof (real loop closed on `abbbd11006f7`; one P1 recorded unfixed) | [phase7-deployed-behavioral-proof.md](docs/phase7-deployed-behavioral-proof.md) |
| Phase 7 approval-log privacy repair (P1 closed, `4529a802e34e` deployed, loop re-proved) | [phase7-approval-log-privacy-repair.md](docs/phase7-approval-log-privacy-repair.md) |
| Demo world and seeded case | [seeded-demo-case.md](docs/seeded-demo-case.md), [demo-fixture-anchoring.md](docs/demo-fixture-anchoring.md), [demo-world-roll.md](docs/demo-world-roll.md) |
| Demo world restore (local proof only) | [demo-world-restore.md](docs/demo-world-restore.md) |
| Order system | [order-system.md](docs/order-system.md) |
| Claims against their evidence | [claims-audit.md](docs/claims-audit.md) |
