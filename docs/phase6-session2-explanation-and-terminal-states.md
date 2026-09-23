# Phase 6 session 2 — why it escalated, and how the customer's page ends

Date: 2026-09-23. Entry at `cdb450304ebd`, tracked tree clean, `main` equal to `origin/main`, the
eleven known untracked artefacts left as they were, the `pr` workflow green on that SHA and the
effect-set workflow red as expected. Read-model and presentation work only. **Nothing here is
deployed**: the deployed host still serves `931a296decad`, and no AWS resource, IAM policy, SUR-1
artefact, effect-set artefact, frozen manifest or earlier record was touched. The session 1
record, [`phase6-ux-journey-polish.md`](phase6-ux-journey-polish.md), is left exactly as it was;
this document is what came after it.

No recovery rule, authorisation rule, state, transition or consent path changed. Every change
below reads a row that already existed and says it in words.

## 1. Why did it escalate? The audit

Session 1 recorded (finding 5) that the deployed case read "Covered by a standing preference"
and "needs you" on the same row, with nothing saying why. The audit was held to four questions
before anything was edited.

**Every reachable transition into `ESCALATED`**, read from source:

| module | path | recorded reason |
|---|---|---|
| `recovery` | plan confirmation, a `BLOCKED` track | `BLOCKED` |
| `recovery` | plan confirmation, an automatic track with no chosen option | `NO_CHOSEN_OPTION` |
| `recovery` | §14.1's ten minutes pass with the plan unconfirmed | `PLAN_UNCONFIRMED` |
| `recovery` | the confirmed plan no longer matches the world before it is applied | `PLAN_STALE` |
| `recovery` | the amendment is abandoned after its retry bound | `DOWNSTREAM_UNAVAILABLE` |
| `recovery` | the order system accepted the change and never echoed it | `MIRROR_NOT_RECONCILED` |
| `approvals` | the request step finds no chosen option | `NO_CHOSEN_OPTION` |
| `approvals` | no approval window is left before the deadline | `NO_APPROVAL_WINDOW` |
| `approvals` | the deadline passes with no answer | `APPROVAL_EXPIRED` |
| `approvals` | the message cannot be delivered | `MESSAGE_UNDELIVERABLE` |
| `approvals` | a second non-literal reply | `CONFIRMATION_UNANSWERED` |
| `approvals` | a literal no | `APPROVAL_DECLINED` |
| `revalidation` | check 7: a yes whose window has since closed | `APPROVAL_EXPIRED` |
| `withdrawal` | a withdrawal after something had already gone out | `WITHDRAWN_AFTER_EFFECTS` |

**Whether the cause exists durably.** It does, on every path. Each transition appends a domain
event in the same transaction that writes `ESCALATED`, carrying `payload.reason` and the track in
`entity_refs`: `track.escalated` on all paths but one, and `approval.expired` /
`approval.delivery_failed` on the path that closes a request. The audit ledger carries it too,
but in four different shapes (a per-track `after.reason`, a case-level map on
`PLAN_CONFIRMED`, a decision with no reason key, a withdrawal with none at all).

**The narrowest authoritative source** is therefore the domain event: one field, one shape,
appended by the transition itself. `ESCALATED` is terminal, so a track has at most one; the read
keeps the latest in ledger order so that this is observed rather than assumed.

**Whether it projects read-only.** It does, through the existing layers and nothing new:
`analysis.read_case_status` reads the events for the case into `TrackStatus.escalation`,
`status_view` turns the token into a clause, and the API and the screen carry both. No workflow
persistence, no state-machine semantics and no second reason system: the tokens are the
workflow's own, and a test holds the phrase table to every `ESCALATION_*` constant the three
writing modules define, and the event names to the constants that append them.

**Root cause of the gap.** Not a missing record. The read service had been built to show
`tracks.reason_detail` — the engine's classification reason — and `recovery` deliberately
records the escalation reason *elsewhere* so as not to overwrite it. Nothing read that second
place back. The screen answered "why was this planned" and had no answer to "what then stopped
it", so a covered promise that escalated contradicted itself.

