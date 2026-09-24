# Phase 7 — the local release-candidate gate, closed

Date: 2026-09-24. Entry at `fe0cf8075dd8`, tracked tree clean, `main` equal to `origin/main`, the
eleven known untracked artefacts left as they were, the `pr` workflow green on that SHA and the
effect-set workflow red as expected. **Nothing here is deployed**: the deployed host still serves
`931a296decad`, and no AWS resource, IAM policy, SUR-1 artefact, effect-set artefact, frozen
manifest or earlier record was touched. [phase7-local-rc-correctness.md](phase7-local-rc-correctness.md)
is left exactly as it was; this record is what came after it.

That record left one P1 open and two adjacent items recorded. Each was reproduced through the
product's own paths before anything changed, and each has one verdict here.

| # | item | verdict |
|---|---|---|
| 1 | a silent sibling costs an answered promise its window (finding 4) | **REPRODUCED, FIXED** — [ADR-0025](adr/0025-an-answer-is-revalidated-when-it-arrives.md) |
| 2 | an amendment committed in time is first dispatched after its production start | **REPRODUCED, FIXED** — [ADR-0026](adr/0026-a-first-dispatch-that-provably-sends-nothing-is-judged-again.md) |
| 3 | the approval-window refusal claims a message was never delivered | **FIXED** (wording, internal row text) |

Both state-machine decisions were written as ADRs and committed **before** any production code.

## 1. A silent sibling

### Reproduced before editing

Proof C's world exactly as ADR-0023 built it (`with_charlotte_variant` authored, C's constraint set
to ask), so the canonical report asks Tomas about B and the Okafor-Reyes wedding about C. The
fixture's own schedule gives the unequal windows, and the test asserts them from the rows:
`B.deadline < B.start < C.deadline`. Tomas answered a literal `YES`; C's customer said nothing. No
workflow row was written by hand; the only clock moved is the one the step runner and the timer
sweep read, by a fixed offset.

`test_silent_sibling.py` was written first and run at `fe0cf80`: **6 of its 12 behavioural tests
failed**, each on the defect —

| test | failure at `fe0cf80` |
|---|---|
| B answered, C silent | `B's yes was not revalidated while C was silent` — no `revalidate:B` step |
| B's start passes | B still `WAITING_FOR_CUSTOMER`, never applied |
| C answers later | B's revalidation had never run on its own |
| **C times out** | **B ends `PENDING`**: refused `STALE` at C's deadline and re-planned behind its own start |
| C answers while B applies | B never reached `APPLYING` |
| B goes stale while C is silent | B's refusal never ran until C answered |

— and the other six (decline, replay, the joined round in both claim orders, an unconfirmed
re-plan, unrelated promises) passed at `fe0cf80`, as contracts that must not regress should.

### Root cause

`cases.settled_case_state` moved `WAITING → REVALIDATING` only once **no** request on the case was
open. One case state gated every track's revalidation on the slowest customer. It was not a simple
gate: the rest of the machine leaned on it (a decision in `REVALIDATING`, `RECONCILING` or
`PLANNED` had no exit; `RECONCILING` could be entered only once), so relaxing it alone would have
stranded the other track instead. ADR-0025 §"Why relaxing the gate alone is wrong" lists the four.

### The decision (ADR-0025)

One row-derived definition — an **unchecked approval**: a track `WAITING_FOR_CUSTOMER` whose carried
request is `ANSWERED` and decided, with no revalidation step under that request's key.

