# Predeclaring the G7 ten-turn voice measurement

*Everything below was fixed **before** any turn was ever taken, and **amended once, on
2026-09-14, before any turn had been taken.** A predeclaration may be amended while no measured
turn exists and never afterwards -- an amendment made after a reading exists is a reading choosing
its own protocol. **No turn has been recorded, no timing exists, no interval has been computed and
there is no K/10.** Nothing was run, no browser was opened, no stack was started, no product code
or test was changed, and no AWS resource was touched.*

**Amendment 1 -- 2026-09-14.** `confirm` became speakable through the same composer after this was
first written ([ADR-0015](adr/0015-a-spoken-yes-checked-by-the-server.md),
[a-spoken-yes.md](a-spoken-yes.md)), so §4, §8 and §12 are corrected below. The original ten and
the original reasoning are kept verbatim in §4 under *Superseded*, with the date, the commit and
the three reasons they were replaced -- one of which is a defect found by verifying them. A
predeclaration that is quietly replaced is not a predeclaration. §5, §6, §7, §9, §10 and §11 are
untouched.

---

## 1. The requirement, quoted

Two lines in `new_roadmap.md` §G7 carry it. Neither is paraphrased here and nothing below adds a
criterion either one states.

`new_roadmap.md:354`:

> Record **10 real voice turns**, including failures/timings. Strategic release target: at least
> 9/10 start a truthful spoken response within 4 seconds of speech ending. Long work gets honest
> progress, never premature success. This is a usability gate, not a statistical production SLA.

`new_roadmap.md:358`:

> Predeclare the ten voice turns and measurement setup; record speech-end to first truthful spoken
> response, all timings and failures. Publish actual K/10 within 4 seconds, identifying honest
> progress replies separately from completed answers. At least 9/10 is the gate, not an assumed
> observation; no cherry-picked replacement turns. Carry this measurement to all three submission
> artifacts.

`docs/p7.1-judge-ux-contract.md` §7 restates it and adds nothing to it:

> G7 requires **ten real predeclared voice turns**, recorded with failures and timings, with at
> least nine starting a truthful spoken response within four seconds of speech ending. **No turn
> has been recorded and no timing exists.**

**What the requirement does not say.** It does not name a transport, a browser, a stack, a
recogniser, a synthesiser, a scenario, or which of the five frozen verbs the ten turns must
exercise. Those are method, and method is what this document fixes. Where a frozen document does
not support something this protocol needs, §12 reports the gap instead of filling it.

---

## 2. What this document is

It is the predeclaration `new_roadmap.md:358` requires: the ten utterances, the transport, the
anchor, the definition of a truthful spoken response, the environment, the starting state, the
arithmetic and the failure rule -- all fixed in advance so that none of them can be chosen later
against a number that already exists.

It is not the measurement. It takes no reading and contains no estimate of one.

---

## 3. The transport, named -- and verified in the code before it was written down

**The ten turns are taken through the browser conversation surface, which posts to the API's own
session-authenticated `/api/conversation/*` routes. It does not call the MCP server.**

```
speech  ->  TurnComposer  ->  apps/frontend/src/api/client.ts
        ->  POST <origin>/api/conversation/report     (session cookie + X-CSRF-Token)
        ->  POST <origin>/api/conversation/clarify
        ->  promisepatch.api.routers.conversation
        ->  intake.open_physical_exception / intake.answer_clarification
```

### How that was verified

| claim | how it was checked | what was found |
|---|---|---|
| the browser calls `/api/conversation/*` | read [client.ts](../apps/frontend/src/api/client.ts) | four functions, four paths: `/api/conversation/report`, `/clarify`, `/confirm`, `/withdraw` |
| the browser never calls the MCP server | `grep -rni "mcp\|/internal\|jsonrpc\|service.token\|X-Service" apps/frontend/src/` | **zero matches** |
| the credential is the session, not the service token | [conversation.py](../apps/backend/src/promisepatch/api/routers/conversation.py) module docstring; `CsrfPrincipalDep` on all four routes | session row plus CSRF; the internal shared secret is not accepted |
| the actor is server-derived | same module | `worker_id = principal.worker_id`; the request models forbid extras and have no actor field |
| every turn leaves the browser through one instrumented place | [queries.ts](../apps/frontend/src/api/queries.ts) `timed()` | `turnSent(verb)` before the request, `responseReceived(...)` either way |

### Why this differs from the frozen contract, and where that is now recorded

`docs/p7.1-judge-ux-contract.md` §7 defines voice as *"a clearly labelled Alexa+ simulation that
really calls the deployed Streamable HTTP MCP server"*, over *"the same four tools, over the same
authenticated transport"*. The surface that was built does not do that, and
`docs/p7.3-implementation-plan.md` §11's departures table did not record the difference. It does
now -- the row is added by this work, with the reason P7.3 §7 E already gives:

