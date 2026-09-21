# Prerequisites, integration cost and limitations

**Status: drafted here, finalised in P9 with the final measured numbers.** Every figure below
is labelled *measured*, *estimated* or *not measured*, and the labels are the point. Where a
number could not be derived from this repository, this page says it was not measured rather
than supplying one.

Nothing on this page is written from what a system like this usually needs. Every prerequisite
names the file, table, column, constant or decision record that imposes it, so a reader can
check it rather than believe it.

## The obligation this page discharges

From the locked roadmap, verbatim:

> **Potential Impact without external evidence:** publish one
> prerequisites/integration-cost/limitations page (P7, finalized P9; 3-4 hours documentation).
> List required order/dependency/recipe-variant/constraint accuracy, who maintains it, worker
> permissions, customer identity/channel setup, adapter/auth/webhook/version contracts and
> hosting. Separate measured setup effort from estimates for an unbuilt commercial POS adapter.
> Demonstrate proposal delivery, consent, recovery and escalation through the actual supported
> loop; label fixtures and simulator. Disclose no commercial POS validation, no operator study,
> no adoption/demand evidence and no measured labor savings or ROI. **4/5 is the defensible
> planning ceiling for Impact; 5/5 is not an evidence-supported projection.** The official
> criterion does not formally require external validation, but controlled artifacts cannot
> establish real demand or deployment economics.

---

## 1. Data that must be accurate, and who maintains it

**The external order system is the system of record for orders. PromisePatch has no order
editor and will not have one.** It keeps a *mirror* of what that system says, and the only
write it ever makes to an order is a governed recovery amendment, pushed at the order system
and applied by it ([`docs/order-system.md`](order-system.md); the invariant is stated in
`CLAUDE.md`). `promisepatch.domain.order_mirror` is the single path that writes `orders` and
`order_lines`, and it runs in the worker; `promisepatch.integrations` is forbidden by an
import-linter contract from importing `promisepatch.db` or SQLAlchemy at all, so the outbound
adapter physically cannot move the mirror it just asked somebody else to move.

Two consequences of that boundary are worth stating before the table, because both are
refusals rather than behaviours:

- **An event about an order PromisePatch does not already mirror is refused, not onboarded.**
  `order_mirror._lock_order` rejects it — "creating one from an event would mean an external
  system could add customer promises to this bakery's book by sending a message."
- **Nothing invents a `RecipeVersion` because an external system named one.**
  `order_mirror._resolve_line` refuses a catalogue item no `order_line_mappings` row
  translates, and rolls the whole delivery back.

