# Phase 6 session 3 — a re-planned promise is asked again

Date: 2026-09-23. Entry at `f9bf715be986`, tracked tree clean, `main` equal to `origin/main`, the
eleven known untracked artefacts left as they were, the `pr` workflow green on that SHA and the
effect-set workflow red as expected. One workflow-correctness repair. **Nothing here is
deployed**: the deployed host still serves `931a296decad`, and no AWS resource, IAM policy, SUR-1
artefact, effect-set artefact, frozen manifest or earlier record was touched.
[`phase6-session2-explanation-and-terminal-states.md`](phase6-session2-explanation-and-terminal-states.md)
is left exactly as it was; its finding 7 is what this session closes.

The decision is [ADR-0022](adr/0022-an-approval-episode-is-opened-by-the-confirmation-that-asks.md),
written before any production code changed.

## 1. Reproduced first

Through the product's own paths against the local PostgreSQL, with nothing inserted by hand:
the canonical report, the clarification, a worker's approval and confirmation, the customer's
literal `YES` on request A about promise `B` (EXT-B), the order moved one version
(`bump_order_version(ORDER_B)`), a drain, then a worker's approval and confirmation of the
re-plan, then a drain.

| read, after the re-confirmation and a full drain | at `f9bf715` |
|---|---|
| confirmation's `awaiting_approval` | the asked track |
| case | `EXECUTING` |
| the asked track | `PENDING`, `approval_request_id` null |
| approval requests | one: A, `SUPERSEDED`, decided |
| outstanding steps | **none** |
| `approval:<track>` step | `DONE`, result `REQUESTED`, from A |
| timers | A's deadline only, a no-op on a superseded request |
| A's `option_id` / the re-planned track's `chosen_option_id` | **identical** |

Session 2's description was accurate, and incomplete in one way that decides the design: the
re-plan re-chose the very option A asked about. Option ids are derived from the track and the
engine's option, so `request_id_for(track, option)` would have reproduced A's primary key. A fix
to the step key alone would have run a request step whose insert wrote nothing (`ON CONFLICT DO
NOTHING`) and whose track update re-bound the track to A — superseded, and carrying the
customer's old yes.

## 2. Root cause

Every approval identity was derived from the **track** alone, and §13.6's "one ApprovalRequest per
track" had been read as an identity rather than as a rule about one live request at a time. That
reading makes §14.4's "a new request (if any) follows" impossible. The collision is not one key
but the whole second episode:

| identity | before | collides in episode 2 with |
|---|---|---|
| request step | `approval:<track>` | A's `DONE` step — the reported stall |
| request id | `uuid5(track, option)` | A's row, whenever the option is re-chosen |
| delivery continuation | `approval-sent:<track>`, `approval-abandoned:<track>` | A's `DONE` steps — B would never be marked waiting |
| revalidation | `revalidate:<track>` | A's `STALE` checklist — B's yes would never be checked |
| re-plan | `replan:<track>` | A's re-plan — B going stale would never be re-planned |
| amendment authority | `PROCEED` read from `revalidate:<track>` | A's step, a key that does not say which request |
| amendment provenance | the decision joined by `track_id`, `one_or_none()` | two decisions — `MultipleResultsFound` |
| workspace evidence | revalidation read from `revalidate:<track>` | A's `STALE` checks shown beside B |

The last three are latent: unreachable until the first is fixed, and wrong the moment it is.

## 3. The approval-episode identity

**One approval episode is one track asked under one confirmed plan.** The confirmation that asks
is already bound to a `plan_id` (ADR-0010, ADR-0018), `plan_approvals` is already unique on
`(case_id, plan_id)`, and a plan identity covers the case version, so no two confirmations of one
case can quote the same one.

| identity | a track's first ask (unchanged) | a re-ask |
|---|---|---|
| request step | `approval:<track>` | `approval:<track>:<plan_id>` |
| request id | `uuid5("approval:<track>:<option>")` | `uuid5("approval:<track>:<option>:<plan_id>")` |
| sent / abandoned | `approval-sent:<track>` / `approval-abandoned:<track>` | `…:<track>:<request>` |
| revalidation | `revalidate:<track>` | `revalidate:<track>:<request>` |
| re-plan | `replan:<track>` | `replan:<track>:<request>` |
| message key, link, reply id, supersede notice, deadline timer | per request, already | per request, already |

