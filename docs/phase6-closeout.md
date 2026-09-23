# Phase 6 closeout — two asked promises, one stale, and the phase audited

Date: 2026-09-23. Entry at `5faff0b25257`, tracked tree clean, `main` equal to `origin/main`, the
eleven known untracked artefacts left as they were, the `pr` workflow green on that SHA and the
effect-set workflow red as expected. **Nothing here is deployed**: the deployed host still serves
`931a296decad`, and no AWS resource, IAM policy, SUR-1 artefact, effect-set artefact, frozen
manifest or earlier record was touched. The session 1–3 records —
[`phase6-ux-journey-polish.md`](phase6-ux-journey-polish.md),
[`phase6-session2-explanation-and-terminal-states.md`](phase6-session2-explanation-and-terminal-states.md)
and [`phase6-session3-reask-liveness.md`](phase6-session3-reask-liveness.md) — are left exactly as
they were; session 3's §7 named the shape this session closes.

The decision is [ADR-0023](adr/0023-a-re-plan-returns-the-case-to-planned-for-that-track-only.md),
committed before any production code changed.

## 1. The shape, and what it did

Session 3 left one shape unconstructed: a case with **two** customer-approval tracks in which only
one goes stale. It was built through the product's own paths against the local PostgreSQL. The
world is the fixture's own Proof C — `hollow_oak.with_charlotte_variant` authored in advance, and
C's constraint set to ask — so the canonical report, clarification and confirmation ask two
customers: Tomas about B (EXT-B) and the Okafor-Reyes wedding about C (EXT-C). Both said a literal
`YES` on their own request, C's order then moved one version, and the worker drained. No workflow
row was inserted; the only levers were the world and the claim order of the two revalidations,
which the product creates in one transaction and therefore orders by their random ids.

| claim order | at `5faff0b` |
|---|---|
| C's revalidation first | C `STALE`, `replan:C` enqueued. B's `PROCEED` counted no other *revalidation* outstanding and moved the case to `RECONCILING`. `replan:C` then **skipped** (it runs only in `REVALIDATING`), and reconcile skipped (C is not terminal). **C sat `STALE` for ever** — never re-planned, re-asked or escalated, with nothing armed to move it. |
| B's revalidation first | B `PROCEED`, `apply:B` ran and **the amendment was delivered to the order system**. `replan:C` then moved the whole case to `PLANNED`, and `finalize:B` **skipped** there. **B sat `APPLYING` for ever** with its order already changed; after the worker re-confirmed C and C was asked again, the case stood at `EXECUTING`, because an `APPLYING` track counts as runnable and the case could never wait. |

Both are **P1**: a promise the system stops moving without saying so, and — in the second — an
order the order system changed that the promise ledger never settles, while the screen says the
change is still being made. Neither is a consent or authority breach: no customer's answer reached
the other's order, and nothing was applied without its own yes.

## 2. Root cause

§14.2 lists a revalidation round's outcomes **per track** — "valid + APPROVE → RECONCILING; …
fingerprint mismatch → STALE → re-plan (case returns to PLANNED for that track only …)". The build
keeps one state per case and read "returns to PLANNED" as the whole case. Two case-level exits
from one round were each blind to the other:

1. the round was declared over when the last *revalidation* finished, though a re-plan is part of
   the same round; and
2. the re-plan moved every track's case to `PLANNED`, where a sibling whose own yes had already
   passed could not finish.

With one asked track the two readings agree, which is why sessions 1–3 never met it.

## 3. The repair (ADR-0023)

- **A revalidation round ends once**, when its last revalidation *or re-plan* finishes, in either
  claim order: `cases.revalidation_round_exit`, used by the revalidation outcomes and by the
  re-plan. It goes to `PLANNED` if a re-plan left a promise waiting for a worker's yes, and to
  `RECONCILING` otherwise, and a move to `PLANNED` arms §14.1's ten-minute timer as a re-plan's
  always did.
