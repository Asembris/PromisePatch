# G7 — finished product and voice: the closeout

**G7 is CLOSED, with one criterion deliberately not performed.** This page walks the frozen G7
text criterion by criterion, names the file and the passing test behind each one, and states
every exception, deferral and decline it closes with. Nothing here softens a gap into a pass; the
one criterion nobody performed is recorded as not performed, not as met.

*Written in a session that changed no product code, no test, no fixture and no acceptance
criterion, ran no scored effect-set run, computed no `X/16`, deployed nothing and touched no AWS
resource.*

---

## 0. What was verified here, rather than inherited

Four of the criteria below had never been checked against the implementation — only asserted in
prose. They were verified in code in this session, and every test named for them was run rather
than quoted:

| criterion | file | passing test |
|---|---|---|
| a blocked promise carries an owner, a next action and a reason | [`status_view.py`](../apps/backend/src/promisepatch/domain/status_view.py) — `_PROMISE_OWNERS`, `_PROMISE_ACTIONS`, `_next_action` | `test_case_workspace.py::test_a_blocked_promise_names_an_owner_a_reason_and_a_next_action`; `caseWorkspace.test.tsx` *gives every blocked promise an owner, a reason and a next action* |
| an approval names the exact change and its deadline | [`messaging.py`](../apps/backend/src/promisepatch/domain/messaging.py) `build_approval_request`; `ApprovalEvidenceView.deadline`; `PromiseView.deadline_at` / `deadline_phrase` | `test_consent_parser.py::test_the_message_names_the_exact_change`; `test_status_view.py::test_a_deadline_keeps_its_machine_form_in_the_field_built_for_it` and `::test_a_spoken_deadline_is_not_read_out_as_a_machine_timestamp` |
| stale consent explains why the previous plan cannot execute | [`recovery.py`](../apps/backend/src/promisepatch/domain/recovery.py) `mark_stale` and the ten revalidation checks; `PromiseState.STALE`'s phrase | `test_recovery_revalidation.py::test_an_order_amended_while_waiting_makes_the_approval_stale` and `::test_a_stale_refusal_is_audited_as_ours_and_not_as_the_customers`; `evidence.test.tsx` *puts expected beside actual on every revalidation check* |
| a reload or restart cannot falsely reset state | [`useCaseRoute.ts`](../apps/frontend/src/app/useCaseRoute.ts); the durable case behind `GET /api/cases/{id}`; the profiled `seed` service | `test_customer_approval.py::test_a_waiting_case_survives_a_worker_that_stops_and_restarts`; `test_deployment_definition.py::test_a_restart_cannot_reseed_the_database`; `caseWorkspace.test.tsx` *mounting at a case address reads that case* |

Every test above was run in this session and passed. One qualification: `e2e/durability.spec.ts`
— *a reload lands on the same durable case*, *a restored tab …*, *a second browser …* — is the
browser-level proof of the same reload guarantee, and it needs the full running stack. It was
**not** run here, and is named as evidence that exists rather than as evidence re-checked.

**One precision on the approval, stated rather than glossed.** Two different moments are called a
deadline, and they live in different places. The **answer window** — the moment by which a
customer's reply still counts — is the approval request's own `deadline`, and it reaches the
product surface twice: as `ApprovalEvidenceView.deadline`, which is not nullable, printed by
`ApprovalLine` as *"Asked …, answer due by …"*, and as `PromiseView.deadline_at` /
`deadline_phrase` on the promise row. The **customer's outbound message** names the exact change —
the product ordered, the product that would arrive, and the named substitution beneath both — and
the order's own due moment, and it does **not** name the answer window. That is not a shortfall
against the frozen contract: the frozen spec's approval-window entry fixes the customer wording
verbatim, and the two sentences it fixes are the two this build sends (`CONSENT_INSTRUCTION`,
`CONFIRMATION_INSTRUCTION`). The criterion is met on the product surface, which is what the G7
bullet it sits in is about; the outbound message is unchanged and nothing here proposes changing
it.

---

## 1. The criteria, one at a time

### 1.1 "One primary case workspace, concise promise view, stable dependency view and expandable evidence drawer. Each concept need not become a separate screen."

