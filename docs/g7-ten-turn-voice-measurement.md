# The G7 ten-turn voice measurement

**`K = 1/10`. The gate is `K >= 9`. It was not met, and the G7 voice obligation stays OPEN.**

**Three of the declared ten turns were taken. Seven were never attempted** -- the run was stopped
deliberately after turn 3, once two nonpasses had made the gate arithmetically unreachable. Those
seven score `pass_answer = 0` under §9's own rule, which says a turn with no record did not start a
truthful spoken response within four seconds of speech ending as far as anybody can show. The
denominator is 10 and does not change.

Nothing here was rerun, replaced, discarded or re-anchored. No product code, test or acceptance
criterion was changed by this work, and no AWS resource was touched.

## 1. The requirement

`new_roadmap.md:354` and `:358`, quoted in full in
[the predeclaration](g7-ten-turn-voice-predeclaration.md) §1: ten real predeclared voice turns,
recorded with failures and timings, at least nine starting a truthful spoken response within four
seconds of speech ending; `K/10` published with honest-progress replies identified separately.

## 2. What fixed the method, and when

[docs/g7-ten-turn-voice-predeclaration.md](g7-ten-turn-voice-predeclaration.md), written in
`a161051` and **amended once in `d2da355`** on 2026-09-14, while no measured turn existed. **The
amended ten were run**, not the superseded ten. Nothing in the protocol was changed by this
session, and no turn had been taken when it was read.

## 3. The measured commit, and how the stack was verified to serve it

| | |
|---|---|
| branch | `main` |
| commit | `0523b7938172526a65a1bdfe83dbc0092cea768a` |
| working tree | clean -- `git status --porcelain` empty before turn one |
| images | `promisepatch-backend:local` and `promisepatch-frontend:local`, both rebuilt from this tree |

Verified rather than assumed, in both halves:

* **Backend.** A SHA-256 over the 129 `.py` files of the installed `promisepatch` package inside
  the running `api` container equals the same hash over `apps/backend/src/promisepatch` in the
  working tree: `ee6e5b584eac604752fd0c5ccc13b698a7828c52a858b3e7cfb43ba653b15c0e`.
* **Frontend.** All 39 files under `/app/src` in the running `frontend` container are
  byte-identical to `apps/frontend/src`, compared file by file. Vite serves those files directly,
  so the SPA under test is that commit's source.

Schema `0008_observer_worker_role`, reported at head by `/readyz`. Fixture `hollow-oak`.

## 4. The environment, read from the machine

| | |
|---|---|
| stack | local `docker compose`; frontend served by Vite on `http://127.0.0.1:55173` |
| transport | `/api/conversation/*`, session cookie plus CSRF (predeclaration §3) |
| machine | Windows 10 Pro 19045 |
| browser | Google Chrome, reduced UA string `Chrome/152.0.0.0`; the exact build was not captured |
| `navigator.language` | `en-TN` -- the recogniser's language is taken from this |
| recogniser / synthesiser | the browser's own `SpeechRecognition` and `speechSynthesis`; 22 voices loaded. No Transcribe, no Polly, no Alexa skill, no wake word |
| microphone | the machine's own input device; push-to-talk. Its device name was not captured |
| other load | no other application driven during the run; one unrelated browser extension logged errors of its own |

**The measured interval carries no public-internet round trip to `us-east-1`, so every interval
published here is shorter than the same turn taken against the deployed host would be.**
Predeclaration §7 requires that sentence beside any published `K`, and §12 gap 3 records why the
deployed host could not be used: it has no documented on-demand reseed.

## 5. A rehearsal happened, and nothing from it is counted

One unscored rehearsal of world W1 was walked through first -- `report`, `clarify`, `confirm`.
**Nothing from it is recorded, published or counted here.** The page was then reloaded, which
empties the module-level record array the instrumentation keeps, and the world was reseeded;
`window.promisepatchVoiceTimings.records().length` was read as **`0`** before turn one.

Three things the rehearsal established, each of which changed how the scored run was operated:

1. **The `reply` utterance fires reliably on this machine.** Every rehearsal record carried an
   `at` for it, so Chrome's `speechSynthesis.cancel()`-then-`speak()` is not swallowing the
   backend's answer, and the §6 gate is measurable here.
