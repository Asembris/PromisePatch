# G8 adversarial proof map

**Status: AUDIT ONLY. Nothing was built, repaired, weakened or deployed by this page.**

This maps every adversarial fault the frozen G8 gate names, in four of its bullets, to the
artifact that proves it — or declares it unproven. It is a reading of the implementation, not a
claim about it: every row was settled by opening the test and reading its assertions, never by
trusting a test's name.

Audited at commit **`c4e75035a3e91ff2629ad21f56c2b94841c128b7`**
(*docs(fixtures): where the demo's dates come from, and when they stop being today*).
The working tree carried one untracked file, `REMAINING_WORK_ASSESSMENT.md`, which is unrelated to
this audit and was not read as evidence. No tracked file was modified before the audit.

---

## 0. Scope, and the roadmap's exact words

`new_roadmap.md` §11 *G8 — release proof* is frozen, gitignored, local-only and authoritative. It
was read first. Four of its bullets are in scope here; the other five — the demo-contract runner,
the five deployed rehearsals, curated DEVELOPMENT evidence, the licence and standalone-engine
check, and the release-SHA CI freeze — are **out of scope for this page and are not audited by it.**

**One fidelity note, stated because the audit brief quoted the bullets rather than the file.** The
brief's quotations are exact *prefixes* of the roadmap's bullets; the roadmap carries three
additional trailing sentences the brief omits. Nothing in them contradicts the brief, and each
raises the bar rather than lowering it, so the roadmap wins and this page audits against the
roadmap's full text:

| bullet | the sentence the brief does not quote | what it adds |
|---|---|---|
| 1 | *"Reuse core tests rather than duplicate for counts."* | Forbids inflating the proof count by writing a second test for a fault a core test already proves. This page therefore cites the existing core test for each fault and never asks for a new one. |
| 2 | *"Ten green checks alone are insufficient."* | A passing revalidation checklist does not discharge the bullet on its own. §2 below is graded against that stricter reading. |
| 4 | *"Make the smallest scheduling correction only if observed responsiveness misses the gate."* | The correction is conditional on a measurement. With no measurement, no correction is authorised either. |

---

## 1. Bullet one — the eleven named faults

> *"Test lost MCP response/replay, foreign identity, model self-confirmation, stale plan/callback,
> wrong customer, duplicate webhook, timeout, crash before/after external acceptance, browser
> disconnect and external convergence. Reuse core tests rather than duplicate for counts."*

### 1.1 Lost MCP response / replay — **PROVEN**

**Artifacts.** `apps/backend/tests/test_intent_api.py::test_a_redelivered_command_returns_the_same_case`;
`::test_one_command_id_carrying_two_different_statements_is_a_conflict`;
`::test_a_redelivered_confirmation_confirms_once`; `::test_a_redelivered_withdrawal_withdraws_once`;
`apps/backend/tests/test_mcp_protocol.py::test_a_repeated_client_request_id_reaches_the_same_command`;
`::test_an_idempotency_key_cannot_reach_another_caller_s_case`;
`apps/backend/tests/test_browser_conversation.py::test_a_redelivered_command_is_the_same_statement_arriving_twice`.

**What they assert.** Against real PostgreSQL, a command delivered twice under one `command_id`
returns the same `case_id` with `created: false` and leaves exactly one stored report; the same id
carrying different words is a `409 COMMAND_CONFLICT` rather than a second statement. At the MCP
surface, two calls sharing a `client_request_id` derive one `command_id` and an absent one derives
a fresh id each time; the derivation is namespaced by the credential's own digest, so the same key
from two clients is two different commands — an idempotency key is not an addressing scheme into
somebody else's case.

### 1.2 Foreign identity — **PROVEN**

**Artifacts.** `apps/backend/tests/test_mcp_protocol.py::test_no_tool_argument_can_carry_an_actor_a_time_or_a_version`;
`::test_a_tool_argument_naming_a_worker_changes_nothing`;
`apps/backend/tests/test_intent_api.py::test_a_request_that_names_a_worker_is_refused_outright`;
`::test_a_tool_call_from_another_surface_reaches_nothing`;
`apps/backend/tests/test_browser_conversation.py::test_a_request_carrying_an_actor_is_rejected_rather_than_ignored`.

**What they assert.** No tool's input schema has a field for an actor, a time or a version, so a
claimed identity has nowhere to arrive. A call that smuggles `worker_id` / `attested_by` anyway has
them stripped — the forwarded body is asserted to be exactly `{command_id, text}` — and the answer
is attributed to the server's own `PP_SURFACE_WORKER_ID`. The browser route refuses such a request
outright rather than silently ignoring the field, and a surface may not read or confirm a case a
different surface opened.

### 1.3 Model self-confirmation — **PROVEN**

**Artifacts.** `apps/backend/tests/test_orchestrator.py::test_a_model_cannot_confirm_a_plan_the_worker_did_not_say_yes_to`;
`::test_a_confirmation_sends_the_identity_the_server_gave_and_not_one_it_was_told`;
`::test_a_selection_cannot_carry_an_argument_of_any_kind`;
`::test_glue_that_reports_an_outcome_fails_the_whole_answer`.

**What they assert.** With the phase permitting `CONFIRM` and a real plan identity in hand, a model
choosing `CONFIRM` on a turn whose worker said *"that plan looks right to me"* calls no `confirm`
tool at all: `surface.names == ["status"]`, the turn is `NEEDS_THE_WORKERS_YES`, and the model's
friendly preface is dropped because the turn did not act. The `plan_id` that reaches the tool is
asserted to be the one copied out of `status`, never one the model named — and a selection carrying
`plan_id`, `case_id`, `answer`, `text` or `on_behalf_of` is a `SCHEMA_INVALID` failure, so a
fabricated identity is refused by the absence of the field rather than by a later check.

### 1.4 Stale plan / stale callback — **PROVEN**

**Artifacts, plan side.** `apps/backend/tests/test_intent_api.py::test_a_plan_that_was_re_made_after_it_was_read_cannot_be_confirmed`;
`::test_a_stale_plan_confirmed_over_the_transport_is_refused_and_changes_nothing`;
`apps/backend/tests/test_browser_conversation.py::test_a_confirmation_replayed_after_the_case_moved_is_refused`;
`apps/backend/tests/test_orchestrator.py::test_a_case_that_moved_between_the_decision_and_the_call_is_reported_as_such`.

**Artifacts, callback side.** `apps/backend/tests/test_order_mirror.py::test_a_stale_event_is_ignored_and_the_mirror_does_not_move_back`;
`apps/backend/tests/test_customer_approval.py::test_a_late_reply_cannot_approve_even_before_the_timer_runs`;
`::test_an_expiry_that_committed_first_refuses_a_later_yes`.

**What they assert.** A plan identity recomputed under the confirming lock and found changed is
refused with `PLAN_SUPERSEDED` / `PLAN_NOT_CONFIRMABLE` and nothing is written; over the real socket
the same refusal leaves the case where it was. In the loop, a case that moved between the read and
the call answers `CASE_NOT_IN_STATE`, says *"moved on"*, re-reads, and leaves the conversation
holding the **new** plan identity rather than the one it was carrying. On the callback side an order
event older than the mirror is ignored, the mirror does not move backwards and the refusal is
audited; a customer reply arriving after the window closed is compared against the stored deadline
on the decision path itself rather than relying on the expiry timer having fired first.

### 1.5 Wrong customer — **PROVEN**

**Artifacts.** `apps/backend/tests/test_consent_authority.py::test_a_yes_from_another_number_is_refused_on_identity`;
`::test_the_refused_sender_differs_from_the_customer_only_in_who_it_is`;
`apps/backend/tests/test_customer_approval.py::test_a_reply_from_the_wrong_sender_authorises_nothing`;
`::test_an_unauthorised_reply_is_kept_and_put_on_the_owners_desk`;
`apps/backend/tests/test_recovery_revalidation.py::test_a_decision_that_no_longer_matches_the_orders_channel_authorises_nothing`;
`apps/backend/tests/test_effect_sets.py::test_s08_foreign_sender`.

**What they assert.** A literal `YES` from a different number produces zero decisions, leaves the
request `SENT` and undecided, raises the unauthorised-approval audit — and is asserted **never to
have reached the semantic provider at all** (`reply_readings(provider) == 0`), so identity is checked
before the words are. The companion test grounds that refusal by asserting the two senders share a
channel kind and differ only in address, which rules out a refusal that merely rejected a malformed
sender. Downstream, a stored decision whose channel no longer matches the order's authorises nothing.

### 1.6 Duplicate webhook — **PROVEN**

**Artifacts.** `apps/backend/tests/test_order_mirror.py::test_the_same_event_delivered_ten_times_is_one_stored_record`;
`::test_a_redelivered_event_does_not_move_the_version_again`;
`apps/backend/tests/test_customer_approval.py::test_a_duplicate_provider_delivery_is_absorbed`;
`apps/backend/tests/test_effect_sets.py::test_s10_replayed_approval_webhook`.

**What they assert.** Ten signed deliveries of one order event yield `202` then nine `200`s and
exactly one inbox row. The processor is proved idempotent **independently of that unique index**: a
second inbox record for the same logical event is force-inserted past the index, and processing it
returns `Disposition.DUPLICATE`, leaves `external_version` at 2, and writes exactly one
`MIRROR_UPDATED` audit. On the consent wire, one reply delivered twice under the same provider event
id is one stored reply and one decision.

### 1.7 Timeout — **PROVEN**, with one stated precision

**Artifacts, model.** `apps/backend/tests/test_bedrock_semantic.py::test_a_timeout_is_a_timeout_and_never_an_answer`;
`apps/backend/tests/test_orchestrator.py::test_a_provider_that_cannot_be_reached_causes_no_effect_and_says_so`.
**External effect.** `apps/backend/tests/test_recovery_execution.py::test_a_timeout_before_the_provider_applied_keeps_the_effect_retryable`;
`::test_a_recovered_timeout_finishes_the_recovery_under_the_same_key`.
**Transport.** `apps/backend/tests/test_workflow_outbox.py::test_a_timeout_schedules_a_retry_and_keeps_the_key`;
`apps/backend/tests/test_mcp_protocol.py::test_an_unreachable_engine_is_an_unavailable_answer_not_an_answer`.

**What they assert.** Both a `ModelTimeoutException` and a connect timeout raise
`SemanticTimeoutError` rather than returning any reading, and a timed-out `SELECT_TOOL` ends the turn
as `NOT_UNDERSTOOD` with `acted is False` and only `status` called. An effect that timed out before
the provider applied it stays `PENDING` with `adapter.effect_count == 0`, keeps its idempotency key,
and finishes later under that same key with exactly one external effect. A tool whose engine never
answers returns `ENGINE_UNAVAILABLE` rather than an empty or hopeful case.

**The precision.** No test names a *read* timeout on the MCP→intent-API hop specifically. It is
caught by the same `except httpx2.HTTPError` clause at
[`engine.py:186`](../apps/backend/src/promisepatch/mcp/engine.py) that the tested connect failure
exercises, and the orchestrator's surface catches bare `Exception` at
[`surface.py:102`](../apps/backend/src/promisepatch/orchestrator/surface.py). The branch is proved;
the exception class is not enumerated.

### 1.8 Crash before external acceptance — **PROVEN**

**Artifacts.** `apps/backend/tests/test_recovery_execution.py::test_a_message_claimed_by_a_dead_dispatcher_is_reclaimed_under_the_same_key`;
`apps/backend/tests/test_recovery_revalidation.py::test_a_worker_that_dies_before_the_revalidation_commits_leaves_nothing`.

**What they assert.** The worker dies at `crash.AFTER_OUTBOX_CLAIM` — after the claim commits,
before the provider is called — and the assertions are that the effect is visibly `IN_FLIGHT` rather
than lost, and that `adapter.call_count == 0`, so nothing reached the outside. A fresh worker with a
different identity reclaims the row after the lease expires and presents **exactly** the original
idempotency key.

### 1.9 Crash after external acceptance — **PROVEN**

**Artifacts.** `apps/backend/tests/test_recovery_execution.py::test_a_provider_effect_applied_before_a_crash_becomes_exactly_one_recovery`;
`apps/backend/tests/test_order_amendment.py::test_a_death_after_the_order_system_applied_it_recovers_under_the_same_key`;
`apps/backend/tests/test_effect_sets.py::test_s15_crash_after_external_acceptance`.

**What they assert.** The provider accepted the amendment and the process died before the
acknowledgement committed. The test asserts both halves of the danger: the effect really did land
outside (`provider.effect_for(key) is not None`, `effect_count == 1`) while locally it is only
`IN_FLIGHT`. A fresh worker then retries; the assertions are `call_count == 2` and
`effect_count == 1` — two transport calls, one logical external effect — settling `DELIVERED` with
the same key, the same `provider_ref`, and one `RECOVERED` track. S15 is the same fault end to end
over the real MCP chain and the real order simulator, and it **passed** the first scored run.

### 1.10 Browser disconnect — **PROVEN**, with one limitation stated

**Artifacts.** `apps/backend/tests/test_event_stream.py::test_a_reconnect_replays_exactly_what_follows_the_cursor`;
`::test_a_duplicate_reconnect_may_redeliver_and_cannot_lose`;
`::test_a_subscriber_with_no_cursor_is_told_where_the_ledger_is`;
`apps/frontend/tests/eventStream.test.tsx` *shows reconnecting when the feed drops* and *resumes from
the last sequence it was given after a reconnect*; `apps/frontend/tests/conversation.test.tsx` *shows
no turn at all until the backend has accepted it* and *draws the state the re-read returned, never the
one the turn implied*; `apps/frontend/e2e/durability.spec.ts` *a reload / a restored tab / a second
browser … lands on the same durable case* and *a feed that cannot open leaves the case on screen and
never claims to be live*.

**What they assert.** All three failure modes of a disconnect are covered separately. *Nothing lost:*
a reconnect from cursor *n* replays exactly *n+1…latest* in ascending order, and a cursorless
subscriber is handed a resync frame carrying a real resume id rather than being silently restarted
from "now". *Nothing duplicated as an effect:* the same cursor twice yields the same events —
at-least-once, stated as the honest guarantee — and an in-flight turn redelivered under one
`command_id` is one turn (§1.1). *Nothing falsely claimed:* the indicator moves to `reconnecting`
when the feed drops or cannot open, and the panel draws no turn until the backend accepted it, then
only the state a re-read returned.

**The limitation.** No e2e severs the connection *mid-mutation* against the running stack. That case
is proved at the API layer by the redelivery tests, not in a browser.

### 1.11 External convergence — **PROVEN**

**Artifacts.** `apps/backend/tests/test_order_amendment.py::test_an_echo_that_arrives_before_the_acknowledgement_also_converges`;
`::test_an_uncertain_answer_never_becomes_a_second_order_change`;
`apps/backend/tests/test_order_mirror.py::test_a_version_gap_is_repaired_from_the_authoritative_order`;
`::test_a_gap_never_passes_through_the_version_it_skipped`;
`::test_a_gap_with_no_authoritative_read_fails_closed`.

**What they assert.** The hostile interleaving is driven explicitly: the amendment reaches the order
system, the answer is lost, and the order system's own echo is applied to the mirror **while the
effect is still `PENDING`**. The mirror is asserted correct before the acknowledgement exists; the
retry then presents the same key, and the assertions are `attempts == 2`,
`event_count(ORDER_A) == 1` and `len(simulator.commands()) == 1` — one order change, whichever order
the two messages arrived in. A version gap is never applied blind: the order is fetched whole, the
mirror is made equal to it, `mirror_source_event_id` is `None` to record that it was not moved by
the event, no audit claims the skipped version, and a gap with no authoritative read fails closed to
`FAILED`.

---

## 2. Bullet two — the approved stale plan

> *"Show an approved stale plan refusing mutation after external order/stock changes. Ten green
> checks alone are insufficient."*

| claim | test | what it actually asserts | verdict |
|---|---|---|---|
| Refuses mutation after an external **order** change | `test_recovery_revalidation.py::test_an_order_amended_while_waiting_makes_the_approval_stale` | Planned at version *N*, approved by the customer, amended externally to *N+1*: the revalidation refuses at check 2, the `RECOVERY_STALE` audit is written, and the stored check carries `vN` as *expected* beside `vN+1` as *actual*, so the refusal names the two values it compared rather than asserting a verdict. | **PROVEN** |
| Refuses mutation after an external **stock** change | `test_recovery_revalidation.py::test_a_substitute_eaten_while_waiting_makes_the_approval_stale` | The approved substitute is consumed while the case waits; the revalidation refuses at check 5 and the `RECOVERY_STALE` audit is raised. Consent to a change that can no longer be made is not consent to make it anyway. | **PROVEN** |
| *"Ten green checks alone are insufficient"* | `test_recovery_revalidation.py::test_a_change_landing_after_a_passing_revalidation_still_stops_the_amendment`; `::test_a_change_to_watched_state_is_seen_by_the_commit_guard` | The roadmap's extra sentence answered directly. The case is driven only as far as the checklist, which **passes** against the world as it stands and leaves the case `RECONCILING`; the external change then lands in the window between that pass and the transaction that would emit the amendment. `APPLY_RECOVERY` recomputes the watched-state fingerprint inside that transaction, and the assertions are `amendments_for(track) == []`, the track left `TRACK_STALE`, and the case **not** `RESOLVED`. No external effect under a plan that no longer describes the world, whatever the interleaving. | **PROVEN** |
| The refusal is **shown**, not merely enforced | `apps/frontend/tests/evidence.test.tsx` *puts expected beside actual on every revalidation check*; `apps/frontend/tests/vocabulary.test.tsx` *treats all fourteen promise states and no others*; `test_recovery_revalidation.py::test_a_stale_refusal_keeps_every_word_the_customer_said`; `::test_a_stale_refusal_is_audited_as_ours_and_not_as_the_customers` | The evidence drawer renders each revalidation check with `expected 4.000` beside `actual 1.200` under the `STALE` outcome, so a reader sees the comparison rather than a verdict; the fourteen-state vocabulary table is exhaustive, so `STALE` reaches a promise row with a phrase, a state name and a marker shape. The customer's words survive the refusal intact, and the refusal is audited as the system's own rather than as something the customer did. | **PROVEN** |

**One caveat stated rather than glossed, because it is the only red thing near this bullet.** The two
frozen scenarios that drive exactly this fault end to end — **S06** (stale approved order version)
and **S07** (stale approved stock state) — are two of the five that **failed** the first scored run
and stay committed failing. They do **not** fail on this bullet's claim. Read from the immutable
capture at `docs/effect-sets/runs/20260915T163255509125+0000-scored.json`, every one of their six
diffs is an effect count **lower** than its frozen label — `ord-b/customer_message`,
`ord-b/owner_escalation`, `ord-b/task_hold` — and **no diff is an order amendment**. The declared
amendment count at `CONSENT_SETTLED` is zero, and zero is what was observed; their partitions agree
at every declared checkpoint. What S06 and S07 fail on is what the system does *afterwards* — the
re-ask, the escalation and the kitchen hold — which is causes C and E in
`docs/effect-set-failure-diagnosis.md`, not the refusal this bullet names.

---

## 3. Bullet three — whole-delivery, unrelated work, and the protected-order zero

> *"Whole-delivery changes the plan; unrelated external changes do not invalidate unrelated work.
> Verify zero protected-order recovery amendments/messages/reservation changes/task holds with
> baseline/case attribution."*

| claim | test | what it actually asserts | verdict |
|---|---|---|---|
| Whole-delivery changes the plan | `test_whole_delivery_counterfactual.py::test_the_raspberry_only_answer_leaves_priya_and_tomas_a_recovery`; `::test_the_whole_delivery_answer_takes_that_recovery_away`; `::test_the_two_frozen_branches_differ_in_feasibility_and_not_in_breadth` | The same fixture, the same external edit and the same spoken report are answered two ways over the real MCP surface. On *"just the raspberries"*, Priya's and Tomas's tracks carry non-empty option sets and are not `BLOCKED`. On *"the whole delivery"*, the same two tracks carry `options == []`, `classification == BLOCKED`, `rule_id == "R-SUBSTOCK"` and `reason_detail == "INSUFFICIENT_SUBSTITUTE_STOCK"` — the substitute's own stock, not a constraint and not scope — no approval request exists, and the spoken status says *"Needs the owner:"*. The pure assertion beside them proves both frozen branches move the same two orders, so the difference is feasibility rather than breadth. | **PROVEN** |
| Unrelated external changes do not invalidate unrelated work | `test_effect_sets.py::test_s14_unrelated_external_edit_after_exception`; `test_whole_delivery_counterfactual.py::test_lenas_own_amendment_is_never_counted_as_an_incident_caused_effect` | S14 edits the cafe's order to quantity 30 through the real order system after the exception, and asserts **before counting** that its reservation rows really moved (`moved[line] != since.reservations[line]`, with the message *"the cafe's own edit changed nothing"* firing if they did not) — which is what stops a census that merely read the window from reporting a false positive exactly here. It then requires S14 to be byte-for-byte S01 in partitions and in incident-caused effects at all four checkpoints. S14 **passed** the first scored run. The counterfactual's companion test does the same for an edit made *before* the incident: Lena's version, her order-system event and her reservations all demonstrably moved, and she still carries no pair of any kind in the census, with her track `UNAFFECTED` — considered, and considering is evidence rather than an effect. | **PROVEN** |
| Zero protected-order amendments / messages / reservation changes / task holds, with baseline and case attribution | `test_whole_delivery_counterfactual.py::test_every_untouched_order_carries_zero_incident_caused_effects`; the census in `apps/backend/tests/_effect_set_observation.py` (`census`, `commanded_order_changes`) | All four effect kinds are asserted per untouched order against a baseline captured before the case opened: external `version` unchanged, simulator `event_count` unchanged, `reservations[line] == since.reservations[line]`, and `tasks[...][1] is None` for the hold — plus no outbox row, no approval request, and the track `UNAFFECTED`. Attribution is not a time window: `commanded_order_changes` reads the idempotency key carried on each order-system event and keeps only keys belonging to one of *this case's* tracks, so a customer's own edit inside the window is excluded by the command that produced it. The same zero is then read a second way, as the case itself reports it — `projected.untouched_effect_count == 0` over `status_view.project`, which is the number a screen carrying the claim would draw. | **PROVEN** |

---

## 4. Bullet four — the head-of-line measurement

> *"Measure delayed semantic calls alongside unrelated ready work. No held DB transaction does not
> prove no head-of-line delay. Make the smallest scheduling correction only if observed
> responsiveness misses the gate."*

This bullet is a **measurement**, not a test. The audit brief scopes it to one question — was it ever
taken and recorded anywhere in the repository — and forbids taking it. It was not taken.

| claim | artifact | what exists | verdict |
|---|---|---|---|
| Delayed semantic calls measured alongside unrelated ready work | **None.** | No artifact in the repository records this measurement. The phrase *head-of-line* occurs exactly once in the whole tree, at `new_roadmap.md:367` — the requirement itself. No run capture, no document under `docs/`, no script under `scripts/` and no test records a delayed semantic call timed against unrelated ready work. | **UNPROVEN** |

**Two things exist that are near it, and neither is it.** Both are named because mistaking either one
for the measurement is the specific error this bullet was written to forbid.

- `apps/backend/tests/test_order_amendment.py::test_the_amendment_is_sent_with_no_database_transaction_held`
  measures, rather than reviews, that the application pool had zero connections checked out at the
  moment the provider was called (`set(observed) == {0}`). This is **exactly** the evidence the
  roadmap's second sentence names as insufficient: it proves no held transaction, and the roadmap
  says that does not prove no head-of-line delay.
- `apps/backend/tests/test_customer_approval.py::test_a_waiting_case_does_not_stall_unrelated_work`
  asserts selective continuation — one case parked on a customer, another advancing past
  `RECEIVED` / `INTERPRETING` with no outstanding steps. It is a correctness assertion about a case
  *waiting on a person*, contains no timing at all, and says nothing about a slow **semantic call**
  occupying the worker.

The per-call model latencies published in `docs/semantic-benchmark.md`,
`docs/semantic-benchmark-rerun.md`, `docs/customer-intent-challenger-stage-a.md` and
`docs/nemotron-challenger-stage-a.md` are single-call figures from the evaluation harness, measured
with nothing else running. They are not this measurement either.

Per the brief: recorded UNPROVEN, and stopped there.

---

## 5. What was run, and what was read but not run

**Run** — three cheap invocations, each chosen because it settled a row that reading alone left open:

| command | result |
|---|---|
| `pytest apps/backend/tests/test_orchestrator.py::test_a_model_cannot_confirm_a_plan_the_worker_did_not_say_yes_to ::test_a_confirmation_sends_the_identity_the_server_gave_and_not_one_it_was_told ::test_a_case_that_moved_between_the_decision_and_the_call_is_reported_as_such` | **3 passed.** Settles §1.3 and the plan half of §1.4. This file is pure — no model, no socket, no database. |
| `npx vitest run tests/eventStream.test.tsx` (in `apps/frontend`) | **8 passed.** Settles §1.10's frontend half. |
| A read-only Python load of `docs/effect-sets/runs/20260915T163255509125+0000-scored.json` | Confirms `score {passed: 11, of: 16}`, implementation SHA `e81b5aa`, manifest SHA `d41f5a…2cdc`, and every diff of S06, S07, S08, S12 and S13 — which is what §2's caveat rests on. |

**Read but deliberately not run.** Every remaining row was settled by opening the file and reading
its assertions. The database-backed backend suite was **not** run, per the brief and because this
repository's own record puts it at roughly an hour; no row here needed it, because each was a
question about what a test asserts rather than about whether it currently passes. Files read for
assertions and not executed: `test_mcp_protocol.py`, `test_intent_api.py`,
`test_browser_conversation.py`, `test_consent_authority.py`, `test_customer_approval.py`,
`test_order_mirror.py`, `test_order_amendment.py`, `test_recovery_execution.py`,
`test_recovery_revalidation.py`, `test_effect_sets.py`, `test_whole_delivery_counterfactual.py`,
`test_bedrock_semantic.py`, `test_workflow_outbox.py`, `test_event_stream.py`,
`_effect_set_observation.py`, `apps/frontend/tests/conversation.test.tsx`,
`apps/frontend/tests/evidence.test.tsx`, `apps/frontend/tests/vocabulary.test.tsx`,
`apps/frontend/e2e/durability.spec.ts`, plus `mcp/engine.py` and `orchestrator/surface.py` for the
`except` clauses behind §1.7.

Nothing was changed. No production code, no test, no fixture, no manifest. No test was weakened,
skipped, xfailed or deselected. Nothing was deployed and no model was called.

---

## 6. Closing — everything UNPROVEN or PARTIAL, ranked by the work of closing it

Fourteen of the fifteen claims above came back **PROVEN**. One came back **UNPROVEN**, and none came
back **PARTIAL**. Two PROVEN claims carry a stated precision rather than a downgrade, and they are
listed here so that nothing sits only inside a table cell.

| rank | item | verdict | what closing it looks like |
|---|---|---|---|
| **1** | **The head-of-line measurement** (§4) | **UNPROVEN** | The largest by a distance, and the only genuine gap in scope. It needs a measurement harness that does not exist: a deliberately delayed semantic call held open while unrelated ready work queues behind it, with the second stream's service time recorded — then a published record with its conditions, and the roadmap's conditional *"smallest scheduling correction"* only if the observed responsiveness misses the gate. Because the roadmap makes the correction conditional on the measurement, this also blocks any scheduling change that might otherwise be argued for. **Not started.** |
| **2** | **No e2e severs a browser connection mid-mutation** (§1.10) | PROVEN, limitation stated | Small, and arguably unnecessary. The fault is proved at the API layer by the redelivery tests and at the component layer by *shows no turn at all until the backend has accepted it*. Closing it would mean one Playwright case against the running stack that aborts an in-flight `confirm` and asserts the case is unchanged and the retry is one confirmation. The roadmap's own *"reuse core tests rather than duplicate for counts"* argues against writing it purely for the count. |
| **3** | **No test names a read timeout on the MCP→intent-API hop** (§1.7) | PROVEN, precision stated | Smallest. The branch is already asserted through its connect-failure sibling, since both land in one `except httpx2.HTTPError` at `engine.py:186`. Closing it is one parametrisation adding `httpx2.ReadTimeout` beside the existing case. |

**Two things outside these four bullets, found while auditing them and recorded rather than acted
on**, because this page is scoped to four bullets and forbidden production changes:

- `PromiseState.STALE` carries an owner (`ActionOwner.OWNER`) and a next action at
  [`status_view.py:503`](../apps/backend/src/promisepatch/domain/status_view.py) and
  [`status_view.py:529`](../apps/backend/src/promisepatch/domain/status_view.py), and **no backend
  test names `STALE`** — `test_status_view.py` and `test_case_workspace.py` between them name every
  other promise state and not this one, and no test asserts those owner/action tables are total over
  `PromiseState`. The frontend side *is* exhaustive (`vocabulary.test.tsx` *treats all fourteen
  promise states and no others*), so a screen would draw it correctly; what is unasserted is the
  backend pairing. This belongs to G7 §1.5's *"blocked promise has owner/next-action/reason"*, which
  G7 closed, and it is a gap in a test rather than in behaviour. **Not a defect in production code,
  and no repair is proposed here.**
- S06, S07, S12 and S13 remain committed failing (S08 has since been repaired and now matches). That
  is the published, deliberate state of the benchmark under `docs/effect-set-run-protocol.md`, not
  something this audit discovered, and the immutable 11/16 headline is unchanged by this page.

**Nothing here reopens the locked roadmap, and nothing here changes the immutable first-run score.**
G8's own bullets that are out of scope — the demo-contract runner, the five deployed rehearsals, the
curated DEVELOPMENT evidence, the licence and standalone-engine check, and the release-SHA CI freeze
— are untouched by this audit and remain open.

---

## Amendment, 2026-09-17 — §1.3 was proven of the orchestrator and not of the surface

**This page is left as it was written, and this section says what a later trace found.** The audit
above was honest about the artifacts it read; what it did not ask was whether those artifacts
covered every client. They did not.

Every test cited under **1.3 Model self-confirmation** lives in `test_orchestrator.py` and asserts
the behaviour of *our* loop: that `reads_as_worker_confirmation` refuses an agreeable turn, that
the `plan_id` reaching the tool is the one copied out of `status`, and that `ToolSelection` has no
field a fabricated identity could travel in. All four still pass and all four still matter.

None of them is a property of the MCP surface. In the MCP architecture the model *is* the client,
and a different host — or a direct authenticated call with `curl` — runs none of that code. On the
surface itself, `confirm(case_id, plan_id)` over a valid service token moved the case to
`EXECUTING` and wrote an audit row reading `authority = HUMAN_APPROVAL, actor = maya`, with
nothing anywhere in the chain having established that a human was present. Host authentication is
not human consent, and the record said it was.

**§1.3 is now PROVEN of the surface as well as of the loop**, and by server-side evidence rather
than client-side: a confirmation spends a durable, plan-bound approval that only a channel where
this system authenticates a person can write, and the MCP path has no channel it could name. The
sharpest of the new tests is the one that removes the loop's own gate and shows the case not
moving anyway —
`apps/backend/tests/test_orchestrated_conversation.py::test_the_model_choosing_confirm_on_an_unapproved_plan_changes_nothing`
— beside
`apps/backend/tests/test_human_confirmation_boundary.py::test_a_direct_confirm_over_the_service_surface_cannot_manufacture_a_yes`,
which is the defect reproduced exactly as it was reachable and then refused.

See [`mcp-human-confirmation-boundary.md`](mcp-human-confirmation-boundary.md) and
[ADR-0018](adr/0018-a-plan-confirmation-spends-a-human-approval.md). **Nothing else on this page
changes**: the other fourteen rows are unaffected, bullet four's head-of-line measurement remains
**UNPROVEN**, and the immutable 11/16 headline is untouched.

---

## Amendment, 2026-09-18 — bullet four's measurement was taken after this page was written

**This page is left as it was written, and so is the amendment above it.** §4 audited the
repository at `c4e7503` and reported, correctly for that commit, that no artifact recorded the
head-of-line measurement and that the phrase *head-of-line* occurred once in the whole tree. The
measurement has since been predeclared, built, run and dispositioned, so §4's **UNPROVEN**, §6's
rank-1 *"Not started"* and the 2026-09-17 amendment's closing clause *"bullet four's head-of-line
measurement remains UNPROVEN"* are superseded by what follows. None of them is edited.

| what exists now | where |
|---|---|
| the protocol, fixed before the harness | [g8-head-of-line-predeclaration.md](g8-head-of-line-predeclaration.md), amended at `7cb188c` |
| the harness and its tests | `scripts/run_head_of_line.py`, `scripts/tests/test_run_head_of_line.py` |
| nine unedited run captures | `docs/head-of-line/runs/` |
| the measurement | [g8-head-of-line-measurement.md](g8-head-of-line-measurement.md) |
| the owner's decision on the conditional | [g8-head-of-line-disposition.md](g8-head-of-line-disposition.md) |

**The measurement was taken and both delayed arms failed the gate**: `H_representative = 1545.8 ms`
and `H_treatment = 8173.4 ms` against `H ≤ 1000.0 ms`, a threshold fixed before the harness existed
and not moved. **The roadmap's conditional "smallest scheduling correction" is declined**, by the
owner, in the disposition, with its cost stated — not overlooked and not deferred.

So the bullet's *measurement* requirement is discharged and its *conditional* is decided. That is a
different sentence from "the gate passed", and neither this amendment nor the disposition softens
the `FAIL`. **Nothing else on this page changes**: the other fourteen rows are unaffected, §1.3
stands as the 2026-09-17 amendment left it, and the immutable 11/16 headline is untouched.

---

## Amendment, 2026-09-19 — the declined correction was afterwards made

**This page is left as it was written, and so is every amendment above it.** The amendment of
2026-09-18 was written at `8877fcf`, six hours before the correction landed, and its closing
clause *"the roadmap's conditional 'smallest scheduling correction' is declined"* is an accurate
record of the decision that stood when it was written. The project owner has since reversed that
decision and the correction has been made, so that clause no longer describes the worker. It is
superseded here and not edited.

| what exists now | where |
|---|---|
| the correction, its root cause and its before/after | [head-of-line-correction.md](head-of-line-correction.md) |
| the scheduling change | `apps/backend/src/promisepatch/worker.py`, `apps/backend/src/promisepatch/domain/steps.py` |
| its regression tests | `apps/backend/tests/test_worker_responsiveness.py` |

**The gate did not move.** `H <= 1000.0 ms` is still the threshold, is now imported by the
regression rather than restated, and the nine published captures, the measurement and the
disposition are all untouched. The correction was asked for, not triggered: none of the
disposition's three revisiting conditions fired, and none of its reasoning is claimed to have
been wrong.

**What the correction is not offered as.** It is one regression test, not a re-run of the
predeclared nine-capture protocol, and `scripts/run_head_of_line.py` is unchanged. The published
`H_representative = 1545.8 ms` and `H_treatment = 8173.4 ms` stay exactly as measured, and their
`FAIL` against the gate is not softened, retracted or rescored by anything here. A reader who
wants the corrected worker measured under that protocol needs a predeclared amendment first.
**Nothing else on this page changes.**
