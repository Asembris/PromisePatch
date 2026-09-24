# Effect-set manifest v2: the R1 label correction

**Predeclared. Committed before the run it governs, and before any run against v2 exists.**

| | |
|---|---|
| Manifest | `promisepatch-effect-sets` **v2.0.0**, `docs/effect-sets/scenarios.v2.json` |
| Content hash | **`77286e77a2919244118a7c39ace7632290ecca50eacf4318e45a4a72606cb0dd`** |
| Corrects | v1.0.0, `docs/effect-sets/scenarios.v1.json`, `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` |
| Kind | **a label correction, not a product repair**. No product code changes |
| Purpose | G8's release condition, 16/16 on the release candidate only |
| Release candidate | `4529a802e34e` |
| Runner | `scripts/run_effect_sets.py` `RUNNER_VERSION` **`1.1.0`** |
| Headline | **11/16 against v1, immutable.** Nothing here moves it, and no v2 result is ever reported as it |

## 1. What this is, and what it is not

The roadmap's G8 addition allows exactly one route for a wrong label:

> A genuine label error receives a separately versioned, explained correction and separate result;
> never overwrite the original headline or mirror implementation output.

This page is that correction. v1 is **byte-identical** and is still verified exactly as it was
frozen, with R1 unconditional. Its first scored run,
`docs/effect-sets/runs/20260915T163255509125+0000-scored.json`, **11/16**, stays the headline
forever. The denominator of that headline is permanently sixteen.

v2 exists for one sentence of G8, *"G8 requires 16/16 on the release candidate only"*. A v2
result is a **release-condition result**. It is published beside 11/16 and never over it, and
it never becomes "the benchmark's score".

## 2. Why the correction is justified, from evidence that existed before this page

The rule that decides it was written **after** the first scored run and **before** this session.
None of the four answers below uses an observed count.

**Was "started work is escalated to its owner and never held" established before this closure?
Yes.**

- [ADR-0017](adr/0017-a-blocked-promise-does-not-hold-a-started-task.md), accepted 2026-09-17,
  commit `eb0eb23`, amended at `ea75485`.
- [started-work-contract.md](started-work-contract.md), closed 2026-09-17 at `03713f1`. Its
  clause 2 is *"Started work is never represented as held"*, proved by
  `test_started_work_contract.py::test_started_work_on_a_blocked_promise_is_not_held`.
- The same rule was frozen independently as rule **B1** of the SUR-1 manifest,
  `docs/benchmarks/safe-useful-recovery.v1.json`, `relationship_to_effect_sets_v1`.
- It stands as an authority invariant in `CLAUDE.md`: *"Work that has started is never reported
  as stopped."*

The first scored run was taken 2026-09-15, two days before any of these.

**Does S12 stipulate STARTED work? Yes, verbatim.** S12's fourth stipulated fact reads: *"ord-e's
production task is already in a started state, and that is stipulated rather than changed."* The
frozen fixture agrees: `hollow_oak.py:692` gives `ord-e` `TaskState.STARTED`, and it is the only
one of the six orders whose task is not `SCHEDULED`.

**Is `task_hold 0` therefore correct product behaviour? Yes, under the contract in force.** A
hold's only exit is `withdrawal._release_holds`, which writes the literal `SCHEDULED`. Holding
started work would give it exactly one exit, and that exit asserts begun work never began. The
contract forbids that, and ADR-0017 decision 3 calls it the one category this product does not
trade.

**Is v1's expected hold the wrong label? Yes, and the fault is in the rule, not the authoring.**
S12's `ord-e task_hold 1` is v1's **R1**, *"owner_escalation implies task_hold on the same
order"*, applied correctly to the one fixture row where R1 is false. The started-work contract
said so in its section *"Whether a new benchmark-contract version is required: Yes"*. It
specified this exact delta and deliberately left it unwritten for a later session.

ADR-0017 declined the correction *at the time* for one reason: it would have been argued in the
session that found the disagreement. Its *Revisit if* names the condition under which the
argument may be made, *"after a scored run rather than before one"*, under the correction process
and *"beside the 11/16 headline and never over it"*. Both conditions hold. The first scored run
exists, and this correction is written a week after the rule it applies.

## 3. The argument, from S12's stipulated facts alone

1. S12 stipulates that `ord-e` is threatened and has no recovery. It names no substitution-policy
   variant of `rv-raspberry-lemon-2` and no constraint that permits one. So the promise needs its
   owner, and **`owner_escalation` 1** is right. v2 leaves it unchanged.
2. S12 stipulates that `ord-e`'s production task **had already started** before the exception was
   reported.
