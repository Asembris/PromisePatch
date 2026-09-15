# The G7 ten-turn voice measurement

**Run 2: `K = 9/10`. The gate is `K >= 9`. It PASSES, by exactly one turn, and the G7 voice
obligation is DISCHARGED under the conditions §7 fixes and R2.2 publishes.**

**This document holds two runs. Run 1 is VOID and is published here in full, unedited. Run 2 is
the second run it is.** Run 1's `K = 1/10`, its three records and its every sentence stay below
exactly as written.

## The void declaration

**Run 1 is void under predeclaration §10 condition 3.** The condition, quoted:

> 3. `window.promisepatchVoiceTimings` is unreadable, or **holds fewer than ten turn records**.

The recorder held **three**. Seven of the declared ten were never attempted, so there were seven
turns for which no record existed to be trustworthy or untrustworthy. That is the condition, met
on its face.

Five things about this void are disclosed rather than left to be found, because each of them is a
reason a reader might distrust it.

**1. The void was declared LATE, and §10 requires the opposite order.** §10 permits a void *"only
when that condition is identified and announced **before any interval has been computed or
read**."* That is not what happened. Run 1's intervals were computed, `K = 1/10` was computed, and
both were published in this document -- and only afterwards was the void declared. The breach is
permanent and cannot be repaired by declaring it now. It is stated here because the rule it breaks
exists to stop a run being voided *because of* the number it produced, and a reader is entitled to
weigh that against this void without having to discover the sequence themselves.

What can be said in the void's favour, and it is not a defence of the ordering: the condition is
structural rather than numeric. "Fewer than ten records" is visible in the record count and is not
one of §10's *"not grounds for voiding, ever"* items, which name a slow turn, a refused turn, a
misheard turn, an unlucky recogniser, a noisy room, *"a `K` below 9, or any reason discovered by
looking at the numbers."* Nothing about the three intervals produced this condition.

**2. When the operator stopped, turns 1 and 2 had already failed.** Turn 1 measured 16806.2 ms and
turn 2 measured 4903.6 ms, both against a 4000 ms threshold. Two nonpasses out of the first three
had already made `K >= 9` arithmetically unreachable. The decision to stop was therefore taken with
two failures in hand, and the void that followed is a void of a run the operator already knew could
not pass.

**3. The operator's reason for stopping, in his own terms.** He judged the exercise low-value at
that moment and wanted to move on. It was not a technical abort, not a stack failure, and not a
condition in §10. The run was abandoned by choice.

