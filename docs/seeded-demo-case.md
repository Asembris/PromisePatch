# The seeded demo case: how a deployment comes up with something to look at

Date: 2026-09-16
Status: **built.** Nothing was deployed, no AWS resource was touched, and no principal gained
write authority.

## 1. The defect

`pp reset-demo-state` seeds orders, promises, resources and staff and **no case**. A case exists
only once somebody reports an exception, and nothing in the product does that — it was the CLI
recipe, run by hand, and any `docker compose up` re-ran the seed service and erased it.

So the judge entry — one button, no credential,
[ADR-0013](adr/0013-read-only-observer-principal.md) — reached a real case **only if an operator
happened to have built one beforehand and nothing had reset the deployment since**, and has done
since the entry shipped. A judge who pressed it on a freshly deployed host got the product's own
empty sentence and nothing to read.

That is a provisioning defect rather than an authority one, and
[ADR-0016](adr/0016-a-judge-principal-stays-read-only.md) is why the fix is not to let the judge
open the case themselves.

## 2. Where the case is seeded from, and why not the other two places

**Decision: neither the reset recipe nor the deploy's seed. A provisioning step of its own,
`promisepatch.provisioning.ensure_demo_case`, run at the start of the `worker` process and
exposed as `pp ensure-demo-case`.**

| candidate | rejected because |
|---|---|
| **the reset recipe** (`reset_demo_state`) | It is destructive by definition — it truncates every domain row PromisePatch owns. Putting the case inside it inherits the destruction, and in the local stack `seed` is a dependency of `api`, so every `docker compose up` would erase the case it had just created. A case is not fixture data: it is the product of a real attestation, and a projection cannot make one. |
| **the deploy's `seed` service** | Same objection, plus it is profiled so that `up -d` never reaches it — precisely because P6.2 found a reboot silently re-seeding the database. Provisioning must run at *every* start, which is the opposite property. |
| **a new compose service** | The deployed composition is uploaded to an SSM standard-tier parameter and stands at 4052 bytes against a hard 4096-byte cap enforced by `deploy/deploy.sh`. A new service does not fit in 44 bytes without deleting the file's own explanation, and a local-only service would diverge from the deployment it is supposed to model. |

**The worker's start is the one place that costs nothing and diverges from nothing.** It is
present in both stacks with the same image, command and environment file; it already holds
everything a case needs to be interpreted — the database, the effect adapter, the semantic
provider, the order-system client; and it restarts idempotently. `worker.built` was extracted so
the CLI command drives *that* wiring rather than a second copy of it that could quietly reach a
different provider.

### The switch is the judge entry's own

Provisioning is gated on `PP_DEMO_SESSION_ENABLED`, not on a setting of its own. The defect being
fixed is that the judge entry shipped with nothing guaranteeing a case for it to land on; **two
independent switches is exactly how those two facts drifted apart.** Tying them together means
the deployment that offers the entry is by construction the deployment that provisions the case
— and, usefully here, it needs no SSM edit, no new environment variable and no compose byte,
because `env/api.env` already carries `PP_DEMO_SESSION_ENABLED=true` in both stacks and the
worker already reads that file.

## 3. Which scenario, and the one thing it is not

**The seeded case is the canonical Hollow Oak incident on the unmodified fixture: `maya` says
"today's raspberry delivery didn't arrive", answers "just raspberries - the strawberries came",
and the case reaches `PLANNED`.** Its labels are the frozen manifest's **`S01`**:

| order | classification | authority band |
|---|---|---|
| `EXT-A` Priya Nair | `AUTO_RECOVERABLE` | covered by a standing preference |
| `EXT-B` Tomas Lindqvist | `APPROVAL_REQUIRED` | needs the customer |
| `EXT-C` Okafor-Reyes | `BLOCKED` | needs the owner |
| `EXT-D` Lena Fischer | `BLOCKED` | needs the owner |
| `EXT-E` Ahmed Bouazizi | `UNAFFECTED` | left alone |
| `EXT-F` Cafe Marlow | `UNAFFECTED` | left alone |

Every row is asserted in `test_the_provisioned_case_carries_the_bands_a_judge_is_shown`.

