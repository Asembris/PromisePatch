# The audible surface, and the clock that will one day be read

*P7.1 §7's audible column, and the instrumentation half of P7.3 §7 D. **No voice turn has been
recorded and no timing is claimed by this slice or by anything in it.***

---

## 1. What this is

Until now every sound this product could make required a person to find a button and press it.
`speakAloud` had exactly **one** call site — the "read this aloud" control in the conversation
panel — so the nine-state voice contract's "the worker hears" column existed on paper and
nowhere else, and the two states whose audible column is a *statement about the turn* rather
than a case sentence had no implementation at all.

A worker holding a crate at six in the morning is the person the voice path exists for. A reply
they have to look at a screen and press a control to hear is a reply they do not get.

Two things are built here, and nothing else:

1. **The audible column of P7.1 §7**, for the five rows that have one.
2. **The timing anchors** P7.3 §7 D names as the half of the voice work that is not the
   measurement — written down, never interpreted.

---

## 2. What the code showed before anything was built

Established by reading it, not assumed, because the whole slice is void if the premise is wrong:

| question | what the code said |
|---|---|
| every call site of `speakAloud` | one — [Conversation.tsx](../apps/frontend/src/features/case/Conversation.tsx)'s `ReadAloud`, inside an `onClick` |
| is any speech produced without a human pressing a control | no — that `onClick` was the only path to the synthesiser |
| is any speech-end or audio-start instant recorded anywhere | no — `performance.now`, `Date.now` and `onstart` appeared nowhere in `apps/frontend/src` |
| which §7 rows have an audible expectation, and which were satisfied | five: `processing`, `clarifying`, `confirming`, `waiting`, `unavailable`. Three (`clarifying`, `confirming`, `waiting`) were *reachable* through the manual control and automatic in none; `processing` and `unavailable` had no audible surface whatsoever |

The other four rows — `idle`, `listening`, `captured`, `correcting` — have "nothing" in the
audible column, and they still do. See §5.

---

## 3. What was built, and the row each item discharges

### 3.1 The backend's sentence, spoken on turn resolution — `clarifying`, `confirming`, `waiting`

Every accepted turn now reads its own answer aloud, unprompted, as it resolves: the `speech` the
backend returned, **byte for byte**. There is no summary step, no truncation, no first-sentence
trim and no wording composed on the client — `speakTurnReply` takes a string and is structurally
incapable of altering it, exactly as the screen rendering is.

All three of these rows are the same mechanism, because they are the same string: which of them a
worker is in decides what `status_view` renders, and this surface neither knows nor cares.

Four turns speak — `report`, `clarify`, `confirm`, `withdraw`. The report receipt is spoken
before the case it opened is on screen, because it is that turn's answer.

The manual control remains, and its job changed: it is now **stop and replay** — interrupt what
is being said, or hear the standing status again without taking a turn to get it. It also now
tells the truth about itself when an utterance ends, which it previously could not.

### 3.2 The acknowledgement while a turn is in flight — `processing`

One fixed phrase, spoken the instant a turn is sent:

> **"Working on that turn now."**

About the turn, never about a case. Five words, no digit, and none of the thirty-nine outcome
words `semantic/jobs.py`'s `CLAIM_WORDS` bans — the same bar the model's own conversational glue
is held to, because a sentence a screen composed is no more trustworthy than one a model
composed. It is fixed rather than composed per turn: a fixed phrase cannot accidentally report a
result, and a phrase assembled from case state eventually would.

It is cancelled mid-word the moment a real answer exists, rather than queued in front of it.

### 3.3 That a refused turn did not happen — `unavailable`

> **"That turn did not happen. The case is exactly as it was."**

Both clauses are true by construction. It deliberately does **not** read the backend's refusal
message aloud: that message explains why one turn was declined and is not a description of the
case. The message stays on the screen, unchanged, beside it.

### 3.4 The timing anchors — P7.3 §7 D, the instrumentation half

