# The G7 ten-turn voice measurement

**This document holds two runs. Run 1 is VOID and is published here in full, unedited. Run 2 is
the second run it is.**

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
| **network** | the machine's default route runs over a **USB-tethered phone** -- Windows adapter `Ethernet 7`, hardware *Remote NDIS based Internet Sharing Device #3*, link speed 425,984,000 bps, address `192.168.251.195` via gateway `192.168.251.175`. Measured before turn one: `ping www.google.com`, 10 packets, **0% loss, min 35 ms, mean 80 ms, max 224 ms** |
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
