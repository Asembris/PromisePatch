# ADR-0014 — Two renderings of one case: the long one, and the one a worker hears

Status: accepted
Date: 2026-09-14
Phase: 7

G7 requires spoken replies of **≤40 words** and a spoken plan of **≤70**
(`new_roadmap.md`, G7). `docs/voice-audible-surface-and-timing.md` §7 recorded that
`promisepatch.domain.status_view.render` does not meet them and left it for a later slice. This
is that slice. It reopens no frozen decision: the state vocabulary, the authority boundary, the
five tools, the plan identity and the server-derived actor are all untouched.

The measurement was reproduced rather than inherited, and the breach is wider than §7 recorded
because §7 counted one band mix. On the fixture the new budget tests pin, the canonical
six-promise shape is **94 words** at `PLANNED` (budget 70), **83** at `EXECUTING` (budget 40)
and **89** at `ANALYZED`; a twelve-promise case reaches **214**. The overrun is entirely the
**per-promise band** — one line per promise carrying a customer name, an order id, a state
phrase, a deadline and a reason.

## Decision

**1. The short rendering is a new function. `render` is not changed.**

`render_spoken(view)` is added beside `render(view)`. Not a parameter on `render`, not a
rewrite of it: `render`'s exact strings are load-bearing evidence. `test_truthful_recovery.py`
proves the three word-rules by reading the MCP `status` speech and asserting `": changed"`,
`": asked"` and `"Needs the owner:"` — the per-promise line *is* the proof that "changed" is
not said before the order system agreed. `test_case_workspace.py` asserts the workspace's
`speech` is `render(project(status))` byte for byte. A shorter `render` would have meant
editing those, and a test that proves a word rule is not a test to weaken for a word budget.

**2. The short rendering counts what the long one names.**

Every promise in the long rendering contributes one line. In the short one every promise
contributes to a **count**, grouped by its state in the truthful vocabulary and qualified by
the authority band it sits in:

```
Planned, and waiting for you. Nothing has been done yet.
4 planned - waiting for you: 1 covered by a standing preference, 2 needs the customer and 1 needs the owner.
2 promises were left alone.
```

State is the primary axis because the state vocabulary is what the product contract is about,
and because it is the axis the budget question is asked of — `PLANNED` is not `REQUESTED` is
not `RECOVERED`. Authority qualifies it, since at `PLANNED` every threatened promise holds the
same state and the band is the only thing distinguishing what a standing preference covers from
what needs the customer from what needs the owner.

Three sub-rules, each of which removes words without removing a distinction:

* Where every threatened promise shares one band, the band is named **once** as a header rather
  than repeated on each clause. Nothing is lost: they all share it.
* Where a state's own phrase already *is* the band phrase — `AUTHORIZED` is "covered by a
  standing preference", and so is its band — the qualifier is dropped rather than stuttered.
* `LINKED`, `WITHDRAWN` and `UNTOUCHED` take no band qualifier, because `_authority` returns
  `NONE` for them *because of* the state. The band there is derived, not independent.

**3. What is dropped is identity, not certainty.**

Gone from the spoken form: the customer's name, the order's external id, the per-promise
deadline, and the per-promise reason. Kept: the headline sentence, the open question with its
options, every distinct promise state with its count, every authority band with its count, the
escalation, and the counted untouched claim. The screen keeps all of it — this slice removes
nothing from the workspace.

**4. Nothing is truncated. Ever.**

There is no ellipsis, no character cap and no trimmed sentence anywhere in this decision.
Shorter means *composed* shorter by the domain. The length of the spoken rendering is
independent of how many promises a case holds and grows only with how many distinct
(state, band) pairs it holds — at most one clause each. A case holding more distinct postures
than the budget has room for **speaks longer**, because a reply that fits by claiming more than
it knows is worse than one that does not fit.

**5. The surfaces that change are the browser's, and only by addition.**

The three browser conversation responses and the case workspace response gain a sibling
`spoken` field. `speech` keeps exactly what it carries today.

* **The browser reads `spoken` aloud and renders `speech`.** `speakTurnReply` is the one place
  a worker hears a sentence, and it now reads `spoken`. The panel and the workspace keep
  showing `speech`.
* **The MCP `status` tool is not touched.** Its result schema is frozen, its `speech` is the
  full rendering, and that full rendering is the evidence four P5.4 tests read. A conversational
  client reading it is reading a transcript, not listening to one.

Two receipts — `render_report_receipt` (25 words) and `render_clarification_receipt` (28) —
are already inside budget, so their `spoken` is the same string. `render_confirmation` crosses
at 41 in its fullest branch only; `render_confirmation_spoken` drops its closing invitation
("ask me for the status to hear what actually happened"), which is conversational guidance
rather than a fact about the case, and keeps every count and "Nothing has been changed yet."

**6. The withdrawal reply is deliberately left long.**

`render_withdrawal` reaches 104 words when a withdrawal stood four things down and could not
undo three. Every clause names a distinct consequence class with its own count, and
`docs/bounded-withdrawal.md` fixes that the applied half is never dropped and that the sentence
must never read as an undo. Counting four reversal kinds as "8 things" would drop exactly the
distinction that document exists to protect. It stays long, and this is recorded rather than
quietly fixed.

## Consequences

* Two renderings of one case now exist, and both are the backend's. No sentence is composed on
  a client; the browser chooses which of two server-composed strings to speak and to show.
* A wording change to `_PROMISE_PHRASE` or `_AUTHORITY_BAND` now moves both renderings, which is
  the intended coupling: they are two views of one vocabulary, not two vocabularies.
* The budgets are pinned by tests across promise counts and every case headline, so a future
  phrase that grows fails the suite rather than the demo.
* No voice turn has been recorded and no timing is claimed by this decision. The G7 ten-turn
  measurement and its K/10 are untouched and unstarted.

## Revisit if

* The state vocabulary grows a phrase long enough to cross a budget on a realistic shape — the
  pinning tests will say so first.
* A product decision makes the MCP `status` tool a listening surface rather than a reading one,
  at which point it needs `spoken` too and its schema change must be argued on its own.