[turnTiming.ts](../apps/frontend/src/instrumentation/turnTiming.ts) records, per turn:

| anchor | source |
|---|---|
| `speech_end_final_result` | the recogniser's **last** final-result event |
| `speech_end_recogniser_end` | the recogniser's `onend` |
| `sent` | immediately before the request is issued |
| `received` | when the answer arrived — **a refusal is a response and is timed like one** |
| `audio[]` | `SpeechSynthesisUtterance.onstart`, one entry per utterance, each labelled |

Four decisions in that table are the whole point of it:

- **Speech end is recorded twice and neither is chosen.** Which instant G7's "speech ending"
  means is not declared in any frozen document. A recorder that picked would be quietly deciding
  the denominator of a published number. Both readings are kept under their own names; whoever
  measures picks in the open and can see how far apart they were.
- **First audio is the utterance's, not the call's.** `speechSynthesis.speak` returns as soon as
  the utterance is queued, which on a cold voice list is well before any sound exists. The return
  of `speak` is never recorded as though it were when a worker started hearing something.
- **Each utterance carries its kind** — `acknowledgement`, `reply`, `refusal`, `replay`. The gate
  counts an honest-progress reply separately from a completed answer, and a recorder that wrote
  one "first audio" field would have made that impossible after the fact.
- **A turn cannot inherit an earlier turn's anchors.** A typed turn carries none and says
  `origin: "typed"`, rather than borrowing a spoken turn's and looking fast.

Readings are `performance.now()` — monotonic, unaffected by a clock correction mid-turn — with
one wall-clock stamp per record so a session can be placed in time. The send and receive instants
are taken in `queries.ts` rather than at the four buttons, because that is the one place every
turn actually leaves the browser; an anchor added per button is an anchor somebody eventually
forgets, and the first one forgotten would be discovered as a hole in a number already published.

Records are readable out of a real browser session at `window.promisepatchVoiceTimings` —
`.records()` and `.json()`, readers only, published once from `main.tsx`.

**It computes nothing.** No duration, no comparison, no threshold, no verdict. A test asserts the
complete field list of a record precisely so that a measurement cannot be smuggled in as a field.

---

## 4. What this deliberately does not do

- **It takes no measurement.** No turn was run, no timing was recorded, no K/10 exists, and
  nothing here should be read as evidence about latency. The G7 gate — ten predeclared turns, at
  least nine starting a truthful spoken response within four seconds of speech ending — is a
  later slice's, and the ten predeclared turns are not authored here.
- **It speaks nothing at capture end.** The `captured` row's audible column is "nothing", and it
  stays nothing. The worker has not had an answer yet, and acknowledging a microphone is not a
  response to a turn — it would be the product talking about itself at the one moment a person is
  waiting to hear about their case.
- **It speaks nothing on arrival.** Opening a case is not a question anybody asked.
- **It does not change transcript review.** Capture → shown → editable → discardable → then sent,
  exactly as before.
- **It does not touch the authority boundary.** No route, request field, server-derived actor or
  `plan_id` binding changed. Nothing audible reaches a write, and the speaking happens strictly
  after the domain has already decided.
- **It amends no frozen document.** Every item is a row that was already specified.
- **No backend code changed, nothing was deployed, no AWS resource was touched and no model was
  called.**

---

## 5. The four silent rows, and why silence is the implementation

`idle`, `listening`, `captured` and `correcting` have "nothing" in P7.1 §7's audible column, and
they are silent. That is not an omission to be closed later — it is the row. Two tests assert it
directly, because the natural instinct when building an audible surface is to make the microphone
chirp, and that instinct would break the contract at exactly the state where a transcript is
sitting unsent in front of a worker.

---

## 6. What was proved

36 new frontend tests, in two files; 274 pass across the whole suite.