> **The browser never touches `/internal/intents` and never holds the service token.**

That is the real reason and it is a good one: the MCP boundary is authenticated by a shared
service secret, and a page that held one would be holding a credential no browser may ever have.
The authority properties P7.1 §7 asks voice to preserve are all preserved by the route that was
built instead -- server-derived actor and clock, `require_permitted` enforced inside the domain,
`plan_id` binding on confirmation, and `status_view` rendering delivered unchanged. What is not
preserved is the *shape* of the boundary, and §12 records the one consequence of that which this
measurement runs into.

---

## 4. The ten utterances

*Amended 2026-09-14. The ten declared here replace the ten declared on 2026-09-14 in `a161051`,
which are kept verbatim at the end of this section under **Superseded**, with the three reasons
they were replaced.*

### The verbs voice can actually reach

Established by reading the code, and one row of it changed after this document was first written:

| verb | how a worker takes it | carries speech capture? |
|---|---|---|
| `report` | `TurnComposer` in [ReportEntry.tsx](../apps/frontend/src/features/case/ReportEntry.tsx) | **yes** |
| `clarify` | `TurnComposer` in [Conversation.tsx](../apps/frontend/src/features/case/Conversation.tsx) | **yes** |
| `confirm` | `TurnComposer` in `Conversation.tsx`, drawn only where `permitted_verbs` offers `confirm` and a `plan_id` is present, with the worker's words read on the server by `reads_as_worker_confirmation` | **yes, since [ADR-0015](adr/0015-a-spoken-yes-checked-by-the-server.md)** |
| `withdraw` | a control in `Conversation.tsx` | no |
| `status` | not a turn in the browser -- the workspace already shows it, and the read-aloud control replays it | no |

`startCapture` still has exactly **one** call site, `TurnComposer`. `TurnComposer` now has
**three**: report, clarify and confirm. `speechEnded` is called from nowhere else, so a spoken
confirmation leaves the same two anchors §5 chooses between, and a control press still leaves
none.

**The two remaining controls are not oversights, and each is unreachable for its own reason.**

* **`withdraw`** has its own closed list, `WITHDRAWALS`, matched only at the start of a turn.
  ADR-0015 §7 scopes itself to `confirm` and says why: giving `withdraw` a spoken path *"is the
  same decision made again rather than this one extended"*. Until that decision is made, a
  withdrawal is a control press with no speech-end instant.
* **`status`** is not a turn at all. There is nothing to send: the workspace already shows the
  case, and the read-aloud control replays a standing reading, which §6 excludes from every count
  because it is not a response to anything a worker just said.

**The canonical sequence now reaches `confirm` by voice.** P7.1 §3's step 6 -- Maya reading the
plan and saying yes -- is a measurable turn of this gate. Its step 9, Maya asking for status, is
still a screen. `withdraw` does not occur in `S11` at all. §12 reports what is left.

### Where the words come from

Every utterance below is quoted from a frozen source. None is composed for this document.

* `docs/effect-sets/scenarios.v1.json` -- the frozen 16-scenario manifest, content hash
  `d41f5afcd01eda8e6fa4c28784f1fb0c238bbc27711019aac670914db62b2cdc` -- the `stipulated_facts` of
  `S01`, `S02`, `S03`, `S04` and `S11`. Four scenarios supply words; the fifth supplies a world.
* The whole-delivery answer is additionally the domain's **own** option label:
  `interpretation.py` composes it as `f"the whole {commitment.supplier_name} delivery"`, and the
  offered option on the seeded fixture reads back as *the whole Valley Produce delivery*.
* The three confirmations are members of `promisepatch.orchestrator.policy.AFFIRMATIONS`, the
  closed set the server reads a spoken yes against.

### The ten, verbatim and in order

Four worlds. §8 says how each is seeded, and why they carry three turns, three turns, three turns
and one.

| # | world | verb | the words spoken, verbatim | frozen source |
|---|---|---|---|---|
| 1 | W1 | `report` | today's raspberry delivery didn't arrive | `S01` stipulated facts |
| 2 | W1 | `clarify` | just the raspberries | `S04` stipulated facts |
| 3 | W1 | `confirm` | yes | `AFFIRMATIONS`; `S04` stipulates the confirmation |
| 4 | W2 | `report` | today's raspberry delivery didn't arrive | `S02` stipulated facts |
| 5 | W2 | `clarify` | the whole Valley Produce delivery | `S02` stipulated facts; also the domain's own option label |
| 6 | W2 | `confirm` | go ahead | `AFFIRMATIONS`; `S02` stipulates the confirmation |
| 7 | W3 | `report` | today's raspberry delivery didn't arrive | `S01` stipulated facts |
| 8 | W3 | `clarify` | just the raspberries | `S04` stipulated facts |
| 9 | W3 | `confirm` | do it | `AFFIRMATIONS`; `S11` stipulates the confirmation |
| 10 | W4 | `report` | the mascarpone in the walk-in went off | `S03` stipulated facts |