- **A track whose own yes passed revalidation finishes its recovery at `PLANNED`.**
  `APPLY_RECOVERY` and `FINALIZE_RECOVERY` now also run in `PLANNED`. Their authority is their own
  track's — the confirmed plan that asked, the customer's literal yes, a `PROCEED` against a fresh
  snapshot — and the apply step still recomputes its own fingerprint before it emits anything.

Nothing else moved: a revalidation still runs only in `REVALIDATING`, a confirmation still acts
only on `PENDING` tracks, §14.1's escalation still escalates only `PENDING` tracks, and no consent
rule, parser, link, approval identity, table or column changed. ADR-0022 is untouched and holds:
the re-asked C is a new episode keyed by the plan that asked.

After the repair, both orders end the round the same way: B `RECOVERED` with exactly one delivered
amendment, C `PENDING` and unbound, its first request `SUPERSEDED`, the case at `PLANNED` with its
timer armed and nothing outstanding. A person's approval and confirmation then asks C — and only
C — again, and the case waits on C.

## 4. What is guaranteed, and where it is proved

All in [`test_two_track_reask.py`](../apps/backend/tests/test_two_track_reask.py), against the
real PostgreSQL, the real worker and, for links, the real HTTP hop.

| invariant | test |
|---|---|
| neither claim order strands a track; B applied once and settled, C re-planned, case `PLANNED` with its timer | `test_either_order_applies_the_approved_promise_and_re_plans_the_stale_one[stale_first, approved_first]` |
| only C is asked again, as a plan-scoped new episode; B is not asked, superseded or replayed, and B's request, deadline and decision are unchanged | `test_only_the_stale_promise_is_asked_again_and_the_case_waits_on_it` |
| B's link, C's superseded link and B's own channel all fail to answer C's new question; each page ends on its own question | `test_neither_customer_s_answer_authorises_the_other_promise` |
| both settle on their own authority; each amendment's provenance names its own request and decision | `test_both_promises_settle_on_their_own_authority` |
| replaying every step of the round and the re-ask creates no request, message, decision or amendment | `test_replaying_the_round_and_the_re_ask_asks_nobody_twice` |
| an unconfirmed re-plan escalates C only (`PLAN_UNCONFIRMED`, beside its unchanged planning reason); B stays changed; the case resolves | `test_an_unconfirmed_re_plan_goes_to_the_owner_and_the_settled_promise_stays[…]` |
| a *declined* sibling goes to the owner where it lands and C is still re-planned and re-asked | `test_a_declined_sibling_goes_to_the_owner_and_the_stale_one_is_still_re_planned[…]` |
| A, D, E and F are untouched through the round and the re-ask; E and F get no effect and no request | `test_nothing_unrelated_is_touched_by_the_round_or_the_re_ask` |

**The regression reproduces the defect.** Run against the `5faff0b` versions of the four changed
modules, `stale_first` fails at `('SKIPPED', 'NOT_APPLICABLE') == ('DONE', 'REPLANNED')` and
`approved_first` at `'APPLYING' == 'RECOVERED'`; the unforced run lands in `RECONCILING` on its own.
Restored, every test passes.

## 5. A headline that said nothing had been done

Found while proving §3, and judge-visible: every `PLANNED` case said **"Planned, and waiting for
you. Nothing has been done yet."** — in band 1, in the case list and in the spoken status. At a
re-planned case that is untrue: the canonical re-plan has EXT-A already `changed` and a customer
already messaged, and after ADR-0023 a sibling's order can change *while* the case is `PLANNED`.
The row beside the headline said "changed" and the headline said nothing had been done — the same
class of self-contradiction as session 1's finding 5, so it is recorded **P1** and fixed.

A first plan is recognisable from rows alone: planning writes only `PENDING`, `UNAFFECTED` and
`LINKED`, so a planned case holding any other track state was confirmed before and acted on it.
Such a case now says **"Re-planned, and waiting for you. What was done before stays done."** The
headline stays `PLANNED`, the plan offered and the next action are unchanged, and a first plan's
sentence — the one G7 measured — is byte for byte what it was. The case list reads the same fact
with one grouped query, so the list and the workspace cannot disagree. Backend only: the frontend
renders the server's sentence.

