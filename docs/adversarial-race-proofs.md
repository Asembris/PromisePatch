# Adversarial race proofs — contention, fencing and revalidation

**Status: six proofs added, one boundary audited, no defect found.** Nothing in the frozen
effect-set manifest, the `11/16` headline or the `SUR-1` benchmark was read as authority, run,
scored or edited by this work. `SUR-1` was not executed.

Built at HEAD `29e2185` (*docs(g8): amend the proof map where it still says the correction is
declined*), on the branch `main`. The working tree carried five untracked files before and
after — `REMAINING_WORK_ASSESSMENT.md` and four `docs/effect-sets/runs/*-development.json`
captures — none of which was read as evidence or staged.

This page is the companion to [g8-adversarial-proof-map.md](g8-adversarial-proof-map.md),
which audited the faults the G8 gate *names*. This one covers the faults it does not name: what
happens when two actors, or an actor and the clock, contend for the same thing at the same
instant.

---

## 1. Prior coverage, before anything was written

The audit came first, because the roadmap's own G8 bullet says *"reuse core tests rather than
duplicate for counts"*. Every row below was settled by opening the test and reading its
assertions.

| race | already proved by | verdict |
|---|---|---|
| **Stale revalidation — order version** | `test_recovery_revalidation.py::test_an_order_amended_while_waiting_makes_the_approval_stale` | **covered** |
| **Stale revalidation — substitute stock** | `::test_a_substitute_eaten_while_waiting_makes_the_approval_stale` | **covered** |
| **Stale revalidation — recipe pin** | `::test_a_repinned_recipe_version_makes_the_approval_stale` | **covered** |
| **Stale revalidation — constraint snapshot** | `::test_a_rewritten_constraint_snapshot_makes_the_approval_stale` | **covered** |
| **Stale revalidation — production task** | `::test_a_task_that_has_started_…`, `::test_a_task_whose_start_has_passed_…`, `::test_a_task_another_case_holds_…`, `::test_a_task_this_case_holds_does_not_block_its_own_recovery` | **covered** |
| **Change landing *after* a passing checklist** | `::test_a_change_landing_after_a_passing_revalidation_still_stops_the_amendment`, `::test_a_change_to_watched_state_is_seen_by_the_commit_guard` | **covered** |
| **Concurrent claim of one step** | `test_step_execution.py::test_two_workers_cannot_own_the_same_step`, `::test_skip_locked_lets_workers_take_different_steps`, `test_worker_recovery.py::test_two_workers_share_the_work_without_coordinating` | **covered, but only sequentially** |
| **Concurrent claim of one outbound effect** | `test_workflow_outbox.py::test_two_dispatchers_cannot_claim_one_message` | **covered, but only sequentially** |
| **Lease expiry and the fencing token** | `test_step_execution.py::test_an_expired_lease_is_reclaimable_and_bumps_the_fencing_token`, `::test_a_live_lease_cannot_be_stolen`, `::test_a_worker_holding_the_execution_row_lock_cannot_be_reclaimed_from` | **covered** |
| **A fenced worker writing nothing** | `::test_a_stale_worker_cannot_overwrite_the_work_that_replaced_it`, `::test_a_reclaimed_step_rejects_its_previous_owner_before_anyone_finishes_it`, `::test_a_stale_worker_writes_nothing_when_the_step_was_already_settled`, `test_workflow_outbox.py::test_a_dispatcher_that_lost_its_lease_cannot_record_a_result` | **covered database-side only** |
| **A preparation outliving its lease** | `test_worker_responsiveness.py::test_a_preparation_that_outlives_its_lease_still_commits_nothing` | **covered** |
| **Approval race — expiry** | `test_customer_approval.py::test_an_expiry_that_committed_first_refuses_a_later_yes`, `::test_a_decision_that_committed_first_makes_the_timer_a_no_op`, `::test_a_late_reply_cannot_approve_even_before_the_timer_runs` | **covered** |
| **Approval race — two answers** | `::test_a_yes_and_a_no_racing_leave_exactly_one_decision`, `::test_the_decision_that_won_is_never_overwritten`, `::test_a_decided_request_cannot_be_answered_twice` | **covered** |
| **Approval race — supersession** | `test_recovery_revalidation.py::test_a_superseded_request_authorises_nothing`, `::test_a_decision_bound_to_another_plan_authorises_nothing` | **covered** |
| **Approval race — withdrawal** | **nothing** | **GAP** |
| **Duplicate / replay — customer reply** | `test_consent_authority.py::test_a_redelivered_reply_decides_once`, `test_customer_approval.py::test_a_duplicate_provider_delivery_is_absorbed` | **covered** |
| **Duplicate / replay — inbound record** | `test_workflow_inbox.py::test_a_repeated_delivery_stores_one_record`, `::test_a_repeated_delivery_produces_no_second_piece_of_work`, `::test_reprocessing_a_record_cannot_duplicate_its_successor` | **covered** |
| **Duplicate / replay — effect delivery** | `test_workflow_outbox.py::test_a_delivered_message_is_never_sent_again`, `::test_a_retry_presents_the_identical_key`, `test_recovery_revalidation.py::test_an_approved_amendment_applied_twice_by_transport_is_one_effect` | **covered** |
| **Deferred semantic — bound and no duplication** | `test_worker_responsiveness.py::test_several_slow_cases_progress_together_and_none_of_them_twice` | **covered** |
| **Deferred semantic — unrelated cases independent** | `::test_unrelated_ready_work_does_not_wait_behind_a_slow_semantic_preparation` | **covered** |
| **Deferred semantic — same-case work overtaking** | `::test_a_claim_sweep_leaves_an_excluded_case_alone` proves the *exclusion argument* in isolation; nothing drives the real loop | **GAP** |