[turnTiming.test.ts](../apps/frontend/tests/turnTiming.test.ts) — 17 tests over the recorder as a
pure module: both anchors kept separately with no field naming a winner; the last final result is
the one kept; a recogniser end with no final result; a new capture not inheriting an abandoned
one's anchors; a typed turn carrying none and saying so; a typed turn not borrowing the spoken
turn before it; the send stamped before the response; a refusal timed as a response; a response
belonging to no turn ignored rather than invented; acknowledgement and reply kept as separate
utterances; a replay with no turn getting its own record; the complete field list containing no
measurement; no case, promise, worker or sentence held; a handed-out copy that cannot edit the
session's history; and a published handle that exposes readers only.

[spokenTurns.test.tsx](../apps/frontend/tests/spokenTurns.test.tsx) — 19 tests through the real
panels against a driveable synthesiser and recogniser: the answer spoken with nobody pressing
anything; spoken byte for byte; a confirmation's answer; a report's receipt; **silence on
arrival**; the acknowledgement spoken while the backend still holds the turn, and replaced rather
than queued; the acknowledgement's vocabulary against `CLAIM_WORDS`; a refused turn saying it did
not happen; the backend's refusal message shown but not spoken; no case sentence spoken for a
refused turn; **silence at capture end**, with the transcript on screen and nothing sent; replay
without taking a turn; stop reporting correctly about itself; first audio recorded at `onstart`
and **not** when two utterances were merely queued; both speech-end anchors plus both transport
instants written for a spoken turn; and a refused turn timed rather than dropped.

Gates: frontend `tsc` clean, `eslint` clean, `vitest` 274/274. `ruff check`, `ruff format
--check`, `mypy` in all three groups and `lint-imports` (29 contracts kept) all green. The
database-backed backend suite was not re-run: no Python file changed, and the repository's own
`fast-validate` rule is explicit that a frontend change validates as typecheck, lint and vitest.
CI remains the broad regression authority.

---

## 7. A finding, reported and not fixed

G7 requires spoken replies of **≤40 words** and a plan of **≤70**. What `status_view` renders
today was counted against those budgets. It is a later slice's to act on; nothing was changed
here.

| rendering | words | budget | |
|---|---|---|---|
| `render_report_receipt()` | 25 | 40 | ok |
| `render_clarification_receipt()` | 28 | 40 | ok |
| `render_confirmation(...)`, already confirmed | 25 | 40 | ok |
| `render_confirmation(...)`, all three bands non-zero | **41** | 40 | **over by 1** |
| `render(view)` — `RECEIVED` | 10 | 40 | ok |
| `render(view)` — `CLARIFYING` with its question and options | 22 | 40 | ok |
| `render(view)` — `PLANNED`, 1 promise | 36 | 70 | ok |
| `render(view)` — `PLANNED`, canonical six-promise shape | **90** | 70 | **over by 20** |
| `render(view)` — `EXECUTING`, 3 threatened + 1 untouched | **60** | 40 | **over by 20** |

Where each one crosses:

- **`render_confirmation`** exceeds 40 only in its fullest branch — applying *and* awaiting
  approval *and* escalated all non-zero, which is 41 words. Every other combination is 16–35. The
  count of orders does not change the word count; the number of *bands* does.
- **`render(PLANNED)`** crosses 70 at **3 threatened + 2 untouched (73)**, and at 4 threatened
  with no untouched (75). One promise costs about 13 words. The canonical demo shape — 4
  threatened, 2 untouched — is 90.
- **`render(EXECUTING)`** crosses 40 at **2 promises (42)**; one promise is 30.

The shape of the breach matters more than the numbers: the fixed sentences are all comfortably
inside budget, and every overrun is the **per-promise band** — one line per promise, each about
twelve or thirteen words, read out in full. A case with more than two or three promises cannot
satisfy the budget without something deciding what not to say aloud, and *what a screen or a
speaker may omit* is a contract question rather than a wording one. It is recorded here and left
open deliberately.