**Verb coverage: `report` x4, `clarify` x3, `confirm` x3. `withdraw` and `status`: none**, for the
reason above. **Seven distinct sentences across the ten turns**, where the superseded ten had two.

**Why the confirmations vary least, and why that is not a shortcut.** `AFFIRMATIONS` is a closed
set of nineteen, and it is closed **by design**: what may authorise a plan has to be a short list
a person can read, matched at the start of a turn, rather than a reading of how agreeable a
sentence sounds. Its own docstring says so -- *"Not a sentiment reading and not a classifier"* --
and ADR-0015 keeps one implementation of it for both surfaces so they cannot drift. Three distinct
members are declared here; a fourth would be a fourth word from the same nineteen. The variation
worth measuring is in the two verbs where a worker is genuinely speaking freely, and that is where
this section spends it.

**Why the reports repeat, and one clarification repeats once.** The frozen manifest quotes exactly
**two** worker reports across its sixteen scenarios -- `S01`'s delivery report and `S03`'s
spoilage report -- and exactly **two** speakable clarification answers, `S02`'s and `S04`'s. All
four are used. Nothing else in it is a sentence a worker says; the rest is stipulation written in
the third person, and composing a sentence to fill a row is precisely what a predeclaration may
not do. The repetition that remains is the manifest's ceiling, stated rather than papered over.

### How each of the ten was verified reachable, before it was declared

Read-only and offline: the repository's own pure functions, called on the shipped Hollow Oak
dataset through the context builder in `apps/backend/tests/test_physical_interpretation.py`, and
`promisepatch.orchestrator.policy.reads_as_worker_confirmation` called directly. **No database, no
stack, no browser, no microphone, no model, no clock and no timing.** Nothing was written, and no
source file, test or fixture was changed.

| what was checked | how | what came back |
|---|---|---|
| turns 1, 4, 7 are interpretable | `interpretation.interpret` on *today's raspberry delivery didn't arrive* | `ClarificationRequired`, slot `SCOPE`, resource `res-raspberries` -- the scope question §8 needs |
| the question offers both declared answers | the same call's options | `WHOLE_DELIVERY` labelled *the whole Valley Produce delivery*; `JUST_RASPBERRIES` labelled *just the raspberries* |
| turns 2 and 8 resolve | `interpret` with *just the raspberries* as the answer | `ResolvedObservation`, `scope_line_ids = ('cl-vp-today-raspberries',)` |
| turn 5 resolves | `interpret` with *the whole Valley Produce delivery* as the answer | `ResolvedObservation`, both lines: `('cl-vp-today-raspberries', 'cl-vp-today-strawberries')` |
| turn 10 is interpretable | `interpret` on *the mascarpone in the walk-in went off* | `ResolvedObservation`, `STOCK_UNUSABLE`, resource `res-mascarpone`, quantity `None` -- a total loss, and no question asked |
| turn 10's world can carry it | the `hollow_oak` resource list and ledger | `res-mascarpone` exists and is seeded at the fixture's ample on-hand, so it is not the `UNKNOWN_QUANTITY` escalation; and `MASCARPONE` appears in no recipe version, which is `S03`'s fourth stipulated fact checked against the fixture rather than taken on trust |
| turns 3, 6 and 9 read as a yes | `reads_as_worker_confirmation` on *yes*, *go ahead*, *do it* | `True` for each, and each is a member of `AFFIRMATIONS` |
| the panel will offer turns 3, 6 and 9 | [Conversation.tsx](../apps/frontend/src/features/case/Conversation.tsx) | the composer is drawn on `may_speak && permitted_verbs.includes('confirm') && plan_id !== null`, which is exactly §8's declared state before each of them |

Two things this verification found, and both changed what is declared:

* **A spoken confirmation has to be sayable without an apostrophe to be read as one.**
  `normalise` splits on every non-alphanumeric character, so *that's right* becomes `that s right`
  and never matches the `thats right` member. It is a real member of the closed set that a natural
  transcript cannot reach. The three declared confirmations were checked rather than assumed, and
  none of them has this problem.
* **The superseded ten's clarification answer does not resolve when it is spoken.** The evidence
  and the consequence are below, and §12 carries it as a gap.

### What this measurement does not claim

It borrows frozen utterances and frozen seeding; it scores no effect set. The manifest's labels
are hand-labelled expectations for the sixteen-scenario runner, and **no partition, effect or
refusal is asserted by any turn here**. W1 in particular is seeded only as far as `S04`'s first
two stipulated facts -- the second physical attestation is never made -- so nothing here is a
claim about `S04`'s effect set; and W3 borrows `S04`'s wording inside `S11`'s world, which is a
claim about neither's labels. This document measures one interval per turn and nothing else.