| from | before | after |
|---|---|---|
| `WAITING` | `→ REVALIDATING` only when no request is open | `→ REVALIDATING` on an unchecked approval (§14.2's per-decision exit); otherwise unchanged |
| `EXECUTING`, nothing runnable | `→ WAITING` if any request is open | an unchecked approval goes to `REVALIDATING` first |
| `REVALIDATING` | no exit; a decision arriving enqueued nothing | an approval arriving **joins the round**; the round still ends once (ADR-0023) |
| `RECONCILING` | `→ WAITING` if a request is open, even mid-change; `→ RESOLVED` | nothing leaves while a change is in flight; then `→ REVALIDATING` (unchecked approval), `→ WAITING` (open request), `→ RESOLVED` |
| `PLANNED` | a reply was **skipped** (and a second press of the link writes nothing: lost) | a reply is read and a literal decision recorded; the case does not move; the confirmation or the ten-minute escalation carries it on |
| reconcile step | one per case | one per entry into `RECONCILING`, keyed by how many have settled |

### Before and after, the defect's own flow

Before:

```text
B yes → WAITING (C open) ··· nothing reads B's yes ···
C deadline → REVALIDATING → B STALE (start passed) → PLANNED → B re-planned behind its start
```

After:

```text
B yes → REVALIDATING → B PROCEED → RECONCILING → apply B → B RECOVERED → WAITING (on C, nothing running)
C yes     → REVALIDATING → C PROCEED → RECONCILING (entry 2) → apply C → RESOLVED
C timeout → REVALIDATING → C NO_DECISION → RECONCILING (entry 2) → RESOLVED, owner attention
C no      → C ESCALATED at the decision → REVALIDATING → RECONCILING (entry 2) → RESOLVED
```

### Invariants proved (`test_silent_sibling.py`, 14 tests)

| invariant | test |
|---|---|
| B's yes is revalidated and applied while C is silent; the case goes `REVALIDATING → RECONCILING → WAITING` and waits on C with nothing outstanding | `…revalidated_and_applied_while_its_sibling_is_silent` |
| B's start passing afterwards changes nothing; no re-plan of B | `…b_s_start_passing_changes_nothing_once_b_is_settled` |
| C answering later is revalidated once, on its own request; B's checklist row is the same row, same attempt, same result; Tomas's reply to C's question authorises nothing; each amendment's authority names its own request | `…c_answering_later_is_revalidated_once_and_b_is_not_touched_again` |
| replaying every revalidation, apply, finalize and reconcile of both rounds adds no request, decision or effect | `…replaying_every_step_of_both_rounds_changes_nothing` |
| C timing out (clock only) escalates C; B stays changed once, not replayed, not undone | `…c_timing_out_escalates_c_and_neither_undoes_nor_replays_b` |
| C declining escalates C; B untouched | `…c_declining_escalates_c_and_neither_undoes_nor_replays_b` |
| C's answer read during B's round joins it, in **both** claim orders; the first checklist does not end the round | `…joins_the_round_in_either_claim_order[b]`, `[c]` |
| C's answer read while B's amendment is in flight is recorded now and checked only after B settles (so check 5 counts B as RECOVERED); B's amendment goes out twice under one key and changes the order once | `…c_answering_while_b_is_being_applied_waits_for_b_to_settle` |
| B stale while C silent: the round ends `PLANNED` with C open; C's yes is kept (not lost), checked after the worker confirms, applied once; B asked again once | `…b_going_stale_while_c_is_silent_re_plans_b_and_c_answers_into_the_plan` |
| the same, with nobody confirming: B to the owner, C's kept yes still checked once | `…an_answer_kept_through_an_unconfirmed_re_plan_is_still_checked` |
| A, D, E, F: identical state and effect count through B settling and C timing out; E and F never asked | `…nothing_unrelated_is_touched_while_b_settles_and_c_times_out` |
| `cases.RECOVERY_WORK_KINDS` equals `recovery`'s own three constants; both reconcile-key shapes name the case | two pins |

### One helper changed, and why it is not a weakening

`test_two_track_reask.one_round` built ADR-0023's shape — both answers in one round — by draining
after B's answer and **asserting the case was still `WAITING` with B's yes unchecked**. That
assertion was the defect. The helper now holds B's checklist (`defer`, then `release`, the
existing claim-order levers) only until C's reply has been read, so both answers still meet in one
round, and it asserts the new posture on the way (`REVALIDATING` after a yes, `WAITING` after a
no). Every outcome assertion of the module's eleven tests is unchanged and passes, in both claim
orders.

## 2. The first dispatch

### Reproduced before editing

The canonical case, Tomas's `YES`, the worker run until `PROCEED`, then `APPLY_RECOVERY` run while
B's start was ahead and the worker **killed at the product's own `AFTER_TRANSITION_COMMIT` crash
point**. The amendment was `PENDING` at **zero attempts**. Then only the clock moved past B's start,
and a fresh worker drained. At `fe0cf80`,
`test_a_committed_amendment_never_attempted_is_not_first_sent_after_its_start` failed: **one
provider call carried B's key** — the order changed after the start.