| Data | Where it lives | What breaks if it is wrong | Whose job it is |
|---|---|---|---|
| **Orders** — `external_id`, `external_version`, `customer_id`, `due_at`, `state` | `promisepatch.orders` (migration `0001_baseline`) | The reachability walk from an exception runs over these rows. An order the mirror does not hold is a customer promise nobody looks at; a stale `external_version` makes the next real change look like an event already overtaken, and it is correctly ignored | The **order system**. PromisePatch mirrors and never authors. `external_version` is the order system's own monotonic counter ([`docs/order-system.md`](order-system.md)) |
| **Order lines** — `recipe_version_id`, `quantity`, `customization_note` | `promisepatch.order_lines` | A line pointing at the wrong authored version repairs the wrong thing, or repairs something that was never threatened | The **order system**, through the event contract; the translation is the bakery's (next row) |
| **Catalogue translation** — external item id to authored `RecipeVersion` | `promisepatch.order_line_mappings` | An unmapped catalogue item **fails the whole delivery closed**: the transaction is rolled back and the failure recorded. Nothing is invented at runtime to make an event fit | **The bakery / PromisePatch operator.** `order_mirror._resolve_line`: "`order_line_mappings`, which PromisePatch owns". It must gain a row whenever the order system's catalogue gains an item |
| **Recipe variants** — versions, their lines and their roles | `promisepatch.recipe_versions`, `recipe_version_lines` (`role` in `STRUCTURAL`, `FILLING`, `VISIBLE_DECORATION`; `qty_per_unit`), `recipe_version_equipment` | `role` is what decides whether a substitution is a *visible* change, and therefore whether the customer must be asked. A filling mislabelled as decoration silently changes the authority a recovery needs | **The recipe author.** The schema refuses an unattributed version: `ck_recipe_versions_authorship_required` requires `btrim(authored_by) <> ''` |
| **Substitution policies** — pre-authored (affected resource, role, source version) to candidate version, substitute, `visible_change` | `promisepatch.substitution_policies`, unique on `(affected_resource_id, role, source_version_id)` | Recovery selects **only** pre-authored `RecipeVersion`s named by a `SubstitutionPolicy` (`CLAUDE.md`). A threatened promise with no policy naming a version has nothing to select, so it cannot be classified `AUTO_RECOVERABLE` | **The recipe author / owner.** Nothing at runtime creates, derives or synthesizes a version |
| **Order constraints** — `NO_SUBSTITUTION`, `PREAPPROVED_ALTERNATIVE`, `ASK_BEFORE_VISIBLE_CHANGE`, `EXCLUDE_RESOURCE` | `promisepatch.order_constraints`; shape enforced by `ck_order_constraints_constraint_shape` | These decide whether a change may be made silently, must be asked for, or is forbidden. A missing `NO_SUBSTITUTION` turns a refusal into an amendment; a missing pre-approval turns an automatic repair into a message a customer has to answer | **Whoever took the customer's instruction.** `ck_order_constraints_provenance_required` refuses a constraint with no `recorded_by`, so every constraint names who recorded it and when |
| **Commitment lines** — `received_state` (`EXPECTED` / `RECEIVED` / `NOT_RECEIVED` / `SHORT`), `received_qty`, `settled_at`, `attested_by` | `promisepatch.supplier_commitments`, `commitment_lines`; check constraints tie `settled_at` to state and `received_qty` to `SHORT` | A line left open that actually arrived inflates expected supply, so a threatened promise reads as safe. The invariant is that a line is open or settled, settlement posts its outcome once, and a settled line contributes **zero** to expected supply (`CLAUDE.md`) | **Whoever receives deliveries**, by attestation. Physical facts are authoritative independently of recovery authorization, and **only an explicit correcting attestation reverses one** — see §4 for where that is reachable from today |
| **Customers and their approval channel** — `approval_channel_kind` in `telegram` / `whatsapp` / `console`, plus the address | `promisepatch.customers`; `ck_customers_approval_channel_kind` | The channel **is** the consent identity. `domain.approvals` refuses a reply whose `sender` is not the request's `customer_channel`, so a wrong address sends the question to the wrong person *and* makes the right person's answer a foreign sender | Carried by the order system in the event contract (`CustomerRef.approval_channel`, `packages/order-contract/.../events.py`). **The mirror does not create or update customer rows**, so today these come from the seeded fixture — see §4 |
| **Resource names and aliases** | `promisepatch.resources`, `resource_aliases` | A proposed resource is accepted "only if the worker's sentence contains that resource's stored name or one of its recorded aliases" (`domain.grounding`). An ingredient no alias covers cannot be grounded, and the reading fails closed to a human. This is the rule that separates parsing from knowing | **The bakery.** Every way the kitchen actually says a thing out loud has to be a row |
| **Workers and their roles** — `baker`, `owner`, `observer` | `promisepatch.workers`; `ck_workers_role` (the observer role added by `0008_observer_worker_role`) | An observer may not attest a physical fact and may not speak on a case; `require_attestor` refuses it *before* a case exists, because whoever opens a case is whom `require_permitted` admits to it afterwards | **The deployment.** `domain.intake.may_attest` is the single rule, and both the screen and the write call it, so what a surface offers and what the database allows cannot drift apart |

Unknown or conflicting state fails closed to `BLOCKED` — never `UNAFFECTED`, never
`AUTO_RECOVERABLE` (`CLAUDE.md`). Inaccurate data therefore tends to produce an escalation
rather than a wrong silent repair. That is a design choice, not a reason to be relaxed about
accuracy: an escalation is a person's time.

## 2. Setup an integrator must do

### 2.1 Worker identity and permissions

- **Seed the staff rows first.** Roles are `baker`, `owner`, `observer` (`ck_workers_role`).
  `require_attestor`, `require_permitted` and `require_readable` in `domain.intake` are the
  enforcement.
