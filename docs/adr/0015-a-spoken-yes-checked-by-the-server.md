# ADR-0015 — A spoken yes, checked by the server, with the rule that already exists

Status: accepted
Date: 2026-09-14
Phase: 7

A worker at `PLANNED` could confirm the plan only by pressing a control.
`docs/p7.1-judge-ux-contract.md` §5 asks them to *"read the plan and say yes"*, and
`docs/g7-ten-turn-voice-predeclaration.md` §4 established from the code that `confirm` had no
speech path at all: `startCapture` has one call site, `TurnComposer`, used by `report` and
`clarify` only. This decision gives `confirm` the same spoken path those two have.

**No frozen text fixes confirmation as a button.** §5's `PLANNED` row asks for *"the plan as
rendered, one explicit confirmation, and one withdrawal control"* — one explicit *yes*, for one
plan. It does not say by which control, and its own prose says *say yes*. §7 requires voice to
hold no authority text does not, which is a ceiling and not a floor.

## The question this decides

A spoken confirmation is a **sentence**, and a sentence has to be read before it can be treated as
a yes. Where that reading happens is the whole decision, because the reading is the thing that
turns words into an authorisation.

## Decision

**1. The literal rule is applied on the server, on the route. Never on the client.**

The browser sends the worker's words; the route decides whether they were a yes. It is not done
in TypeScript before sending, for two reasons that are not about tidiness:

* **A sentence a client interpreted would be authorising the plan.** If the browser decided, the
  server would receive an ordinary confirmation and could not tell a spoken yes from a control
  press from a bug. The authority for "this worker agreed" would have moved into a page.
* **It would be a second rule.** A TypeScript copy of a closed word list drifts from the Python
  one — not all at once, and the first divergence would be discovered by somebody confirming
  something they did not agree to.

**2. It is the rule that already exists, imported, not re-implemented.**

`promisepatch.orchestrator.policy.reads_as_worker_confirmation` — the same closed `AFFIRMATIONS`
set the conversational orchestrator has used since
[ADR-0011](0011-conversational-orchestrator-authority.md). *yes*, *go ahead*, *do it* confirm;
*yes but not the strawberries* does not. One implementation, one word list, one behaviour, and a
change to it moves both surfaces at once.

> **Amended 2026-09-17.** At the time of this decision the rule was an opening affirmation plus a
> closed `NEGATIONS` blacklist of words that disqualify a yes anywhere in the turn. That rule was
> unsound and is gone; `AFFIRMATIONS` must now span the **whole** turn, and `NEGATIONS` no longer
> exists. Nothing in this decision changes — the same function, on the server, on the route,
> shared with the orchestrator — and the amendment only narrows what it accepts. It is recorded
> here because this section stated the old rule as fact. See *The rule, exactly* below.

`promisepatch.api` already sits **above** `promisepatch.orchestrator` in the layers contract, so
this import is one the architecture already permits. `policy` is the module whose own contract
says it *"decides without doing"*: no clock, no socket, no client, no provider. A worker's yes is
a function of what the worker said.

**3. The words travel as an optional field, and their absence is the control.**

`ConfirmTurn` gains `text: str | None`, default `None`.

* **Absent** — the explicit confirmation control was pressed. The press *is* the yes; there is no
  sentence to read and none is invented. Behaviour is exactly what it was.
* **Present** — the worker's own words. They must read as a plain yes or the turn is refused.

The screen never fabricates a sentence to fill this field. A control that sent `"yes"` on a
worker's behalf would be a page composing an attestation nobody made, which is the same failure as
acting on a misheard one.

**4. `plan_id` is untouched.**

Still required, still opaque, still the identity the case response rendered, still compared under
the confirming lock by `recovery.confirm_plan` exactly as
[ADR-0010](0010-plan-bound-worker-confirmation.md) fixes. A spoken yes against a plan the case has
moved past is `PLAN_SUPERSEDED`, by the same code path and the same lock as a pressed one. The
literal check is an **additional** gate in front of that one; it removes nothing and relaxes
nothing.

