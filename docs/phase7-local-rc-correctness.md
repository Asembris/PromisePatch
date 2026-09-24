# Phase 7 session 1 — the local release-candidate correctness gate

Date: 2026-09-24. Entry at `3c0d914bdab4`, tracked tree clean, `main` equal to `origin/main`, the
eleven known untracked artefacts left as they were, the `pr` workflow green on that SHA and the
effect-set workflow red as expected. **Nothing here is deployed**: the deployed host still serves
`931a296decad`, and no AWS resource, IAM policy, SUR-1 artefact, effect-set artefact, frozen
manifest or earlier record was touched. Every earlier record, the Phase 6 closeout included, is
left exactly as it was.

An independent audit left four findings open against the local release candidate. Each was
reproduced or traced from source before anything changed, and each has one verdict here.

| # | finding | verdict |
|---|---|---|
| 1 | execution-time freshness | **CONFIRMED, FIXED** ([ADR-0024](adr/0024-freshness-is-judged-where-the-effect-is-committed.md)) |
| 2 | authority provenance at completion | **CONFIRMED, FIXED** |
| 3 | network uncertainty on the customer page | **CONFIRMED, FIXED** |
| 4 | a silent sibling costs an answered promise its window | **CONFIRMED, NOT FIXED — stopped and reported** |

## 1. Execution-time freshness

### Reproduced before editing

The canonical case through the product's own paths: Tomas's literal `YES` on B, the worker run
only until B's revalidation recorded `PROCEED` and `apply:B` was queued. Then **only the clock
moved** — the step runner's `now` was advanced past B's production start; no row was written.

| read | before ADR-0024 |
|---|---|
| revalidation of B | `PROCEED` at 08:47 |
| B's fingerprint, before the clock moved | equal to the planned one |
| `apply:B`, at 12:48 | committed `APPLYING` and the amendment |
| the amendment | `DELIVERED`, one attempt |
| B / case | `RECOVERED` / `RESOLVED` |
| B's task | `SCHEDULED`, start 12:47 — already past when the order changed |

`APPLY_RECOVERY` recomputed the fingerprint, which covers the task's state, start and holder, but
check 6's other half — *now < scheduled start* — is a comparison with the clock, and nothing
re-asked it after the checklist. The same code path serves automatic tracks.

### The contract (ADR-0024)

- **The approval deadline governs the answer, not the execution.** It is judged by the parser, the
  sweep and check 7 in the revalidation that consumes the decision — the transaction that records
  `PROCEED` and queues the one `APPLY_RECOVERY`. A yes consumed in time stays the authority for
  its change.
- **What must stay true until the first external mutation:** the authority chain, every watched
  row (the fingerprint), and *now < the line's scheduled production start*.
- **The durable commit boundary** is `APPLY_RECOVERY`'s transaction: track `APPLYING` and the
  outbox row commit together. Before it nothing exists to send; after it the effect is decided.
- **"Nothing sent" versus "accepted, acknowledgement lost".** Nothing is provably unsent only
  before the first dispatch claim. From then on the order system may hold the change, so the
  dispatcher has **no** time gate for an amendment: a retry after a lost acknowledgement goes out
  under the same key, even past the start, and is collapsed by the order system. A refusal there
  would record "not changed" for an order that may have changed, and would route to
  `DOWNSTREAM_UNAVAILABLE`, which would be false.

### The fix

`_apply` reads the line's production task and, if its start is unknown or not after `now`, takes
the existing apply-time refusal: `PLAN_STALE` to the owner with scheduled work held, nothing
emitted, nothing re-planned. One query, one branch, no state, table or column.

### Proved in `test_execution_freshness.py`

| test | pins |
|---|---|
| `test_an_approved_amendment_is_not_committed_after_its_production_start` | the reproduction, now refused: no amendment, B `ESCALATED` `PLAN_STALE`, task `HELD`, the `PROCEED` and the one decision kept |
| `test_an_approval_consumed_in_time_executes_after_its_deadline_while_the_start_is_ahead` | the deadline does not govern execution: B applied, one delivered amendment |
| `test_an_automatic_amendment_is_held_to_the_same_production_start` | automatic tracks too |
| `test_a_committed_amendment_whose_acknowledgement_was_lost_is_still_delivered_once` | no retry-time gate: two attempts, one key, one logical effect, B `RECOVERED` |