### Three notes on saying them out loud, fixed now so they cannot be adjusted later

* **Punctuation is not spoken, and none of the ten needs any.** Every declared utterance was
  verified as bare words, which is what a recogniser produces.
* **The transcript is whatever the recogniser produced.** It is reviewed, corrected if wrong, and
  sent. Correcting means making the transcript say what the worker said -- never adding
  punctuation to help a parser. A turn is judged by §9's clock, never by how closely the
  transcript matched these characters.
* **Both scope answers resolve deterministically, and the mechanism was read rather than assumed.**
  A `SCOPE` answer is not keyword-scored: `_resolve_scope_answer` calls `read_scope`, which splits
  the sentence into clauses on a fixed separator list and attributes a physical polarity to each.
  *just the raspberries* is one clause naming one resource under a `RESTRICT_MARKERS` word, so it
  reads as that line missing; *the whole Valley Produce delivery* names no resource and carries a
  `WHOLE_MARKERS` word, so it reads as the whole commitment.

### Superseded: the ten declared on 2026-09-14 in `a161051`

**Kept verbatim. Three reasons they were replaced, none of them discovered by looking at a number,
because no number exists.**

1. **`confirm` became speakable.** [ADR-0015](adr/0015-a-spoken-yes-checked-by-the-server.md) and
   [a-spoken-yes.md](a-spoken-yes.md) gave it the same composer, the same route and the same
   anchors, with the reading done on the server. A predeclaration that describes a surface the
   product no longer has would measure the wrong product. `a-spoken-yes.md` deliberately did not
   edit this document, because amending a predeclaration is an act for its own session; this is
   that session.
2. **They were two sentences repeated five times each.** Ten turns of two utterances measure one
   sentence's latency five times and call it ten.
3. **Turn 2's utterance does not resolve when it is spoken** -- which the superseded §4 asserted it
   would, from a reading of the wrong function. `_resolve_scope_answer` does not score keywords; it
   splits clauses on a fixed list, and that list holds an em dash but **not** a double hyphen, and
   not the absence of punctuation that a spoken sentence has. Checked three ways on the seeded
   fixture: the sentence written with a real em dash resolves to the raspberry line; the same
   sentence written with `--` returns `ClarificationRequired`; and the bare spoken words *just the
   raspberries the strawberries came* also return `ClarificationRequired`, because one clause
   naming both resources with *came* in it reads as both having arrived. The question would simply
   be asked again, and the world would never reach the plan the next turn confirms. `S04`'s frozen
   wording is declared instead: it resolves to the identical `scope_line_ids`, so it makes the same
   physical claim in words a worker can actually say.

The superseded declaration, unedited:

> ### The ten, verbatim and in order
>
> Five worlds, two spoken turns each. §8 says why a world carries only two.
>
> | # | world | verb | the words spoken, verbatim | frozen source |
> |---|---|---|---|---|
> | 1 | W1 | `report` | today's raspberry delivery didn't arrive | `S11` / `S01` stipulated facts |
> | 2 | W1 | `clarify` | just the raspberries -- the strawberries came | `S11` stipulated facts |
> | 3 | W2 | `report` | today's raspberry delivery didn't arrive | `S11` / `S01` stipulated facts |
> | 4 | W2 | `clarify` | the whole Valley Produce delivery | `S02` stipulated facts; also the domain's own option label |
> | 5 | W3 | `report` | today's raspberry delivery didn't arrive | `S11` / `S01` stipulated facts |
> | 6 | W3 | `clarify` | just the raspberries -- the strawberries came | `S11` stipulated facts |
> | 7 | W4 | `report` | today's raspberry delivery didn't arrive | `S11` / `S01` stipulated facts |
> | 8 | W4 | `clarify` | the whole Valley Produce delivery | `S02` stipulated facts; also the domain's own option label |
> | 9 | W5 | `report` | today's raspberry delivery didn't arrive | `S11` / `S01` stipulated facts |
> | 10 | W5 | `clarify` | just the raspberries -- the strawberries came | `S11` stipulated facts |
>
> **Verb coverage: `report` x5, `clarify` x5. `confirm`, `status` and `withdraw`: none**, for the
> reason above.
>
> Three notes on saying them out loud, fixed now so they cannot be adjusted later:
>
> * **Punctuation is not spoken.** `--` is a pause. The words are the manifest's words.
> * **The transcript is whatever the recogniser produced.** It is reviewed, corrected if wrong, and
>   sent. A turn is judged by §9's clock, never by how closely the transcript matched these
>   characters.
> * **Both answers resolve deterministically, and this was checked rather than assumed.**
>   `_resolve_scope_answer` scores the two options by whole-word keywords: `WHOLE_MARKERS` is
>   `whole / entire / all / all of it / everything / the lot`; the restricting option is
>   `just / only / nothing but` plus the resource's own terms. *the whole Valley Produce delivery*
>   scores the first and not the second; *just the raspberries -- the strawberries came* scores the
>   second and not the first.