**Met.** One route holds five bands and the conversation panel
([`CaseWorkspace.tsx`](../apps/frontend/src/features/case/CaseWorkspace.tsx)); the promise view is
customer, order, phrase, state name, reason, deadline and next action, every one of them a string
the backend composed ([`Propagation.tsx`](../apps/frontend/src/features/case/Propagation.tsx));
the dependency view is `CHAIN_GRID`'s four fixed columns; the drawer is four layers, collapsed,
arriving with the case ([`Evidence.tsx`](../apps/frontend/src/features/case/Evidence.tsx)).

Tests: `caseWorkspace.test.tsx` *the band order is fixed, and the untouched band is never the one
that goes*; `propagation.test.tsx` *gives each of them its own chain, with no shared trunk between
them*; `evidence.test.tsx` *is collapsed until it is asked for* and *reaches every layer without
issuing a single request*. Recorded criterion by criterion in
[`case-workspace-closeout.md`](case-workspace-closeout.md).

### 1.2 "Explain resource → version/task → promise only where causal. Unrelated promises remain visible but quiet. Stable graph placement; statuses use text as well as color."

**Met.** `CAUSAL_SLOTS` draws a chain only where a path exists and nothing where none does;
[`Untouched.tsx`](../apps/frontend/src/features/case/Untouched.tsx) keeps the unrelated promises
on screen, quiet, never collapsed, counted against the case's own universe;
[`vocabulary.ts`](../apps/frontend/src/components/vocabulary.ts) gives all fourteen promise states
and all nine case headlines a phrase, a state name and a marker **shape**, so no state is carried
by colour alone.

Tests: `propagation.test.tsx` *states the backend's reason and draws no edge at all*;
`untouched.test.tsx` *draws no edge and no node back to the incident* and *is never drawn as an
achievement*; `vocabulary.test.tsx`, `vocabularySweep.test.tsx`; `caseWorkspace.test.tsx` *states
every promise as text as well as colour*.

### 1.3 "Voice/text share intents and authority. Visible capture/transcript, correction, interruption/retry and text fallback. Replies ≤40 words; plan ≤70, shorter where possible."

**Met, with two stated exceptions on the word budgets.**

*Shared intents and authority.* `voice.test.tsx` *produces exactly the request a typed turn
produces* — the spoken path and the typed path issue the same request on the same route. The
model's boundary is unchanged: `select_tool` returns a verb and nothing else, and a spoken
confirmation is read by the **server**, on the route, by the literal rule
([ADR-0015](adr/0015-a-spoken-yes-checked-by-the-server.md)).

*Capture, transcript, correction, retry, fallback.* `voice.test.tsx` *shows the transcript and
issues no request at all*, *sends only when the person who spoke says so*, *throws a transcript
away without sending anything*, *puts a misheard transcript in the field to be corrected, and
still sends nothing*, *claims no listening between turns*, and — for the fallback — *offers no
voice control and says so once* / *takes the same turn by text, on the same route*. The nine
states have words as well as treatment: `voiceStates.test.tsx` *names all five without a colour*
and *claims no outcome in any of them*.

*The budgets.* `render_spoken` was added beside `render`, which is unchanged because its exact
strings are load-bearing evidence ([ADR-0014](adr/0014-two-renderings-one-case.md)). The canonical
six-promise shape went from 94 words to 36 at `PLANNED` (budget 70) and from 83 to 29 at
`EXECUTING` (budget 40), and the short rendering's length tracks the number of distinct postures
rather than the number of promises, so it holds at 36 and 29 from four promises to twelve.
`apps/backend/tests/test_spoken_budget.py` — 461 pure tests, no I/O — pins both budgets across
every case headline, promise counts 1–12 and 0/1/2/6 left alone, and pins that **nothing is
truncated**: no ellipsis, and every line ends in a full stop or a question mark.

**The spoken word budget is met with two stated exceptions.**

1. **The 104-word withdrawal reply.** `render_withdrawal` reaches 104 words when a withdrawal
   stood four things down and could not undo three, and `spoken` is byte for byte the same string
   as `speech`. It is kept long deliberately: each clause names a distinct consequence class with
   its own count, and [`bounded-withdrawal.md`](bounded-withdrawal.md) fixes that the *applied*
   half is never dropped and that the sentence must never read as an undo. Compressing four
   reversal kinds into one number would delete exactly the distinction that document exists to
   protect.
2. **The budgets are unproved for a case holding many distinct postures at once.** They are proved
   across every case state, promise counts 1 to 12 and 0 to 6 left alone. They are **not** claimed
   for an adversarial case holding a dozen different (state, authority) pairs simultaneously. Such
   a case speaks longer, because there is no truncation anywhere in the rendering and a reply that
   fits by claiming more than it knows is worse than one that does not fit.

