# Claims audit: what the evidence supports, and what it does not

**Verification only. Nothing was fixed, rerun, reseeded, deployed or proposed.** This page was
written by a reader who was present for no decision in this repository. It treats every document
as a pointer to evidence and never as the evidence, and it reports where the pointer holds and
where it does not.

| | |
|---|---|
| Audited at | `13b9931`, working tree clean, 15 September 2026 |
| Read | `CLAUDE.md`, `README.md`, every file in `docs/` and `docs/adr/`, the three local frozen documents where a page quoted them, and the code, tests, captures and commits each names |
| Executed | the manifest verifier and `--check`; 174 pure backend and script tests; the `scripts/` suite (378 passed, 1 skipped); the frontend suite (290 tests, 25 files); `test_spoken_budget.py` (461 passed); the offline `evals replay`; read-only `GET`s against the deployed host; a recomputation of every voice interval from the raw records |
| Not executed | any database-backed test, any scored or development effect-set run, any model call, anything that writes to AWS |
| Findings | **16**, ranked by how badly a judge finding it first would damage the project |
| Claims checked and not broken | listed in §5 |

Four kinds are used, as the brief defines them: **OVERCLAIM** (the evidence exists but does not
support the strength of the sentence), **UNSUPPORTED** (the cited evidence does not exist, does not
pass, or does not say that), **STALE** (true when written, false now) and **CONTRADICTION** (two
documents disagree, or a document disagrees with the code).

---

## 1. Findings, ranked

### F1 — the no-repair rule was not amended "before a single scenario was wired"

**Kind: UNSUPPORTED, and CONTRADICTION with the protocol's own commit and capture.
Severity: HIGH.**

The sentence, three times:

> `CLAUDE.md:315-316` — "Before a single one was built, the run protocol was amended to bound what
> a development run may repair"

> `docs/effect-set-harness.md:184-185` — "The protocol was amended before a single scenario was
> wired to say why"

> `docs/g7-closeout.md:184-185` — "The run protocol was amended **before a single scenario was
> wired**"

And the protocol's own claim about itself:

> `docs/effect-set-run-protocol.md:3` — "Predeclared. Written before the runner existed, in a
> session that scored nothing."

> `docs/effect-set-run-protocol.md:25` — "So the definition is settled here, before the harness is
> written and before any scenario has been executed against the manifest with any intent to record."

**Evidence checked.** `git log --date=iso` on the four commits, `git show` of the amendment, the
development capture, and the tree at the protocol's commit.

| what | commit | time (+0200) |
|---|---|---|
| protocol committed, claiming "before the runner existed" | `12627fc` | 15:01:17 |
| development capture written against `12627fc`, **dirty tree**, `wired: [S02, S11, S12]`, `S12: FAIL` with the three `ord-e/task_hold` diffs | `docs/effect-sets/runs/20260915T130854543810+0000-development.json` | 15:08:54 |
| harness committed: runner, judge, observation, three scenarios wired | `d9a0db5` | 15:11:32 |
| protocol **amended** to add "What a development run may repair, and what it may not", naming S12 as "the first case" | `a774ab5` | 16:19:33 |

The tree at `12627fc` holds `_effect_sets.py`, the verifier and its test, and nothing else of
the harness. But the capture seven minutes later ran a 413-line runner and judged three wired
scenarios against that same SHA with a dirty tree, so the runner existed in the working tree when
the protocol was committed. The same protocol commit says so itself at line 270: "Three of the
sixteen scenarios are wired — S02, S11, S12". A document cannot both be "written before the runner
existed" and record which scenarios the runner had wired.

The repair rule came sixty-eight minutes after S12's disagreement was captured and after three
scenarios were committed wired. The three sentences quoted above are false as written. What is
true, and what the amendment itself discloses by naming S12, is that the rule was written *after
the first disagreement was in hand* and in the stricter direction: it forbade repairing what had
just been seen.