## 6. The Phase 6 audit

Sessions 1–3 were re-read against the running code, and each claim checked for a live test that
pins it rather than taken from the record.

| claim | status | pinned by |
|---|---|---|
| an observer never appears authorised: no verb, "the worker" in the third person, told it may not speak | holds | `test_case_workspace.py` — `test_an_observer_is_told_it_may_not_speak_rather_than_left_to_infer`, `…_is_offered_no_verb_that_would_change_anything`, `…_is_not_told_the_worker_s_move_is_theirs` |
| the escalation cause and the planning reason stay distinct | holds, and now also in the two-track shape (`PLAN_UNCONFIRMED` beside C's unchanged reason) | `test_status_view.py`, `test_case_workspace.py`, `test_two_track_reask.py` |
| the customer page ends truthfully after approve, decline, expiry, a window closing after a yes, an order-system refusal, withdrawal before and after an answer, and a stale yes | holds; the two-track pages end on their own questions | the eight `test_one_tab_…` / `…never_told_the_next_plan_s_progress` tests; `test_neither_customer_s_answer_authorises_the_other_promise` |
| a superseded link neither describes nor authorises a later plan | holds, for the same track and across tracks | `test_approval_reask.py`, `test_two_track_reask.py` |
| repeated re-asks work | holds: a third ask for a third world | `test_a_re_asked_promise_that_goes_stale_again_is_re_planned_and_asked_again` |
| plain language before technical tokens | holds | session 2's `44ecf91` tests in `test_status_view.py` / `test_case_workspace.py` |
| deadlines and time zones are unambiguous | holds: every date names its zone, the customer page prints its own deadline | `time.test.ts`, `test_customer_approval_link.py` |
| responsive customer and judge paths | see §7 | `customer-approval.spec.ts`, `judge-journey.spec.ts`, `responsive.spec.ts` |

**No P0 was found in any session, and none here.** Nothing on any surface implies authority a
model, a Telegram reply, an observer or a service credential lacks, and no path lets one
customer's answer reach another's order. The two P1s this session found — the stranded two-track
round and the untrue `PLANNED` sentence — are fixed. **No known P1 remains.**

## 7. Validation

Sequential throughout: no `xdist`, no worktree, no temporary clone, no test weakened, skipped,
deselected or `xfail`ed, and no existing assertion or literal moved.

| check | result |
|---|---|
| `test_two_track_reask.py`, new — 11 tests, real PostgreSQL, worker, HTTP link hop | **11 passed** |
| the regression against the `5faff0b` versions of the four changed workflow modules | **failed as the defect**: `stale_first` at `('SKIPPED', 'NOT_APPLICABLE') == ('DONE', 'REPLANNED')`, `approved_first` at `'APPLYING' == 'RECOVERED'` |
| 24 files in one sequential run on the repair: the new module, `test_approval_reask`, `test_customer_approval`, `test_customer_approval_link`, `test_customer_intent`, `test_consent_authority`, `test_human_confirmation_boundary`, `test_adversarial_races`, `test_recovery_revalidation`, `test_truthful_recovery`, `test_recovery_execution`, `test_order_amendment`, `test_step_execution`, `test_workflow_outbox`, `test_workflow_inbox`, `test_workflow_timers`, `test_worker_recovery`, `test_withdrawal`, `test_impact_analysis`, `test_whole_delivery_counterfactual`, `test_case_workspace`, `test_status_view`, `test_causal_chain`, `test_cli` | **714 passed**, 0 failed, 0 skipped |
| after the headline change, one sequential run: the new module, `test_case_workspace`, `test_status_view`, `test_spoken_budget`, `test_cli`, `test_intent_api`, `test_mcp_protocol`, `test_orchestrator` | **852 passed, 12 failed** — see below |
| `test_status_view.py` + `test_spoken_budget.py` (no database) | passed; 4 new status cases, 1 new budget case |
| `mypy` over `packages/promise-graph packages/order-contract apps/backend` | no issues, 293 files |
| `lint-imports` | 30 kept, 0 broken |
| `ruff check`, `ruff format --check` on every changed file, Markdown included | clean |
| frontend unit suite | **340 passed** of 340 (no frontend source changed) |
| `npm run typecheck`, `npm run lint`, `npm run build` | clean |
| `customer-approval.spec.ts` + `judge-journey.spec.ts` + `responsive.spec.ts`, real stack on images built from `956e072`, all four widths | **35 passed** |

**The twelve failures are not this work, and that was measured rather than assumed.** All are in
`test_mcp_protocol.py` and all are the transport's own *refusals* — the eight missing- or
wrong-credential cases, an unlisted origin, an unlisted host, malformed JSON and a missing
`Accept` — each ending in a client `ReadTimeout` or "peer unexpectedly closed" on a real loopback
socket. With the six modules this session changed swapped back to their `5faff0b` versions, **the
same twelve fail identically**. It is the local TLS-intercepting proxy that truncates small non-2xx
bodies, the same one that makes `smoke` read 9/12 from this machine; none of the twelve reaches a
domain module. The `pr` workflow, green on `5faff0b`, is the authority for them.

`mypy` groups B and C were not run: nothing under `apps/order-simulator`, `evals` or `scripts`
changed. The whole backend suite was not run (roughly an hour); GitHub CI is the regression
authority, and nothing is pushed. The browser specs needed the judge entry, which this machine's
`docker/env/api.env` turns off; it was enabled on `api` alone through a compose override kept
outside the repository, and `api` was recreated on its own environment afterwards. The stack is as
it was found — `api`, `mcp`, `postgres`, the order system and the frontend up, the worker stopped
— on images rebuilt from this work. The reseeds the specs and the suite perform erased the local
cases, which were demo data.

**The optional read-only AWS check was not taken.** The deployed image predates the escalation read
fields, so the deployed case's cause can only be read from its database, and reaching that private
database means an SSM `SendCommand` on the host — a write-class call, which this session's terms
exclude.

## 8. What remains

**Phase 6 is closed.** No P0 was found in any of its four sessions, and no known P1 remains.

Known P2s and limitations, none with a runtime correctness impact:

- **A sibling settling during `PLANNED` moves the plan identity.** The identity covers the case
  version and every track's state, so a worker who read the plan before B's change landed is
  refused and re-reads. That is the existing stale-plan protection failing closed, and it costs one
  re-read.
- **The `PLANNED` next action still says "confirm it before anything is done"** at a re-planned
  case, where a sibling's already-approved change may be finishing. The headline beside it now says
  what was done; the next action is about the plan awaiting a yes.
- Recorded earlier and still standing: session 2's finding 8 (a revalidation refused
  `UNAUTHORIZED` keeps its link page re-reading; reachable only through a broken persisted reply
  chain), and `explanations.CONSENT_AUTHORITY`'s frozen G7 wording, which reaches no runtime
  surface.
- **Nothing in Phase 6 has been exercised live.** The re-ask, the two-track round and every refusal
  path (`STALE`, `EXPIRED`, `UNAUTHORIZED`, `NOOP`) are proved locally against the fake provider.
- The twelve `test_mcp_protocol.py` refusals time out **on this machine only**, as above.

**Deployment is deferred to Phase 7.** The deployed host still serves `931a296decad`, and none of
sessions 1–4 is on it. The next step is, in this order:

1. **Read the deployed historical case first**, read-only, before anything can erase it: its
   `track.escalated` events, to confirm or refute session 2's `PLAN_UNCONFIRMED` hypothesis. The
   demo restore in step 3 truncates that case.
2. **Release the Phase 6 head.** Build and push its images through `deploy.sh images`, then carry
   the image tag to the host the way `931a296decad` went — a parameter-only change set against the
   previously deployed template, gated on an empty resource change list and authorised explicitly
   by the project owner. `deploy.sh stack` cannot carry it, and
   [non-destructive-release.md](non-destructive-release.md) §10.1 is unchanged.
3. **Restore the demo world** with `pp restore-demo-world --confirm destroy-and-restore`, carrying
   the real Telegram binding across, and take smoke from the host.