Three gaps, and they are the three this work closed. Everything marked *covered* was left
alone: no test was rewritten, renamed or duplicated for a count.

---

## 2. What was added

One file, `apps/backend/tests/test_adversarial_races.py`, six tests. Each carries the five
lines the brief asked for — initial state, race, invariant, receiver-side observation,
expected fail-closed result — in its own docstring, so a reader of the test does not have to
come here.

### 2.1 Real contention, not a written-down order

The existing claim proofs are sequential: A claims, then B claims, and B is told there is
nothing to take. That proves the predicate but never produces contention — B's call begins
after A's has committed, so nothing ever raced.

`sessions` is a fixture of **four independent `RuntimeDatabase` handles, one connection each**.
`pool_size=1` is the point rather than an economy: a handle that could hand out a second
connection would let a contender queue behind itself, and the race would be with the pool
instead of with PostgreSQL. Four rather than two, because two contenders pass a broken
`SKIP LOCKED` by luck often enough that a flake reads as a pass.

| test | what it races | result |
|---|---|---|
| `test_four_independent_sessions_racing_one_step_leave_exactly_one_owner` | four sessions call `claim_step` inside one `asyncio.gather` against one `PENDING` row | exactly one claim; the other three are told `None`, the same answer an empty queue gives. The winner holds attempt `1`, so no loser bumped the fencing token on its way past. |
| `test_racing_sessions_that_all_execute_deliver_one_effect_to_the_provider` | the same four sessions claim *and execute* concurrently against an `EMIT_EFFECT` step | one `COMPLETED`; **one** outbox row; **one** call to the recording adapter under that idempotency key. |

### 2.2 Receiver-side fencing

The existing fencing proofs stop at the database — they assert no case version, no successor,
no audit row, no event. None of them follows the chain to the provider, which is the only place
a duplicate would be one a customer could feel.

`test_a_fenced_worker_causes_no_second_call_to_the_provider` closes that. A claims; A's lease
is aged into the past; B reclaims as attempt 2, executes, and the effect B enqueued is
**dispatched all the way to the adapter**. Only then does A wake and try to finish. The
provider-call count is taken twice — once before A resumes and once after — so a second call
caused by A's resumption cannot hide inside the first. A is refused `STALE`; the count is `1`
both times; the outbox holds one row.

### 2.3 A withdrawal crossing a customer's reply

The gap. `test_withdrawal.py` proves a decision recorded *before* a withdrawal survives it;
`test_recovery_revalidation.py` proves a superseded request authorises nothing. Between them
no test lets a **real reply cross a real withdrawal in flight**.

Both new tests stage the canonical case waiting on promise B's customer, then:

1. the literal `YES` is delivered — stored as an inbound row, **not yet swept**;
2. the worker withdraws the case, and that commits;
3. only then does a worker drain, and read the reply that was already sitting there.

`test_a_yes_queued_before_a_withdrawal_authorises_nothing_after_it` asserts B's track carries
no `ORDER_AMEND` effect, the request is `SUPERSEDED`, the case is terminal, and the order book
is unchanged **across the drain**. `test_a_superseded_request_records_no_customer_decision_at_all`
asserts zero decision rows, no growth in outbound effects, and that the customer's words are
still kept verbatim as a reply — refused as authority, kept as testimony.

> **One correction made during the work, recorded because it changed an assertion.** The first
> version of the order-book baseline was taken *before* the withdrawal and failed on
> `production_tasks`. That was the test being wrong, not the system: a withdrawal is entitled to
> release the production holds its case took, which is its documented reversal and is pinned by
> `test_withdrawal.py::test_a_withdrawal_after_a_hold_releases_only_this_case_s_holds`. The
> baseline now brackets the **drain** rather than the withdrawal, which is what was under
> attack. No assertion was weakened to make a race pass; the assertion was aimed at the right
> interval.

### 2.4 A deferred preparation holds its case