2. **It is the `acknowledgement` that gets swallowed**, not the reply: on a fast turn the reply
   cancels it before it makes a sound and no `acknowledgement` entry is written at all.
   `K_progress` can therefore sit legitimately below `K`, and §9 already handles it. This was then
   observed again in the scored run, on turn 2.
3. A confirmation taken through the text box records `origin: "typed"` and no anchors, which §9
   scores 0. All three scored turns were spoken and all three carry `origin: "spoken"`.

## 6. The seeding

W1 was seeded exactly as §8 requires, and the state was read back rather than assumed: `pp
reset-demo-state` with the anchor deliberately omitted, then the External Order System reset, in
that order. Before turn one: **0 cases**, order system `EXT-D` at version 1 `ACCEPTED`
`rv-raspberry-lemon-2`, and PromisePatch's mirror agreeing.

**One defect in the starting state was found and fixed before turn one.** The order system was
still carrying a previous session's `S11` edit -- `EXT-D` at version 2, `AMENDED`,
`rv-lemon-curd-1` -- because `docker compose up` does not reset it; it holds its own volume. W1,
W2 and W4 each stipulate *"the base Hollow Oak world, unmodified"*, so this would have seeded three
of the four worlds with an edit none of them names. It was reset and both systems were read back
into agreement.

## 7. The ten turns

`S` is `speech_end_final_result`, the anchor §5 chose; `end` is `speech_end_recogniser_end`,
published beside it so the distance is visible; `A` is the first `reply` or `refusal` utterance;
`P` is the first `acknowledgement`. All instants are `performance.now()` milliseconds. Every turn
taken was `origin: "spoken"` and `outcome: "accepted"`; there were no refusals.

| # | world | verb | declared words | transcript sent | S | end | sent | received | audio | delta_answer | <=4000 | overall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | W1 | `report` | today's raspberry delivery didn't arrive | today's raspberry delivery didn't arrive | 62421.9 | 62583.4 | 79068.1 | 79123.1 | ack 79111.5; reply 79228.1 | **16806.2** | FAIL | **NONPASS** |
| 2 | W1 | `clarify` | just the raspberries | just say raspberries | 222926.0 | 223084.7 | 227677.7 | 227736.3 | reply 227829.6 | **4903.6** | FAIL | **NONPASS** |
| 3 | W1 | `confirm` | yes | yes | 301179.0 | 301327.3 | 302268.1 | 302337.3 | ack 302325.8; reply 302464.5 | **1285.5** | PASS | **PASS** |
| 4 | W2 | `report` | today's raspberry delivery didn't arrive | -- | -- | -- | -- | -- | -- | -- | FAIL | **NOT ATTEMPTED** |
| 5 | W2 | `clarify` | the whole Valley Produce delivery | -- | -- | -- | -- | -- | -- | -- | FAIL | **NOT ATTEMPTED** |
| 6 | W2 | `confirm` | go ahead | -- | -- | -- | -- | -- | -- | -- | FAIL | **NOT ATTEMPTED** |
| 7 | W3 | `report` | today's raspberry delivery didn't arrive | -- | -- | -- | -- | -- | -- | -- | FAIL | **NOT ATTEMPTED** |
| 8 | W3 | `clarify` | just the raspberries | -- | -- | -- | -- | -- | -- | -- | FAIL | **NOT ATTEMPTED** |
| 9 | W3 | `confirm` | do it | -- | -- | -- | -- | -- | -- | -- | FAIL | **NOT ATTEMPTED** |
| 10 | W4 | `report` | the mascarpone in the walk-in went off | -- | -- | -- | -- | -- | -- | -- | FAIL | **NOT ATTEMPTED** |

### Turn ids and spoken responses