**5. A non-yes confirms nothing and does nothing else.**

`NOT_A_PLAIN_YES`, `409`, *"that was not a plain yes, so nothing was confirmed"*. Refused before
`recovery.confirm_plan` is called, so no command is written, no plan is touched and the case is
exactly as it was. It is **not** re-routed to `clarify`, not stored as an answer, not treated as a
withdrawal and not shown as a question — a surface that quietly did something else with a sentence
it could not read as a yes would be guessing at what a worker meant.

`409` rather than `400` or `422` because every `409` this router returns means the same thing to
the panel and to a listener: *the case is exactly as it was*. That is precisely what a non-yes
leaves behind, and it is already the treatment the refusal path renders and speaks.

**6. Transcript review is unchanged, and it matters most here.**

Capture, shown, editable, discardable, then sent — the composer's existing discipline, reused
without modification. A misheard *yes* cannot be sent unseen, because no path sends anything the
worker has not looked at. This is why the spoken confirmation goes through `TurnComposer` rather
than through a new control: the review step is the composer's, and a second control would be a
second chance to get it wrong.

**7. Scope is `confirm`.**

`withdraw` and `status` are unchanged by this decision. `withdraw` remains a control and `status`
remains a screen and a replay, for the reason `g7-ten-turn-voice-predeclaration.md` §12 records,
and neither gains a spoken path here.

## Consequences

* **A worker can authorise a plan by voice**, through the same composer, the same route, the same
  server-derived actor and the same plan binding, with the reading done where every other decision
  in this product is done.
* **The spoken path produces the same turn-timing anchors as every other spoken turn**, because it
  is the same composer and the same instrumented exit in `queries.ts`. Nothing about the
  instrumentation changed, and no timing was recorded by this decision.
* **The API process now imports `promisepatch.orchestrator`**, which transitively pulls in the MCP
  client SDK and `httpx2`. Stated rather than left to be discovered: it costs import time and
  reads oddly for a package whose point is being a client. It opens no authority path — `policy`
  is values and pure functions — and it violates no contract, because the layers contract already
  places `api` above `orchestrator`. The alternative was moving the word lists into a new leaf
  package, which restructures the module the conversational authority argument rests on for a
  five-word list.
* **The two confirmation affordances give one act.** Pressing the control and saying yes are two
  ways to give the same single explicit confirmation to the same single plan. Neither is a second
  authority.

## The rule, exactly

*(added 2026-09-17, superseding the `AFFIRMATIONS` + `NEGATIONS` description above)*

A turn is a yes when, after case-folding and replacing every non-alphanumeric run with a space,
**every word of it, in order, is spanned by phrases drawn from `AFFIRMATIONS` and nothing else.**
Concatenation is allowed, which is what makes *yeah go ahead* a yes; anything the set does not
contain, appearing anywhere, fails the whole turn.

Two defects made the previous rule unsafe, and an allowlist closes both by construction rather
than by enumeration:

* **A blacklist is only as complete as the last sentence somebody thought of.** *"yes, if the
  customer agrees"* and *"yes, once the oven is fixed"* contained no blacklisted word and
  authorised a plan nobody had authorised.
* **Normalisation destroys the very negations a blacklist looks for.** `don't` becomes `don t`,
  so the blacklisted `dont` was never present to be found and *"yes, don't proceed"* executed
  the plan. Under the allowlist it cannot matter what normalisation makes of an apostrophe:
  whatever tokens come out are not affirmations, so the turn fails as a whole.

The accepted set itself is unchanged and was deliberately **not** widened. *that's right* remains
unreachable for the same normalisation reason and is left that way, so the measurement recorded in
`docs/claims-audit.md` still reproduces.

## Revisit if

* A third surface needs the same rule, at which point the word lists have earned a leaf package of
  their own and the transitive import above stops being worth its cost.
* `withdraw` gains a spoken path. It has its own closed list, `WITHDRAWALS`, matched only at the
  start of a turn, and it would be the same decision made again rather than this one extended.