Both are recorded where the work was done: [`spoken-word-budget.md`](spoken-word-budget.md).

### 1.4 "Record 10 real voice turns, including failures/timings … at least 9/10 start a truthful spoken response within 4 seconds of speech ending."

**Met, at the minimum that passes, by one turn.**

**The voice gate passed at `K = 9/10` — the minimum that passes, by one turn — on the local stack
with no public-internet round trip, after a first run that was voided late.** Every clause of that
sentence is load-bearing:

- `K = 9`, gate `K >= 9`. Turn 7 measured 4807.8 ms against a 4000 ms threshold and missed by
  807.8 ms. There is no comfortable margin here, and no artifact carrying `K` may present one.
- `K_progress = 6/10` is published beside it and is not gated. Refusals: 0.
- The measurement ran against the **local** `docker compose` stack over `/api/conversation/*`, so
  every published interval is shorter than the same turn taken against the deployed host would be.
  The deployed host was not used because it has no documented on-demand reseed.
- **Run 1 is void and is published in full, unedited, with its `K = 1/10`.** The void was declared
  **late** — after run 1's intervals and its `K` had been computed and published — which is the
  opposite of the order the predeclaration requires. That breach is permanent, and it is stated in
  the measurement itself rather than left to be found. The condition it was voided under is
  structural (fewer than ten records; three were taken) and is not one of the reasons the
  predeclaration forbids voiding for.

Predeclared in [`g7-ten-turn-voice-predeclaration.md`](g7-ten-turn-voice-predeclaration.md),
recorded in [`g7-ten-turn-voice-measurement.md`](g7-ten-turn-voice-measurement.md).

### 1.5 "Blocked promise has owner/next-action/reason. Approval names exact change and deadline. Stale consent explains why the previous plan cannot execute. Reload/restart cannot falsely reset state."

**All four met.** Verified in code in this session — §0 above has the file and the passing test for
each, and the one precision about which deadline lives where.

### 1.6 "Demo-narrative comprehension check: show the demo to three unfamiliar viewers … each identifies changed / waiting / blocked / untouched promises."

**NOT PERFORMED. Declined by the project owner, who judged it low value relative to its cost.**

This is a G7 criterion and it is not met. It was not attempted and abandoned, and no partial result
exists: no viewer saw the demo, no misunderstanding was recorded, and no narrative revision came
out of it. **G7 therefore closes with one criterion deliberately not performed**, by the owner's
decision, and this page records that rather than reporting the criterion as satisfied by something
else.

Nothing elsewhere in this repository may cite comprehension evidence, and no claim about what an
unfamiliar viewer understands is supported by anything in this build.

### 1.7 "Author the executable 16-scenario fixtures/runner against the P5 manifest in P7 slack; keep label semantics unchanged. Close any P5 deferred withdrawal/classifier-removal/workspace items under G7. Cut optional polish before encroaching on P8."

**The runner is AUTHORED, all sixteen are wired, five effect disagreements are published and
deliberately unresolved, and no scored run has happened — no `X/16` exists.**

Four separated parts — reader, judge, observation, runner — each with its own import surface, so
the expectation and the observation cannot come from the same place
([`effect-set-harness.md`](effect-set-harness.md)). Every one of the sixteen performs its own
stipulated facts against the real system: real MCP calls, a real worker, the real External Order
System, real signed webhooks. The manifest's published content hash
`d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` is asserted before anything
runs, and label semantics are unchanged — the manifest file was not touched.

**Every scenario agrees with its frozen labels on all four partitions at every declared
checkpoint.** Not one order is misclassified anywhere in the manifest. Five disagree on *effects*,
and every divergence is a **missing** `task_hold`, `owner_escalation` or second `customer_message`
— never an extra effect, never an unauthorised one, never a duplicate. They are committed
**failing**, unrepaired, with their exact diffs published: S12, S08, S13, and S06/S07.

They stay unresolved on purpose. The run protocol was amended **before a single scenario was
wired** to say that a harness defect may be diagnosed and fixed during development and a
disagreement between a frozen label and the implementation's behaviour may not — it is recorded,
published, and left alone until the first scored run has been taken and its `X/16` captured
([`effect-set-run-protocol.md`](effect-set-run-protocol.md)). Repairing them now would make that
run trivially sixteen out of sixteen and G8's *"whatever the result"* a performance.

