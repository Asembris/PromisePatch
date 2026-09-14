# Bringing spoken replies inside the G7 word budgets

`new_roadmap.md`'s G7 line reads: *"Replies ≤40 words; plan ≤70, shorter where possible."*
`docs/p7.1-judge-ux-contract.md` §7 binds those two numbers to two audible states — the
clarifying question and the plan. `docs/voice-audible-surface-and-timing.md` §7 measured what
`promisepatch.domain.status_view.render` produced against them, found it over, and deliberately
left it: *"It is a later slice's to act on; nothing was changed here."* This is that slice.

The decision is [ADR-0014](adr/0014-two-renderings-one-case.md). This record is the numbers,
before and after, and what was deliberately left long.

**No voice turn has been recorded and no timing is claimed by any of this.** The G7 ten-turn
measurement, its predeclaration and its K/10 are untouched and unstarted. Everything below is a
word count over pure functions: no database, no transport, no clock, no provider, no model call,
`$0`.

## How a word is counted

`len(text.split())` — whitespace-separated tokens, punctuation included, a bare `-` counted. The
same ruler `voice-audible-surface-and-timing.md` §7 used, so its numbers and these are
comparable. `apps/backend/tests/test_spoken_budget.py::words` is the one implementation.

## What was measured before

Reproduced from scratch rather than inherited, and the breach is wider than §7 recorded — §7
counted one band mix, and did not sweep promise counts or case states.

### the canonical six-promise shape, per case state

The frozen manifest's demo shape: four threatened promises across all three authority bands, two
left alone. `render` spends one line of about thirteen words on each promise.

| case state | budget | `render` — before | `render_spoken` — after |
|---|---|---|---|
| `ANALYZED` | 40 | **89** | **37** |
| `PLANNED` | 70 | **94** | **36** |
| `EXECUTING` | 40 | **83** | **29** |
| `REVALIDATING` | 40 | **83** | **29** |
| `RECONCILING` | 40 | **83** | **29** |
| `WAITING` | 40 | **84** | **30** |
| `RESOLVED` | 40 | **77** | **25** |
| `CANCELLED` | 40 | **77** | **25** |

### by promise count

Threatened promises spread across all three bands, plus two left alone. This is the shape of the
problem: the long rendering tracks the promise count, the short one tracks the number of
*distinct postures*, of which there are three here however many promises there are.

| promises | `PLANNED` before | `PLANNED` after | `EXECUTING` before | `EXECUTING` after |
|---|---|---|---|---|
| 1 + 2 | 43 | **26** | 38 | **16** |
| 2 + 2 | 61 | **32** | 54 | **23** |
| 3 + 2 | 79 | **36** | 70 | **29** |
| 4 + 2 | 94 | **36** | 85 | **29** |
| 6 + 2 | 124 | **36** | 111 | **29** |
| 8 + 2 | 154 | **36** | 139 | **29** |
| 12 + 2 | 214 | **36** | 193 | **29** |

`PLANNED` crosses 70 at three threatened promises; `EXECUTING` crosses 40 at two.

### the four case states that carry no promise at all

Intake never reaches `ANALYZED` — `promisepatch.domain.observation` says so in as many words — so
a case has no track until propagation has run. These four were already inside budget and are
unchanged, because with no promise to count the two renderings are the same string.

| case state | before | after |
|---|---|---|
| `RECEIVED` | 10 | 10 |
| `INTERPRETING` | 10 | 10 |
| `CLARIFYING`, with its question and both options | 22 | 22 |
| `NEEDS_HUMAN_INTERPRETATION` | 10 | 10 |

### the conversation replies

| reply | `speech` — before | `spoken` — after |
|---|---|---|
| `render_report_receipt()` | 25 | 25 |
| `render_clarification_receipt()` | 28 | 28 |
| confirmation: applying 1, asking 1, escalated 0 | 35 | **24** |
| confirmation: applying 1, asking 0, escalated 1 | 31 | **20** |
| confirmation: applying 0, asking 1, escalated 1 | 34 | **23** |
| confirmation: applying 2, asking 3, escalated 1 | **41** | **30** |
| withdrawal: four reversals and three applied | **104** | **104** — kept, see below |

## What the short rendering says

The canonical plan, heard in full:

```
Planned, and waiting for you. Nothing has been done yet.
4 planned - waiting for you: 1 covered by a standing preference, 2 needs the customer and 1 needs the owner.
2 promises were left alone.
```

The same case once it is being carried out — 29 words, against 83 for the long one:

```
Carrying out what you confirmed.
2 asked, needs the customer.
1 changing the order now, covered by a standing preference.
1 needs you, needs the owner.
2 promises were left alone.
```