The superseded §4 also recorded, of the verb table: *"The canonical sequence does reach `confirm`
and `status` -- but not by voice."* Half of that is no longer true, and the half that is stays in
§12.

---

## 5. The speech-end anchor

[turnTiming.ts](../apps/frontend/src/instrumentation/turnTiming.ts) records two candidate instants
per capture and deliberately privileges neither:

| field | what it is |
|---|---|
| `speech_end_final_result` | the recogniser's **last** final-result event |
| `speech_end_recogniser_end` | the recogniser's `onend`, when the microphone closed |

**The anchor is `speech_end_final_result`.**

`speech_end_final_result` is the **earlier** of the two. `onend` follows it: the recogniser
finalises the words first and closes the microphone afterwards, after its own silence timeout or
after the worker releases the control.

The choice is made on what "speech ending" means, not on which number is kinder. G7 measures from
**speech ending** -- the instant the worker stopped speaking. The last final result is the
recogniser's report of the last words it heard, which is a fact about the speaker.
`recogniser_end` is a fact about the recogniser: it is the silence timeout elapsing and the
microphone closing, and a recogniser configured with a longer timeout would make every turn look
faster without anything about the product changing. An anchor a configuration value can move is
not an anchor.

**Choosing the earlier instant lengthens the measured window.** Every interval published under
this protocol is longer than the same turn measured from `recogniser_end` would have been. Both
readings are recorded for every turn and both are published, so the distance between them is
visible rather than asserted.

**No fallback.** A turn whose record carries no `speech_end_final_result` is a nonpass under §9.
It is not re-anchored to `recogniser_end`, because falling back to the later instant is exactly
the shortening this section refuses.

---

## 6. What counts as a truthful spoken response

Three sentences can reach a worker's ear for a turn, and
[turnVoice.ts](../apps/frontend/src/features/voice/turnVoice.ts) labels each one where it starts.
The measured instant is always `SpeechSynthesisUtterance.onstart` -- when sound actually began --
never the return of `speechSynthesis.speak`, which resolves as soon as an utterance is queued.

| `audio[].utterance` | the sentence | what it is |
|---|---|---|
| `acknowledgement` | *Working on that turn now.* | **honest progress.** Fixed, five words, about the turn and never about a case, no digit and none of the thirty-nine `CLAIM_WORDS`. Spoken the instant the turn is sent, before any answer exists. |
| `reply` | the backend's `spoken`, byte for byte | **a completed answer.** Composed by `status_view`, delivered unchanged, and structurally unalterable by the browser. |
| `refusal` | *That turn did not happen. The case is exactly as it was.* | **a completed answer that the turn was declined.** Both clauses true by construction. |
| `replay` | -- | **not a response to a turn.** The read-aloud control replaying a standing status. Excluded from every count. |

### Which of them the gate is measured against

`announceTurnSent()` fires on **every** turn, before the request is issued. The `acknowledgement`
is therefore the first utterance of essentially every turn, and a K computed from it would measure
the browser reaching its own synthesiser and would be passed by a product whose backend never
answered at all.

**The gate is measured against the completed answer:** the first utterance of kind `reply` or
`refusal`. A fixed phrase the browser composed and spoke before anything responded is not a
response to the turn -- it is the surface saying it heard. Gating on it would measure the product
talking to itself.

This is the **stricter** of the two available readings of `new_roadmap.md:354`. It relaxes
nothing: every turn that passes under this definition also passes under the looser one.

`new_roadmap.md:358` requires honest progress to be identified separately from completed answers,
so both are computed and both are published (§9). A refusal is a completed answer for this purpose
and its interval is published in its own column, because a refusal is a response and must not be
quietly dropped from a denominator.

### What the window necessarily contains

The window from speech end to the completed answer contains, in order: the worker reading the
transcript, the worker pressing send, the request, the backend's work, the response, and the
synthesiser starting. **Transcript review before send is mandatory** -- P7.3 §7 D fixes it, because
a voice surface that acts on a misheard sentence has produced an attestation nobody made -- so the
review is inside the window by construction and is not excused out of it.

Two rules fix the human half now, so it cannot be tuned against a number later:

* **Send as soon as the transcript is legible and correct.** No deliberation, no re-reading, no
  waiting for a better moment.
* **A wrong transcript is corrected, and the correction is inside the window.** Correcting a
  misheard sentence is what the review step is for; the time it costs is time the worker spends
  and is measured.

---

## 7. The environment

Fixed here; every field is recorded from the actual machine before turn one and published with the
result.