The confirmation tells first ask from re-ask by whether the track has any approval request, read
under the track locks it already holds. That is exact, not a heuristic: analysis runs only before
a confirmation, and the only way a confirmed case returns to `PLANNED` is a `REPLAN_TRACK` that
supersedes the request it replaces. A request knows which it is from its own row —
`approvals.ask_scope(request)` is `None` when its id is the per-track derivation of its own track
and option, and its own id otherwise — and every downstream key is built from that.

Each step about one request acts only if the track still carries **that** request
(`approvals.step_names`); anything else is skipped and changes nothing. A request step does not
ask a track that already carries a request. The amendment's authority check reads the
revalidation of the carried request, and its provenance names the carried request's decision.

**Rejected**, with reasons in the ADR: a minted key (not replay-safe), resetting the `DONE` step
(rewrites the ledger), a fingerprint key (a world that moves and moves back reproduces A), a
per-track ordinal (names nothing that authorised the ask), chaining from the predecessor (needs
"latest by timestamp"; a replay after B exists derives C), escalating on re-plan instead (live,
but contradicts §14.4 and §23), and plan-scoping every ask (moves every first ask's identity for
no liveness gain).

**No migration.** No table or column changed. `approval_requests` has no uniqueness beyond its
primary key, and `case_steps.step_key` is `VARCHAR(128)`; the longest new key is 110 characters.
**No public protocol changed**: the literal parser, the link format, `pp:approval:<request>`, the
§14.4 notice and every HTTP shape are as they were. Keys written before the change keep executing,
because a per-track key still names the track's first ask.

## 4. Before and after

```text
T is the asked promise's track; A is its first request, B the re-ask, P2 the re-planned plan.

before  YES on A → order moves → revalidate:<T> STALE → replan:<T> (A SUPERSEDED, T unbound)
        → case PLANNED → person approves + confirms P2 → awaiting_approval=[T]
        → enqueue approval:<T>  ── declined: DONE from A
        → case EXECUTING, T PENDING, nothing outstanding, nothing armed. Stopped, unannounced.

after   … → person approves + confirms P2 → awaiting_approval=[T]
        → approval:<T>:<P2> → request B = uuid5(T, option, P2), bound, message pp:approval:<B>
        → delivered → approval-sent:<T>:<B> → T WAITING_FOR_CUSTOMER, case WAITING
        → YES on B → revalidate:<T>:<B> → PROCEED → apply → RECOVERED, provenance names B
        → or: order moves again → revalidate:<T>:<B> STALE → replan:<T>:<B> → asked a third time
```

## 5. What is guaranteed, and where it is proved

All in [`test_approval_reask.py`](../apps/backend/tests/test_approval_reask.py), against the real
PostgreSQL, the real worker and — for the link — the real HTTP hop.

| guarantee | test |
|---|---|
| the exact defect: re-confirmed, listed as awaiting, now asked; case `WAITING`, nothing stalled | `test_a_promise_re_planned_after_a_stale_yes_is_asked_again` |
| B has its own id, deadline timer, message key and link, though the option is the same | `test_the_second_request_has_its_own_identity_deadline_message_and_link` |
| A and its decision stay as history, with the per-track identity they always had | `test_the_first_request_and_its_decision_stay_exactly_as_they_were` |
| A's link (approve and decline) and a literal `YES` naming A authorise nothing about B | `test_the_old_link_answers_nothing_about_the_new_request` |
| A's yes never carries: B lapses unanswered and nothing is applied | `test_the_old_yes_never_carries_into_the_new_request` |
| only a yes to B, revalidated as B, reaches the order; provenance names B's decision | `test_a_yes_to_the_new_request_is_revalidated_and_applied_as_that_request` |
| replayed confirmation, request, delivery and re-plan work make no C; a second command is refused | `test_replaying_the_confirmation_and_the_re_ask_work_asks_no_third_time` |
| worker killed before the re-ask commits: nothing; the next worker asks once | `test_a_worker_that_dies_before_the_re_ask_commits_leaves_nothing_behind` |
| worker killed after it commits: one request, one message | `test_a_worker_that_dies_after_the_re_ask_commits_asks_exactly_once` |
| B going stale is re-planned and asked a third time | `test_a_re_asked_promise_that_goes_stale_again_is_re_planned_and_asked_again` |
| no service credential, and not the first plan's spent approval, can open the re-ask | `test_a_re_ask_is_authorised_by_a_person_approving_the_new_plan` |
| A, C, D, E and F are not touched by the re-ask; E and F get no effect and no request | `test_nothing_unrelated_is_touched_by_the_re_ask` |