Every promise contributes to a count instead of a line. What is gone is **identity**: which
customer, which order, by when, and why. What is kept is every distinction the truthful
vocabulary carries — the headline, the open question with its options, each promise state present
with its count, each authority band present with its count, the escalation, and the counted
untouched claim. The phrases are the same tables' (`_PROMISE_PHRASE`, `_AUTHORITY_BAND`); this
rendering owns no vocabulary of its own.

## Which surfaces changed

Only the browser's, and only by **addition**. Three browser conversation responses and the case
workspace response gained a sibling `spoken` field; `speech` carries exactly what it carried
before.

| surface | what it shows | what it reads aloud |
|---|---|---|
| case workspace (`GET /api/cases/{id}`) | `speech` — unchanged | `spoken` |
| conversation panel (`report`, `clarify`, `confirm`, `withdraw`) | `speech` — unchanged | `spoken` |
| MCP `status` tool | `speech` — **untouched, schema unchanged** | not a listening surface |

`speakTurnReply` and the panel's read-aloud control now read `spoken`. Both strings are the
backend's: the browser chooses which goes to the screen and which to the loudspeaker, and
composes neither. **Nothing was removed from the workspace** — every band, per-promise line,
reason, deadline, owner and causal row it drew before, it still draws.

The MCP tool is untouched for two reasons. Its result schema is frozen, and its full rendering is
load-bearing evidence: `test_truthful_recovery.py` proves the three word-rules by asserting
`": changed"`, `": asked"` and `"Needs the owner:"` in that exact `speech`, so the per-promise
line *is* the proof that "changed" is not said before the order system agreed.

## What was deliberately kept long

**The withdrawal reply.** `render_withdrawal` reaches 104 words when a withdrawal stood four
things down and could not undo three. Each clause names a distinct consequence class with its own
count, and `docs/bounded-withdrawal.md` fixes that the applied half is never dropped and that the
sentence must never read as an undo. Counting four reversal kinds as "8 things" would drop exactly
the distinction that document exists to protect. It stays long, and `spoken` is byte for byte the
same string as `speech`.

**The clarification question itself.** It is the domain's own question, composed from the
delivery's own rows, and its options are what the answer will be matched against. A truncated
question is a question nobody can answer correctly. The canonical one fits comfortably; a longer
one would be spoken in full rather than clipped.

**The confirmation's counts and its closing certainty.** The only thing the short confirmation
drops is the closing invitation — "ask me for the status to hear what actually happened" — which
is guidance about the conversation rather than a fact about the case. Every count survives, each
band keeps its own wording, and "Nothing has been changed yet." survives, because a listener who
heard only the numbers still has to be told that nothing is done.

**A case holding more distinct postures than the budget has room for.** There is no truncation
anywhere in this change — no ellipsis, no character cap, no trimmed sentence. The spoken
rendering's length is independent of how many promises a case holds and grows only with how many
distinct (state, band) pairs it holds, at most one clause each. A case past that point speaks
longer, because a reply that fits by claiming more than it knows is worse than one that does not
fit. The budgets are proved across every case state, promise counts 1 to 12, and 0 to 6 left
alone; they are not claimed for an adversarial case holding a dozen different postures at once,
and such a case is read out in full rather than shortened into something untrue.

## What pins it

`apps/backend/tests/test_spoken_budget.py`, 461 pure tests, no I/O:

* both budgets across every case headline, promise counts 1–12, and 0/1/2/6 left alone;
* the canonical six-promise shape in each of the eight case states a promise can exist in;
* every branch of the short confirmation, and both receipts;
* that the short plan still separates all three authorities, that `PLANNED`, `REQUESTED` and
  `RECOVERED` stay three different answers, that one escalation among eleven recovered promises is
  still said out loud, and that the untouched count survives at every size;
* that every promise state a case can reach is spoken by name;
* that nothing is truncated — no ellipsis, and every line ends in a full stop or a question mark;
* that the short rendering says nothing the long one does not, and is shorter on the demo shape;
* that the long rendering is unchanged and still names people.

Plus `test_case_workspace.py` (the workspace's `spoken` is the domain's own, differs from
`speech`, and is inside budget), `test_browser_conversation.py` (each turn answers with a `spoken`
inside the reply budget, and a confirmation still says nothing has been changed), and
`apps/frontend/tests/spokenTurns.test.tsx` (the browser reads the short rendering, never the long
one, when the two differ — and still shows the long one).

## What this does not do

No timing was recorded, no K/10 was computed, no voice turn was taken, and the ten predeclared
turns are not written. Nothing was deployed, no AWS resource was touched, no data was reseeded and
no model was called. Both holdouts stay sealed.