| | fixed |
|---|---|
| **stack** | the **local `docker compose` stack**, with the frontend served by Vite on `http://127.0.0.1:55173` |
| **transport** | `/api/conversation/report` and `/api/conversation/clarify` (§3) |
| **served commit** | the working tree at `HEAD`, clean, with the backend image rebuilt from it |
| **machine** | Windows 10 Pro 19045 (the development machine; exact model recorded before turn one) |
| **browser** | Google Chrome. Version `152.0.7977.84` was installed when this document was written; **the exact version at run time is read from `chrome://version` and published**, because Chrome updates itself |
| **recogniser / synthesiser** | the browser's own `SpeechRecognition` and `speechSynthesis`. No Amazon Transcribe, no Polly, no Alexa skill, no wake word |
| **microphone** | the machine's own input device, named and published before turn one; push-to-talk, not continuous |
| **network** | the development machine's own connection, published before turn one. Note that Chrome's speech recognition is a network service, so the recogniser's own round trip is inside the capture and **before** the anchor |
| **other load** | no other application is driven on the machine during the run |

### Verifying the served commit before turn one

The local stack does not serve a built bundle from a registry, so the check is of the tree itself
and of the image built from it:

1. `git rev-parse HEAD` -- recorded.
2. `git status --porcelain` -- must be empty. A dirty tree voids the run before it starts (§10).
3. `docker compose build migrate`, then bring the stack up, so the backend container is built from
   that tree rather than from a stale one.
4. `GET /healthz` -- `version` and the schema revision recorded.

Vite serves the working tree directly, so the SPA under test is that commit's source by
construction; the rebuild is what makes the backend the same commit.

### Why not the deployed host, stated plainly

`docs/p7.1-judge-ux-contract.md` §7 wants voice pointed at the deployed loop, and
`https://184.194.40.87.sslip.io` is real. The measurement is not run there because §8 needs the
world reset five times and **the deployed host has no documented on-demand reseed** -- its seed
runs at boot, and the only recorded way to re-run it replaces the instance. Rebooting the
deployment five times to take ten readings is not a measurement setup.

**The cost of that choice, stated rather than buried:** the measured interval carries **no
public-internet round trip to `us-east-1`**, so every published interval is shorter than the same
turn taken against the deployed host would be. **No artifact may publish K without this sentence
beside it.** The deployed gap is reported in §12 and is not filled here.

---

## 8. The starting case state, and exactly how it is seeded

*Amended 2026-09-14 with §4. Five worlds of two turns become **four worlds of three, three, three
and one**, because a world can now carry `report` -> `clarify` -> `confirm`. The seeding steps
below replace the superseded ones; the reason a world carries at most one **report** is unchanged
and is restated at the end.*

Each world carries exactly one case, and each is built from a fresh reset.

**Before every world, without exception:**

1. `docker compose run --rm seed` -- `pp reset-demo-state`, which reloads the Hollow Oak fixture
   and replaces every domain row PromisePatch owns. The anchor is omitted deliberately:
   `resolve_anchor` corrects `now` through `demo.resolve_demo_anchor` for the two hours a day that
   would otherwise put both Valley Produce deliveries on one bakery day and leave the scope
   question unanswerable.
2. Reset the External Order System to its seeded state.
3. Sign in to the workspace as the worker. The case list is empty: a case exists only once somebody
   reports something.

**One world needs a fourth step, and only that one.** Before turn 7, and after steps 1--3, apply
**`S11`'s stipulated pre-incident edit**: Lena changes `EXT-D` from the Raspberry Lemon Layer to
the Lemon Curd Layer (`rv-lemon-curd-1`), external version 1 to 2, in the order system's own
interface. Wait for the signed event to cross and the mirror to move. This is step 1 of P7.1 §3's
demo sequence and it is what makes `S11` `S11`. **W1, W2 and W4 do not get it**: `S01`, `S02`,
`S03` and `S04` each stipulate *"the base Hollow Oak world, unmodified"*, and applying an edit
they do not name would be seeding a world none of them describes.

### The four worlds

| world | turns | seeded as | what the world is for |
|---|---|---|---|
| W1 | 1, 2, 3 | base, unmodified | the restricted-scope branch: `S01`'s report, `S04`'s answer, a confirmation |
| W2 | 4, 5, 6 | base, unmodified | the whole-delivery branch: `S02`'s report, `S02`'s answer, a confirmation |
| W3 | 7, 8, 9 | base **plus `S11`'s pre-incident external edit** | the canonical demo's world, where Lena's own edit removed her dependency before anything was reported |
| W4 | 10 | base, unmodified | `S03`: a real physical exception that threatens nobody, and asks nothing |

### The declared state before each turn