| # | turn id | opened | the spoken response, which is the backend's own sentence delivered unchanged |
|---|---|---|---|
| 1 | `7135dbac-a8f0-45f4-b9df-5c400b1d2a08` | `2026-09-15T10:24:29.331Z` | the scope question and its two options |
| 2 | `10278aad-2be2-4349-8eb0-c7997c5b33d9` | `2026-09-15T10:26:57.940Z` | *"Got it, and I have written that down exactly as you said it. Nothing has changed yet..."* |
| 3 | `989a078e-00be-4242-9aa3-6770a31e4a00` | `2026-09-15T10:28:12.531Z` | *"Confirmed: 1 order covered by a standing preference, 1 order where I still have to ask the customer and 2 orders that need the owner. Nothing has been changed yet..."* |

**All three responses were truthful.** Each `reply` utterance is `status_view`'s rendering read out
by `speakTurnReply`, which cannot alter it. None of the three is a nonpass on truthfulness; every
nonpass in this run is an interval, and seven of them are an absence of a turn.

### Where the time actually went

Computed from the same records, and this is the finding the run is worth publishing for:

| # | speech end -> sent (the operator's mandatory transcript review) | backend | synthesiser start after the response |
|---|---|---|---|
| 1 | **16646.2 ms** | 55.0 ms | 105.0 ms |
| 2 | **4751.7 ms** | 58.6 ms | 93.3 ms |
| 3 | 1089.1 ms | 69.2 ms | 127.2 ms |

**The product's own contribution is 150-200 ms on every one of the three turns.** Both measured
failures are entirely the human review step that P7.3 §7 D makes mandatory and that §5 anchors
before. On turn 1 the operator opened the browser console and captured the page before pressing
send; on turn 2 the delay was smaller but still four and a half seconds. §6 fixes the operator's
conduct in advance -- *"Send as soon as the transcript is legible and correct"* -- precisely so
this cannot be argued away after a number exists, and it is not argued away here. Turn 3, operated
as §6 requires, measured **1285.5 ms**.

Predeclaration §12 gap 4 named this in advance: *"the published interval is a property of the
product's honesty requirement as much as of its latency."* This run is evidence for that sentence
rather than a refutation of it.

### The transcript deviation on turn 2

The recogniser produced **"just say raspberries"** for *just the raspberries*, and it was sent
uncorrected. It still resolved to the restricted scope -- `cl-vp-today-raspberries` `NOT_RECEIVED`,
`cl-vp-today-strawberries` `RECEIVED` -- which is the same physical claim the declared wording
makes. §4 fixes that a turn is judged by §9's clock *"never by how closely the transcript matched
these characters"*, so this is recorded as a deviation and is not the reason turn 2 failed; its
interval is. The rehearsal had already shown this recogniser renders the phrase as *"Justin
raspberries"*, so the mishearing is reproducible rather than a one-off.

### What the confirmed case did

Not part of the gate, and recorded because it happened: after turn 3, W1's case ran to `EXT-A`
**RECOVERED**, `EXT-B` **REQUESTED**, `EXT-C` and `EXT-D` **ESCALATED** to the owner by hand, and
`EXT-E` and `EXT-F` **UNTOUCHED** with **0 incident-caused operational effects**.

## 8. The raw records, verbatim

Exactly what `window.promisepatchVoiceTimings.json()` returned after turn 3.

```json
[
  {
    "id": "7135dbac-a8f0-45f4-b9df-5c400b1d2a08",
    "verb": "report",
    "origin": "spoken",
    "opened": "2026-09-15T10:24:29.331Z",
    "speech_end_final_result": 62421.90000000037,
    "speech_end_recogniser_end": 62583.40000000037,
    "sent": 79068.10000000056,
    "received": 79123.10000000056,
    "outcome": "accepted",
    "audio": [
      { "utterance": "acknowledgement", "at": 79111.5 },
      { "utterance": "reply", "at": 79228.10000000056 }
    ]
  },
  {
    "id": "10278aad-2be2-4349-8eb0-c7997c5b33d9",
    "verb": "clarify",
    "origin": "spoken",
    "opened": "2026-09-15T10:26:57.940Z",
    "speech_end_final_result": 222926,
    "speech_end_recogniser_end": 223084.7000000002,
    "sent": 227677.7000000002,
    "received": 227736.2999999998,
    "outcome": "accepted",
    "audio": [
      { "utterance": "reply", "at": 227829.60000000056 }
    ]
  },
  {
    "id": "989a078e-00be-4242-9aa3-6770a31e4a00",
    "verb": "confirm",
    "origin": "spoken",
    "opened": "2026-09-15T10:28:12.531Z",
    "speech_end_final_result": 301179,
    "speech_end_recogniser_end": 301327.2999999998,
    "sent": 302268.10000000056,
    "received": 302337.2999999998,
    "outcome": "accepted",
    "audio": [
      { "utterance": "acknowledgement", "at": 302325.7999999998 },
      { "utterance": "reply", "at": 302464.5 }
    ]
  }
]
```