**[P7.1 §3](p7.1-judge-ux-contract.md) fixes the canonical demo as `S11`, and this is not `S11`.**
That is stated rather than glossed. `S11` is this same incident plus one thing: Lena's own edit to
her own order, crossing from the external order system as a signed webhook *before* anybody
speaks, which moves `EXT-D` out of the raspberry world and makes the untouched baseline **3**
instead of 2. Provisioning does not perform it, for two reasons:

1. **It would couple the boot path to two other services.** The edit has to go through the order
   system's own HTTP surface and its webhook has to be accepted by the API. In the local stack
   `api` depends on `seed`, so a provisioning step that needed the API would be a dependency
   cycle; in the deployed stack it would make the worker's start wait on the simulator and the
   API. Boot-time coupling of exactly that shape is where P6.2's eleven defects came from.
2. **It would stage the one thing `S11` exists to prove is not staged.** P7.1's own argument for
   `S11` is that Lena "is untouched because of what is stored, not because somebody arranged for
   her to be". A provisioning step that performs her edit on every fresh boot has *arranged* it —
   it turns the demo's contingency into part of the stage set.

So `S11` stays what it is: a live demonstration performed **on top of** the seeded case — the
operator or the demo video makes Lena's edit in the order system and a judge watches one order
change before anything else happens, which is demo-sequence step 1. The screen renders either
without a change, because P7.1 already requires that `untouched_count` and `threatened_count`
arrive from the backend and that **the screen hardcodes neither number**. The seeded case shows
all three authority bands populated either way; under `S01` the owner band carries two rows
instead of one.

## 4. What state the case is in, and why that state

**`PLANNED`, awaiting confirmation** — demo-sequence step 5, which P7.1 calls one of the two steps
"where the product is won or lost".

It is the state that shows the most of the product **and** the least side effect, and those are
the same fact:

- **Every band is populated at once.** The worker's own sentence and the clarifying question with
  the answer that was given (beat 1); six orders resolved into three authority groups (beat 2);
  the untouched set counted against the case's own universe (beat 3); the evidence drawer that
  arrives with the case (beat 4). All four of the judge journey's comprehension beats are legible
  here.
- **Nothing external has happened, and the screen says so.** A `PLANNED` case has raised **zero
  operational effects** — asserted directly, `effects(physical) == 0`. Every threatened promise
  reads "planned — waiting for you". A judge therefore lands on the authority boundary itself:
  the system knows exactly what to do and has done none of it.
- **Any later state would mean provisioning acted.** Carrying the case past `confirm` would mean
  that every fresh boot amended a real order in the external order system and sent a real customer
  a message. Provisioning speaks; it does not authorise. `PLANNED` is the last state reachable
  without a human saying yes.

A judge cannot press that yes — ADR-0016 — and the screen does not offer it to them: the workspace
response gives an observer `may_speak: false` and `permitted_verbs: ("status",)`, a read verb and
no effecting one.

## 5. Idempotence and non-destruction, and how each is proved

P6.2 records a reboot that silently re-seeded the database and erased the very cases the
deployment exists to prove outlive the host. That defect is not reintroduced, and the argument is
tests rather than reasoning.

**Four independent guards, in the order they are reached:**

1. **The setting.** A deployment that does not serve the judge entry provisions nothing.
2. **`pg_try_advisory_lock`.** Try, not wait: a second process that finds the lock held *skips*
   rather than queueing behind it and repeating the work. It is a session-level lock on a
   dedicated connection and is released in a `finally`, so a connection never returns to the pool
   holding it.
3. **The emptiness check.** Provisioning does nothing at all unless `cases` is **entirely empty**
   — not "no open case", no case. That is the strongest available form of "never clobber", and it
   needs no judgement about which case matters.
4. **Fixed command identities.** Both statements carry a constant `command_id`, so the case id is
   derived from it and a redelivered command is recognised by intake rather than opening a second
   case — idempotence that holds even if the check above were somehow reached twice.

**Nothing in this path truncates, deletes or updates a pre-existing row.** The only writes it can
make are `intake.open_physical_exception` and `intake.answer_clarification`, both through the
ordinary audited boundary, and the worker cycles those enqueue.