* **Before a `report` turn (1, 4, 7, 10): no case.** The `report` composer is the surface.
* **Between a `report` and its `clarify` (before 2, 5, 8):** the reported case is left to reach
  `CLARIFYING` and the open question is read. **Before the answer is spoken, the question's slot is
  confirmed to be `SCOPE`** -- the scope question, not the commitment question. Confirming a
  precondition is not a rerun of a turn; if the slot is not `SCOPE`, that world is rebuilt from
  step 1 and no turn of it has been taken yet.
* **Between a `clarify` and its `confirm` (before 3, 6, 9):** the case is left to reach `PLANNED`,
  and the plan is read. **Before the yes is spoken, the panel is confirmed to be offering the
  confirmation composer** -- which it draws only where `permitted_verbs` contains `confirm` and a
  `plan_id` is present, so its presence *is* the precondition rather than a proxy for one. If it is
  absent, that world is rebuilt from step 1 and no turn of it has been taken yet.
* **After the `confirm` turn:** the world is finished with. The case is left exactly where the
  confirmation put it; recovery is neither hurried nor stopped, nothing is withdrawn, and the next
  world starts from step 1.
* **W4 ends after turn 10.** `S03`'s report resolves without a question -- verified in §4 -- so
  there is nothing further for a worker to say in that world. No `confirm` turn is declared there:
  whether a case with nothing threatened offers a plan for a yes at all is not something this
  session may start a stack to find out, and a turn nobody has shown to be reachable is a turn this
  document may not declare.

### Why a world carries three turns now, and still only one report

A clarification answer and a confirmation are the **same case's** next two steps, spoken by the
same worker to the case they are already about. Nothing about them needs a fresh world; what
needed one was a second **report**, and that is unchanged:

> A clarification answer attests the delivery's lines and settles them. A settled commitment line
> contributes zero to expected supply and cannot be reported as not-arrived again, so a second
> report of the same delivery in the same world is a different interpretation with a different
> answer.

Rather than predeclare behaviour nobody has observed, each reported case gets its own world. Ten
turns therefore need four resets rather than the superseded five, and §7 still needs a stack whose
reset is a documented one-liner for exactly that reason.

---

## 9. The acceptance arithmetic

Computed from the records `window.promisepatchVoiceTimings.json()` returns, which are
`performance.now()` readings in milliseconds -- monotonic, unaffected by a clock correction
mid-turn.

**The denominator is 10 and never changes.**

For each turn *i* in 1..10:

```
S(i) = record[i].speech_end_final_result                          (§5)
A(i) = min{ a.at : a in record[i].audio, a.utterance in {reply, refusal} }
P(i) = min{ a.at : a in record[i].audio, a.utterance = acknowledgement }

delta_answer(i)   = A(i) - S(i)     milliseconds
delta_progress(i) = P(i) - S(i)     milliseconds

pass_answer(i)   = 1 if delta_answer(i)   <= 4000 else 0
pass_progress(i) = 1 if delta_progress(i) <= 4000 else 0

K          = sum over i of pass_answer(i)      the gate's number
K_progress = sum over i of pass_progress(i)    published beside it, not gated
```

**The gate: `K >= 9`.** `K = 10` and `K = 9` pass. `K = 8` and below fail, and the failure is
published exactly as a pass would be.

Four rules that settle the edges before any number exists:

* **Four seconds is exactly 4000 milliseconds.** `delta = 4000.0` passes; `delta = 4000.1` does
  not. No rounding is applied before the comparison, and intervals are published to 0.1 ms.
* **A turn with no `S(i)`, no `A(i)`, no record, or `origin != "spoken"` scores
  `pass_answer(i) = 0`.** There is no unmeasurable bucket. A turn that cannot be measured did not
  start a truthful spoken response within four seconds of speech ending, as far as anybody can
  show.
* **A refused turn is measured.** Its `refusal` utterance is its completed answer and its interval
  counts. Refusals are additionally published in their own column so a reader can see how many of
  the ten were refusals.
* **Both anchors are published for every turn**, so the interval measured from `recogniser_end` is
  visible beside the one the gate uses.

**What is published, in full, whatever the result:** the ten records verbatim as JSON; per turn the
verb, the utterance, the world, both speech-end anchors, `sent`, `received`, the outcome, and every
`audio` entry with its kind and instant; `delta_answer` and `delta_progress` per turn; `K`,
`K_progress`, and the pass or fail against the gate; the environment of §7; and the sentence from
§7 about the absent public-internet round trip. `new_roadmap.md:358` carries this measurement to
all three submission artifacts, and none of them may carry `K` without `K_progress` and the
measurement conditions.

---

## 10. The failure rule

**Each of the ten turns is attempted exactly once.**

* A turn that fails for **any** reason -- unheard, misrecognised past correction, refused by the
  backend, no audio produced, a synthesiser that never started, a dropped request, a slow one -- is
  recorded with what happened and scores `pass_answer = 0`.