**No scored run has happened. `--scored` was not invoked, no `X/16` was computed, printed or held
privately, and none was computed in this session either.**

One stipulated fact is disclosed as unreachable rather than hidden: S04's partial spoilage has no
deterministic attestation carrying a number, and the divergence cannot reach any label.

**The three P5-deferred items are closed, each with its own record.**

| item | record |
|---|---|
| bounded withdrawal (the fifth frozen tool) | [`bounded-withdrawal.md`](bounded-withdrawal.md) — across the domain, both transports, the orchestrator and the workspace; 70 targeted tests, three of them end to end over the real MCP transport |
| runtime customer-intent classifier removal | [`customer-intent-classifier-removal.md`](customer-intent-classifier-removal.md) — the call, the label and the unavailable-provider retry are gone; three guards keep it out; the evaluation surface is untouched |
| case-workspace finishing | [`case-workspace-closeout.md`](case-workspace-closeout.md) — criterion by criterion against the frozen text, each with a named passing test |

**Optional polish was cut rather than allowed to encroach.** One design item stays recorded as
unmet where it was recorded: the five demo-critical frames do not each compose in one unscrolled
1280×800 viewport ([`p7.3-visual-acceptance.md`](p7.3-visual-acceptance.md) §2). That item comes
from this project's own P7.1 design handoff, not from the roadmap, and reaching 800 means
compressing the causal rows — the one thing on the screen a judge is meant to read. It is a
composition preference traded against content, not a capability the product lacks.

### 1.8 "Predeclare the ten voice turns and measurement setup … Publish actual K/10 … Carry this measurement to all three submission artifacts."

**Predeclared, published, and carried as far as the artifacts that exist.**

The predeclaration and the measurement are each their own committed document, written in separate
sessions, with the predeclaration committed before turn one so its pre-run status is checkable by
commit order rather than asserted afterwards. Honest-progress replies are counted separately
(`K_progress = 6/10`) and are not gated. No turn was replaced and no turn was re-run.

The README now carries `K = 9/10` with its conditions and a link to the full timings. **The
one-pager and the video do not exist**, so the measurement is carried to one of the three
submission artifacts and not to three. That is not a gap this phase could have closed: G9 requires
all three artifacts to surface **three** measured numbers together, and one of them is the
first-run `X/16`, which by the roadmap's own construction does not exist until G8. Carrying all
three numbers to all three artifacts is a G9 line item and is named as such.

### 1.9 The P7 row's own gate: "Job completed without CLI; speech agrees with ledger; outcomes understood immediately."

**Two of three met; the third is the declined check.**

*Job completed without CLI.* A judge reaches a real case in one action with nothing typed
(`judgeEntry.test.tsx` *reaches a real case in one action, with nothing typed*, *publishes no
credential for the judge to type*), and a worker reports, answers, confirms and withdraws from the
conversation panel inside the workspace (`conversation.test.tsx`). One capability is the stated
exception — correcting a physical fact, §2 row 6.

*Speech agrees with ledger.* Everything a worker is told is rendered by `status_view` from the
durable case and delivered as given; the browser chooses which string goes to the screen and which
to the loudspeaker and composes neither (`spokenTurns.test.tsx` *speaks it byte for byte, adding
and removing nothing*, *reads the short rendering, never the long one, when the two differ*). A
turn is never drawn before the backend accepted it, and the case is re-read from the server after
every turn rather than patched (`conversation.test.tsx` *shows no turn at all until the backend has
accepted it*, *draws the state the re-read returned, never the one the turn implied*).

*Outcomes understood immediately.* This is the comprehension check, and it was declined. §1.6.

---

## 2. What G7 closes WITH — every exception, deferral and decline

Nothing in this list is an oversight; each is a decision somebody took, with a reason.