**The regression reproduces the defect.** The first test was run against the `f9bf715` versions
of the five changed modules and failed at `assert len(requests) == 2` with one request, A,
`SUPERSEDED`; restored, it passes.

**No second consent path.** Nothing here reads Telegram inbound, adds a parser or an
`ApprovalChannel` member, or lets a model or service write a decision or a plan approval. A
customer answers the re-ask exactly as they answered the first: through the signed link for
*that* request. The option code is the same on both requests, because it is derived from the
option; a reply is always bound to one request by its transport, so a code quoted against A
reaches A.

## 6. Validation

| check | result |
|---|---|
| `test_approval_reask.py`, new — real PostgreSQL, worker, HTTP link hop | **12 passed** |
| the defect regression against the `f9bf715` versions of the five changed modules | **failed as the defect**: `assert 1 == 2` requests, A alone and `SUPERSEDED` |
| 23 files in one sequential run on the fixed tree: the new module, `test_customer_approval`, `test_customer_approval_link`, `test_customer_intent`, `test_consent_authority`, `test_human_confirmation_boundary`, `test_adversarial_races`, `test_recovery_revalidation`, `test_truthful_recovery`, `test_recovery_execution`, `test_order_amendment`, `test_step_execution`, `test_workflow_outbox`, `test_workflow_inbox`, `test_workflow_timers`, `test_worker_recovery`, `test_withdrawal`, `test_impact_analysis`, `test_whole_delivery_counterfactual`, `test_case_workspace`, `test_status_view`, `test_causal_chain`, `test_cli` | **702 passed**, 0 failed, 0 skipped |
| re-run on the final tree: the new module and the strengthened session 2 link tests | **16 passed** |
| `mypy` over `packages/promise-graph packages/order-contract apps/backend` | no issues, 292 files |
| `mypy` over `evals scripts` | no issues, 147 files |
| `lint-imports` | 30 kept, 0 broken |
| `ruff check`, `ruff format --check` on every changed file, Markdown included | clean |

Sequential throughout; no `xdist`, no worktree, no test weakened, skipped, deselected or `xfail`ed.
One existing test changed, and it was strengthened:
`test_a_yes_that_went_stale_is_never_told_the_next_plan_s_progress` asserted only that the
re-planned track was not `STALE`; it now asserts the track is `WAITING_FOR_CUSTOMER` on a
request other than the superseded one, and the neighbouring docstring that said the case "does
not ask again" says what is now true. No existing assertion or literal moved, because a first
ask's identity did not.

The whole backend suite was not run (roughly an hour); GitHub CI is the regression authority, and
nothing is pushed. The compose `api` and `mcp` containers were stopped for the suite and started
again afterwards; the worker was found stopped and left stopped. The containers serve their
images, not this tree: nothing was rebuilt.

## 7. What remains

- **Nothing is deployed.** A release is deployment work, and §10.1 of
  [non-destructive-release.md](non-destructive-release.md) still stands.
- **A case with two approval tracks, one of them re-planned.** `_replan` moves the whole case to
  `PLANNED` while another track may be mid-revalidation. The canonical case has one approval
  track, this session did not construct two, and ADR-0022 says it does not decide that shape.
- **No refusal path has been exercised live**, and the re-ask has not been either: every proof
  above is local, against the fake provider.