## 9. The arithmetic, computed exactly as §9 defines it

```
turn  1  delta_answer=  16806.2  delta_progress=  16689.6  pass_answer=0  pass_progress=0
turn  2  delta_answer=   4903.6  delta_progress=       --  pass_answer=0  pass_progress=0
turn  3  delta_answer=   1285.5  delta_progress=   1146.8  pass_answer=1  pass_progress=1
turn  4  delta_answer=       --  delta_progress=       --  pass_answer=0  pass_progress=0   no record
turn  5  delta_answer=       --  delta_progress=       --  pass_answer=0  pass_progress=0   no record
turn  6  delta_answer=       --  delta_progress=       --  pass_answer=0  pass_progress=0   no record
turn  7  delta_answer=       --  delta_progress=       --  pass_answer=0  pass_progress=0   no record
turn  8  delta_answer=       --  delta_progress=       --  pass_answer=0  pass_progress=0   no record
turn  9  delta_answer=       --  delta_progress=       --  pass_answer=0  pass_progress=0   no record
turn 10  delta_answer=       --  delta_progress=       --  pass_answer=0  pass_progress=0   no record
```

**`K = 1/10`.** **`K_progress = 1/10`**, published beside it and not gated. **Refusals: 0.**

Turn 2 has a `delta_answer` and no `delta_progress` because its `acknowledgement` never started
making sound -- the reply cancelled it first. That is the behaviour the rehearsal predicted, and it
is why the two numbers are computed separately rather than one standing in for the other.

## 10. The acceptance result

**The gate is `K >= 9`. `K = 1`. The gate FAILS.**

**VOICE MEASUREMENT OPEN.** The G7 obligation at `new_roadmap.md:354` and `:358` is **not**
discharged. Nothing was fixed, changed or tuned in response to this result, and no turn was rerun.

## 11. Limitations and failures, in full

1. **Seven of the ten turns were never attempted.** The run was stopped after turn 3. They are
   scored 0 rather than excused, and the denominator stays 10 -- but this is a three-turn
   observation reported against a ten-turn gate, and it must not be read as a ten-turn measurement
   that happened to score 1.
2. **Two of the three measured failures are the operator, not the product.** The backend answered
   in 55-69 ms on every turn and the synthesiser began 93-127 ms later. A protocol that anchors at
   speech end and mandates transcript review before send measures the reviewer, and §12 gap 4 said
   so before any number existed.
3. **No conclusion about the product's latency may be drawn from `K = 1`.** Three turns is not a
   sample, and the one turn operated as §6 requires measured 1285.5 ms. Equally, no conclusion that
   the product *would* pass may be drawn from that one turn.
4. **No public-internet round trip is in any of these numbers** (§7, §12 gap 3).
5. **The exact Chrome build and the microphone device name were not captured** before turn one, as
   §7 requires. Only the reduced UA string `Chrome/152.0.0.0` was recorded.
6. **`withdraw` and `status` were not exercised**, per §12 gap 1: neither has a speech path. The
   three turns taken cover `report`, `clarify` and `confirm` -- one of each, by accident of where
   the run stopped.
7. **W2, W3 and W4 were never used.** `S11`'s pre-incident external edit was never applied, and the
   whole-delivery branch and `S03`'s no-question report were never spoken.
8. **The rehearsal was W1 only.** W2, W3 and W4 were not rehearsed.

## 12. What this measurement did not claim

It scored no effect set, asserted no partition, effect or refusal from the frozen manifest, and
opened neither holdout. It measured one interval per turn on three turns, and reported that
nothing was measured on seven.
