# ADR-0010 — Plan-bound worker confirmation, and the two conversational tools that reach it

Status: accepted
Date: 2026-09-10
Phase: 5

Records the decisions P5.2 had to make to add `clarify` and `confirm` to the transport spine
[ADR-0009](0009-mcp-transport-spine.md) established. It does not reopen that ADR; §5 of it
already said these two tools were the next slice. The rules they have to satisfy are in the
[P5 product contract](../p5-product-contract.md).

## Decision

**1. A confirmation is bound to a plan, not to a case.**

`recovery.confirm_plan` now takes a required `plan_id`: the identity of the plan the worker
was shown. It is checked, under the same lock the confirmation is written with, against the
plan the case is currently offering. A confirmation quoting a superseded plan is refused and
nothing about the case changes.

Before this, a confirmation named a case, and a case is not a plan. Between reading and saying
yes, a track can be re-planned against changed stock, a promise can join or leave the untouched
band, or another case can take one over — and a yes that landed on whatever was there would be
authorising recoveries nobody read out. Since worker confirmation is the one authority in the
whole conversational surface that belongs to a person rather than to the engine's bookkeeping,
what it is attached to is the whole of what it is worth.

**2. That identity is derived, opaque, and never stored.**

A SHA-256 digest over the case id, the case version and every track — untouched ones included
— reduced to what band 3 of the workspace shows: state, classification, chosen option, the
version that option would write, and the fingerprint planning watches. Sorted by track id, so
it does not depend on which query produced the rows.

*Derived*, because a stored `plan_id` column would be a second answer to "what plan is this",
and the two would eventually disagree with nothing to say which was right. A mismatch has to
mean the rows moved, not that a cache went stale.

*Over the whole case*, because "these three change and these three do not" is the claim the
worker is agreeing to. A promise that quietly left the untouched band has changed the
agreement.

*Opaque*, because a caller must be able to quote a plan and unable to describe one. There is
no tool argument naming a track, an option or a recipe version, so a confirmation cannot be
assembled — only quoted back.

Including the case version makes it fail closed on **any** committed change to the case, not
only on the ones the digest would otherwise notice. Re-reading the status is one turn; a yes to
something nobody saw is not recoverable.

**3. `status` carries the question and the plan identity, so a surface never invents either.**

`CaseStatus` gains the open clarification and the plan identity; `status_view` projects both
and renders the question into the spoken status. A surface told only "waiting for your answer"
has to reconstruct what was asked, and the only material it has is the original sentence —
which is exactly the invention the clarification protocol exists to prevent. The plan identity
is present **only** while a plan is actually on offer (`PLANNED`), because handing one over on
any other state would invite a confirmation of something nobody is being asked about.

**4. The new speech is rendered in the domain and delivered as given.**

Both new tools return a `speech` produced by `status_view` — the module that owns the truthful
vocabulary — rather than composed in the transport. Confirmation is precisely where language
outruns reality, so the sentence that reports it is written beside the table that says
`AUTHORIZED` is a permission and `RECOVERED` is an observation, and is covered by that module's
purity contract. `report`'s fixed sentence stays where P5.1 put it; it contains no state.

**5. The refusal vocabulary is not extended.**

A superseded plan is `PLAN_SUPERSEDED` at the intent API and reaches the model as
`CASE_NOT_IN_STATE`, one of the five frozen codes in the architecture's MCP section. The
remedy is identical to the other things that code covers — read `status` again — so a sixth
code would buy the conversation nothing and would edit a frozen list without a reason.

**6. The withdrawal is still absent.**

`ConfirmIntent` has no `confirmed: bool`. A false one would be a withdrawal wearing a
confirmation's name; withdrawal is its own intent with its own rules and is not in this slice.
Calling the endpoint *is* the yes.

## Context

P4.9 established that nothing a model says, fails to say or fails to answer can reach a write,
a consent decision or a physical attestation. P5.1 added a transport that could not undo that,
but its two tools only stored words and read rows. `confirm` is the first tool in the product
that authorises anything, and `clarify` is the first that records evidence about a physical
fact somebody else will act on. Both are where a conversational surface would most plausibly
overreach: the question is already on the screen and the answer is one word long.

## Alternatives rejected

- **Case-only confirmation, with staleness left to revalidation.** Revalidation already
  protects each *track* at apply time, and would have caught a changed world before anything
  was sent. It would not have caught the thing this is about: the worker authorised a
  different set of promises from the one that executes. Refusing at the boundary is also the
  answer a person can act on, and a track quietly going `STALE` after a yes is not.
- **The case version alone as the plan identity.** Simpler, and it says nothing about what the
  plan *is*: two unrelated cases would be indistinguishable, and the identity would carry no
  evidence that the thing confirmed was a plan at all. The digest includes the version, so it
  is strictly stronger at the same cost.
- **A stored `plan_id` column, written when planning finishes.** A second source of truth for
  a question the rows already answer, and one more thing a re-plan has to remember to update.
- **A `confirmed: bool` argument, per the frozen tool table's abridged schema.** The frozen
  table predates the decision that withdrawal is a separate bounded intent. A boolean that can
  be false is a second verb hiding in one tool, and the false branch would have no rules
  written for it.
- **A sixth refusal code for staleness.** See §5.
- **Letting the transport compute the plan identity.** It has no rows, which is the point; a
  process that could mint one could mint one for a plan nobody was shown.

## Consequences

- `recovery.confirm_plan` has a required keyword argument, so every caller names a plan. The
  CLI's `confirm-plan` gained `--plan`, and `case-status` prints the identity to quote.
- The request fingerprint a confirmation is deduplicated by now includes the plan, so one
  command id carrying two different plans is a `COMMAND_CONFLICT` rather than a retry.
- `analysis.read_case_status` does one more query per read (the open clarification) and
  computes a digest. Both are per-case, not per-track.
- Two producers of one identity now exist — the read service's joins and the confirming
  transaction's locked scan — and a test drives both and asserts they agree. If they ever
  drifted, every honest confirmation would be refused as stale, so the test is the thing that
  makes the drift visible as itself.
- `promisepatch.domain.plan_identity` is a new pure module with an import-linter contract of
  its own: no clock, no rows, no environment, no `uuid`. An identity that could differ between
  the read and the check would defeat the binding.

## Revisit triggers

- A legitimate confirmation is refused as stale in normal use because something outside the
  plan bumped the case version. The fix is to narrow what the digest covers, not to drop the
  check.
- The bounded withdrawal lands and needs to reach a confirmed case, which is a decision about
  `confirm`'s neighbours rather than about this binding.
- A conversational surface appears that cannot hold a plan identity between two turns.