**The deployed case.** Its shape — left `PLANNED` after the restore, later `RESOLVED` with every
threatened order `ESCALATED`, zero effects and no approval request — is exactly §14.1's plan
window closing unconfirmed, which escalates every live track and sends nothing. That is a
hypothesis from the shape, not a diagnosis: this session read nothing on the host. The local
reproduction (§5) shows what the deployed screen would now say, from the host's own ledger, once
this is released.

## 2. What was found

| # | class | finding | disposition |
|---|---|---|---|
| 1 | **P1** | An escalated promise shows why it was *planned* and nothing about what *stopped* it. The cause is durable and was never read back. | fixed, `f1643f8` |
| 2 | **P1** | The customer page reads the track's *current* state, but a re-plan or withdrawal supersedes the request and unbinds the track in one transaction. A superseded yes was then reported through whatever the track did next: silent once the re-plan left it `PENDING`, and — by the same code — "the bakery checks your order", with the page re-reading, or "your order now shows this change", for a later plan the customer never saw. | fixed, `c9d6bdb` |
| 3 | **P2** | A `REQUESTED` row said "the customer has been asked and has not answered" twice. | fixed, `802d1dc` |
| 4 | **P2** | Evidence layer 3 printed `Revalidation: PROCEED` and `A decision is recorded: APPROVE`. | fixed, `44ecf91` |
| 5 | **P2** | The case list's read failure said "They will be retried on the next event". | fixed, `3bc552b` |
| 6 | P2 | `explanations.CONSENT_AUTHORITY` says "their own channel". | **left**, see below |
| 7 | **P1**, out of scope | A promise re-planned after a stale yes is never asked again. Re-confirming lists it under `awaiting_approval`, but the request step's key is `approval:<track>`, already `DONE` from the first request, so no step runs; the case sits at `EXECUTING` with the track `PENDING`. Found while proving finding 2. | recorded, not fixed — workflow semantics |
| 8 | P2, out of scope | A revalidation refused `UNAUTHORIZED` leaves the track waiting for the owner by design, so a link page for it keeps re-reading "the bakery checks". Reachable only through a broken persisted reply chain; a link answer cannot produce it, because the link is minted for the channel it answers on. | recorded |

**No P0.** Nothing on any surface implied authority a model, a Telegram reply or an observer does
not hold.

Finding 6 was re-verified rather than taken on trust: `CONSENT_AUTHORITY` reaches only
`verbalisation`, which nothing in the API, the worker or the CLI imports — its callers are the
closed explanation gate's evals. It is frozen G7 material, not active product text, and the
instruction was to change it only if it were the latter.

Finding 4 has one deliberate limit. The explanation layer publishes two clauses per revalidation
outcome, the verdict and what follows. Only the verdict is shown: for `PROCEED` the second is
"the approved change is applied", and beside a promise whose amendment is unconfirmed, or was
never observed and went to the owner, that would claim a change nobody saw. Whether the change
landed stays the promise's own state to say.

## 3. What changed

| commit | change |
|---|---|
| `f1643f8` `feat(workspace): say what handed a promise to the owner, apart from why it was planned` | `TrackStatus.escalation` read from the escalating event; `PromiseView.escalation_reason` / `escalation_phrase`; the API carries both on the promise, and `escalation_reason` / `escalated_at` on the evidence row. The row gains a labelled **stopped because** line under the unchanged reason; layer 1 adds "Then it went to the owner, because …"; the token and its time sit in the technical record. The spoken status is byte for byte unchanged, and a test says so. |
| `c9d6bdb` `fix(customer): never report a later plan's progress on a superseded question` | The customer view reads the track only while `track.approval_request_id` is this request — set when the request is created, cleared only by the transaction that supersedes it. A superseded yes says "Your order changed after you were asked, so this question no longer applies." and stops re-reading; a question superseded before any answer keeps the stood-down and follow-up sentences and loses the ones that would claim this change. |
| `3bc552b` `fix(ui): say a failed case-list read in plain words` | "The list of cases could not be read. Nothing about any case has changed; the screen will try again by itself." True: a failing read re-tries on its own interval. |
| `802d1dc` `fix(workspace): stop an asked promise saying the same sentence twice` | The `REQUESTED` next action is now "Nothing until the customer answers on their approval page." |
| `44ecf91` `fix(workspace): say revalidation and the customer's answer in words above their tokens` | `RevalidationEvidenceView.outcome_phrase` from the explanation layer's own verdict; layer 3 reads "Checked again before anything changed: the plan is still valid." with `PROCEED · check n — detail` beneath, and the approval line uses the domain's consent sentence ("The customer said yes.") with the decision token moved to the technical record. |