### The contract (ADR-0026, amending ADR-0024)

- **The outbox commit decides the effect; the first dispatch claim is where it becomes
  irrevocable.** Every claim commits `attempts + 1` before any provider call, so a claim that reads
  `attempts == 1` is provably the first and **no earlier call exists**.
- **On that claim only**, an `ORDER_AMEND` re-judges check 6's time half: *now < the line's
  scheduled production start* (unknown start fails closed). Otherwise it is refused **unsent** —
  `FAILED` at one attempt, no provider reference, `last_error` prefixed
  `refused unsent at its first dispatch` — and the failure continuation ends the track exactly as
  an apply-time refusal would: `ESCALATED` `PLAN_STALE`, scheduled work `HELD`, nothing re-planned.
  Never `DOWNSTREAM_UNAVAILABLE`, which would say the order system failed when it was never asked.
- **From `attempts ≥ 2` there is no time gate.** The rows cannot tell "died before the call" from
  "applied, acknowledgement lost", so it is treated as possible acceptance and re-sent under the
  same key, which the order system collapses.

### Proved (`test_execution_freshness.py`, 4 new, 8 total)

| test | pins |
|---|---|
| `…never_attempted_is_not_first_sent_after_its_start` | zero calls carrying the key; row `FAILED`, 1 attempt, no provider ref; B `ESCALATED` `PLAN_STALE`; task `HELD`; the `PROCEED` and the one decision kept |
| `…never_attempted_is_sent_first_while_its_start_is_ahead` | the same pause with the start ahead: one call, `DELIVERED` at 1, B `RECOVERED` |
| `…accepted_before_a_crash_is_re_sent_after_its_start_and_changes_once` | `AFTER_EXTERNAL_SUCCESS`, then the clock past the start: two calls, one logical effect, `DELIVERED` at 2 |
| `…claimed_but_unrecorded_is_treated_as_possibly_sent` | `AFTER_OUTBOX_CLAIM` (no call made), then past the start: not gated, one call, one effect — the disclosed residual |

The ADR-0024 lost-acknowledgement test (`RETRYABLE` path) is unchanged and passes: exactly one
logical external effect in every uncertain path.

## 3. The approval-window wording

The approval-message gate refuses on every claim, which is right, but its row text said the window
closed "before the message could be delivered" — false when an earlier attempt may have reached
the customer. It now uses the same discriminant as §2: at one attempt, "the approval window closed
before the message was sent"; after that, "…before this attempt; an earlier attempt may already
have reached the customer". Proved in `test_customer_approval.py` by
`…refused_at_its_first_claim_says_it_was_not_sent` and
`…window_closing_after_an_uncertain_attempt_claims_nothing_it_cannot_know` (the provider holds the
message; the row no longer denies it). The text is shown to an operator only, verbatim, in the
evidence drawer; no frontend code or copy changed.

## 4. Validation

Sequential throughout: no `xdist`, no worktree, no temporary clone, and no test weakened, skipped,
deselected or `xfail`ed. The compose `worker`, `api` and `mcp` were stopped for every database run.
The broad run below ran against exactly the code that is committed; only this record and the
operating contract changed after it started.