| test | what it catches |
|---|---|
| `test_a_fresh_stack_comes_up_with_exactly_one_planned_case` | The defect itself: a fresh database ends with exactly one case, `PLANNED`, opened by `maya`. |
| `test_a_restart_does_not_open_a_second_case` | Duplication. The second run reports `PRESENT` and the case list is byte-identical. |
| `test_a_case_that_already_exists_is_never_replaced` | **P6.2's defect.** A case opened by hand under its own command id — neither the same row nor recognisable as a redelivery — survives a provisioning run untouched, and no second case appears. |
| `test_a_second_process_provisioning_at_once_skips_rather_than_repeating` | Two hosts booting together. With the lock held elsewhere the run reports `CONTENDED` and writes nothing. |
| `test_a_deployment_that_does_not_offer_the_judge_entry_provisions_nothing` | A deployment being given a demo case it never asked for. |
| `test_a_run_that_cannot_finish_leaves_the_case_where_it_stopped` | Guessing under failure. Out of budget, the case sits at `RECEIVED` with its words intact, nothing answered blindly and no effect raised. |
| `test_a_stopped_run_is_finished_by_the_next_start` | That a half-provisioned case is not orphaned: the next start declines to touch it and ordinary cycles carry it the rest of the way. |
| `test_a_provisioning_failure_never_stops_the_worker_starting` | The worst regression available here — a provisioning bug taking the worker down with it. |
| `test_the_worker_says_the_words_rather_than_writing_the_case` | That the case is the product of two spoken statements, stored verbatim, rather than rows arranged to look like one. |
| `test_the_provisioned_case_carries_the_bands_a_judge_is_shown` | The declared state and its declared labels, plus zero operational effects. |
| `test_the_judge_entry_lands_on_the_provisioned_case` | That the entry's own path — demo session, then the newest case — reaches this case with its bands populated. |
| `test_a_judge_reading_the_provisioned_case_still_may_not_speak_on_it` | That every refusal that stood before this case existed stands over it: `may_speak: false`, a read verb only, and the write route refused. |

## 6. What a judge sees if provisioning fails

[P7.1 §9](p7.1-judge-ux-contract.md) forbids an empty state that tells a judge to run a command,
and **no frontend change was needed to satisfy it** — the product already had the sentence:

> there is no case to look at yet. Nothing has gone wrong; nothing has been reported here.

That is `NO_CASE_TO_OPEN` in `apps/frontend/src/api/queries.ts`, raised when the judge entry finds
no case to open, drawn by `LoginScreen`, and already pinned by
`apps/frontend/tests/judgeEntry.test.tsx` — *"says there is nothing to look at rather than pressing
into an empty list"*. The case list's own empty state is the same kind of sentence: *"No case has
been opened. A case starts when somebody says what went wrong."* Neither names a command, a
process or a build system.

Three separate things make sure a judge reaches that sentence rather than a broken page:

- **Provisioning cannot stop the worker starting.** The call is wrapped, the failure is logged as
  `worker.demo_case.failed`, and the loop runs regardless. A judge losing a case to read is
  survivable; a worker that will not start costs the deployment every case anybody opens
  afterwards.
- **Provisioning does not gate the API.** It runs inside the `worker` process, which nothing else
  depends on being finished. The API is up and answering whether or not a case was provisioned.
- **A partial failure leaves a real state, not a broken one.** If the interpreter asks a question
  provisioning cannot answer — the two-hour window near the bakery's midnight where both Valley
  Produce deliveries fall on one day and every option carries the same words — the case is **left
  sitting on that open question** rather than guessed at. Guessing would cost an answer, and two
  unmatched answers escalate a case permanently. What a judge then sees is demo-sequence step 3:
  an open question, not a result.

## 7. What this did not do

Nothing was deployed, no AWS resource was read or mutated, and the live host was not touched — the
deployment is the next session's work, and it needs no configuration change to pick this up. No
principal gained write authority; no permission check was added, removed or weakened. No test was
weakened, skipped or deleted. The effect-set scenarios, the manifest and every frozen document are
untouched, and both holdouts stay sealed. No model was called: the canonical sentence is read by
the deterministic lexicon, and the suite runs against the fake provider.