## 4. The customer's page, at every ending

Each row is one link read repeatedly while the workflow runs — before the press, after it,
after the decision and after what followed — not a page opened once everything had settled.
`awaiting_outcome` is the server's; the page re-reads while it is true and decides nothing
itself.

| ending | readings, in order (`phase`, outcome, re-reading) | proved by |
|---|---|---|
| yes, carried out | `OPEN` · — · no → `RECEIVED` · — · yes → `APPROVED` · "…checks that your order can still be made this way." · yes → `APPROVED` · "Your order now shows this change." · **no** | `test_one_tab_follows_a_yes_from_the_question_to_the_changed_order` |
| no | `RECEIVED` · yes → `DECLINED` · "The bakery will follow up with you about this order." · **no**; row cause `APPROVAL_DECLINED` | `…_follows_a_no_to_the_bakery_s_follow_up` |
| no answer in time | `OPEN` · no → `EXPIRED` · follow-up · **no**; cause `APPROVAL_EXPIRED` | `…_stops_when_nobody_answered_before_the_window_closed` |
| yes, window closed before it was carried out | `APPROVED` · checks · yes → `APPROVED` · follow-up · **no**; no amendment; cause `APPROVAL_EXPIRED` | `…_stops_when_the_window_closed_before_a_yes_was_carried_out` |
| yes, order system refused the change | `APPROVED` · checks · yes → `APPROVED` · follow-up · **no**; never "now shows" | `…_stops_when_the_order_system_refuses_an_approved_change` |
| yes, then the bakery withdrew | `APPROVED` · follow-up or stood-down · **no**; no amendment | `…_stops_when_the_bakery_withdraws_after_a_yes` |
| withdrawn before an answer | `OPEN` · no → `SUPERSEDED` · **no** | `…_stops_when_the_bakery_withdraws_before_an_answer` |
| yes, went `STALE`, re-planned, re-confirmed | `APPROVED` · checks · yes → `APPROVED` · "…this question no longer applies." · **no**, and still that after the worker re-confirmed | `test_a_yes_that_went_stale_is_never_told_the_next_plan_s_progress` |

Before the fix the last row went silent after the re-plan (`outcome: null`). The states a later
plan could move the track into — asked again, applying, recovered — are not reachable live today
(finding 7 is why), so the rule for them is proved directly on the view's own functions, for both
the answered and the superseded phase. The frontend proves the transition on the page itself: a
tab reading "checks" and then "no longer applies" stops asking, however long it stays open.

## 5. Before and after, for a judge

The local reproduction of the deployed shape: the canonical report, clarified, and the plan
window closed with nobody confirming it.

| row | before | after |
|---|---|---|
| EXT-A, covered by a standing preference | **needs you** · the order already pre-approves this substitution · *next* The owner handles this one by hand. | **needs you** · the order already pre-approves this substitution · **stopped because** nobody confirmed the plan within its time limit, so nothing was changed · *next* … |
| EXT-C, needs the owner (canonical, confirmed) | **needs you** · the order carries a no-substitution constraint | the same, and **stopped because** the confirmed plan had no change it could make to this order |
| EXT-B, asked | *customer* the customer has been asked and has not answered · *next* Nothing. The customer has been asked and has not answered. | *customer* the same · *next* Nothing until the customer answers on their approval page. |
| layer 3, an approved and revalidated promise | Revalidation: PROCEED · A decision is recorded: APPROVE. | Checked again before anything changed: the plan is still valid. `PROCEED` · The customer said yes. |

EXT-E and EXT-F, untouched, carry no cause and no effect in either reproduction.