Run against the pre-fix `recovery.py`, the first and third fail on the emitted amendment; the
other two pass either way, as a contract that must not regress should.

**Disclosed residuals.** The window between `APPLY_RECOVERY`'s commit and the first dispatch claim
is normally the same worker cycle; a crash inside it followed by an outage past the start still
dispatches late. Substitute allocation also reads `now` (expected supply turning overdue), and an
automatic track does not re-run allocation at apply.

## 2. Authority provenance

Traced from the confirmation through `APPLY_RECOVERY`, the outbox, the order-mirror echo and
`FINALIZE_RECOVERY`:

| row | automatic (A) | customer-approved (B), before | after |
|---|---|---|---|
| `RECOVERY_APPLIED` | `CONSTRAINT`/`POLICY` | `HUMAN_APPROVAL` + request, decision, parser, sender | unchanged |
| mirror echo rows | `NONE` | `NONE` | unchanged |
| `RECOVERY_COMPLETED` | `CONSTRAINT`/`POLICY` | **`CONSTRAINT`/`POLICY`** | **`HUMAN_APPROVAL`** + the same request and decision |

`_finalize` wrote `"CONSTRAINT" if option.cited_constraint_ids else "POLICY"` for every track, so
the row that says a customer-approved change is done named a policy as its authority. No surface
rendered that column — the workspace derives authority from classification — but the audit ledger
is the record of what permitted what, and it contradicted itself for one change.

**Fix:** completion copies the authority, and the consent keys of its provenance, from the
`RECOVERY_APPLIED` row written in the same transaction as the effect, under the same idempotency
key. The only writer of `APPLYING` is that governed write, so the row always exists; its absence
raises rather than guesses. Automatic recovery is untouched and still never claims consent.

Proved in `test_authority_provenance.py`: A's two rows agree on `POLICY`/`CONSTRAINT` and carry no
consent key, in a case whose sibling was approved; B's two rows both say `HUMAN_APPROVAL` with the
same request, decision, literal parser and sender, and the completion names the delivered
amendment's key and provider reference.

## 3. Network uncertainty on the customer page

The server commits a pressed answer **before** it builds the response, and a second press of
either button proposes the same derived reply id and writes nothing. Both were already true. The
page was not:

| surface | before | after |
|---|---|---|
| a failed read (non-404) | "Nothing about your order has changed; this page simply cannot read it." | "This page could not read your order just now, so it cannot say what is recorded." |
| a failed answer | "That did not reach the bakery. Nothing was recorded — please try again." with the buttons live | the same request is **read again**; while that read is in flight the buttons are disabled and the page says it is checking; afterwards it renders the reading — the kept answer, or the open question with "We could not confirm that your answer reached the bakery … If your first answer did arrive, it stands, and a second one changes nothing." |

A 5xx or a dropped connection proves nothing about whether the answer was kept, so the page claims
nothing until the re-read returns. Consent and link semantics are unchanged: no field, parser,
route or id moved.

**Proved:**

- `test_customer_answer_uncertainty.py` (backend, real app, real database): a transport lets the
  press reach the application and commit, then raises instead of returning. Exactly one stored
  answer exists (the `YES` in `inbox_events`), and the same link reads `RECEIVED`, not answerable.
  The customer then presses **DECLINE** twice — once before and once after the worker has read the
  first answer — and there is still one stored answer, one reply row from Tomas's channel and one
  `APPROVE` decision.
- `customerApproval.test.tsx`: a lost response to a kept answer is reported from the re-read
  ("we have your answer", no buttons, one POST); a failed answer with the question still open
  re-reads and says "could not confirm", never "nothing was recorded"; a failed read claims nothing
  about the order.

**Two unit tests changed their asserted literals**, because the literals were the defect:
`'Nothing was recorded'` and `/nothing about your order has changed/`. Both are now asserted
*absent*, beside the truthful sentence. Against the old page source, both rewritten tests and the
new one fail.