`test_a_case_held_open_by_a_preparation_starts_no_second_step_beside_it` drives the **real
`run_forever` loop**, not the claim function in isolation. A case whose sentence the lexicon
cannot read is taken to its semantic step; the loop claims it and hands it to a task beside
itself, where it sits in a five-second provider call. **Inside that window** a second step of
the *same* case is enqueued, and then an unrelated case is opened.

The barrier is the claim order, not a sleep. `claim_step` orders candidates by
`created_at, id` and takes one, and the same-case step is created *first* — so if it were
claimable at all it would have been claimed ahead of the unrelated case's step. The unrelated
step having started is therefore proof that a sweep ran, looked at the same-case step, and
skipped it. The held row is asserted `PENDING`, `attempts == 0`, `started_at is None`; after
the preparation finishes it is claimed normally and reaches `attempts == 1`. Held, never lost.

**The test was shown not to be vacuous.** With `exclude_cases=tuple(self._deferred)` replaced by
`exclude_cases=()` in `worker.py`, it fails on exactly the intended line — *"a second step of a
held case ran beside its preparation"*. The mutation was reverted and `worker.py` is
byte-identical to HEAD; no production source was changed by this work.

---

## 3. The one boundary audited and deliberately not pinned

`Worker._execute_one_step` passes two narrowings to `claim_step`:

```python
claim = await steps.claim_step(
    self.database,
    worker=self.identity.value,
    exclude_cases=tuple(self._deferred),
    exclude_kinds=(() if not defer or self.deferred < self.deferred_limit else SEMANTIC_KINDS),
)
```

They are not symmetric, and the asymmetry is worth stating plainly.

`exclude_cases` is **unconditional**: a case with a deferred preparation is excluded whatever
the capacity, which is the invariant §2.4 now pins. `exclude_kinds` applies only when the
deferral budget is exhausted, and it narrows by *kind*, not by case. So in principle a younger
non-semantic step of case X could be claimed ahead of an older, still-`PENDING`, unclaimed
semantic step of the same case X — and `test_worker_responsiveness.py::test_a_claim_sweep_leaves_an_excluded_kind_alone`
asserts exactly that overtaking, as the desired behaviour of the narrowing in isolation.

**It is unreachable in current product flows, and that was checked rather than assumed.** A
semantic step exists only during intake, and a case in intake has exactly one outstanding step,
because the three things that could enqueue a second one all refuse at that point:

| what could enqueue a second step | why it cannot, during semantic intake |
|---|---|
| a correction | `intake.correct_physical_fact` raises `NothingToCorrectError` when `cases.exception_id` is `NULL`, and the exception is not bound until interpretation resolves |
| a clarification answer | requires an open `ExceptionClarification`, which is raised only *after* interpretation resolves |
| an inbound reply, a timer, an outbox continuation | all belong to the consent and recovery phases, which are downstream of intake |

No test was written to pin this. Unreachability is not a property a test can assert honestly —
a test would have to construct the unreachable state and then assert something about it, which
documents the construction rather than the boundary. It is recorded here instead, so that a
future slice which gives a case a second step during intake knows this is the thing to re-check.

---

## 4. Conclusions

- **Concurrency.** Exclusive claim survives genuine contention from four independent PostgreSQL
  sessions, not merely sequential calls. `FOR UPDATE SKIP LOCKED` plus the conditional update
  hands one row to one session; the losers are told the queue is empty.
- **Fencing.** The `(state, lease_owner, attempts)` fence holds through to the receiver. A
  worker that lost its lease writes nothing *and* causes no further provider call, including
  when the replacement's effect has already been delivered.
- **Idempotency.** Every replay path the architecture promises to collapse was already pinned
  and was left alone; the one new duplicate-shaped question — a reply crossing a withdrawal —
  produces zero decisions, zero amendments and zero messages.
- **Revalidation.** Nothing here weakens or re-litigates the stale-plan family. All four named
  facts and the post-checklist window were already proved and were not touched.
- **Defects found: none.** Every adversarial case passed against unmodified production code on
  its first run except the one whose *assertion* was mis-scoped, corrected above. No production
  source file was changed by this work.

## 5. What this does not establish

- It is six tests against a local PostgreSQL on one machine, not a load, soak or fault-injection
  campaign, and it makes no reliability claim of any kind.
- Cross-process ordering within one case is **not** claimed. `exclude_cases` is explicitly a
  statement about one process and binds no other worker; two workers may run two steps of one
  case, and their safety comes from `lock_case` and the fence, not from the exclusion.
- At-least-once delivery is unchanged and is still the honest guarantee: a provider that
  accepts a call and a process that dies before the acknowledgement commits still produces a
  second send under the identical idempotency key.
- No deployed rehearsal, no live model, no AWS resource and no `SUR-1` arm was involved.