* **It is never re-run and never replaced.** `new_roadmap.md:358`: *"no cherry-picked replacement
  turns."* There is no best-of, no discard, no "that one doesn't count", and no turn 11.
* A nonpass is published with the same prominence as a pass, including the reason it failed.

### When a whole run may be voided

A run may be voided only for a condition that makes the **record itself** untrustworthy, and only
when that condition is identified and announced **before any interval has been computed or read**:

1. The served commit is not the clean `HEAD` recorded in §7 -- including a dirty working tree.
2. The world was not in §8's declared starting state at turn one.
3. `window.promisepatchVoiceTimings` is unreadable, or holds fewer than ten turn records.
4. A record's `origin` is not `"spoken"` for a turn that was spoken, or a stray `origin: "none"`
   record appears between turns, so utterances cannot be attributed to the turns that produced
   them.

**Not grounds for voiding, ever:** a slow turn, a refused turn, a misheard turn, an unlucky
recogniser, a noisy room, a `K` below 9, or any reason discovered by looking at the numbers.

**A voided run is still published**, in full, with its records, the condition that voided it, and
the run that replaced it. Nothing is deleted and no run is unpublished. A second run that follows a
voided one is published as the second run it is.

---

## 11. What has not happened

No turn has been recorded. No timing exists. No interval has been computed. There is no `K`, no
`K_progress` and no partial result. The stack was not started, no browser was opened, no microphone
was used, nothing was deployed, no AWS resource was touched, no data was reseeded, no model was
called, and no product code, test or acceptance criterion was changed by this document. Both
holdouts stay sealed.

---

## 12. Gaps reported, not filled

Five, each of which this document declines to solve by inventing something. Gap 1 is narrower
than it was and gap 5 is new; both are Amendment 1's.

**1. Two of the five frozen verbs have no speech path, so ten voice turns cannot cover five
verbs** (amended 2026-09-14; it was three). `confirm` gained one, through the same composer and
the same route, with the words read on the server -- so the ten turns now exercise three verbs
rather than two. `withdraw` is still a control and `status` is still not a turn, each for the
reason §4 gives: ADR-0015 §7 deliberately scoped itself to `confirm` and left `withdraw`'s own
closed list to its own decision, and `status` has nothing to send and no speech-end instant to
measure from. P7.1 §7 specifies voice as *"the same four tools, over the same authenticated
transport"* with *"the same verb-only model boundary"* -- a model choosing the verb from what was
said, which is how P5.3's canonical six-turn conversation reaches `confirm` from *yes, go ahead*
and `status` from *where does that leave us?*. The browser path has no model in it by design
(P7.3 §7 E), so a composer's text goes to the verb whose composer it is; a spoken confirmation is
read by a closed literal rule on the route rather than chosen by anything. Closing either
remaining gap would mean changing product code, which this session may not do, and neither is a
requirement `new_roadmap.md` §G7 states. **Reported here; the ten turns exercise three verbs and
say so.**

**2. P7.3 §11's departures table did not record the voice transport.** It does now -- added by this
work, with the reason from P7.3 §7 E. The verb-coverage consequence above is recorded with it.

**3. The deployed host has no documented on-demand reseed**, so a four-world measurement cannot run
against it (five before Amendment 1), and the measurement P7.1 §7 would prefer -- voice against the deployed loop -- cannot
be taken as this gate is structured. The cost is stated in §7 rather than hidden, and the missing
capability is left as a gap rather than improvised.

**4. The measured window necessarily contains the mandatory transcript review**, because P7.3 §7 D
requires review before send and G7 anchors at speech end. This is not a defect and is not
excusable -- it is what the worker experiences -- but it means the published interval is a property
of the product's honesty requirement as much as of its latency. §6 fixes the operator's conduct in
advance so it cannot be tuned afterwards.

**5. The canonical demo's clarification answer cannot be spoken as written** (new in Amendment 1).
P7.1 §3 step 4 and the manifest's `S01`, `S05`, `S11` and `S12` all write Maya's answer as *just
the raspberries* followed by a dash and *the strawberries came*. Written with a real em dash it
resolves, because an em dash is one of `read_scope`'s clause separators. Written with the
manifest's `--`, or spoken -- which carries no punctuation at all -- it does not: one clause
naming both resources with *came* in it reads as both having arrived, and the case asks the
question again. The three readings were checked on the seeded fixture and are recorded in §4.
This is not fixed here: widening the separator list or reading an unseparated sentence is product
code, and this session changes none. The declared ten use `S04`'s frozen wording instead, which
resolves to the identical `scope_line_ids` and is therefore the same physical claim in words a
worker can say. **The consequence for the demo, stated rather than left to be found: the sentence
the judge contract puts in Maya's mouth at step 4 is one she cannot currently say out loud.**