## 4. A silent sibling and an unequal window

### Constructed through normal paths

Proof C's world, exactly as Phase 6 built it (`with_charlotte_variant` authored, C's constraint set
to ask): the canonical report, clarification and one confirmation ask Tomas about B and the
Okafor-Reyes wedding about C. The fixture's own schedule gives the two unequal windows — B's
deadline at start − 60 min is **six hours** before C's. Tomas answered a literal `YES` at once;
C's customer said nothing. No workflow row was inserted; only the clock was moved, and only after
the observation at the real time had been taken.

| moment | case | B | `revalidate:B` | anything outstanding |
|---|---|---|---|---|
| B's yes durable (09:10; B deadline 12:10, B start 13:10) | `WAITING` | `WAITING_FOR_CUSTOMER`, request `ANSWERED` | **none** | **nothing** |
| clock past B's deadline | `WAITING` | unchanged | none | nothing |
| clock past C's deadline (18:11) | `PLANNED` | **`PENDING`**, request **`SUPERSEDED`** | `STALE`: check 6 (start passed) and check 7 (deadline passed) | C `ESCALATED` |

Tomas answered in time, and his answer was consumable for three hours. It was never looked at
until C's window closed, by which time the start had passed; the round then refused it as stale
and re-planned B — a promise now behind its own start, with no amendment ever made.

### Verdict: incorrect against the intended contract