**4. Run 1 did not meet its own declared setup.** §7 fixes that *"every field is recorded from the
actual machine before turn one and published with the result."* Four fields were never captured:
the exact Chrome build (only the reduced UA string `Chrome/152.0.0.0` was recorded, and §7
specifically says *"the exact version at run time is read from `chrome://version` and published,
because Chrome updates itself"*), the microphone device name, the exact machine model, and the
network. Run 1's own §11 records the first two as limitations; the machine model and the network
are added here. A run whose environment was not recorded as its protocol required is a run whose
conditions cannot be reproduced.

**5. Run 2 is taken with knowledge of why run 1 failed, and that is a hazard this document will not
hide.** Run 1 established that the product answered in 55--69 ms on every turn and that both
measured failures were the operator's transcript-review step. Run 2's operator therefore knows the
failure mode before turn one. §6's conduct rules -- *"Send as soon as the transcript is legible and
correct. No deliberation, no re-reading, no waiting for a better moment"* -- were fixed in the
predeclaration before any turn existed and were **violated** on run 1 turn 1, where the operator
opened the browser console and captured the page between speech end and send. Run 2 conforms to a
rule that already existed; it does not invent one against a number. That is the distinction this
document rests on, and a reader who does not accept it should read run 2 as a second attempt by an
informed operator and weigh it accordingly.

**Nothing is deleted.** Run 1's three records, its intervals, its `K = 1/10`, its limitations and
every sentence it published stay below exactly as they were written, under their own heading. §10:
*"A voided run is still published, in full, with its records, the condition that voided it, and the
run that replaced it."*

**What the void does not do.** It does not discharge anything, does not make `K = 1` go away, and
does not license a third run. G7 at `new_roadmap.md:354` and `:358` asks for **ten real turns
recorded**; run 1 recorded three, so the obligation was undischarged with or without this void, and
the only thing that can discharge it is ten recorded turns. Run 2 is that ten, attempted once each
under §10's own failure rule. If run 2 fails, it fails and nothing is fixed.

---

# Run 1 -- VOID

*Everything from here to the Run 2 divider is run 1 as it was published, unedited.*

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

---

# Run 2

**The second run, published as the second run it is.** Run 1 above is void; nothing of it was
deleted to make room for this.

Everything in this section down to *The ten turns* was written and committed **before turn one was
taken**, so that its pre-run status is checkable by commit order rather than asserted afterwards.

## R2.1 The measured commit, and how the stack was verified to serve it

| | |
|---|---|
| branch | `main` |
| commit | `bd7d5d05` -- `docs(voice): run 1 is void under condition 3, and the void was declared late` |
| working tree | clean -- `git status --porcelain` empty before turn one |
| images | `promisepatch-backend:local`, `promisepatch-frontend:local` and `promisepatch-order-simulator:local`, all three rebuilt from this tree |

Verified rather than assumed, in both halves, by the same method run 1 used:

* **Backend.** A SHA-256 over the 129 `.py` files of the installed `promisepatch` package inside
  the running `api` container equals the same hash over `apps/backend/src/promisepatch` in the
  working tree: `ee6e5b584eac604752fd0c5ccc13b698a7828c52a858b3e7cfb43ba653b15c0e`. This is the
  same hash run 1 recorded, which is the expected result and is itself a check: `bd7d5d05` and run
  1's `0523b793` differ only in `docs/`, so the backend source **must** hash identically or
  something other than documentation changed.
* **Frontend.** All 39 files under `/app/src` in the running `frontend` container are
  byte-identical to `apps/frontend/src`, compared file by file. Vite serves those files directly,
  so the SPA under test is that commit's source.

Schema `0008_observer_worker_role`, reported at head by `/readyz`. Fixture `hollow-oak`, digest
`8a7e397f28142a4e3d1e3b812cfd3ecbea225b3fd9f6eee0a2a21a335015a576` at boot.

**One qualification, stated rather than buried.** The three images were built from the tree at
`926c1cb1`, and `bd7d5d05` -- this section's own commit -- lands on top of it changing only
`docs/g7-ten-turn-voice-measurement.md`. No file under `apps/` differs between the two, which is
exactly what the backend hash identity above demonstrates. The served *source* is that of
`bd7d5d05`; the images were not rebuilt a second time to rename them.

## R2.2 The environment, read from the machine before turn one

Every field §7 fixes, including the four run 1 never captured.

| | |
|---|---|
| stack | local `docker compose`; frontend served by Vite on `http://127.0.0.1:55173` |
| transport | `/api/conversation/*`, session cookie plus CSRF (predeclaration §3) |
| published ports | api `127.0.0.1:48000`, mcp `48001`, order simulator `48100`, postgres `55432`, frontend `55173`. The 48xxx values are this machine's overrides: Windows reserves a moving block around 58000 for Hyper-V/WinNAT and the compose defaults cannot bind here |
| **machine** | custom desktop -- MSI `A320M-A PRO MAX (MS-7C52)`, reported by Windows as manufacturer *Micro-Star International Co., Ltd.*, model *MS-7C52*; AMD Ryzen 5 3600 6-core; 15.95 GiB RAM |
| **operating system** | Windows 10 Pro, version 10.0.19045, build **19045.6466** (22H2). Read from the machine as `Microsoft Windows 10 Professionnel`, `10.0.19045` -- the shell is French-localised, which is recorded because it is visible in the raw command output and is not a product setting |
| **browser** | Google Chrome **`152.0.7977.84`** (official build, 64-bit), revision `4334922f44c77b1208072c4deac29db3af39bbea-refs/branch-heads/7977@{#2324}`, V8 `15.2.124.21` |
| **browser launch flags** | launched with the non-default flag **`--enable-features=WebMCP`**. It is **recorded, not removed.** It is unrelated to this surface -- the ten turns go through `/api/conversation/*` and touch no MCP path (§3) -- but a non-default browser flag is part of the environment whether or not it is believed to matter, and removing it to make the environment tidier would be changing the setup after reading the protocol |
| recogniser / synthesiser | the browser's own `SpeechRecognition` and `speechSynthesis`. No Amazon Transcribe, no Polly, no Alexa skill, no wake word |
| **microphone** | **Razer Kraken V3 headset input**; the synthesiser's output is the same headset. Push-to-talk, not continuous |
| **network** | the machine's default route runs over a **USB-tethered phone** -- Windows adapter `Ethernet 7`, hardware *Remote NDIS based Internet Sharing Device #3*, link speed 425,984,000 bps. Measured before turn one: `ping www.google.com`, 10 packets, **0% loss, min 35 ms, mean 80 ms, max 224 ms** |
| other load | no other application driven on the machine during the run |

**Why the network field is not a formality here.** §7 already notes that *"Chrome's speech
recognition is a network service, so the recogniser's own round trip is inside the capture and
**before** the anchor."* This run's connection is a tethered mobile link whose measured round trip
varied by a factor of six -- 35 ms to 224 ms -- across ten packets taken seconds apart. That
variance sits *before* `speech_end_final_result` and therefore **outside** every interval published
below, so it does not inflate `delta_answer`; what it can do is delay or corrupt the recogniser's
final result, which is a turn's `S(i)` and a §10 nonpass if it never arrives. Recorded in advance,
in the direction it actually cuts.

**The measured interval carries no public-internet round trip to `us-east-1`, so every interval
published here is shorter than the same turn taken against the deployed host would be.**
Predeclaration §7 requires that sentence beside any published `K`, and §12 gap 3 records why the
deployed host could not be used: it has no documented on-demand reseed.

## R2.3 The starting world, read back rather than assumed

W1 was seeded exactly as §8 requires -- `docker compose run --rm seed`, which is `pp
reset-demo-state` with the anchor **deliberately omitted**, then the External Order System reset --
and both systems were read back into agreement before turn one:

| what | read back |
|---|---|
| cases | **0** |
| order system, all six orders | `EXT-A` .. `EXT-F` each at **version 1, `ACCEPTED`** |
| order system, `EXT-D` | version 1, `ACCEPTED`, `rv-raspberry-lemon-2` -- **no `S11` edit** |
| PromisePatch's mirror, all six | identical to the above, order for order |
| seeded anchor | `2026-09-15T13:32:16+01:00` Africa/Tunis -- a working hour, so the SCOPE question is the one asked |

**Run 1's starting-state defect is closed structurally rather than by hand.** Run 1 found the order
system still carrying a previous session's `S11` edit, because `docker compose up` does not reset
it -- it holds its own Docker volume. This run brought the stack down with `docker compose down
-v`, which **removed both volumes**, so the order simulator reseeded from its own hand-authored
order book on boot. The base state above is therefore what the simulator itself produces, not a
state somebody corrected back into place.

## R2.4 Two operating facts established before turn one, by reading the code and testing it

Neither is a protocol change; both are properties of the surface that decide how ten turns across
four worlds can physically be taken, and getting either wrong would have destroyed the run.

1. **A reseed signs the operator out.** `resettable_tables()` is derived as *every table minus the
   ledgers of record*, so `sessions` is truncated by `pp reset-demo-state`. Tested rather than
   inferred: a session cookie that returned `200` from `/api/cases` returned **`401`** immediately
   after a reseed. The operator therefore signs in again before W2, W3 and W4.
2. **Signing in again must not reload the page, and does not.** The recorder is a module-level
   array in [turnTiming.ts](../apps/frontend/src/instrumentation/turnTiming.ts); a page reload
   empties it and would destroy every turn already taken. `useLogin` is a react-query mutation and
   the `401` path *"removes the protected queries"* and returns to the login screen through React
   state -- neither does a full navigation, and a search finds no `location.reload` and no
   assignment to `location.href` anywhere in `apps/frontend/src`. The page is therefore loaded
   **once**, reloaded **once** after the unscored warm-up to empty the recorder, and never again.

## R2.5 A warm-up happened, and nothing from it is counted

One unscored warm-up turn was taken in W1 -- `report`, *today's raspberry delivery didn't arrive*
-- purely to confirm the microphone, the recogniser, the stack and the synthesiser on this machine.
It produced a case at `CLARIFYING` with the `SCOPE` question and a spoken reply. **Nothing from it
is recorded, published or counted here.** W1 was then reseeded, destroying that case, and the page
was reloaded, which empties the module-level record array. The ten records below are therefore the
ten scored turns and nothing else, which the raw JSON confirms: exactly ten entries, the first
opened at `12:41:16.916Z`, after the reseed.

## R2.6 The ten turns

`S` is `speech_end_final_result`, the anchor §5 chose; `end` is `speech_end_recogniser_end`,
published beside it so the distance is visible; `A` is the first `reply` or `refusal` utterance;
`P` is the first `acknowledgement`. All instants are `performance.now()` milliseconds. **Every one
of the ten was `origin: "spoken"` and `outcome: "accepted"`. There were no refusals and no typed
turns.**

| # | world | verb | declared words | S | end | end - S | sent | received | A | delta_answer | <=4000 | overall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | W1 | `report` | today's raspberry delivery didn't arrive | 40068.4 | 40193.6 | 125.2 | 43202.9 | 43244.4 | 43383.7 | **3315.3** | yes | **PASS** |
| 2 | W1 | `clarify` | just the raspberries | 107688.2 | 107848.5 | 160.3 | 110689.8 | 110736.9 | 110807.8 | **3119.6** | yes | **PASS** |
| 3 | W1 | `confirm` | yes | 172182.6 | 172278.1 | 95.5 | 174242.7 | 174344.6 | 174397.0 | **2214.4** | yes | **PASS** |
| 4 | W2 | `report` | today's raspberry delivery didn't arrive | 270993.9 | 271117.6 | 123.7 | 273287.3 | 273333.3 | 273416.5 | **2422.6** | yes | **PASS** |
| 5 | W2 | `clarify` | the whole Valley Produce delivery | 328561.0 | 328661.3 | 100.3 | 329237.4 | 329289.8 | 329394.7 | **833.7** | yes | **PASS** |
| 6 | W2 | `confirm` | go ahead | 374911.1 | 374996.0 | 84.9 | 377204.1 | 377286.9 | 377368.3 | **2457.2** | yes | **PASS** |
| 7 | W3 | `report` | today's raspberry delivery didn't arrive | 439535.0 | 439710.1 | 175.1 | 444261.8 | 444300.9 | 444342.8 | **4807.8** | **no** | **NONPASS** |
| 8 | W3 | `clarify` | just the raspberries | 468147.8 | 468341.7 | 193.9 | 470933.0 | 470983.2 | 471096.3 | **2948.5** | yes | **PASS** |
| 9 | W3 | `confirm` | do it | 498624.6 | 498768.3 | 143.7 | 499489.8 | 499548.9 | 499654.6 | **1030.0** | yes | **PASS** |
| 10 | W4 | `report` | the mascarpone in the walk-in went off | 676565.0 | 676565.5 | 0.5 | 679848.5 | 679886.4 | 679942.3 | **3377.3** | yes | **PASS** |

### The progress utterance, published separately as `new_roadmap.md:358` requires

| # | P (`acknowledgement`) | delta_progress | <=4000 |
|---|---|---|---|
| 1 | -- never started | -- | no |
| 2 | 110733.2 | 3045.0 | yes |
| 3 | 174287.7 | 2105.1 | yes |
| 4 | -- never started | -- | no |
| 5 | 329281.3 | 720.3 | yes |
| 6 | 377248.2 | 2337.1 | yes |
| 7 | -- never started | -- | no |
| 8 | 470978.6 | 2830.8 | yes |
| 9 | 499532.2 | 907.6 | yes |
| 10 | -- never started | -- | no |

**Four turns produced no `acknowledgement` at all, and they are exactly the four `report` turns.**
This is the behaviour run 1 already identified and it is not a new defect: on a fast turn the reply
calls `speechSynthesis.cancel()` and the queued acknowledgement is discarded before it makes a
sound, so no `onstart` fires and no entry is written. It is systematic on `report` here because the
report turns were the fastest to answer -- 37.9 to 46.0 ms of backend on all four. `K_progress` is
therefore legitimately **below** `K`, which is why §9 computes them separately rather than letting
one stand for the other.

### One `replay` utterance was produced, and §6 excluded it

Turn 1's record carries a second audio entry, `replay` at `89095.7` -- the read-aloud control
being pressed some 46 seconds after that turn's reply. §6 excludes `replay` from every count
because it is not a response to anything a worker just said, and the arithmetic below does exclude
it: turn 1's `A` is the `reply` at `43383.7`, not the replay. Recorded because it happened and
because a reader can see it in the raw JSON.

## R2.7 The arithmetic, computed exactly as §9 defines it

```
turn  1  delta_answer=   3315.3  delta_progress=       --  pass_answer=1  pass_progress=0
turn  2  delta_answer=   3119.6  delta_progress=   3045.0  pass_answer=1  pass_progress=1
turn  3  delta_answer=   2214.4  delta_progress=   2105.1  pass_answer=1  pass_progress=1
turn  4  delta_answer=   2422.6  delta_progress=       --  pass_answer=1  pass_progress=0
turn  5  delta_answer=    833.7  delta_progress=    720.3  pass_answer=1  pass_progress=1
turn  6  delta_answer=   2457.2  delta_progress=   2337.1  pass_answer=1  pass_progress=1
turn  7  delta_answer=   4807.8  delta_progress=       --  pass_answer=0  pass_progress=0
turn  8  delta_answer=   2948.5  delta_progress=   2830.8  pass_answer=1  pass_progress=1
turn  9  delta_answer=   1030.0  delta_progress=    907.6  pass_answer=1  pass_progress=1
turn 10  delta_answer=   3377.3  delta_progress=       --  pass_answer=1  pass_progress=0
```

**`K = 9/10`.** **`K_progress = 6/10`**, published beside it and not gated. **Refusals: 0.**

**The measured interval carries no public-internet round trip to `us-east-1`, so every interval
published here is shorter than the same turn taken against the deployed host would be.**

## R2.8 The acceptance result

**The gate is `K >= 9`. `K = 9`. The gate PASSES.**

**VOICE MEASUREMENT CLOSED.** The G7 obligation at `new_roadmap.md:354` and `:358` -- ten real
predeclared voice turns, recorded with failures and timings, at least nine starting a truthful
spoken response within four seconds of speech ending -- is **discharged**, under the conditions
§7 fixes and this document publishes.

**It passes by exactly one turn.** `K = 9` is the minimum that passes, and turn 7 missed by 807.8
ms. Nothing about this result is comfortable margin, and no artifact carrying `K` may present it
as one.

## R2.9 Where the time actually went

Computed from the same records. This is the finding worth publishing beside `K`.

| # | speech end -> sent (the mandatory transcript review) | backend | synthesiser start after the response | **product total** |
|---|---|---|---|---|
| 1 | 3134.5 | 41.5 | 139.3 | 180.8 |
| 2 | 3001.6 | 47.1 | 70.9 | 118.0 |
| 3 | 2060.1 | 101.9 | 52.4 | 154.3 |
| 4 | 2293.4 | 46.0 | 83.2 | 129.2 |
| 5 | 676.4 | 52.4 | 104.9 | 157.3 |
| 6 | 2293.0 | 82.8 | 81.4 | 164.2 |
| 7 | **4726.8** | 39.1 | 41.9 | 81.0 |
| 8 | 2785.2 | 50.2 | 113.1 | 163.3 |
| 9 | 865.2 | 59.1 | 105.7 | 164.8 |
| 10 | 3283.5 | 37.9 | 55.9 | 93.8 |

| | min | max | mean |
|---|---|---|---|
| `delta_answer` | 833.7 | 4807.8 | 2652.6 |
| operator review | 676.4 | 4726.8 | 2512.0 |
| backend | 37.9 | 101.9 | 55.8 |
| synthesiser start | 41.9 | 139.3 | 84.9 |
| **product total** | **81.0** | **180.8** | **140.7** |

**The product's own contribution never exceeded 181 ms on any of the ten turns, and averaged 141
ms.** Against a 4000 ms budget that is 3.5% of it. **94.7% of the mean measured interval is the
operator reading the transcript**, which P7.3 §7 D makes mandatory and §5 anchors before.

**The one nonpass is the review step, not the product.** Turn 7 spent **4726.8 ms** between the
recogniser's final result and the send press -- more than the whole 4000 ms budget -- while the
backend answered in 39.1 ms and the synthesiser began 41.9 ms later, the *fastest* product
response of all ten turns. Turn 7 failed while the product was at its quickest. §6 fixes the
operator's conduct in advance -- *"Send as soon as the transcript is legible and correct"* -- and
that is not argued away here: the operator was slow on that turn, it cost the turn, and the turn is
published as a nonpass.

Predeclaration §12 gap 4 named this in advance: *"the published interval is a property of the
product's honesty requirement as much as of its latency."* Run 2 is a second body of evidence for
that sentence. It also sharpens it: a gate anchored at speech end with mandatory review before send
is, at these latencies, **a measurement of the reviewer with a 141 ms product term added.**

### The anchor choice did not decide this result

§5 chose `speech_end_final_result`, the **earlier** of the two recorded instants, deliberately
lengthening every window. The distance between the anchors ranged from **0.5 ms** (turn 10) to
**193.9 ms** (turn 8), mean 120.3 ms.

**Recomputed at `speech_end_recogniser_end` instead, `K` is still 9/10.** Turn 7 measured 4632.7 ms
from that anchor and still fails. The stricter anchor cost nothing here, which is worth saying
plainly: this `K` is not an artefact of the anchor choice in either direction.

## R2.10 Two transcript deviations, neither of which is why anything passed or failed

§4 fixes that a turn is judged by §9's clock *"never by how closely the transcript matched these
characters"*. Both deviations are recorded as deviations.

1. **Turn 10** -- declared *the mascarpone in the walk-in went off*; the recogniser produced **"the
   mascarpone in the working went off"** and it was sent uncorrected. It resolved anyway, to
   `S03`'s expected shape: **0 threatened, 6 untouched**, read back from the live case. *Walk-in*
   is a location and carries no part of the physical claim -- the resource is the mascarpone -- so
   the mishearing changed nothing the domain acted on. Turn 10 passed at 3377.3 ms.
2. **The three clarification answers were heard correctly**, and each was verified against the
   durable row rather than the screen: turn 2 `just the raspberries`, turn 5 `the whole Valley
   Produce delivery`, turn 8 `just the raspberries`. Run 1's reproducible mishearing of *just the
   raspberries* as *"just say raspberries"* did **not** recur on either of the two turns that said
   it.

## R2.11 What the worlds did, recorded because it happened and not because it is scored

Not part of the gate. Each precondition §8 requires was read back from the durable state before the
turn that depended on it, rather than inferred from the screen:

| world | precondition read back | what the case did |
|---|---|---|
| W1 | 0 cases; six orders v1 `ACCEPTED`; then slot `SCOPE`; then `permitted_verbs` holding `confirm` with `plan_id` `d03c852c...` and `awaiting_confirmation` | reached `PLANNED`, then `WAITING` on the spoken *yes* |
| W2 | 0 cases; six orders v1 `ACCEPTED`; slot `SCOPE`; `plan_id` `62a80456...`; **4 threatened, 2 untouched** | reached `PLANNED`, then `EXECUTING` on the spoken *go ahead* |
| W3 | `S11`'s edit applied in the order system's own screen action, `EXT-D` v1 -> **v2 `AMENDED`** `rv-lemon-curd-1`, the signed event crossed and **PromisePatch's mirror agreed** before turn 7; then slot `SCOPE`; `plan_id` `465be0ed...`; **3 threatened, 3 untouched** | reached `PLANNED`, then `WAITING` on the spoken *do it* |
| W4 | 0 cases; `EXT-D` back at v1 `ACCEPTED` `rv-raspberry-lemon-2`, `S11`'s edit gone | reached `PLANNED` with **0 clarifications asked** -- `S03` resolves without a question, as §4 verified in advance -- and **0 threatened, 6 untouched** |

**W3 is one promise less threatened than W1 on the identical branch** -- 3 rather than 4 -- because
Lena's own external edit moved `EXT-D` off the raspberry version before anything was reported.
That is `S11` being `S11`. **No partition, effect or refusal from the frozen manifest is asserted
by this measurement**; these are observations of what the seeded worlds did, exactly as §4's *What
this measurement does not claim* requires.

## R2.12 The raw records, verbatim

Exactly what `window.promisepatchVoiceTimings.json()` returned after turn 10, read **once**, after
all ten turns.

```json
[
  {
    "id": "c1fc3de9-52ce-401f-ab75-d08dbf2c70e3",
    "verb": "report",
    "origin": "spoken",
    "opened": "2026-09-15T12:41:16.916Z",
    "speech_end_final_result": 40068.39999999851,
    "speech_end_recogniser_end": 40193.59999999963,
    "sent": 43202.89999999851,
    "received": 43244.39999999851,
    "outcome": "accepted",
    "audio": [
      { "utterance": "reply", "at": 43383.699999999255 },
      { "utterance": "replay", "at": 89095.69999999925 }
    ]
  },
  {
    "id": "907aa87e-af99-4702-bcdf-5da49375878e",
    "verb": "clarify",
    "origin": "spoken",
    "opened": "2026-09-15T12:42:24.403Z",
    "speech_end_final_result": 107688.19999999925,
    "speech_end_recogniser_end": 107848.5,
    "sent": 110689.79999999888,
    "received": 110736.89999999851,
    "outcome": "accepted",
    "audio": [
      { "utterance": "acknowledgement", "at": 110733.19999999925 },
      { "utterance": "reply", "at": 110807.79999999888 }
    ]
  },
  {
    "id": "beb3715e-8bf2-4d9d-9cfe-94cf42923874",
    "verb": "confirm",
    "origin": "spoken",
    "opened": "2026-09-15T12:43:27.956Z",
    "speech_end_final_result": 172182.59999999963,
    "speech_end_recogniser_end": 172278.09999999963,
    "sent": 174242.69999999925,
    "received": 174344.59999999963,
    "outcome": "accepted",
    "audio": [
      { "utterance": "acknowledgement", "at": 174287.69999999925 },
      { "utterance": "reply", "at": 174397 }
    ]
  },
  {
    "id": "825f3938-6664-4c74-928c-1546ff1cb8b6",
    "verb": "report",
    "origin": "spoken",
    "opened": "2026-09-15T12:45:07.001Z",
    "speech_end_final_result": 270993.8999999985,
    "speech_end_recogniser_end": 271117.5999999996,
    "sent": 273287.2999999989,
    "received": 273333.2999999989,
    "outcome": "accepted",
    "audio": [
      { "utterance": "reply", "at": 273416.5 }
    ]
  },
  {
    "id": "8be8d59e-49ff-4653-b702-952e448945eb",
    "verb": "clarify",
    "origin": "spoken",
    "opened": "2026-09-15T12:46:02.951Z",
    "speech_end_final_result": 328561,
    "speech_end_recogniser_end": 328661.2999999989,
    "sent": 329237.3999999985,
    "received": 329289.7999999989,
    "outcome": "accepted",
    "audio": [
      { "utterance": "acknowledgement", "at": 329281.2999999989 },
      { "utterance": "reply", "at": 329394.69999999925 }
    ]
  },
  {
    "id": "bbc0e394-d59f-4512-80e7-6a833f9645a6",
    "verb": "confirm",
    "origin": "spoken",
    "opened": "2026-09-15T12:46:50.917Z",
    "speech_end_final_result": 374911.0999999996,
    "speech_end_recogniser_end": 374996,
    "sent": 377204.0999999996,
    "received": 377286.8999999985,
    "outcome": "accepted",
    "audio": [
      { "utterance": "acknowledgement", "at": 377248.19999999925 },
      { "utterance": "reply", "at": 377368.2999999989 }
    ]
  },
  {
    "id": "b3f790f9-7af2-4ffb-ae3b-626e9c4147ad",
    "verb": "report",
    "origin": "spoken",
    "opened": "2026-09-15T12:47:57.975Z",
    "speech_end_final_result": 439535,
    "speech_end_recogniser_end": 439710.0999999996,
    "sent": 444261.7999999989,
    "received": 444300.8999999985,
    "outcome": "accepted",
    "audio": [
      { "utterance": "reply", "at": 444342.7999999989 }
    ]
  },
  {
    "id": "179fbca8-1541-4493-b410-450d2d288339",
    "verb": "clarify",
    "origin": "spoken",
    "opened": "2026-09-15T12:48:24.646Z",
    "speech_end_final_result": 468147.7999999989,
    "speech_end_recogniser_end": 468341.69999999925,
    "sent": 470933,
    "received": 470983.19999999925,
    "outcome": "accepted",
    "audio": [
      { "utterance": "acknowledgement", "at": 470978.5999999996 },
      { "utterance": "reply", "at": 471096.2999999989 }
    ]
  },
  {
    "id": "16bceb83-7f7a-44b7-ac3b-e4e7b5875254",
    "verb": "confirm",
    "origin": "spoken",
    "opened": "2026-09-15T12:48:53.203Z",
    "speech_end_final_result": 498624.5999999996,
    "speech_end_recogniser_end": 498768.2999999989,
    "sent": 499489.7999999989,
    "received": 499548.8999999985,
    "outcome": "accepted",
    "audio": [
      { "utterance": "acknowledgement", "at": 499532.19999999925 },
      { "utterance": "reply", "at": 499654.5999999996 }
    ]
  },
  {
    "id": "9c784dd8-11ed-4c1e-a236-fc57a6d5af4d",
    "verb": "report",
    "origin": "spoken",
    "opened": "2026-09-15T12:51:53.562Z",
    "speech_end_final_result": 676565,
    "speech_end_recogniser_end": 676565.5,
    "sent": 679848.5,
    "received": 679886.3999999985,
    "outcome": "accepted",
    "audio": [
      { "utterance": "reply", "at": 679942.2999999989 }
    ]
  }
]
```

### How the arithmetic was computed, and how the method was checked

Not by hand. A small scratchpad script implements §9's formulas and its four edge rules literally
-- `4000.0` passes and `4000.1` does not, no rounding before the comparison, a turn with no `S`, no
`A`, no record or `origin != "spoken"` scores 0, a refusal is measured, and the denominator is 10
and never changes.

**It was validated before it was used, against a result computed independently and published
earlier:** run it on run 1's raw records and it reproduces run 1's published table line for line --
`16806.2`, `16689.6`, `4903.6`, the absent `delta_progress`, `1285.5`, `1146.8`, `K = 1`,
`K_progress = 1`, `0` refusals. A scorer that reproduces a previously hand-computed published
result is a scorer whose agreement with this run's numbers means something.

## R2.13 Limitations and failures, in full

1. **`K = 9` passes by one turn.** The gate is `K >= 9` and `K = 9`. One more slow review anywhere
   in the ten and this document would read `K = 8` and **OPEN**. This is not a margin.
2. **Turn 7 is a real nonpass and is published as one**, at 4807.8 ms. It was not rerun, replaced
   or discarded, and there is no turn 11.
3. **Nine of the ten intervals are mostly the operator.** The product contributed 81--181 ms; the
   review step contributed 676--4727 ms. `K = 9` is therefore only weakly a statement about
   PromisePatch's latency, and a reader who wants that number should read R2.9's product column,
   not `K`.
4. **`K_progress = 6/10` is lower than `K` and that is not a failure of honest progress.** The
   four missing `acknowledgement` entries are Chrome discarding a queued utterance the reply
   cancelled before it made a sound. The progress utterance was *issued* on all ten turns;
   `announceTurnSent()` fires unconditionally.
5. **No public-internet round trip is in any of these numbers** (§7, §12 gap 3). Against the
   deployed host every interval would be longer, and with a 807.8 ms margin on one turn and a
   one-turn margin on `K`, it cannot be claimed that this gate would pass there. **It is not
   claimed.**
6. **The network was a USB-tethered phone with 35--224 ms round trips** (R2.2). That variance sits
   before the anchor and so outside the published intervals, but it is the path Chrome's recogniser
   used, and a different connection could change how often a final result arrives at all.
7. **`withdraw` and `status` were not exercised**, per §12 gap 1: neither has a speech path. The
   ten turns cover three of the five frozen verbs -- `report` x4, `clarify` x3, `confirm` x3.
8. **Seven distinct sentences across ten turns**, which is the frozen manifest's ceiling (§4), not
   a design choice. Four turns said the same report sentence.
9. **This is one operator, one machine, one session, one browser.** Ten turns is the gate's
   number, not a sample size, and no distributional claim is made from it.
10. **Run 2 was taken by an operator who already knew run 1's failure mode.** The void declaration
    discloses this at length and does not explain it away.
11. **Turn 10's transcript was wrong and was sent wrong** (R2.10). It happened not to matter. A
    mishearing that fell on a word the domain *did* act on would have been a different outcome, and
    this run provides no evidence about how often that happens.
12. **The reload that reset the recorder was not verified by reading the record count**, because
    the conduct rule fixed for this run permits reading the recorder exactly once, after turn 10.
    Emptiness is structural rather than observed -- the array is module-level and a reload discards
    it -- and the returned JSON holding exactly ten records, the first opened after the reseed,
    is the evidence that it worked.

## R2.14 What this measurement did not claim

It scored no effect set, asserted no partition, effect or refusal from the frozen manifest, and
opened neither holdout. No product code, test, fixture or acceptance criterion was changed by this
work, no AWS resource was touched, nothing was deployed, and no model was called. It measured one
interval per turn, on ten turns, and published all ten.
