# CLAUDE.md — PromisePatch operating contract

## Purpose

PromisePatch turns one spoken physical-world exception ("today's raspberry delivery didn't
arrive") into a correct, consent-respecting, selectively-applied set of customer-promise
recoveries, with the reasoning visible. Made-to-order bakery vertical.

## Current state

Deterministic engine, backend foundation, and PostgreSQL baseline schema are complete. The
P4.8 explanation quality gate is **closed**. Its two-run DEVELOPMENT allowance is spent, the one
bounded production repair with it, and the repaired run (`7172c7c894ae`) established that Nova's
verbalisation is safe -- every structural and semantic hard gate zero, faithfulness 5.00 -- and did
not establish that it is complete: nine of twenty-one passages cite a required fact and never say
it, and the judge scored causal completeness 5 on all nine.

P4.8 therefore closes with a selection rather than a further measurement. **User-facing explanations
are rendered deterministically by `promisepatch.domain.explanations.render`**, reached through
`verbalisation.explain`, with `PP_EXPLANATION_VERBALISATION` off by default. The bounded Nova
verbalisation path -- prompt, schema, validators, `prepare`, the dataset, the thresholds, the judge
and both DEVELOPMENT result files -- is preserved intact as evaluated-but-not-selected capability,
one variable away from a later phase with a repaired instrument or a different model. `prepare`
stays ungoverned by that setting so the evaluation harness keeps measuring the model it is pointed
at. Both holdouts -- explanation and customer-intent semantic -- remain sealed and unopened; the
explanation one stays sealed permanently for P4.8, because DEVELOPMENT already answered the shipping
question (see `docs/explanation-quality-gate.md`, *Closeout*).

**P4.9 is closed, and with it Phase 4.** The semantic layer was audited against a bounded threat
set -- injection, cross-kind contamination, adversarial structured output, invented entities and
authority, bootstrap failure, outage, timeout, bounded retry, stale and duplicated results,
replay, consent-authority attacks, late arrival, and both explanation paths. No authority or
correctness defect was found: nothing a model says, fails to say or fails to answer can reach a
write, a consent decision or a physical attestation. Four containment defects were found and
fixed, all of the same shape -- an untyped exception escaping the boundary's two-kind failure
vocabulary, past callers that catch only those two: an over-long worker statement, a Bedrock
response envelope of the wrong shape, an order-system display label too long for one fact, and a
persisted reading carrying none. Eight adversarial proofs were added, offline, zero model calls,
$0. Both holdouts remain sealed. See `docs/p4.9-semantic-failure-hardening.md`.

**P5 is open, and its G5 contract-locking work is done.** Before any P5 implementation, four
things were fixed and committed. The **frozen 16-scenario effect-set manifest**
(`docs/effect-sets/scenarios.v1.json`, `promisepatch-effect-sets` v1.0.0, manifest SHA
`d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc`) declares, per scenario, the
expected order partitions at every ordered checkpoint plus the exact operational effects and
refusals, hand-labelled from stipulated facts and never from engine output; it reuses the
Hollow Oak fixture universe and is structurally verified by
`scripts/verify_effect_set_manifest.py`, which imports no classifier. **ADR-0008** records the
superseding decision to remove the runtime apparent-intent classifier, keeping the literal
parser, the confirmation prompt and every historical measurement unedited. **The P5 product
contract** (`docs/p5-product-contract.md`) locks the conversational authority boundary, the
truthful `PLANNED`/`REQUESTED`/`RECOVERED` state vocabulary, the zero-incident-caused-effect
definition and the first case-workspace hierarchy. Labels precede the *remaining*
implementation, not the pre-existing engine, and that chronology is stated wherever the score
will be. Both holdouts stay sealed; P4.8 stays closed. See `docs/effect-set-manifest.md`.

**P5.1, the MCP transport spine, is done.** The real authenticated Streamable HTTP boundary
exists: `mcp==2.2.0` pinned exactly, serving protocol revision **2025-11-25** through the
`initialize` handshake, stateless, at `POST /mcp` in its own `mcp` process (`pp mcp`). Two of
the five frozen intent tools are implemented -- `report` and `status` -- and the other three are
absent rather than stubbed. The process reaches a case only by an authenticated HTTP call to the
API's new `/internal/intents`, enforced by an import-linter contract that forbids it the domain,
the database, the API package and SQLAlchemy. The attesting worker comes from the intent API's
own `PP_SURFACE_WORKER_ID`; no request field anywhere in the chain carries an actor, and the
clock is the server's. `report` stores the worker's sentence byte for byte; `status` is rendered
deterministically by `promisepatch.domain.status_view` from the durable case and is delivered as
given. Every tool call mints a correlation id that reaches the governed audit row. Proved
offline with a real server and the official SDK client -- handshake, negotiation, discovery,
successful and invalid calls, authentication, `Origin` 403 / `Host` 421, JSON-RPC errors and
reconnect -- plus a PostgreSQL suite that drives the whole chain and asserts the rows. No live
model call: nothing in this slice reaches a provider. See `docs/p5.1-mcp-transport-spine.md` and
ADR-0009.

**P5.2, clarification and plan confirmation, is done.** The surface is now four of the five
frozen tools -- `report`, `clarify`, `confirm`, `status` -- with the bounded withdrawal still
absent rather than stubbed. `clarify` stores the worker's answer to the one open question byte
for byte and hands the case back to the interpreter, concluding nothing; which physical outcome
that answer selects is decided by the worker process, against options captured from the
delivery's own rows when the question was asked. `confirm` requires a **`plan_id`**: a derived,
opaque, never-stored SHA-256 identity of the plan `status` presented, covering the case version
and every track including the untouched ones, recomputed and compared under the confirming lock
and refused if the case has moved on. A yes therefore authorises the plan that was read out and
nothing else -- stale, wrong-case, replayed and repeated confirmations all fail closed through
existing domain semantics, and worker plan confirmation stays wholly distinct from customer
consent. `status` now carries the open question with its options and, only on a `PLANNED` case,
the plan identity and `awaiting_confirmation`; both new tools' speech is rendered by
`status_view` and delivered as given, reporting permission and never completion. Proved by the
canonical conversation driven end to end over the real protocol -- report, question, answer,
plan, explicit yes, authorised status with nothing carried out -- plus staleness, replay and
wrong-state cases, offline protocol tests, and pure tests for the identity and the vocabulary.
No live model call. See `docs/p5.2-mcp-clarification-and-confirmation.md` and ADR-0010.

**P5.3, the truthful conversational orchestrator, is done.** A model is now in the loop and has
no authority it did not have outside it. One bounded semantic job, `select_tool`, returns a
**verb and nothing else**: `ToolSelection` has no field for a case, a plan, a person or any
wording, so a fabricated plan identity is refused because the field does not exist. Which verbs
are on offer is computed deterministically from a `status` reading the server rendered -- seven
closed phases, fail-closed to a read on any gap -- and is checked twice while remaining defence
in depth, because the domain checks every call again. A confirmation needs three independent
things: the phase permits it, the conversation holds the identity `status` returned, and the
worker's own turn is a plain yes by a closed literal parser that is stricter than the domain and
is not the consent parser. Everything a worker is told is rendered by `status_view` and
delivered unchanged; the model's optional glue is capped at 25 words, may hold no digit and none
of 39 outcome words, fails the whole answer rather than being trimmed, and is dropped unless the
turn acted. Two tool calls per turn, at most one effecting, the second always `status`; nothing
is retried. `promisepatch.orchestrator` is a client -- forbidden the domain, the database, the
API, the engine, SQLAlchemy, an AWS SDK and the MCP server's internals. Proved by the canonical
six-turn conversation end to end over the real transport against PostgreSQL, plus 73 offline
tests including the adversarial set (invalid verb for the state, fabricated identity, a
confirmation the worker never gave, provider and tool outages, staleness between decision and
call, and an unsupported final-language claim). **One bounded live Nova conversation** ran once:
all six verbs correct, one attempt each, 9,689 ms wall clock, 10,360 input and 165 output
tokens, case at `EXECUTING` with nothing carried out -- no dollar figure is published because
the rate could not be verified from this account. No benchmark program was started. Both
holdouts stay sealed. See `docs/p5.3-conversational-orchestrator.md` and ADR-0011.

**P5.4, truthful recovery and the first case workspace, is done.** The confirmed canonical case
now runs through the recovery machinery to four real outcomes, and a person can see them. Over
the real MCP transport, a real worker process and the real External Order System: `EXT-A` reaches
`RECOVERED` only once the order system's own event came back, `EXT-B` reaches `REQUESTED` only
once the provider acknowledged delivery, `EXT-C` and `EXT-D` stay an explicit owner action with a
reason and a next action and no automatic step, and `EXT-E` and `EXT-F` carry **0 incident-caused
operational effects**. Each of the three word-rules is proved by holding the intervening state
open and reading the case out loud in the middle of it -- "changing the order now" before the
echo, no `provider_ref` and no "asked" while a message is queued, and an escalation rather than a
success when the order system refuses -- and a planned case drained through every worker cycle
without a confirmation raises no effect at all. `status_view` gained one pure addition, band 2's
single `next_action` with its `ActionOwner`, chosen by an ordered walk so an escalation outranks
a customer's clock; the spoken `status` rendering is unchanged. Two session-authenticated reads,
`GET /api/cases` and `GET /api/cases/{id}`, project one durable `read_case_status` into the
contract's five bands, and the workspace at `?case=<id>` renders them: the worker's own words,
one next action, promises grouped by authority, the untouched band with the backend's own count,
and a collapsed evidence drawer that arrives with the case. The screen renders and does not
decide -- every sentence, count and grouping arrives composed -- and the case id lives in the
address bar, so a reload, a restored tab and a second application process all land on the same
durable case. Proved by 9 end-to-end recovery tests, 13 workspace API tests against real
PostgreSQL and 18 frontend tests. No live model call; both holdouts stay sealed. See
`docs/p5.4-truthful-recovery-and-case-workspace.md`.

**The P5 deployment-entry subset is CLOSED, and P6 may begin.** The roadmap's 18 September
cutoff names a non-negotiable subset rather than the whole of G5, and every item of it is
closed in a committed record. Four real tools -- `report`, `clarify`, `confirm`, `status` --
served over authenticated Streamable HTTP with protocol revision 2025-11-25 pinned, an unlisted
`Origin` refused `403` and an unlisted `Host` `421` (P5.1, P5.2). Canonical orchestration, end
to end over that transport, with the model holding no authority it did not have outside the
loop (P5.3). Server-owned authority throughout: the worker identity and the original turn text
come from the server, and a confirmation binds to the exact plan that was read out (P5.1-P5.3).
Independent-client replay through the official SDK against the server `pp mcp` runs, and
reconnect as a fresh stateless session that picks the same durable case up (P5.1). A minimal
real-state case and status view in the truthful `PLANNED` / `REQUESTED` / `RECOVERED`
vocabulary, reached by a case id in the address bar so a reload or a second process lands on
the same durable case (P5.4). And the published frozen sixteen-scenario manifest, content hash
`d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc`. The whole-delivery branch
is proved **against that frozen identity**: the customer's own external order edit crosses as a
signed webhook before anybody speaks, the whole Valley Produce delivery then fails rather than
half of it, and the expected labels are loaded from the manifest -- S02's frozen labels with
S11's frozen `ord-d` argument applied -- with its published identity asserted before anything
else runs, rather than from anything the run observed.

**P6 is open, and its first slice, the deployment preflight, is CLOSED with no IAM gap
remaining.** The active identity is `PromisePatchDeveloperRole`, and a reproducible
zero-mutation preflight (`scripts/aws_preflight.py`, read-only by construction: a probe naming
an API outside a frozen list aborts the run) reported **2 of 9 required permissions** on its
first run, when the role held nothing but `sts:GetCallerIdentity` and `bedrock:InvokeModel` on
exactly the `us.amazon.nova-2-lite-v1:0` inference profile. One of those seven denials was the
preflight's own fault -- the ECR probe listed the whole registry, which a role scoped to
`repository/promisepatch/*` is correctly denied, so it manufactured a blocker that did not
exist; it now names a repository and reads `RepositoryNotFoundException` as authorization
proved. The account owner has since applied the delta, created both roles, and applied the
one corrected statement the 8-of-9 run identified: `logs:DescribeLogGroups` is evaluated
account-wide and cannot be scoped to `/promisepatch/*`, so it has its own statement with
`Resource: "*"` -- names only, no log content, with everything that can read a line still
scoped. **The preflight now reports 9 of 9 required permissions allowed and exits 0.** Its ECR
row proves the earlier correction against the live account in both directions at once: the named
`promisepatch/backend` is authorized and returns `RepositoryNotFoundException` because it does
not exist, while the registry-wide `repository/*` listing the old probe used is still correctly
denied. Twelve mutating requirements remain `DECLARED` rather than tested -- verified by hand
against their real resource ARNs -- because the script does not yet use the now-permitted
`iam:SimulatePrincipalPolicy`, which is the first P6.2 step. The committed
deployment-role trust policy is byte-identical to the live one: CloudFormation service
principal, no condition, the confused-deputy control having moved to the narrow `iam:PassRole`
in the developer delta. **Nothing was created in AWS by this work and IAM was not broadened by
it.** The
smallest architecture that closes G6 is chosen and fully written: one EC2 host running the same
images with the same per-container environment files as the local stack, a private encrypted RDS
PostgreSQL for the case state, Caddy terminating TLS with a publicly trusted certificate, ECR,
SSM Parameter Store for secrets and configuration, and CloudWatch Logs -- no load balancer, no
NAT gateway, no ECS, no Secrets Manager. Three roles with one job each, both `iam:PassRole`
grants fenced to a single role and a single service and additionally denied by `NotResource`,
and no `AdministratorAccess` anywhere. Cost is list-price arithmetic over declared quantities:
about $33 a month standing, and about $0.0039 per conversation from the measured P5.3 token
counts. **AgentCore is declined for this slice** and the roadmap's ordinary-compute fallback
taken, because the role cannot reach AgentCore at all, adopting it would replace the
authenticated Streamable HTTP boundary G5 closed, and it buys nothing this slice lacks. Nothing
of this project is deployed -- 0 stacks, 0 databases, no image repository and no log group,
though the account does carry an unrelated `careloop` project whose spend is not ours -- no
restart proof is taken, no deployed conversation has run and no Telegram work was started; G6 is
not advanced beyond this preparation. The one precondition still outstanding for P6.2 is a DNS
name for `TlsHostname`. See `docs/p6.1-deployment-preflight.md`.

**P6.2, the first real deployment, is CLOSED.** PromisePatch runs at
**`https://184.194.40.87.sslip.io`** on one `t4g.small` in `us-east-1b` against a private
encrypted RDS PostgreSQL, behind Caddy holding a real Let's Encrypt certificate -- the
deployment's own log records four Let's Encrypt validation servers fetching the HTTP-01
challenge, which is what makes the certificate claim checkable rather than asserted from a
laptop whose antivirus intercepts TLS. `TlsHostname` no longer needs a domain: left empty, the
stack derives `<elastic-ip>.sslip.io` from the address it allocates, so a first deploy needs no
record pointed at an address that does not exist yet, and nothing about TLS is weakened either
way. The seven deployment smoke checks pass **7/7**, four of them asserting refusals. The
canonical conversation runs end to end over the public MCP transport from outside AWS to four
real outcomes -- `EXT-A` recovered, `EXT-B` asked, `EXT-C`/`EXT-D` owner actions, `EXT-E`/`EXT-F`
untouched with **0 incident-caused effects**. A **real Bedrock Nova call succeeds from inside a
container on the deployed host**, on the instance role: `semantic.answered`,
`us.amazon.nova-2-lite-v1:0`, one attempt, repeated across a reboot -- and the case whose
utterance it read still sits at `NEEDS_HUMAN_INTERPRETATION`, because a reading that comes back
inside its schema authorises exactly as much as one that never arrives, which is nothing. A
confirmed case has survived a reboot, a stack update and a second reboot with identical
per-promise outcomes and no duplicated effect.

**Eleven defects were found that no amount of reading the definition could have found**, five by
AWS rejecting the stack, five by running it, and one by the account only granting what was asked
for -- including a reboot that silently re-seeded the database and erased the very cases the
deployment exists to prove outlive the host, and `HttpPutResponseHopLimit: 1`, which left every
container unable to reach IMDS and made the instance role unusable from inside. Each has an
offline test that reproduces it; the deployment suite went 47 to 57 and `scripts/` is 335
passing. Two IAM actions were needed and the account owner granted both --
`ec2:ModifyInstanceMetadataOptions` and `cloudformation:ContinueUpdateRollback`, each scoped to a
resource its role already owned. Two other denials were routed around *without* asking for IAM,
by making the template stop depending on a permission. IMDSv2 stays required, TLS verification is
on everywhere, and the database is private. The evidence UI is still not deployed and Telegram is
untouched. See `docs/p6.2-first-deployment.md`.

**Full G5 is not closed and is not claimed to be.** Three items are carried forward as explicit
G7 obligations, exactly as the cutoff directs and with no promised capability silently deleted:
the **bounded withdrawal**, which is the fifth frozen tool and remains absent rather than
stubbed; the **removal of the runtime customer-intent classifier**, whose superseding decision
is recorded in ADR-0008 but whose removal is a separate implementation slice that has not been
performed -- `domain.customer_intent` is still reached from the worker; and the **finishing of
the case workspace** beyond the minimal real-state view P5.4 shipped. Nothing here reopens the
locked roadmap, and P6 -- the deployed external loop -- may begin under it.

## Authoritative documents

`PROMISEPATCH_PRODUCT_SPEC.md`, `ARCHITECTURE_PLAN.md` and `new_roadmap.md` are frozen, gitignored,
local-only and **authoritative whenever present**. `new_roadmap.md` is the locked P5-P9 roadmap and
its per-phase acceptance gates; reopening it requires a reproduced correctness or eligibility blocker,
or a documented official rule change. Read them before deciding anything they cover. Never
modify them unless explicitly asked. Never commit them.

## Core rule

**The model understands; the deterministic protocol authorizes.**

## Key invariants

- The LLM never authorizes a write and never produces a consent decision.
- Customer consent is only a literal `YES` / option code / `NO`; free text is at most a
  non-authoritative apparent intent that can trigger one confirmation prompt.
- Recovery selects only pre-authored `RecipeVersion`s named by `SubstitutionPolicy`. Nothing
  at runtime creates, derives or synthesizes a version.
- The external order system is the system of record for orders. PromisePatch has no order
  editor; it writes to an order only as a governed recovery amendment.
- Physical facts (received / not received / spoiled / equipment out) are authoritative
  independently of recovery authorization. Declining a plan never un-spoils anything; only an
  explicit correcting attestation reverses a fact.
- A commitment line is open (`EXPECTED`) or settled. Settlement posts its physical outcome to
  the ledger exactly once, and a settled line contributes zero to expected supply. Received
  supply is never also counted as expected.
- Unknown or conflicting state fails closed to `BLOCKED` — never `UNAFFECTED`, never
  `AUTO_RECOVERABLE`.
- Promises not reachable from the exception are untouched: no message, no write, no
  reservation change, no task hold, no audit event.

## Architecture summary

One Python backend (`api`, `worker`, `mcp` entrypoints, plus the `converse` client), one pure engine package
(`promise_graph`), one React evidence UI, one separate External Order System simulator,
PostgreSQL as the single store, a persisted case state machine with a step ledger, Bedrock for
understanding only, MCP for the five intent tools, Telegram for the customer channel.
`promise_graph` depends on the standard library and Pydantic only, does no I/O, reads no
environment, and never calls the wall clock — time is passed in explicitly.

## Development rules

- One phase at a time. Never build Phase N+1 artifacts while in Phase N.
- Do not redesign frozen architecture; amend the ADR first if a decision must change.
- All gates must pass before a phase is complete: pytest with the coverage floor, the
  Hypothesis CI profile, mypy, ruff check, ruff format, import-linter.
- Never weaken, skip or delete a test to make code pass. Fix the code or fix the fixture data
  and say so.
- Secrets are never committed. No `.env`, no tokens, no credentials.
- No synthetic validation, no invented metrics, no performance or impact claims.

## Git

One-line Conventional Commit subjects. No body, no bullets, no trailers, no co-author line,
no generated-by line, no emoji. Example: `feat(engine): propagation`.
Never push unless explicitly asked.