§14.2 lists **"a literal ApprovalDecision received"** as its own exit from `WAITING`, and the
frozen architecture plan draws the same arrow ("ApprovalDecision(parser=LITERAL) → case WAITING →
REVALIDATING"). §14.2 also draws the return: "RECONCILING → WAITING if other tracks are still
waiting". The intended shape is B revalidated and applied promptly, the case then back to waiting
on C. No ADR chose otherwise; the rule dates from `63141e9`.

### Root cause

`cases.settled_case_state` moves `WAITING → REVALIDATING` only when **no** approval request on the
case is still open — "every one of them has been decided or has expired". One case state gates
every track's revalidation on the slowest customer. B's own deadline timer cannot help: it acts
only on open requests, and B's is answered.

### Why it was not fixed here

The gate is load-bearing for the rest of the state machine, so relaxing it alone would strand the
other track instead of B:

1. A decision that arrives while the case is `REVALIDATING` asks `settled_case_state`, which has no
   `REVALIDATING` exit, and enqueues nothing — C's yes would never be revalidated.
2. A decision that arrives while the case is `RECONCILING` reaches `_settled_reconciling`, which
   returns to `WAITING` only while a request is *open*; with C answered and non-terminal, the case
   neither waits, revalidates nor resolves.
3. The same question at `PLANNED`, which ADR-0023 made a state a sibling can be finishing in.

Closing those needs new case edges — at least `RECONCILING → REVALIDATING`, and a decision's own
revalidation from states other than `WAITING` — each of which has to be re-proved against
ADR-0023's round-ends-once guarantee and both claim orders. That is a change to the case state
machine, not a small safe fix, and the brief was to stop rather than redesign scheduling first.
**Nothing was changed for this finding.** The probe that produced the table was a temporary test,
removed and not committed; committing it would have meant pinning a defect or committing a failing
test, and neither is allowed. The table above and the steps in this section are the record.

It is not an authority breach: nothing was applied without its own yes, no customer's answer
reached the other's order, and the refusal failed closed. It is a **liveness and truthfulness P1**:
a promise the customer approved in time loses its recovery to an unrelated customer's silence,
and the case says it is waiting while that happens.

## 5. Validation

Sequential throughout: no `xdist`, no worktree, no temporary clone, and no test weakened, skipped,
deselected or `xfail`ed. The two frontend literals in §3 are the only asserted values that moved,
and they moved from a false sentence to its absence. The compose `worker`, `api` and `mcp` were
stopped for every database run.

| check | result |
|---|---|
| `test_execution_freshness.py`, new | **4 passed**; against the pre-fix `recovery.py`, the two refusal tests **fail** on the emitted amendment |
| `test_authority_provenance.py`, new | **2 passed**; with the old completion expression restored, the approved test **fails** at `'CONSTRAINT' == 'HUMAN_APPROVAL'` |
| `test_customer_answer_uncertainty.py`, new | **2 passed** |
| first sequential run, finding 1 only: the freshness module, `test_recovery_revalidation`, `test_recovery_execution`, `test_truthful_recovery`, `test_order_amendment`, `test_two_track_reask`, `test_approval_reask`, `test_started_work_contract`, `test_whole_delivery_counterfactual`, `test_adversarial_races` | **201 passed**, 0 failed |
| one sequential run on all three fixes, 30 files: the three new modules, `test_recovery_revalidation`, `test_recovery_execution`, `test_truthful_recovery`, `test_order_amendment`, `test_order_mirror`, `test_order_system_boundary`, `test_two_track_reask`, `test_approval_reask`, `test_customer_approval`, `test_customer_approval_link`, `test_customer_intent`, `test_consent_authority`, `test_human_confirmation_boundary`, `test_adversarial_races`, `test_step_execution`, `test_workflow_outbox`, `test_workflow_inbox`, `test_workflow_timers`, `test_worker_recovery`, `test_withdrawal`, `test_started_work_contract`, `test_whole_delivery_counterfactual`, `test_impact_analysis`, `test_case_workspace`, `test_status_view`, `test_causal_chain` | **724 passed**, 0 failed, 0 skipped |
| `mypy` over `packages/promise-graph packages/order-contract apps/backend` | no issues, 296 files |
| `lint-imports` | 30 kept, 0 broken |
| `ruff check`, `ruff format --check` on every changed Python and Markdown file | clean |
| frontend unit suite | **341 passed** of 341 (340 before: one test rewritten, two added); against the old page source the three customer tests **fail** |
| `npm run typecheck`, `npm run lint`, `npm run build` | clean |

**Not run**, and why: the whole backend suite (roughly an hour; GitHub CI is the regression
authority and nothing is pushed); `mypy` groups B and C (nothing under `apps/order-simulator`,
`evals` or `scripts` changed); `test_mcp_protocol.py` (nothing on its path changed, and its twelve
local refusals time out on this machine's TLS proxy as Phase 6 recorded); and the Playwright
specs, which need images rebuilt from this head and the judge entry turned on — the customer page
changed, so `customer-approval.spec.ts` is owed on the release SHA. No live path was exercised:
everything here is proved locally against the fake provider.

## 6. What remains

**Findings 1–3 are closed.** No P0 was found. One P1 remains open:

- **Finding 4, the silent sibling.** A local RC blocker for any case that asks two customers;
  the canonical demo asks one and does not reach it. Closing it needs an ADR that amends the case
  state machine (a decision's own exit from `WAITING`, and the edges it then needs from
  `REVALIDATING`, `RECONCILING` and `PLANNED`), proved in both claim orders against ADR-0023. The
  project owner decides whether that is built before the release or disclosed as a limitation.

Known P2s and residuals, none an authority breach:

- ADR-0024's two disclosed residuals: the milliseconds between `APPLY_RECOVERY`'s commit and the
  first dispatch claim, and substitute allocation's own clock sensitivity on automatic tracks.
- The approval-*message* window gate runs on every claim, including a retry after an attempt the
  provider may have accepted. The track's reason is `APPROVAL_EXPIRED`, which is true, but the
  outbox row's error text says the window closed "before the message could be delivered", which
  it cannot know. Internal text only; the customer's link reads the expired question truthfully.
- Phase 6's P2s stand as recorded there.

**Next AWS session, in this order**, unchanged from the Phase 6 closeout except for its first line:

1. Push this head only when the project owner asks, and wait for `pr` green on the exact SHA
   (effect sets red as expected); run the three Playwright specs on images built from it.
2. Read the deployed historical case read-only, before anything can erase it.
3. `deploy.sh images` for the release SHA, then carry the tag to the host by a parameter-only change
   set against the previously deployed template, gated on an empty resource change list and
   authorised explicitly by the owner. `deploy.sh stack` still cannot carry it.
4. `pp restore-demo-world --confirm destroy-and-restore`, carrying the Telegram binding across;
   smoke from the host; verify the deployed image is the release SHA.