3. `task_hold` means *"this order's production task was held by this case"*. A hold exists so
   that work which cannot be finished is not **started** (§13.5's purpose clause). Work that has
   started cannot be prevented from starting, so the hold's purpose is empty for it.
4. Representing started work as held asserts a stop nobody acknowledged. Through the only release
   path, it would also later assert that the work had never begun. Both are physical claims, and
   physical facts are authoritative independently of recovery authorization.
5. So the correct expected effects for `ord-e` are an owner escalation and **no hold**. The
   escalation carries the obligation: a person must stop the work, and the case tells them so.

Nothing in that argument refers to what PromisePatch produced.

## 4. The exact v1 → v2 delta

Measured by a structural diff of the two JSON documents, and asserted by
`scripts/tests/test_effect_set_manifest.py::test_v2_differs_from_v1_only_by_its_declared_delta`:

| path | v1.0.0 | v2.0.0 | kind |
|---|---|---|---|
| `vocabulary.labelling_rules[0]` (R1) | every escalation holds the task, unconditionally | holds the task **unless it had already started**; a started order is escalated without a hold and never carries one | **the rule** |
| `S12.checkpoints[CONFIRMED].effects_added` | 9 entries, including `ord-e task_hold 1` | 8 entries; `ord-e task_hold 1` removed | **the one label** |
| cumulative `ord-e/task_hold` at `CONFIRMED`, `CONSENT_SETTLED`, `SETTLED` | 1, 1, 1 | 0, 0, 0 | consequence of the label |
| `S12.rationale.ord-e` | *"... whatever the kitchen has begun."* | same text, plus one sentence saying why the task is not held | diagnostic (not a pass criterion) |
| `version` / `authored_at` / `authored_in_phase` | `1.0.0` / `2026-09-09` / `P5` | `2.0.0` / `2026-09-24` / `P8` | metadata |
| `provenance` | four lines | five lines, disclosing that the corrected label is not independent of the implementation in time | metadata |
| `correction` | absent | names v1 and its hash, the kind, the rule, the label and this page | metadata |

**Everything else is v1 byte for byte**: the other fifteen scenarios in full, every other S12
checkpoint, partition, effect, refusal and stipulated fact, the fixture, R2–R5, the partition
algebra, the effect and refusal vocabularies, the checkpoint order and the pass rule. The scenario
ids are unchanged. The major version moves because a labelling rule changed meaning.

**Why only S12 moves.** Conditional R1 only affects an order that is escalated and whose task had
started. `ord-e` is the only started task in the fixture, and S12 is the only scenario in which it
is escalated or holds anything. A scan of all sixteen scenarios, run before authoring, found no
other `ord-e` effect and no other stipulated task state. The rule forces no other label.

## 5. Verifier and harness support

**Verifier** (`scripts/verify_effect_set_manifest.py`):

- `--manifest v2` verifies v2. The default is still v1, and v1's R1 check is unchanged:
  unconditional.
- The rule is chosen by the manifest's own major version, which is inside the hashed document.
  A v1 document cannot acquire the conditional rule without ceasing to be v1.
- For v2, the started set is read from the fixture's own task states (`started_orders()`, which is
  `{ord-e}`), never from a per-scenario flag, as the started-work contract required. An order in
  that set must carry **no** hold. Every other order must still carry one when escalated.
- The tests prove four things: v1 still refuses the corrected S12, v2 refuses a hold on started
  work, v2 still refuses an unheld escalation on scheduled work (`ord-c`), and v2's identity is
  pinned.

**Harness**, at `RUNNER_VERSION` `1.1.0`:

- `run_effect_sets.py --manifest {v1,v2}` defaults to `v1`.
- The runner always writes its choice into the pytest child's `PP_EFFECT_SET_MANIFEST`, overriding
  anything it inherited.
- `_effect_sets.py` reads the selected document and `_effect_set_judge.py` asserts that document's
  **own** pinned hash.
- v2 captures go to `docs/effect-sets/runs-v2/`, never among v1's.
- **Observation and the pass rule are unchanged.** Only the document the expectations are read
  from can differ.
- CI's `effect sets (expected red until 16/16)` job names no manifest, so it still judges v1 and
  stays red on S12 exactly as before. Its workflow is not touched.

## 6. A deviation from the run protocol, disclosed

[effect-set-run-protocol.md](effect-set-run-protocol.md) says *"A session that wrote or changed
harness code does not go on to take the measurement."* This session changes harness code (manifest
selection) and then takes the v2 run, **as the project owner directed**. The rule exists so that
nobody chooses when to stop building after seeing outcomes. Three facts bound that risk here:

- The outcome under v1 was already known before this session, from the owner's authenticated
  reading of the release candidate's CI: 15 of 16 pass, and S12 alone fails, on `ord-e/task_hold`
  at `CONFIRMED`, `CONSENT_SETTLED` and `SETTLED`.
- The correction was specified on 2026-09-17, a week before this page.
- The harness change does not touch observation or judging, only which frozen document is read.

It remains a deviation, and it is recorded as one.

## 7. The run, predeclared

Taken **exactly once**, after this page and the v2 manifest are committed, from a clean tracked
tree, against code whose product paths are identical to `4529a802e34e`:

```bash
uv run python scripts/with_local_env.py -- uv run python scripts/run_effect_sets.py --scored --manifest v2
```

Preconditions, each recorded in the result document:

- `git status --porcelain` shows no tracked modification. The eleven known untracked artefacts
  are not touched.
- `git diff --name-only 4529a802e34e HEAD` names only `docs/`, `CLAUDE.md`, `scripts/` and
  `apps/backend/tests/`, with no product path.
- Local PostgreSQL is up at migration head, and the compose `worker`, `api` and `mcp` are stopped.
- No model provider, AWS credential or messaging account is used. The capture's environment block
  records this.

Rules, fixed now:

- The capture is committed **as written**, whatever it says.
- **If the result is not 16/16**, it is preserved and published, and nothing is repaired. v2 is
  not edited, and the run is not repeated. G8's 16/16 then remains open.
- **If the result is 16/16**, it is published as *G8's release condition against the v2 label
  correction*, beside the immutable v1 11/16, and never as the original benchmark becoming 16/16.
- A harness failure is a nonpass and counts in the sixteen.

The result and its lineage are recorded in
[g8-effect-set-release-condition.md](g8-effect-set-release-condition.md).