**Why it fails.** The 11/16 headline's honesty rests on this rule: it is what "keeps G8's 'whatever
the result' from being theatre" (`CLAUDE.md:319-320`). A judge who checks the timestamps finds that
the rule the project says was fixed in advance was fixed after the first reading existed, which is
exactly the pattern the protocol says a predeclaration exists to prevent ("an amendment made after
a reading exists is a reading choosing its own protocol", `g7-ten-turn-voice-predeclaration.md:4-6`).
The damage is to the *predeclared* framing, not to the labels: the manifest froze six days earlier
(`9a7f4a8`, 9 September) and is byte-identical since, and the amendment made the rule stricter, not
looser.

### F2 — the voice gate is headlined as passed under a protocol whose own rules it broke

**Kind: OVERCLAIM. Severity: HIGH.**

> `docs/g7-ten-turn-voice-measurement.md:3-4` — "Run 2: `K = 9/10`. The gate is `K >= 9`. It
> PASSES, by exactly one turn, and the G7 voice obligation is DISCHARGED under the conditions §7
> fixes and R2.2 publishes."

Carried to `README.md:29-32` ("9 of 10 … the gate is 9, so it passes … A first run is published
void"), `docs/g7-closeout.md:125-128` ("Met, at the minimum that passes, by one turn") and
`CLAUDE.md` ("The voice gate passed at `K = 9/10`").

**Evidence checked.** The predeclaration's §10, quoted from `docs/g7-ten-turn-voice-predeclaration.md`:

> `:575` — "Each of the ten turns is attempted exactly once."

> `:580` — "It is never re-run and never replaced."

> `:585-587` — a run may be voided "only when that condition is identified and announced **before
> any interval has been computed or read**"

> `:596-597` — "Not grounds for voiding, ever: a slow turn, a refused turn, … a `K` below 9, or any
> reason discovered by looking at the numbers."

And the commit order: run 1 with its intervals and `K = 1/10` was published in `926c1cb` at 12:32;
the void was declared in `bd7d5d0` at 13:45; run 2 was taken from 12:41Z (14:41 local) and
published in `c55928b` at 14:55.

Three things follow from the protocol as written. The void was announced after the intervals were
computed, so the one precondition §10 places on voiding was not met. The condition invoked, "fewer
than ten records", was produced by the operator choosing to stop after seeing two failures
(`measurement:38-46` — "the void that followed is a void of a run the operator already knew could
not pass"), which is a decision taken by looking at the numbers. And run 2 re-ran turns 1, 2 and 3
with the same words in the same world, which §10 forbids in so many words.

**Why it fails.** Read strictly, run 1 is the run, `K = 1`, and run 2 is a replacement the
predeclaration says may never happen. The measurement discloses every one of these facts, at
length, in its own void declaration (`:23-50`): the breach is called "permanent", the stop is
called a choice, the informed second operator is called "a hazard this document will not hide",
and the reader is told to "weigh it accordingly". That disclosure is complete enough for a reader
to judge it themselves, and this audit could find nothing withheld. What is overclaimed is the
headline: a result the document itself says a reader may reasonably read as "a second attempt by
an informed operator" is carried to the README, the closeout and `CLAUDE.md` as a pass, with "voided
late" as the only qualifier and without the sentence that the void did not satisfy §10. A judge
who reads §10 first will call this a best-of-two.

What the audit did **not** find: any sign that the numbers of run 2 were altered, selected or
re-anchored. Every one of the twenty intervals, both `K`s, the means, the 94.7 %, the 3.5 %, the
anchor distances and the recomputation at `recogniser_end` reproduce exactly from the raw JSON in
the document (§4 below).

### F3 — run 2's "written before turn one" section was partly written after the run

**Kind: UNSUPPORTED. Severity: MEDIUM.**

> `docs/g7-ten-turn-voice-measurement.md:367-368` — "Everything in this section down to *The ten
> turns* was written and committed **before turn one was taken**, so that its pre-run status is
> checkable by commit order rather than asserted afterwards."

**Evidence checked.** `git diff ca4bc6e c55928b -- docs/g7-ten-turn-voice-measurement.md`. The
pre-run commit `ca4bc6e` (12:37:09Z; the first turn opened 12:41:16.916Z) holds R2.1 through R2.4.
Section **R2.5, "A warm-up happened, and nothing from it is counted"** (`:470-479`), which sits
above *The ten turns* and cites the first turn's own timestamp, was added in `c55928b` after the
run. The section's opening sentence is therefore false for one of its five subsections; the
checkable-by-commit-order property holds for R2.1–R2.4 only. R2.2, the environment, and R2.3, the
starting world, *were* committed four minutes before the first turn, and that is the part that
matters most.

### F4 — the runs that motivated the two "harness fixes" and surfaced the five disagreements have no capture

**Kind: CONTRADICTION between the protocol and the record. Severity: MEDIUM.**

> `docs/effect-set-run-protocol.md:142` — "Every run, of either kind, writes one JSON capture file
> before anything may be repaired."

> `:158-160` — "The capture is written before any repair. … The sequence is: run, capture, commit
> the capture, and only then diagnose."

> `:77-78` (a development run is) "Any invocation of the runner without `--scored`, any pytest
> invocation of the scenario suite, any subset"

**Evidence checked.** `docs/effect-sets/runs/` holds exactly one development capture, at 13:08Z
with three scenarios wired and thirteen unwired. There is no capture of any run in which the
thirteen were executed. Yet `effect-set-harness.md:149-164` describes a census that "would have
counted Cafe Marlow enlarging its own standing order" — a false positive that can only have been
observed by running S14 — and `:176-182` publishes the exact diffs of five scenarios. Those runs
were pytest invocations, which the protocol defines as development runs and says write a capture;
in the code they write one only when the runner's sink variable is set
(`apps/backend/tests/test_effect_sets.py:17`). The census repair (`0b52517`) and the simulator's
quantity edit (`a1405e3`) were both committed with no capture of the run that showed the need for
them.

**Why it fails.** The capture rule exists so that "the record shows what was run while the thing
was being built rather than hiding it" (`:88-89`). For the thirteen scenarios, it does not. The
five diffs are published, and the scored run reproduced them exactly, so nothing about the
*result* is in doubt; what is missing is the trail the protocol promised.

### F5 — "no X/16 was computed, printed or held privately" beside a page that publishes 5 of 16

**Kind: OVERCLAIM. Severity: MEDIUM.**

> `CLAUDE.md:320-321` — "**no X/16 was computed, printed or held privately**, `--scored` was not
> invoked, and the building session is not the scoring session."

> `docs/effect-set-harness.md:307-308` — "**No X/16 was computed, printed, written or held
> privately** — not in a document, not in a commit message, not in a report, and not as a working
> figure that could later become a claim."

Also `docs/g7-closeout.md:191-192`.

**Evidence checked.** The same harness page, `:178-182`: "Every one of the sixteen agrees with its
frozen labels on all four partitions … What diverges is effects, in five scenarios". The first
scored run, `docs/effect-set-first-scored-run.md:134-136`: "The diffs above are the same ones
published in `effect-set-harness.md` before this run was taken". Sixteen minus five is not a
private figure; it is on the page. The sentence is true of the runner's `score` field and false of
what the building session knew, and it is the second sense a hostile reader will test. The scoring
"session" ran 1 h 48 m after the harness page was committed, with no code changed in between
(`git diff --stat 3f28f8c e81b5aa -- apps packages scripts` is empty), so the separation of
sessions was real in the sense the protocol defines and formal in the sense that matters to a
reader: the number was already known.

**What survives.** The labels were frozen before any of this, the five stayed failing, nothing was
repaired, and the scored capture's `implementation_sha` is a clean tree. The headline is
honest; the sentence about ignorance of it is not.

### F6 — the third of "three P7.3 backend additions" did not land, and nothing records that

**Kind: UNSUPPORTED. Severity: MEDIUM.**

> `docs/p7.1-judge-ux-contract.md:384` — "the MCP correlation id that reaches the governed audit
> row is not on this response. P7.3 must carry it"

> `CLAUDE.md:249-251` — "**three P7.3 backend additions** where no field exists: the causal chain
> itself, the incident-caused-effect count on untouched orders, and the MCP correlation id."

**Evidence checked.** `docs/p7.3-implementation-plan.md:94` planned `correlation_id: UUID | None`
on `EvidenceView`. `grep correlation` over `apps/backend/src/promisepatch/api/schemas/cases.py`
and `domain/status_view.py` finds nothing; the word appears only in the error, middleware, intents
and events modules. The other two additions exist (`causal_chain`, `cases.py:152`;
`untouched_effect_count`, `cases.py:339`). Neither `p7.3-deployed-judge-surface.md`,
`p7.3-visual-acceptance.md`, `case-workspace-closeout.md` nor `g7-closeout.md` mentions the
correlation id. A judge who follows P7.1 §6's evidence table to the drawer finds one of its
"P7.3 must" rows unmet and unrecorded.

### F7 — the eleven deployment defects are broken down differently by `CLAUDE.md` and by their source

**Kind: CONTRADICTION, plus a STALE heading. Severity: MEDIUM-LOW.**

> `CLAUDE.md:220-222` — "Eleven defects were found that no amount of reading the definition could
> have found, five by AWS rejecting the stack, five by running it, and one by the account only
> granting what was asked for"

> `docs/p6.2-first-deployment.md:75` — "## 3. Five defects, all found by deploying and none
> findable without it"

**Evidence checked.** The section's own subheadings: §3.1 "The five the deploy found", §3.2 "The
two found by reading the definition against the code, before deploying", §3.3 "One found
pre-emptively", §3.5 "Three more the deploy found, after the stack was up" — 5 + 2 + 1 + 3 = 11.
Three of the eleven were found by reading, which is what both sentences say could not happen. The
heading survives from an earlier ten-defect revision of the page.

### F8 — the explanation gate's judge ledger counts half the judge calls on disk

**Kind: UNSUPPORTED. Severity: LOW-MEDIUM.**

> `docs/explanation-quality-gate.md:747` — "NVIDIA JUDGE CALLS 21 (7172c7c894ae; free_hosted_trial,
> USD not modelled)"

**Evidence checked.** `.eval-results/explanation-p48dev.jsonl` holds 21 judge records and
`.eval-results/explanation-7172c7c894ae.jsonl` holds 21: 42 Nemotron judge calls, not 21. The
page's own body (`:407-413`) discusses p48dev's judge verdicts, so the table contradicts the
narrative above it. The Nova figures in the same table (42 calls, $0.03293092) reproduce.

### F9 — one Stage A cost row is computed at two different price lists

**Kind: UNSUPPORTED. Severity: LOW.**

> `docs/customer-intent-challenger-stage-a.md:204-205` — "estimated spend on these cases
> $0.0063010 … estimated $ / 1,000 calls $0.577592" (Nova column)

**Evidence checked.** 17,420 input and 430 output tokens (the run file agrees). At the old
$0.30 / $2.50 per million: $0.0063010. At the corrected $0.33 / $2.75 (`evals/budget.py`):
$0.0069311, which per thousand calls over twelve is $0.5776. The spend cell uses the old rate and
the per-thousand cell the new one; the page's own cumulative line says "corrected Nova usage".

### F10 — the 104-word withdrawal reply is true, and is not pinned by the test the page says pins it

**Kind: UNSUPPORTED (the pinning, not the number). Severity: LOW.**

> `docs/spoken-word-budget.md:165-167` — "## What pins it — `apps/backend/tests/test_spoken_budget.py`,
> 461 pure tests, no I/O"

with the table row at `:85` "withdrawal: four reversals and three applied | **104** | **104**".

**Evidence checked.** `grep -c withdraw apps/backend/tests/test_spoken_budget.py` is 0. The 461
tests pass and pin every other row. `render_withdrawal` with all four reversal kinds and all
three applied kinds was recomputed at 104 words, so the figure stands; a test for it does not.

### F11 — "three bounded jobs" is now four

**Kind: STALE. Severity: LOW.**

> `README.md:94` — "three bounded jobs, strict schemas, and a check that every identifier …"

> `docs/semantic-boundary.md:10` — "One port, three bounded jobs, and a single acceptance gate."

**Evidence checked.** `SemanticJob` has four members — `INTERPRET_UTTERANCE`,
`CLASSIFY_REPLY_INTENT`, `VERBALISE`, `SELECT_TOOL` — the fourth added in P5.3 and described at
length in `CLAUDE.md`. The boundary page's jobs table omits it.

### F12 — one of the "Eight adversarial proofs" no longer exists

**Kind: STALE. Severity: LOW.**

> `CLAUDE.md:38` — "Eight adversarial proofs were added, offline, zero model calls, $0."

> `docs/p4.9-semantic-failure-hardening.md:158` — names
> `test_a_reply_too_long_to_be_one_message_is_never_sent_to_a_model` in `test_customer_intent`

**Evidence checked.** The test is absent from `apps/backend/tests`; its deletion is recorded in
`docs/customer-intent-classifier-removal.md` as part of removing the classifier. Seven of the eight
survive. The P4.9 page also names five further tests under names that have since been renamed and
two that no longer exist (`test_every_apparent_intent_asks_and_decides_nothing`,
`test_a_provider_that_cannot_be_reached_creates_no_authority`); the remaining forty named tests are
where the page says.

### F13 — the P7.3 plan describes itself as uncommitted and voice as reaching two verbs

**Kind: STALE. Severity: LOW.**

> `docs/p7.3-implementation-plan.md:3` — "**Local and uncommitted, on purpose.**"

> `:600` — "Voice reaches two of the five frozen verbs, not four … `confirm` and `withdraw` are
> buttons"

**Evidence checked.** `git ls-files` lists the page (`70fef02`). ADR-0015 later made `confirm`
speakable and the predeclaration measures three verbs; the departures row carries no superseded
note.

### F14 — `CLAUDE.md`'s "current state" still says the evidence UI is not deployed

**Kind: STALE. Severity: LOW.**

> `CLAUDE.md:230` — "The evidence UI is still not deployed and Telegram is untouched."

> `CLAUDE.md:235` — "the deployed `/` is still one line of plain text and a `404`."

**Evidence checked.** `README.md:22` ("It is deployed … serves the single-page application") and
`docs/p7.3-deployed-judge-surface.md`. A read-only `GET` on 15 September: `/` answers 200
`text/html`, `/healthz` answers 200 with image `acfdd975dd4d`, an unauthenticated `POST /mcp`
answers 401. The file is headed "Current state" and the P7.3 slice has no paragraph in it.

### F15 — three smaller stale sentences a judge could quote

**Kind: STALE. Severity: LOW.**

- `docs/semantic-boundary.md:525` "No explanation text reaches the UI or a durable step yet" and
  `:531` "Explanation *quality* is unmeasured" — both superseded by P4.8 and the evidence drawer.
- `evals/README.md:389` "the challenger workflow itself is not implemented and no challenger has
  been run" — three challenger runs are recorded in `.eval-results` and three challenger pages.
- `docs/adr/0006-customer-channel-telegram.md:39` "verified by `pp channel check`" — no such
  command exists in `cli.py`, and Telegram is recorded everywhere else as unbuilt.

### F16 — two voice-run artefacts cannot be reproduced by a reader

**Kind: UNSUPPORTED (unreproducible, not shown false). Severity: LOW.**

> `docs/g7-ten-turn-voice-measurement.md:45-48` and R2.1 — "A SHA-256 over the 129 `.py` files of
> the installed `promisepatch` package … equals the same hash over `apps/backend/src/promisepatch`
> in the working tree: `ee6e5b58…`"

> R2.12 — "A small scratchpad script implements §9's formulas"

The file count reproduces (`git ls-tree` at `0523b79`: 129 `.py` files; 39 frontend files), and
the two commits differ only under `docs/`, so the identity of the two hashes is expected. But the
hash's method — file order, separators, path inclusion — is not stated, so nobody can recompute
`ee6e5b58…`, and the scorer is uncommitted. The raw records live only inside the markdown. This
audit recomputed every published figure from those records with its own script and found no
difference, which is the strongest thing that can be said for an artefact nobody else can run.

---

## 2. The four areas a hostile reader goes to first

### 2.1 The ten-turn voice measurement

**Conclusion: the numbers are sound; the pass is defensible only outside the protocol's own
letter; the disclosure is sufficient for a reader to judge, and the headlines do not carry it.**

The predeclaration is a real predeclaration: `a161051` and its one amendment `d2da355` were
committed the evening before any turn (run 1's first record opened 10:24Z on the 15th). The ten
utterances, the anchor, the arithmetic and the failure rule were fixed there, and run 2's
environment and starting world were committed four minutes before its first turn. Every published
interval reproduces from the raw JSON (§4). The anchor choice is the stricter one and did not decide
the result. Turn 7 is a real nonpass, published as one.

Against that: §10 permitted a void only before any interval was read, and forbade re-running a
turn. Run 1's intervals were read and published, then voided, then all three of its turns were
taken again. The void condition was structural on its face and self-inflicted in substance. The
measurement says all of this itself and tells the reader how to weigh it; the README, the G7
closeout and `CLAUDE.md` say "voided late" and "passes". A judge reading §10 will conclude that,
under the rules the project wrote, the gate's number is 1 and 9 is a second attempt. The project's
strongest honest position is the one its own measurement page takes and its headlines drop.

### 2.2 The effect-set build sessions and the "harness fix" rule

**Conclusion: neither change made under the rule moved a frozen expectation toward the
implementation, and both are defensible on the manifest's own definitions. The rule itself was
written after the first disagreement, and the runs that motivated both changes are uncaptured.**

Every change in the build window was examined: `git diff --stat 12627fc 3f28f8c` over
`apps/backend/src`, `packages` and `apps/frontend/src` is empty. Two changes touched anything but
tests and scripts.

**The census attribution (`0b52517`).** A reservation change is now counted only when the
order-system event that moved the mirror carries an amendment idempotency key belonging to this
case. Could that hide a case-caused reservation change that reaches the mirror another way? No:
`grep` over `apps/backend/src/promisepatch` finds reservations written in exactly one place,
`domain/order_mirror.py` (`graph/loader.py` is the fixture load), so every reservation change is an
order-mirror event and every case-commanded one carries the key. The manifest defines the effect as
a change "as a consequence of this case" and R5 forbids counting a customer's own edit; the
pre-fix census violated that definition, which is the protocol's own description of a harness
defect ("a census that counts the wrong thing"). And the two captures bracket it: S02, S11 and S12
have identical verdicts and identical diffs before (`13:08Z`, pre-fix) and after (`16:32Z`, scored),
which is what the harness page claims and what a repair that changed the measurement would have
broken.

**The simulator's quantity edit (`a1405e3`).** Thirty lines in `apps/order-simulator`, a product
component rather than the harness, letting the operator screen change a line's quantity. S06, S13
and S14 stipulate exactly that edit, and without it their drive would "perform a different fact
from the one the scenario stipulates", which the rule names as a harness defect. The edit adds a
capability and changes no classification, no effect kind and no label; the mirror already read
quantity (`order_mirror.py`, unchanged since 5 September). It did not make a frozen expectation
reachable: S06 and S13 still fail, and S14 passes because of the census, not the edit. It is,
however, a `feat(order-simulator)` commit made during a session the protocol says may fix only the
harness, and the harness page is candid that it is a second control on a product screen.

What is not defensible is the chronology in F1 and the missing trail in F4.

### 2.3 Could the sixteen labels have been authored by reading the implementation?

**Conclusion: it cannot be proved either way, the repository says so, and the evidence on balance
favours independent authorship of the effects and says little about the partitions.**

*For the reader who argues they were read from the implementation.* The engine predates the labels
by five days and the same person wrote both. All sixteen partitions match at all sixty checkpoints,
and the partitions are close to determined by the fixture's own design: the three authority bands
are the three constraint kinds Hollow Oak was built with, so a partition label is largely a reading
of fixture data. Tests asserting the canonical classification existed from 4 September. The
manifest's provenance array is self-attested ("No label … was read from, compared against, or
reconciled with any PromisePatch classification output") and nothing in the repository can check
it. The failure diagnosis finds the labels to be, in several places, "the spec transcribed", and
the spec is what the engine was built from.

*For the reader who argues they were not.* Five of sixteen scenarios disagree on effects, every
disagreement is in the direction of the label demanding *more* than the code does, and three of
those five were named as likely disagreements the day the manifest froze
(`ee67dd0:61-62`: "the started-task case in S12, the uniform 'an escalation holds the task' rule,
the second ask in S06"). Labels tuned to output do not fail in predicted places. The manifest file
is byte-identical since `9a7f4a8` (`git diff` is empty), its hash is asserted by the runner and the
judge before anything runs, and the runner, judge and observation modules did not exist for six
days after it froze. The engine's behaviour on the thirteen non-canonical scenarios had no
executable path when the labels were written.

*Weighing it.* The partition score is weak evidence of anything, because a correct partition was
largely designed into the fixture; the project should not lean on "not one order is misclassified"
as if it were the finding. The effect score is real evidence, and the shape of the five failures is
the best argument the project has that the labels were written from the spec and the stipulated
facts rather than from the code. The manifest page already says both halves
(`docs/effect-set-manifest.md:33-39`, "What it cannot prove is that the engine was written blind");
that sentence should travel with the number, and the README's "not derived from PromisePatch's own
output" states the self-attestation as a fact.

### 2.4 Every published number

See §4.

---

## 3. What was read and what was executed

**Read.** `CLAUDE.md`; `README.md`; the forty-one files in `docs/` and the fifteen in `docs/adr/`;
`evals/README.md`; the three local frozen documents where a page quoted a line from them; the
code, tests, captures and commits each of those names, including the full text of the four voice
and six effect-set pages and the diffs of every commit in the effect-set build window.

**Executed.**

| what | result |
|---|---|
| `uv run python scripts/verify_effect_set_manifest.py` | hash `d41f5afc…`, coherent, exit 0 |
| `uv run python scripts/run_effect_sets.py --check` | identity intact, 16 wired, 0 unwired, exit 0 |
| `test_physical_interpretation`, `test_effect_set_judge`, `test_status_view`, `test_plan_identity`, `scripts/tests/test_effect_set_manifest`, `scripts/tests/test_run_effect_sets` | 174 passed |
| `uv run pytest scripts/` | 378 passed, 1 skipped |
| `apps/backend/tests/test_spoken_budget.py`, `test_withdrawal_contract.py` | 461 passed; 11 passed |
| `npx vitest run` in `apps/frontend` | 290 passed, 25 files |
| `python -m evals replay`, `explanation-plan --split development` | offline, 0 clients constructed, 0 model calls |
| recomputation of both voice runs' arithmetic from the raw JSON in the measurement page | identical to every published figure |
| `reads_as_worker_confirmation` on the three declared confirmations and *that's right* | `True`, `True`, `True`, `False` — as the predeclaration says |
| read-only `GET /healthz`, `GET /`, unauthenticated `POST /mcp` against the deployed host | 200, 200 `text/html`, 401 |

Not executed: any database-backed backend test, any run of the effect-set scenarios, any model
call, any AWS mutation.

---

## 4. Every number, and where it traces

| number | where published | observation it traces to | result |
|---|---|---|---|
| `K = 9/10`, `K_progress = 6/10`, refusals 0 | measurement R2.7; README; `CLAUDE.md`; G7 closeout | ten raw records in `measurement.md` R2.12, recomputed under §9 | reproduces |
| `K = 1/10`, `K_progress = 1/10` (run 1) | measurement §9 | three raw records in §8, recomputed | reproduces |
| 807.8 ms (turn 7's miss), 4807.8 ms | measurement R2.8; README | `444342.8 − 439535.0 − 4000` | reproduces |
| all twenty `delta_answer`, ten `delta_progress`, `end − S` per turn | R2.6 | raw records | every one reproduces |
| product 81.0–180.8 ms, mean 140.7; review mean 2512.0; mean interval 2652.6; 94.7 %; 3.5 % | R2.9 | raw records | reproduces |
| anchor distance 0.5–193.9 ms, mean 120.3; turn 7 at `recogniser_end` 4632.7 ms, `K` still 9 | R2.9 | raw records | reproduces |
| run 1 review 16646.2 / 4751.7 / 1089.1 ms; backend 55–69 ms | measurement §7 | raw records | reproduces |
| 129 `.py` files, 39 frontend files | measurement §3, R2.1 | `git ls-tree 0523b79` | reproduces |
| backend hash `ee6e5b58…` | measurement §3, R2.1 | method unstated | **not reproducible** (F16); identity across the two commits is expected, `git diff` under `apps/` empty |
| 19 members of `AFFIRMATIONS`; 39 `CLAIM_WORDS`; 25-word cap | predeclaration §4; `CLAUDE.md`; several pages | `policy.py`, `semantic/jobs.py`, counted | reproduces |
| run-2 environment committed before turn one | R2 preamble | `ca4bc6e` 12:37:09Z vs first record 12:41:16.916Z | holds for R2.1–R2.4; **not for R2.5** (F3) |
| **11/16** | first scored run; README; `CLAUDE.md`; protocol table | `…163255509125+0000-scored.json`: `score {passed 11, of 16}`, `implementation_sha e81b5aa…`, `working_tree_dirty false`, `manifest_sha d41f5afc…`; `.log` shows the same 16 verdicts and diffs | reproduces; diffs in the page match the capture line for line |
| manifest SHA `d41f5afc…`; frozen at `9a7f4a899ade…` | README; manifest page; every effect-set page | verifier and `--check` recompute it; `git log` on the file shows one commit | reproduces; file unchanged since |
| 16 scenarios, 60 checkpoints, 96 rationale arguments, 6 orders | manifest page | counted in `scenarios.v1.json` | reproduces |
| development capture: 3 wired, 13 unwired, S12 FAIL | protocol status; harness page | `…130854543810+0000-development.json` | reproduces, and dates the runner before the protocol commit (F1) |
| 9,689 ms; 10,360 in / 165 out tokens; 6 calls, 1 attempt each | `CLAUDE.md`; P5.3; P6.1 | `live-smoke.json` at the repository root, **gitignored**: `wall_clock_ms 9689`, sums 10360 / 165, `attempts [1,1,1,1,1,1]`, `chose == expected` on all six | reproduces from a local file a repository reader cannot see; the page says so |
| $0.0039 per conversation; $33 a month | P6.1 §6; `CLAUDE.md`; prerequisites | 10.360 × $0.00033 + 0.165 × $0.00275 = $0.003873; the P6.1 table sums to $32.85 | reproduces as list-price arithmetic; the per-token rates are quoted, not sourced |
| 7/7 smoke checks, 4 refusals (P6.2); 12/12, 5 refusals (P7.3, README) | `CLAUDE.md:209`; README:24 | `scripts/deployment_smoke.py` `CHECKS` had 7 entries at `1465fcd` and has 12 at `HEAD`; refusal checks 4 and 5 | both true at their time; **no committed capture of any smoke run** exists, the outputs are pasted blocks |
| 2 of 9, 8 of 9, 9 of 9 preflight; 12 `DECLARED` | P6.1; `CLAUDE.md` | `scripts/aws_preflight.py` has 9 probed and 12 declared requirements | structure reproduces; the live results are uncheckable offline |
| deployment tests 47 → 57; `scripts/` 335 passing | P6.2; `CLAUDE.md` | 35 and 45 definitions plus a 13-way parametrize at the two commits; today 78 in that file and 379 collected | reproduces at its time; 335 could not be reproduced exactly |
| eleven deployment defects | P6.2; `CLAUDE.md` | §3.1–3.5 sum to 11 | total reproduces; **breakdown does not** (F7) |
| 70 withdrawal tests (26 + 11 + 9 + 6 + 7 + 3 + 8), 3 end to end | `CLAUDE.md:289`; withdrawal page | counted in the seven named files | reproduces |
| 73 offline orchestrator tests | `CLAUDE.md:108`; P5.3 | `pytest --collect-only` at `40a662e`: 73 in `test_orchestrator.py` (95 today) | reproduces at its commit |
| 9 recovery, 13 workspace API, 18 frontend tests (P5.4) | `CLAUDE.md:136`; P5.4 | collected at `a204e00`: 9, 13, and 18 `it(` blocks (36 and 23 today) | reproduces at its commit |
| 44 / 58 protocol, 19 / 43 intent, 18 / 33 status-view, 12 identity tests (P5.1, P5.2) | P5.1, P5.2 | collected at `f888123` and `f3d6a2c` | reproduces; P5.2's first publication was wrong and corrected the same day |
| 238 tests / 22 files; 274; 290 / 25 | case-workspace closeout; voice page; spoken-yes page; G7 closeout | `npx vitest run` today: 290 / 25; the chain 238 + 36 = 274, + 15 + 1 = 290 | reproduces; `spokenTurns.test.tsx` "19 tests" is now 20 |
| 461 pure spoken-budget tests | spoken-word-budget; G7 closeout | run: 461 passed | reproduces |
| 94 → 36 and 83 → 29 words; 104-word withdrawal | ADR-0014; spoken-word-budget; G7 closeout | the 461 tests pin the first two; 104 recomputed by hand, **no test** (F10) | reproduces |
| 14 promise states, 9 case headlines | P7.1; `CLAUDE.md`; closeouts | `PromiseState`, `CaseHeadline`, `vocabulary.ts`, counted | reproduces |
| 29 import-linter contracts (23 in P4.9) | spoken-yes page; P4.9 | `lint-imports`: 29 kept, 0 broken | reproduces; 23 was true then |
| 35-case explanation dataset (21 / 14); run `7172c7c894ae` 21/21, 26 attempts, 37,835 / 1,634 tokens, $0.01697905; faithfulness 5.00, causal 4.857; nine of twenty-one | explanation gate; `CLAUDE.md` | `evals/datasets/explanation_*.json`; `.eval-results/explanation-7172c7c894ae.jsonl`; recomputed | reproduces |
| Nova 42 calls / $0.03293092 for the gate; NVIDIA judge 21 | explanation gate `:745-747` | ledger and run files | Nova reproduces; **judge is 42** (F8) |
| 56 customer-intent cases; 105 = 49 + 56; 58 / 47 | classifier removal; ADR-0008; benchmark pages | dataset manifests | reproduces |
| benchmark `36c1f008de80` and `a2470b4320e5` figures; challenger `1dd2dba0d7f6`, `6bbb247da030` | benchmark, rerun, challenger pages | run JSON in `.eval-results` | reproduce, except the latency percentiles on the two Stage A pages, which match neither the run summaries nor nearest-rank recomputation (order of magnitude fine), and the mixed-rate row (F9) |
| eight adversarial proofs (P4.9) | `CLAUDE.md:38`; P4.9 | seven of eight exist by name | **seven** (F12) |
| 4052 bytes / 44 bytes of SSM headroom / 919 bytes of comments | ADR-0012 | the committed blob is 3925 bytes; 4052 is the CRLF checkout `deploy.sh` actually measures | reproduces on a Windows checkout only |

---

## 5. What was verified and could not be broken

- **The manifest is what it says it is.** One commit, byte-identical since 9 September, hash
  recomputed by the verifier, the runner, the judge and this audit; the runner refuses a different
  hash before executing anything; 16 scenarios, 60 checkpoints, 96 arguments; the reader imports
  no engine, the judge imports no backend, the verifier imports only the fixture module.
- **The scored run is what its page says.** The capture's SHA, clean tree, command, kind, score,
  sixteen verdicts and every diff match the page and the log; the five failures are the five the
  harness page published; no `HARNESS_FAILURE`; no model or credential configured; no product code
  changed between the harness page and the run.
- **No harness fix moved a label toward the code** (§2.2). Reservations are written in one place,
  so the census rule cannot hide a case-caused change; the pre- and post-fix captures agree on the
  three scenarios both hold.
- **Both voice runs' arithmetic, to the tenth of a millisecond**, and the predeclaration's
  code claims: four `/api/conversation/*` routes each behind `CsrfPrincipalDep` with a server-derived
  actor; no `mcp`, `/internal`, `jsonrpc` or service-token string anywhere in `apps/frontend/src`;
  one `startCapture` call site, three `TurnComposer` uses, two `speechEnded` anchors; the confirm
  composer drawn only on `may_speak && permitted_verbs.includes('confirm') && plan_id !== null`;
  no `location.reload` or `location.href` assignment; the acknowledgement and refusal sentences
  byte-identical; the server reads a spoken yes with the orchestrator's own
  `reads_as_worker_confirmation`; *that's right* is unreachable and the three declared confirmations
  are not.
- **The failure diagnosis's citations.** Twenty-four of twenty-six `file:line` references land on
  the named symbol; the other two land one line from it. Every sentence it quotes from the frozen
  spec and the architecture plan is in the local copies at the cited section, including the
  "task HELD", "customer told once", "Auto-escalates to owner after 10 min" and "Applies equally to
  AUTO tracks" rows.
- **The classifier is off the customer reply path**: `worker.py` calls only `semantic_intake.prepare`;
  the import-linter contract, the AST source assertion and the provider that raises on
  `CLASSIFY_REPLY_INTENT` all exist and the contract is kept.
- **The bounded withdrawal**: offered in `CLARIFYING` and `PLANNED` only, drawn only where
  `permitted_verbs` says so, never as a disabled control; the 70-test breakdown counts; the
  "please disregard" message is genuinely absent.
- **The spoken budgets** (461 tests), the fourteen states and nine headlines, the 25-word glue cap
  with 39 claim words, `PP_EXPLANATION_VERBALISATION` off by default and read in one place, the
  canonical report asserted at zero model calls, `evals` unable to import an AWS SDK.
- **Both holdouts unopened**: no holdout case id appears in any of the seventeen run files.
- **The deployment definition**: sslip.io derivation, `HttpPutResponseHopLimit: 2`, IMDSv2
  required, private encrypted RDS, the `/internal` 404 before the catch-all, the two-repository ECR
  grant, the `TLS_BYPASSES` sweep — every one has the named test and the test passes.
- **The deployed host answers**, on the day of the audit, as the README describes.

---

## 6. The P5 pages

*(The P5 transport, clarification, orchestrator and recovery pages were checked by the same
method; their findings are folded into §1 and §4 where they rank, and the rest is listed here.)*

**Verified and not broken.** Every test count in the five pages is exact at the page's own commit
(`pytest --collect-only` against `git archive` extracts of `f888123`, `f3d6a2c`, `40a662e` and
`a204e00`): `test_mcp_protocol.py` 44 → 58, `test_intent_api.py` 19 → 43, `test_status_view.py`
18 → 33, `test_plan_identity.py` 12, `test_orchestrator.py` 73, `test_orchestrated_conversation.py`
4, `test_semantic_contracts.py` 49, `test_truthful_recovery.py` 9, `test_case_workspace.py` 13,
`caseWorkspace.test.tsx` 18. `mcp==2.2.0` is pinned in `apps/backend/pyproject.toml` and
`uv.lock`; the handshake revision `2025-11-25` is asserted by
`test_the_pinned_sdk_speaks_the_revision_we_claim`; `POST /mcp` is stateless with `json_response`
off; an unlisted `Origin` is 403, an unlisted `Host` 421, a missing bearer 401 with
`WWW-Authenticate`; the intent schemas forbid extras and carry no actor; the worker comes from
`PP_SURFACE_WORKER_ID`; `ConfirmIntent` is exactly `command_id, case_id, plan_id`; the plan
identity is a sorted SHA-256 recomputed under the confirming lock, with the "two producers" test
present; forwarded bodies are exactly three fields; `ToolSelection` has two fields and a 200-character
cap; `MAX_TOOL_CALLS_PER_TURN = 2`, `CORRECTIVE_RETRIES = 1`; the seven phases and the three extra
headlines exist; the orchestrator's import-linter contract forbids what the page says it forbids;
the 25 / 26 / 28 contract counts match the commits they were written at. P5.2's first published
counts were wrong and were corrected the same day (`d8e86ab`), which the history shows plainly.

**STALE, unmarked.** "The bounded withdrawal is absent rather than stubbed", or that
`ConversationTool` "has no member for it", stands unedited in `p5.2:143`, `p5.3:279`, `p5.4:191`,
ADR-0009 §5, ADR-0010 §6 and ADR-0011's revisit trigger; the tool has been registered since
`e780df1`. `CLAUDE.md` patches its own P5.2 paragraph ("at that time; it has since landed") and the
pages do not. ADR-0011's stated revisit trigger has fired and no ADR records the revisit.

**STALE, unmarked, and worth a line.** `p5.4:91-93` says the workspace read runs
`intake.require_permitted` "exactly as it runs for the MCP surface". Since ADR-0013 it runs
`require_readable`, which admits the observer role, and asks `require_permitted` separately only to
fill `may_speak`; "no such case" and "not yours" still stay different answers
(`api/routers/cases.py:84-96`). `p5.4:81` "there will not be a write among them" is true of the two
reads it describes and sits beside an API process that now carries four `POST /api/conversation/*`
routes, which a hostile reader will quote out of context.

**Could not verify.** The mypy file counts (226 / 228 / 235 + 14 + 64), the manual `docker compose
up mcp` pass, and "the full repository suite" being green at `40a662e`.

---

## 7. Files changed, and what did not happen

This audit added one file, this page. No code, test, fixture, label, manifest, capture or frozen
document was changed; `git status` before it was clean and after it shows only `docs/claims-audit.md`.
Nothing was rerun that produces a score, no `X/16` was computed, no AWS resource was read for
mutation or written, no data was reseeded, no model was called, and no work is proposed here.