| check | result |
|---|---|
| `test_silent_sibling.py` at `fe0cf80`, before any production change | **6 failed**, 6 passed (the failures listed in §1) |
| the four new `test_execution_freshness.py` tests at `fe0cf80` | **1 failed** (one provider call carried B's key after its start), 3 passed |
| `test_silent_sibling.py` | **14 passed** |
| `test_two_track_reask.py` (ADR-0023, both claim orders) | **11 passed** |
| `test_execution_freshness.py` | **8 passed** |
| the two new wording tests and the existing queued-window test | **3 passed**; the two new ones assert the new literal, which the old code does not produce |
| one sequential run over 34 modules: the three above, `test_customer_approval`, `test_authority_provenance`, `test_customer_answer_uncertainty`, `test_recovery_revalidation`, `test_recovery_execution`, `test_truthful_recovery`, `test_order_amendment`, `test_order_mirror`, `test_order_system_boundary`, `test_approval_reask`, `test_customer_approval_link`, `test_customer_intent`, `test_consent_authority`, `test_human_confirmation_boundary`, `test_adversarial_races`, `test_step_execution`, `test_workflow_outbox`, `test_workflow_inbox`, `test_workflow_timers`, `test_workflow_handlers`, `test_worker_recovery`, `test_worker_responsiveness`, `test_withdrawal`, `test_withdrawal_contract`, `test_started_work_contract`, `test_whole_delivery_counterfactual`, `test_impact_analysis`, `test_case_workspace`, `test_status_view`, `test_causal_chain`, `test_plan_identity` | **806 passed**, 0 failed, 0 errors, 0 skipped (2116 s) |
| `mypy` over `packages/promise-graph packages/order-contract apps/backend` | no issues, 297 files |
| `lint-imports` | 30 kept, 0 broken |
| `ruff check`, `ruff format --check` on every changed Python and Markdown file | clean |

**Not run**, and why: the whole backend suite (roughly an hour; GitHub CI is the regression
authority and nothing is pushed); `mypy` groups B and C (nothing under `apps/order-simulator`,
`evals` or `scripts` changed); the frontend suites (no frontend code or copy changed — the evidence
drawer renders the outbox row's text as data); `test_mcp_protocol.py` (nothing on its path changed,
and its local refusals time out on this machine's TLS proxy); the Playwright specs (they need images
rebuilt from the release SHA); the effect-set scenarios and every SUR-1 artefact (out of scope and
frozen — published runs are history and are not re-scored; a future run would meet the new case
behaviour). No live path was exercised: everything is proved locally against the fake provider.

## 5. What remains

**No known local P0 or P1 remains.** Finding 4 is closed by ADR-0025, the first-dispatch residual
by ADR-0026, and the wording by §3.

Known residuals, disclosed, none an authority breach:

- **ADR-0026's irreducible window.** A dispatcher that dies between committing an amendment's first
  claim and calling the provider leaves rows identical to one that died after the call; the next
  claim is ungated, so a death inside that window *and* an outage past the start still delivers
  late — once, under the same key. Pinned by `…claimed_but_unrecorded_is_treated_as_possibly_sent`.
- **An answer read while the case is `PLANNED`** waits for the worker's confirmation or the armed
  ten-minute escalation before it is checked (ADR-0025). Bounded, and it cannot be lost.
- **Check 5 counts only siblings already `RECOVERED`** (§14.3's own wording). When two answers meet
  in one round, the second checklist can run while the first track has passed but not yet applied,
  so two tracks sharing one scarce substitute could both pass. Pre-existing, not introduced here,
  and **not reproduced**: no authored world has two asked promises sharing a substitute (B's is
  rose, C's strawberry). ADR-0025 narrows it — an answer that arrives while a sibling is applying
  is now checked after that sibling settles. Rated P2 here; the owner decides.
- ADR-0024's substitute-allocation clock sensitivity on automatic tracks, unchanged.
- Phase 6's P2s stand as recorded there.

**Next AWS session — the RC deployment, in this order and nothing else:**

1. Push this head only when the project owner asks; wait for `pr` green on the exact SHA (effect
   sets red as expected). Build images from that SHA and run the three Playwright specs against
   them, `customer-approval.spec.ts` included (owed since Phase 7 session 1).
2. Read the deployed historical case read-only, before anything can erase it.
3. `deploy.sh images` for the release SHA; carry the tag to the host by a parameter-only change set
   against the previously deployed template, gated on an empty resource change list and authorised
   explicitly by the owner. `deploy.sh stack` still cannot carry it (non-destructive-release §10.1).
4. `pp restore-demo-world --confirm destroy-and-restore` with the reseed and channel settings
   supplied on the host, carrying the Telegram binding across; smoke from the host (not from this
   machine, whose TLS proxy truncates three probes); verify the deployed image is the release SHA.
5. Optionally, and only if the owner wants live evidence of the new behaviour: nothing in the
   canonical demo reaches ADR-0025 (it asks one customer), so a two-customer live proof would need
   the Proof C world on the host — a separate, explicitly authorised step, not part of the release.