| # | what | kind | where it is recorded |
|---|---|---|---|
| 1 | **The 104-word withdrawal reply**, over the ≤40-word spoken budget and deliberately kept long, because compressing four reversal kinds into a count deletes the distinction the withdrawal record exists to protect | stated exception | [`spoken-word-budget.md`](spoken-word-budget.md) |
| 2 | **The spoken budgets are unproved for a case holding many distinct postures at once.** Proved for every case state, 1–12 promises and 0–6 left alone; not claimed beyond that. Such a case is read out in full rather than shortened into something untrue | stated exception | [`spoken-word-budget.md`](spoken-word-budget.md) |
| 3 | **The voice gate passed at `K = 9/10`** — the minimum that passes, by one turn — **on the local stack with no public-internet round trip, after a first run that was voided late.** Run 1's `K = 1/10` is published in full and unedited | measured result, at the margin | [`g7-ten-turn-voice-measurement.md`](g7-ten-turn-voice-measurement.md) |
| 4 | **The sixteen-scenario runner is authored and all sixteen are wired; five effect disagreements are published and deliberately unresolved; no scored run has happened and no `X/16` exists** | authored, unscored by rule | [`effect-set-harness.md`](effect-set-harness.md), [`effect-set-run-protocol.md`](effect-set-run-protocol.md) |
| 5 | **The Telegram customer channel is UNBUILT and DEFERRED to P6.3.** It is a **G6** requirement — ADR-0006 chose it and nothing implements it: no bot, no webhook ingress, no `secret_token` check, no `update_id` deduplication, no send path, and no `pp channel check`. The consent protocol itself is real and durable; what is missing is the transport between it and a real person's phone. It is **recorded rather than deleted** | deferral of a G6 requirement, target phase named | [`prerequisites-integration-cost-and-limitations.md`](prerequisites-integration-cost-and-limitations.md) §4.1, [`p6.2-first-deployment.md`](p6.2-first-deployment.md) §9 |
| 6 | **Correcting a physical fact remains CLI-only**, exactly as P7.1 records it: `intake.correct_physical_fact` exists in the domain and no MCP tool and no intent route reaches it. A correction is a new attestation and never an undo, and no disabled control is drawn for it | recorded limitation | [`p7.1-judge-ux-contract.md`](p7.1-judge-ux-contract.md) §5 |
| 7 | **The demo-narrative comprehension check was DECLINED by the project owner, who judged it low value relative to its cost.** It is a G7 criterion, so **G7 closes with one criterion deliberately not performed** — not met, not satisfied by something else, and not supported by any evidence in this build | declined criterion | this page, §1.6 |
| 8 | **The five demo-critical frames do not each compose in one unscrolled 1280×800 viewport** — a composition preference from this project's own P7.1 handoff list, traded against the causal rows. Not a frozen roadmap criterion | recorded unmet design item | [`p7.3-visual-acceptance.md`](p7.3-visual-acceptance.md) §2 |
| 9 | **The measurement is carried to one of three submission artifacts.** The one-pager and the video do not exist; carrying all three measured numbers to all three artifacts is a G9 line item, and one of those numbers cannot exist before G8 | forward obligation, named | this page, §1.8 |

---

## 3. What was done in this session

- **Verified** the four never-checked criteria against the implementation, and ran every test named
  for them (§0). Documents' claims were treated as pointers to evidence, never as the evidence.
- **Corrected** [`README.md`](../README.md) §Status, which still said *"There is no deployment"* —
  false since P6.2 and P7.3 — and still said the MCP surface carried **four** of the five intent
  tools, false since the bounded withdrawal landed. The manifest paragraph, which still said the
  suite *"has not been executed yet"*, now says what is true: all sixteen are wired and executable,
  five effect disagreements are published, and **no scored run has happened and there is no
  `X/16`**. The README also now carries the measured voice number, since it is one of the three
  artifacts G7 names.
- **Added a superseded note** to [`p7.1-judge-ux-contract.md`](p7.1-judge-ux-contract.md) §7, whose
  *"No turn has been recorded and no timing exists"* was true when written and is false now. The
  sentence is left unedited — that page is a record of what was fixed before implementation, not a
  running status — and the note points at the predeclaration and the measurement.
- **Wrote this page.**

Gates run for what changed: `apps/frontend` — **290 tests across 25 files, all passing**;
`apps/backend/tests/test_spoken_budget.py`, `test_status_view.py`, `test_consent_parser.py` and the
four database-backed criterion tests, all passing;
`scripts/tests/test_deployment_definition.py::test_a_restart_cannot_reseed_the_database`, passing.
No test was changed, weakened, skipped or added, and no product code was touched.

## 4. What this page does not close

- **G8.** The first scored effect-set run and its immutable `X/16` whatever it is, the five deployed
  rehearsals, and the release freeze.
- **G9.** The one-pager, the video, and the three measured numbers surfaced together on all three
  submission artifacts.
- **The Telegram customer channel**, which is G6's and is deferred to P6.3.
- **The demo-narrative comprehension check**, which is not deferred. It was declined, and G7 closes
  without it.

Both holdouts — explanation and customer-intent semantic — remain sealed and unopened. P4.8 stays
closed.