**Read live**, as the observer, on the local stack rebuilt from `44ecf91`, off a case the browser
specs had left at `WAITING`. That case's EXT-A had escalated during the run, and the row now says
what its own ledger recorded — which the specs never set out to produce, and nobody chose:

```text
Priya Nair  EXT-A  needs you  ESCALATED
  the order already pre-approves this substitution
  STOPPED BECAUSE the order system did not take the change after repeated tries
  NEXT The owner handles this one by hand. Nothing will change until they do.
Tomas Lindqvist  EXT-B  asked  REQUESTED
  the change is visible and the order says to ask · by 23 sept., 23:15 UTC+2
  CUSTOMER the customer has been asked and has not answered
  NEXT Nothing until the customer answers on their approval page.
Okafor-Reyes wedding  EXT-C  needs you  ESCALATED
  the order carries a no-substitution constraint
  STOPPED BECAUSE the confirmed plan had no change it could make to this order
```

Before this session the same row read "needs you" beside "pre-approves this substitution" and
nothing else. The spoken status on the same screen is unchanged, byte for byte.

## 6. Validation

| check | result |
|---|---|
| `test_status_view.py` | **74 passed**, 9 new |
| `test_case_workspace.py`, `test_customer_approval_link.py`, `test_truthful_recovery.py`, `test_spoken_budget.py`, `test_cli.py` — real PostgreSQL, one sequential run on the final tree | **619 passed**, 0 failed, 0 skipped |
| of which new: 2 in `test_case_workspace.py`, 14 in `test_customer_approval_link.py` (8 transitions, 5 rule cases, 1 drawer) | passed |
| frontend unit suite | **340 passed** of 340, 8 new |
| `npm run typecheck`, `npm run lint`, `npm run build` | clean |
| `ruff check`, `ruff format --check` on every changed Python file; `mypy` group A | clean; 291 files, no issues |
| `lint-imports` (`analysis` gained a model import) | 30 kept, 0 broken |
| `customer-approval.spec.ts`, real stack, rebuilt images, worker running | **7 passed** |
| `judge-journey.spec.ts` + `responsive.spec.ts`, all four widths | **28 passed** |

Sequential throughout; no `xdist`, no worktree, no test weakened, skipped or deselected. Two
existing expected literals moved with the product text they pin — the `REQUESTED` next action in
`test_status_view.py` and in the frontend fixture — and each assertion stays exact.

Disclosed rather than smoothed over:

- The first customer-spec attempt failed before any test ran: `resetOrderSystem` targets the
  e2e default `localhost:58100`, which this machine cannot bind. With `E2E_API_URL` and
  `E2E_ORDER_SYSTEM_URL` pointed at the stack's real `48xxx` ports, all seven passed. No spec
  was changed.
- The browser specs need the judge entry, which this machine's `docker/env/api.env` turns off
  for the SUR-1 path. It was enabled on `api` alone through a compose override kept outside the
  repository, and `api` was recreated on its own environment afterwards. The worker ran for the
  browser specs and was stopped again. The stack is as it was found — `api`, `mcp`, `postgres`,
  the order system and the frontend up, the worker stopped — on images rebuilt from this work.
  The reseeds the specs and the suite perform erased the local cases, which were demo data.
- The whole backend suite was not run (roughly an hour); GitHub CI is the regression authority.

## 7. What remains

- **Finding 7 is the most important thing this session found and did not fix.** A promise
  re-planned after a stale yes can never be asked again, and its case stops moving without
  escalating — the "promise that stops moving without saying so" the status projection exists to
  prevent. It needs a workflow decision (a request step keyed by request rather than by track, or
  an escalation on re-plan), and that is state-machine work, so it was stopped at and reported.
- **Nothing here is deployed.** The deployed case would now explain itself from its own ledger
  once a release carries it, and that release is deployment work.
- **The deployed cause is inferred from its shape**, not read. A read-only look at that case's
  `track.escalated` events on the host would confirm or refute `PLAN_UNCONFIRMED` in one query.
- Finding 8, and the live refusal paths recorded in
  [`customer-disclosure-hardening.md`](customer-disclosure-hardening.md) §7, remain proved by
  tests only.
