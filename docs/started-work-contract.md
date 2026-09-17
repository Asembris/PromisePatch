# The started-work contract

**What PromisePatch may and may not say about kitchen work that has already begun.**

| | |
|---|---|
| Status | closed at `29272ce`; no production behaviour was changed to close it |
| Decides | the semantics the upcoming comparative benchmark freezes for started work |
| Rests on | [ADR-0017](adr/0017-a-blocked-promise-does-not-hold-a-started-task.md), verified against HEAD |
| Proved by | `apps/backend/tests/test_started_work_contract.py`, 11 tests, all passing |
| Frozen evidence | untouched: `scenarios.v1.json` is byte-identical, the immutable **11/16** headline stands |

This document exists because ADR-0017 settled *one scenario's* disagreement and this project is
about to freeze a comparative benchmark that will ask the same question of many. A decision
about `ord-e` is not a contract. This is the contract.

## The rule

> **A physical fact is authoritative independently of recovery authorization.** Work that has
> started has started. PromisePatch may refuse to let work begin, may tell a person that work
> which has begun must stop, and may record that a person stopped it — but it may never write a
> row that asserts, on its own authority, that begun work has stopped or was never begun.

Everything below is that sentence applied to a surface.

## The seven clauses, and where each is enforced

| # | Clause | Enforced at | Proved by |
|---|---|---|---|
| 1 | Scheduled work on a blocked promise may be prevented from starting. | `recovery.hold_tasks`, [recovery.py:767](../apps/backend/src/promisepatch/domain/recovery.py#L767) | `test_scheduled_work_on_a_blocked_promise_is_held` |
| 2 | Started work is never represented as held. | the same predicate, which matches `SCHEDULED` and nothing else | `test_started_work_on_a_blocked_promise_is_not_held` |
| 3 | Affected started work still produces a truthful owner obligation. | `recovery._escalate_track` → `TRACK_ESCALATED`, and `needs_owner_attention` | `test_the_started_promise_still_reaches_its_owner` |
| 4 | Already-performed work is never described as undone. | `status_view.render_withdrawal`'s applied half, never dropped | `test_withdrawal.py::test_a_delivered_effect_is_reported_as_applied_and_is_not_rewritten` |
| 5 | A withdrawal never turns started work back into not-started. | `withdrawal._release_holds` is scoped to rows in `HELD`, [withdrawal.py:621](../apps/backend/src/promisepatch/domain/withdrawal.py#L621) | `test_a_withdrawal_does_not_rewind_started_work` |
| 6 | Promises the exception never reaches receive no effect of any kind. | `recovery._affected_lines` reads persisted `track_paths` | `test_work_the_exception_never_reaches_is_untouched` |
| 7 | No surface claims a physical stop nobody acknowledged. | the BLOCKED vocabulary says *"goes to the owner"*, never *"held"*; counts are read from rows that moved | `test_a_withdrawal_releases_only_the_work_it_really_stopped`, `test_the_withdrawal_sentence_claims_no_stop_that_did_not_happen` |

Clause 2 is load-bearing and clause 5 is the reason. They are one mechanism seen from two ends:
**release restores the literal `SCHEDULED`**, and `production_tasks` has no column remembering
what a task was before it was held, so a hold taken on started work would have exactly one exit
and that exit would be a lie. This is ADR-0017's argument, re-verified here against HEAD:
`ProductionTask` carries `held_by_case_id` and no `held_from_state`, and the table has exactly
two writers of `state` — `recovery.hold_tasks` and `withdrawal._release_holds`.

## The complete S12 path, traced

S12 is the only scenario in the frozen fixture that reaches clause 2, because `ord-e` carries
the only production task that is not `SCHEDULED`
([hollow_oak.py:692](../packages/promise-graph/src/promise_graph/examples/hollow_oak.py#L692)).

1. **External change.** Ahmed re-pins `ord-e` to `rv-raspberry-lemon-2` in the order system
   before any exception is reported; external version 1 → 2, crossing as a signed event, and
   the mirror updates. It is his command, never an effect of a case that has not opened.
2. **Affected-set computation.** Propagation reads stored state at the moment of the exception.
   The order now names a raspberry version, so the shortfall reaches it and `ord-e` joins the
   threatened set.
3. **Classification.** No `SubstitutionPolicy` offers a variant of `rv-raspberry-lemon-2` and
   `ord-e` carries no recorded customer constraint that could permit one → `BLOCKED`. The
   partition is produced correctly; S12 diverges on nothing here.
4. **Production-task state.** `task-ol-e` is `STARTED`, stipulated by the fixture rather than
   arranged by the scenario. Its `scheduled_start` is 80 minutes *after* the anchor, so the
   task state is the only thing that distinguishes it.
5. **Recovery and escalation.** The track is escalated to the owner in the confirmation's own
   transaction, beside the holds taken for `ord-c` and `ord-d`.
6. **Holds.** `hold_tasks` runs against `ord-e`'s line and matches zero rows. The census records
   `task_hold 0` because it reads the real row's holder.
7. **Withdrawal and release.** `_held_tasks` selects only rows in `HELD` held by this case.
   `task-ol-e` was never held, so it is never selected, and the statement that would write
   `SCHEDULED` never reaches it. The started fact survives a withdrawal *because* the hold was
   never taken.
8. **Status and effects.** Nothing claims a hold. The workspace shows `ESCALATED` with an owner
   and a reason; the "held by case" badge is rendered from `held_by_case_id` and stays absent;
   the withdrawal sentence names two released tasks, not three.

**Observed divergence, unchanged:** `ord-e/task_hold` expected `1`, observed `0`, at `CONFIRMED`,
`CONSENT_SETTLED` and `SETTLED`. Nothing else in S12 differs.

## What ADR-0017 gets right

Every load-bearing claim in it was re-checked against HEAD and holds:

* the hold predicate is `SCHEDULED` and unchanged;
* release restores the literal `SCHEDULED`, unconditionally;
* there is **exactly one** release path, and it has no memory;
* `production_tasks` has no column recording the pre-hold state;
* `ord-e` is the only order of the six whose task is not `SCHEDULED`;
* no screen claims the task is held, because it is not;
* declining the repair and declining the relabelling are both recorded, and S12 stays failing.

The decision is correct and is not reopened. No contradictory evidence was found.

## What ADR-0017 leaves out

Two facts, both verified here, that the ADR does not record. Neither contradicts it; both
matter to a benchmark that will ask this question again.

### 1. The disagreement is with a manifest-wide rule, not with S12's label

The ADR frames the conflict as one scenario's label against an invariant. It is wider than
that. The frozen manifest declares, in `vocabulary.labelling_rules`:

> **R1** — Every escalation to the owner holds that order's production task: `owner_escalation`
> implies `task_hold` on the same order.

R1 is unconditional, and it is enforced structurally: `verify_effect_set_manifest.py` refuses
any manifest in which an order escalates without a hold
([line 222](../scripts/verify_effect_set_manifest.py#L222)), and
`scripts/tests/test_effect_set_manifest.py` tests that refusal. So S12's label is not an
authoring choice that happened to be wrong — it is R1 correctly applied to the one fixture row
where R1 is false. **No relabelling of S12 alone can fix this**, because a v1 manifest with
`ord-e owner_escalation 1` and no `task_hold` is structurally invalid by its own verifier.

This strengthens ADR-0017's decision 4 rather than weakening it: the label could not have been
quietly corrected even if somebody had wanted to.

### 2. Decision 5's named repair is not sufficient as specified

ADR-0017 decision 5 names the future repair as a `held_from_state` column plus a release that
restores the remembered state, after which "the predicate widens to `SCHEDULED` and `STARTED`".
That repairs release. It does not repair **reading**.

`revalidation._task_is_ours`
([revalidation.py:251](../packages/promise-graph/src/promise_graph/revalidation.py#L251)) treats
`HELD by our own case` as satisfying check 6, *"production task not started and still ahead"*
([revalidation.py:201](../packages/promise-graph/src/promise_graph/revalidation.py#L201)). That
equivalence is sound **today, and only because** `hold_tasks` can hold nothing but a `SCHEDULED`
task, so `HELD` is a faithful proxy for "was scheduled". Widening the hold predicate to
`STARTED` breaks that soundness relation at its root: `HELD` would no longer imply not-started,
while the check that depends on it reads only `state` and `held_by_case_id` and would not see
the difference. `held_from_state` alone does not reach it.

**So decision 5's repair has a third part, and it is a precondition rather than a follow-up:**
`_task_is_ours` must refuse a hold whose remembered state was `STARTED`, before any predicate
widens. Recorded here so that a future session implementing decision 5 does not discover it
from a customer.

This is a hazard in a repair that has not been made, not a defect at HEAD. No current path
reaches it, because no started task is ever `HELD`.

## Whether a new benchmark-contract version is required

**Yes — and the reason is R1, not S12's count.**

A benchmark whose structural rules cannot express "this promise is blocked and its work cannot
be stopped by us" cannot measure started-work semantics at all. It can only score a system as
wrong for telling the truth. That is a defect in the contract, and it will recur in every
scenario a comparative benchmark adds where work has begun — which, in a made-to-order kitchen,
is most of the interesting ones.

The required delta, specified and **deliberately not authored here**:

* **R1 becomes conditional.** *Every escalation to the owner holds that order's production task,
  unless that task had already started when the exception was reported; started work is
  escalated without a hold.* The verifier's implication check gains the same qualification, read
  from the fixture's own task states rather than from a per-scenario flag.
* **No new effect kind.** `owner_escalation` already carries the obligation truthfully, and
  adding a kind for "work is running and a person must stop it" would require new production
  behaviour. A benchmark that induces the behaviour it measures is not a benchmark.
* **Everything else is unchanged.** R2 through R5, the partition algebra, the checkpoints and
  the pass rule all survive verbatim.

Under [the correction process](effect-set-run-protocol.md#if-a-frozen-label-turns-out-to-be-wrong)
that delta needs a separately versioned manifest with its own hash, an argument written from
stipulated facts alone, and a separate result published **beside** the original — never over it.

**This session authors none of it**, for the same reason ADR-0017 declined to: a replacement
contract written in the session that verified the implementation disagrees is not
distinguishable from a repair of the score, however good the argument. The delta is specified
so that the work is scheduled rather than rediscovered. The authoring, the hash and the run
belong to a separate session.

## Treatment of the frozen evidence

Nothing was touched.

* `docs/effect-sets/scenarios.v1.json` is byte-identical; content hash
  `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` unchanged.
* The immutable **11/16** first scored run stands exactly as published. The denominator is
  permanently sixteen.
* Later development runs reached **15/16** with S12 the only failure. That is development
  evidence and is **not** a score; it does not replace, amend or stand beside 11/16.
* S12 stays committed failing, unrepaired, unskipped, in the denominator, with its diff
  published. No expectation was edited and no test was weakened, deselected or xfailed.
* `test_s12_escalates_ahmeds_promise_and_holds_no_task_for_it` characterises the divergence
  rather than repairing it: it asserts what is true, so that a change on either side becomes
  visible immediately instead of silently closing the gap.

## What was not done

* No production code was changed. HEAD already implements every clause above; what was missing
  was the contract and the proof, not the behaviour.
* Decision 5's schema change was not made, and is not recommended before the release — the
  deployment constraints ADR-0017 records still hold, and part three above adds to its cost.
* No benchmark was run, no manifest was versioned, and no v2 was authored.