- **`PP_SURFACE_WORKER_ID` must name a worker that exists.** The conversational surface has no
  actor field anywhere in the chain — the attesting worker comes from the intent API's own
  setting and the clock is the server's. If it names nobody, intake refuses with
  `SURFACE_WORKER_MISSING` and **every `report` fails on the first spoken turn**. This is
  defect 7 of [`docs/p6.2-first-deployment.md`](p6.2-first-deployment.md) §3.2, found by
  reading the deployment definition against the code.
- The durable worker process mints its own `host:pid:boot` lease identity
  (`domain.identity.WorkerIdentity`) and this is not configuration. The boot component exists
  so a restarted container cannot complete work its dead predecessor claimed.

### 2.2 Customer identity and channel setup

- One `customers` row per customer, with a channel kind the schema permits and an address.
  `promise_graph.channel` is the only codec between the engine's opaque `"tg:1001"` string and
  the schema's `(kind, address)` pair — "a codec written twice is a codec that eventually
  disagrees with itself".
- The consent identity is the channel address, and the reply must arrive from it. There is no
  second way to authenticate a customer.
- **Today there is no channel that can carry a message to a real person.** See §4.

### 2.3 What an order system must satisfy

The contract is a shared package, `packages/order-contract`, and it is the whole surface:

| Concern | The contract | Where |
|---|---|---|
| **Events** | `order.updated`, `order.cancelled`, carrying `event_id`, `occurred_at`, `previous_version`, `changed_line_ids` and a full `OrderSnapshot` (`external_id`, `version > 0`, `state`, customer with approval channel, `due_at`, lines) | `order_contract/events.py` |
| **Versioning** | `SCHEMA_VERSION = 1`, one number for the whole contract. `version` is the order system's own monotonic counter. The already-applied event is a no-op, an older one is ignored and audited as stale, and a version **beyond** the next one makes PromisePatch fetch the whole order authoritatively and make the mirror equal to it | `order_contract/events.py`; the table in [`docs/order-system.md`](order-system.md) |
| **Webhook auth** | HMAC-SHA256 over the exact request bytes plus a timestamp, in `X-Order-Signature` and `X-Order-Timestamp`, verified **before** the body is parsed, inside a `DEFAULT_TOLERANCE` of 5 minutes, with a `MAX_BODY_BYTES` of 256 KiB. Missing, expired, forged and tampered deliveries get one indistinguishable answer | `order_contract/signing.py`; `api/routers/integrations.py` |
| **Delivery semantics** | `(source, provider_event_id)` is unique in `inbox_events`, so a webhook delivered ten times is one logical record and at most one mirror change | [`docs/order-system.md`](order-system.md) |
| **Amendments** | `POST /orders/{external_id}/amendments`, carrying the option planning chose and the version the plan was made against, with a stable `Idempotency-Key` derived from persisted identity | `order_contract/amendments.py`; `integrations/order_system.py` |
| **Refusals** | Eight declared codes, of which the deterministic ones are terminal: `VERSION_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `ORDER_NOT_FOUND`, `LINE_NOT_FOUND`, `UNKNOWN_ITEM`, `LINE_MOVED`, `ORDER_NOT_OPEN`, `UNSUPPORTED_SCHEMA_VERSION`. An order that moved on must be **refused** rather than overwritten, and PromisePatch escalates instead of reporting success | `order_contract/amendments.py` |
| **Retry** | A lost answer is retried with the **same key**, and the order system must replay its stored result rather than act twice | [`docs/order-system.md`](order-system.md) |
| **Finish condition** | A track becomes `RECOVERED` only once the mirror shows the change the order system said it made. An acknowledgement is not an observation | [`docs/order-system.md`](order-system.md) |

The integrator also owns, on the PromisePatch side, an `order_line_mappings` row per catalogue
item and a shared webhook secret held by both applications
(`PP_ORDER_SYSTEM_WEBHOOK_SECRET` / `OS_WEBHOOK_SECRET`).

### 2.4 Hosting

Derived from what is actually deployed and what the preflight declared —
[`docs/p6.1-deployment-preflight.md`](p6.1-deployment-preflight.md) and
[`docs/p6.2-first-deployment.md`](p6.2-first-deployment.md):

- One EC2 host (`t4g.small`, IMDSv2 required, `HttpPutResponseHopLimit: 2` because every
  process runs in a container and the Docker bridge costs a hop), running the same images with
  the same per-container environment files as the local stack.
- A private, encrypted RDS PostgreSQL — not publicly accessible, in private subnets.
- Caddy terminating TLS with a publicly trusted certificate. `TlsHostname` may be left empty,
  in which case the stack derives `<elastic-ip>.sslip.io`, so a first deploy needs no DNS
  record pointed at an address that does not exist yet.
- ECR for images, SSM Parameter Store for secrets and configuration, CloudWatch Logs.
- **No load balancer, no NAT gateway, no ECS, no Secrets Manager**, and no
  `AdministratorAccess` anywhere: three roles with one job each, both `iam:PassRole` grants
  fenced to a single role and a single service.
- **`PP_LLM_PROVIDER` must be named explicitly.** It defaults to `fake` and is deliberately
  not inferred from `PP_ENV`; a deployment that omits it comes up healthy, holds
  conversations, and never calls a model once (P6.2 §3.2, defect 6).
- The MCP process needs its own bearer token and its `Origin` and `Host` allowlists
  (`PP_MCP_ALLOWED_ORIGINS`, `PP_MCP_ALLOWED_HOSTS`); an unlisted `Origin` is refused `403`
  and an unlisted `Host` `421`.

Local development needs no cloud account at all: Python 3.12 with uv, Docker with Compose v2,
Node.js 24, and `scripts/bootstrap_local_env.py` to generate the gitignored environment files
(see the README). No secret value appears in this repository, in a log line or in an error
message.

## 3. Cost — measured, estimated, and not measured

### 3.1 Measured

Everything here has a named source in this repository. None of it is a bill.

| Figure | Value | Where it came from |
|---|---|---|
| Standing infrastructure | **about $33 / month** | [`p6.1`](p6.1-deployment-preflight.md) §6: AWS public list prices for `us-east-1`, read on 2026-09-10, multiplied by the quantities the architecture declares. Itemised there across ten meters — compute $12.26, database $11.68, public address $3.65, volumes, storage and logs the remainder |
| Per conversation | **about $0.0039** | [`p6.1`](p6.1-deployment-preflight.md) §6: arithmetic over the **measured** token count of the one bounded live Nova conversation recorded in P5.3 — six turns, 10,360 input and 165 output tokens — at published list rates |
| IAM delta | first preflight run **2 of 9** required permissions, then **8 of 9**, then **9 of 9** and exit 0 | [`p6.1`](p6.1-deployment-preflight.md). One of the seven initial denials was the preflight's own defect: its ECR probe listed the whole registry, which a role scoped to one repository prefix is correctly denied |
| Permissions declared but untested at preflight time | **12** mutating requirements | [`p6.1`](p6.1-deployment-preflight.md). Two of the denials that later stopped the first deploy were both in that untested set |
| Further IAM needed to finish the deployment | **2 actions**, each scoped to a resource its role already owned | [`p6.2`](p6.2-first-deployment.md) §7: `ec2:ModifyInstanceMetadataOptions` and `cloudformation:ContinueUpdateRollback`. Two other denials were routed around *without* asking for IAM, by making the template stop depending on a permission |
| Defects only deployment found | **11** | [`p6.2`](p6.2-first-deployment.md) §3: five by AWS rejecting the stack, two by reading the definition against the code before deploying, one pre-emptively, three after the stack was up |
| Test cost of those defects | deployment-definition tests **47 to 57** | [`p6.2`](p6.2-first-deployment.md) §8. Every defect above has a test that reproduces it offline |

Two honest caveats carried from their sources. The $33 is **marginal**: the account already
carries an unrelated project, so a total read from Cost Explorer will not equal it. And the
$0.0039 is a list price — the rate could not be verified from this account, and the account's
own charge may differ.

An idle deployment is not free and is not much cheaper: stopping the instance removes $12.26
and leaves the database, the volume and the address ([`p6.1`](p6.1-deployment-preflight.md) §6).

### 3.2 Estimated — the unbuilt commercial POS adapter

**This is an estimate of scope and nothing more. No duration and no money figure is given for
it, because none can be derived from this repository, and inventing one would make every
measured number above worth less.**

A Square Sandbox adapter behind the same `OrderSystemPort` was kept as optional upside by
[ADR-0005](adr/0005-order-system-simulator.md) and was then **removed from the remaining
roadmap** along with the optional messaging adapters. It has not been built, is not scheduled,
and nothing in this repository has been validated against a commercial point of sale.

What an estimate *can* be grounded in is the enumerable contract surface such an adapter would
have to satisfy — every item of it is listed in §2.3 above, and each is a file that exists:

1. An outbound adapter implementing the same port as `integrations/order_system.py`, mapping
   that provider's errors onto the eight declared refusal codes and preserving the
   applied / deterministically-refused / uncertain trichotomy the retry story depends on.
2. An idempotency mechanism the provider actually honours, or the at-least-once guarantee
   changes shape.
3. A monotonic per-order version, or the staleness rules in §2.3 have nothing to compare.
4. Inbound event delivery authenticated at the bytes, with a replay window and a stable
   provider event id.
5. `order_line_mappings` rows for that provider's catalogue, maintained by the bakery.

ADR-0005 records the reason this was never on the critical path: Square Sandbox Dashboard
line-item editing is undocumented, and the dashboard is a limited subset of the production one.
Its revisit trigger — a verified Sandbox Dashboard line-item edit with a webhook round trip
under five seconds — has not fired.

### 3.3 Not measured

- **Engineer time.** No setup, integration or maintenance effort in this project was timed.
  Every hour figure that could be written here would be invented, so none is.
- **Ongoing maintenance burden** for the data in §1 — how often a catalogue changes, how many
  mappings a real bakery needs, how long a recipe author spends authoring policies. Not
  measured; there is no operator to measure.
- **The real monthly bill.** `ce:GetCostAndUsage` was denied at preflight time and no billing
  period has been reconciled. [`p6.1`](p6.1-deployment-preflight.md) lists taking that reading
  as remaining work.
- **Onboarding effort for a bakery that is not the fixture.** There is no order-import path to
  measure (§4).

## 4. What is not built, and what is simulated

### 4.1 The Telegram customer channel is half built and has never spoken to Telegram

[ADR-0006](adr/0006-customer-channel-telegram.md) chose the Telegram Bot API as the canonical
customer channel. **The outbound half now exists and the inbound half does not.**

*What exists.* [`integrations/telegram.py`](../apps/backend/src/promisepatch/integrations/telegram.py)
sends one approval message — the frozen §13.6 wording plus the signed possession link — through
the outbox's existing provider boundary, selected by `PP_CUSTOMER_CHANNEL_PROVIDER=telegram`
and credentialled by `PP_TELEGRAM_BOT_TOKEN`. See
[`customer-message-transport.md`](customer-message-transport.md).

*What does not.* There is no bot, no webhook ingress, no `secret_token` check, no `update_id`
deduplication, no `getUpdates` and no inbound path of any kind — deliberately, because a
second route by which the word `YES` could arrive would be a second consent parser.
`pp channel check`, the verification step ADR-0006's consequences describe, does not exist as
a CLI command either.

*What has never happened.* **No live Bot API call has been made from this repository.** Every
test of the adapter runs against a scripted transport; no bot has been created, no token
issued, no message delivered to a second device, and no deployed process has ever had the
provider set to `telegram`. Until a deployed rehearsal does that, "PromisePatch can contact a
customer" is a claim about code that has never spoken to Telegram.

`domain.adapters.FakeEffectAdapter` remains the default provider everywhere — CI, every test
and the local stack — and is deliberately honest about what it models: it behaves like a
provider *with* idempotency-key support, so that a duplicate send under one key can be shown
collapsing to one effect on its side. The real Bot API has no such key, which the transport
document states rather than engineers around.

**So the customer side is still a labelled simulation in every run anybody has taken.** The
consent protocol itself is real and durable — the request, its captured order version, recipe
version and constraint hash, the deadline, the sender binding, the literal parser, the single
confirmation prompt, the escalation on a second unreadable reply — and a customer answers
either through the signed link ([`customer-approval-link.md`](customer-approval-link.md)) or
through `pp receive-customer-reply`, an operator command that deliberately cannot record an
approval itself.

**Recorded as deferred, with its target:** [`p6.2`](p6.2-first-deployment.md) §9 states it
plainly — "**The customer loop over Telegram is absent** — that is P6.3." The delivery path
is now written; the deployed proof is not.

### 4.2 The order system is a labelled simulator

The External Order System is [`apps/order-simulator`](../apps/order-simulator): a small FastAPI
application with its own SQLite database, its own port, its own window and its own hand-authored
order book, run as a separate process. [ADR-0005](adr/0005-order-system-simulator.md) requires
that it "look unmistakably like a separate system, or a judge may read it as a hidden
PromisePatch editor", and that it never share code or a database with PromisePatch.

[`docs/order-system.md`](order-system.md) states the limit of what it proves, and this page
repeats it rather than softening it: "It is **not Square, not a production point of sale, and
not a real customer system.** It proves integration mechanics — a signed contract, idempotent
amendments, monotonic versions, durable delivery, and the effect of an external change on what
PromisePatch decides. It proves nothing whatsoever about third-party product adoption."

### 4.3 The fixture is a fixture

All demo data is the shipped **Hollow Oak** dataset, authored once in
`promise_graph.examples.hollow_oak` and loaded by `pp reset-demo-state`. It holds **six**
orders, `ord-a` through `ord-f`. The name of the loaded dataset is recorded on `fixture_state`
so an operator can see which one is in the database. The staff the demo logs in as are the
fixture's own attesting worker and its own recipe author, read off the dataset rather than
typed in again.

The sixteen effect-set scenarios reuse that same fixture universe
([`docs/effect-set-manifest.md`](effect-set-manifest.md)).

### 4.4 Capabilities that exist but are not reachable from the product surface

- **Correcting a physical fact.** `intake.correct_physical_fact` exists in the domain and is
  reachable **only from the CLI**. No MCP tool and no intent route reaches it
  ([`docs/p7.1-judge-ux-contract.md`](p7.1-judge-ux-contract.md)). Since only an explicit
  correcting attestation reverses a physical fact, the one way to reverse one today is a
  command line.
- **Onboarding orders.** There is no import path. Orders enter the mirror from the seeded
  fixture, and an event about an unknown order is refused by design (§1).

## 5. Limitations

Stated without softening, because a claim this project cannot support is worth less than the
admission that it cannot.

- **No commercial POS validation.** Nothing here has been run against Square or any other
  production point of sale. The adapter was declined (§3.2), and the only order system that has
  ever answered this code is the labelled simulator.
- **No operator study.** No bakery worker, owner or recipe author outside this project has used
  PromisePatch. None is scheduled.
- **No adoption or demand evidence.** There are no users, no pilots and no waiting list, and
  nothing on this page should be read as implying any.
- **No measured labour saving and no ROI.** No task was timed with the system and none without
  it, so there is no baseline, no comparison and no saving to report. The per-conversation
  model cost in §3.1 is a cost, not a benefit.
- **The manifest and its labels are developer-authored, finite and public — not an
  independently validated or held-out benchmark.** The whole manifest is readable in the
  repository ([`docs/effect-set-manifest.md`](effect-set-manifest.md)). Its content hash is
  published so that a result cannot be quietly scored against different labels; that makes the
  claim *checkable*, not *correct*.
- **Reproducibility makes claims inspectable; it does not prove correctness, demand or
  economics.** A clean clone can recompute the manifest hash and run the suites with no cloud
  account. That establishes that the published claims describe this code. It establishes
  nothing about whether anyone needs it.
- **Cost is list-price arithmetic, not a bill** (§3.1), and the per-conversation figure rests
  on a **single** measured conversation.
- **The deployed evidence is a small number of runs, not a sample.** One deployment, on one
  account, in one Region.

The roadmap's own conclusion is the one this page is written to support: **4/5 is the defensible
planning ceiling for Impact; 5/5 is not an evidence-supported projection.**

---

*Drafted in P7. To be finalised in P9 with the final measured numbers — the first-run effect-set
score, the settled-outcome funnel, the voice timings and, if a billing period has been
reconciled by then, a real cost figure in place of the list-price arithmetic in §3.1.*
