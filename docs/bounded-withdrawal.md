# The bounded withdrawal — the fifth tool, and what it refuses to pretend

*The G7 obligation carried forward from the G5 closeout. This is its record.*

---

## 1. What it is

A worker can now call a case off, and the product says honestly what that did and did not
achieve. The fifth frozen tool — absent rather than stubbed since P5.1 — is implemented across
the domain, both transports, the conversational orchestrator and the case workspace.

The whole operation is one claim:

> **Future work stops. The past does not move, and nothing pretends it did.**

Everything below is that sentence made checkable.

---

## 2. The contract, reconstructed rather than designed

Nothing here is new semantics. The frozen sources already decided every branch, and this slice
implements what they say. The sources, and what each one fixed:

| source | what it fixed |
|---|---|
| Spec §14.1 | `any non-terminal ──(worker retracts, no consequential write yet)──▶ CANCELLED`, and `any non-terminal ──(worker retracts after writes)──▶ ... (reverse what is reversible) → RESOLVED(with escalation)` |
| Spec §14.2 | a worker retraction is one of the exact events that takes a `WAITING` case out of waiting |
| Spec §23 | "Before any write: CANCELLED. After writes: reversible writes reversed (reservations, task hold, un-sent requests); sent requests cannot be unsent ...; track ESCALATED for owner awareness." |
| Spec §13.4 | `WITHDRAWN` is a terminal track state |
| Spec §15.2 / §26 | the tool is `retract_exception`, `{conversation_id, case_id}` in, `{case_id, state, reversed, irreversible}` out |
| Spec §16.3 | the phases that offer it: **clarifying and planned**, and *not* the opening phase |
| ARCHITECTURE_PLAN §11.8 | *consequential* means "a write that touches a customer promise: an order amendment, a reservation move, a task hold, a message sent to a customer". Physical-fact postings are **not** consequential. |
| ARCHITECTURE_PLAN §11.8 | a physical fact is reversed by a correcting attestation and by nothing else |
| Roadmap G7 item 8 | "stop future authorized work where permitted; explain effects already applied and hand off where needed. Never silently reverse physical facts or external changes." |
| ADR-0010 §6 | withdrawal is its own intent with its own rules, which is why `confirm` has no `confirmed: bool` |
| ADR-0011 | it is an effecting verb and needs its own phase rule **and its own gate** |
| P7.1 | when it lands it lands "as a verb in the table above with the same permitted-phase discipline as the other four" |

---

## 3. States and transitions

### The case

| the case is | the withdrawal | because |
|---|---|---|
| `RECEIVED`, `INTERPRETING`, `CLARIFYING`, `NEEDS_HUMAN_INTERPRETATION`, `ANALYZED`, `PLANNED` and no consequential write exists | → **`CANCELLED`** (terminal) | §14.1's first arrow |
| `EXECUTING`, `WAITING`, `REVALIDATING`, `RECONCILING`, or any state in which a consequential write already exists | → **`RECONCILING`**, carried by the existing reconcile step to **`RESOLVED`** with `needs_owner_attention` | §14.1's second arrow |
| `RESOLVED` or `CANCELLED` | **refused** (`CASE_NOT_WITHDRAWABLE`) | §14.1 says "any non-terminal". A finished case has no future work to stop, and answering "withdrawn" would tell somebody something had been stopped that had already happened. |

### The tracks

| a track is | it becomes | reason |
|---|---|---|
| non-terminal, nothing consequential applied | `WITHDRAWN` | §13.4's terminal state for a promise this case no longer holds |
| non-terminal, something consequential applied | `ESCALATED`, reason `WITHDRAWN_AFTER_EFFECTS` | §23's "track ESCALATED for owner awareness" |
| already terminal (`RECOVERED`, `UNAFFECTED`, `ESCALATED`, `LINKED`, `WITHDRAWN`) | **untouched**, byte for byte | it is not this case's to move any more |

Every live track reaching a terminal state is load-bearing rather than tidy.
`ix_tracks_one_live_per_promise` is unique over non-terminal tracks, so a withdrawal that left one
`PENDING` would lock that promise out of every future case, silently, for ever.
`test_withdrawal_contract.py` asserts the index predicate rather than trusting it.

### What is reversed, and what is not

| | |
|---|---|
| **reversed** | production-task holds **this case** took; approval requests still open, marked `SUPERSEDED`; queued effects nobody has dispatched; enqueued steps nobody has claimed |
| **not reversed, and reported** | an order amendment the order system accepted; a message a customer received; any effect a dispatcher is holding right now |
| **never touched** | every physical fact — `exception_facts`, settled commitment lines, the inventory ledger; a customer's recorded decision; any promise this exception never reached |

The un-sent approval request needs no new mechanism: marking the request `SUPERSEDED` is enough,
because the dispatcher already refuses to deliver a message whose request is not open
(`approvals.refuse_if_window_closed`). Queued `ORDER_AMEND` effects do need stopping, and are
marked `FAILED` with the withdrawal named as the reason — the outbox's own word for "will not be
delivered", the same posture an approval message reaches when its window closes before dispatch.

An effect that is `IN_FLIGHT` is reported as in flight and touched by nothing. This transaction
genuinely cannot know whether it will land, and guessing would put a claim in the record that
nothing observed.

---

## 4. What is deliberately not built

**§23's "customer gets one 'please disregard' message" is not implemented.** It would be a
customer-facing message template and outbox path that this build has no precedent for: §14.4's
own supersede message, described in the same frozen document, is also not implemented, and
`analysis._supersede_approval` sends nothing. Rather than invent a customer message here, the
withdrawal reports the sent request as applied, escalates the track, and hands the owner the job —
which is the other half of the same sentence in §23. **It is stated here rather than left to be
discovered.**

Nothing else in the frozen contract is left out.

---

## 5. The authority boundary, unchanged

- **The actor is the server's.** `PP_SURFACE_WORKER_ID` on the intent API, the session row on the
  browser route. No request model anywhere in the chain has a field for one, and `extra="forbid"`
  makes an attempt a `422` rather than a value quietly ignored.
- **No field can name a physical fact.** Withdrawing a plan is not a claim about the kitchen.
  Correcting a fact is a separate attestation under a separate authority, and a withdrawal that
  could carry one would be two authorities travelling in one call.
- **No field can name a reason.** A reason is not an authority, and storing unattested prose as
  the record of why a customer promise stopped being recovered would be evidence nobody made.
- **The model holds no new authority.** `ToolSelection` still returns a verb and nothing else.
  The withdrawal it can choose carries a case id the conversation already had, and nothing a
  model produced reaches the call.
- **A worker's own word is required.** `policy.reads_as_worker_withdrawal` is a closed literal
  parser, separate from the confirmation gate and unrelated to the consent parser. A model that
  chose `WITHDRAW` on a turn that did not say so is blocked before the surface is touched.
- **Observers are refused by the domain**, on `require_permitted`, exactly as everywhere else —
  not by a check in either router.

## 6. Where the verb is offered

`PERMITTED` gains `WITHDRAW` in **`CLARIFYING`** and **`PLANNED`**, which is §16.3's frozen table
read literally. Every other phase keeps the read-only offer it already had.

The domain is deliberately wider: §14.1 admits a withdrawal from **any** non-terminal case, so
`EXECUTING` and `WAITING` are withdrawable through the domain and the transports while the
conversation does not offer the verb there. That is the defence-in-depth the policy module keeps
describing — what a phase *offers* is narrower than what the engine accepts, and every call is
checked again behind it. §16.3's own conversation ends at the confirmation and has no phase for a
case that is executing, so nothing in the frozen sources names one, and this slice does not invent
it. **If that gap should close, it is a decision for an amended ADR rather than a table edit.**

The case workspace needs no new backend field: `/api/cases/{id}` already returns
`permitted_verbs`, computed from this same table and narrowed by `may_speak`. The screen draws the
control when `withdraw` is in that list and draws nothing at all when it is not — no disabled
button, no "coming soon".

---

## 7. Idempotency, staleness and restart

- **One command, one withdrawal.** The accepted command is a `case_steps` row keyed on the
  caller's own `command_id`, exactly as a confirmation is. A redelivery returns `created: false`
  and writes nothing; the case version is unchanged.
- **A command id already spent on a different request is a conflict**, not a retry — including a
  confirmation's id reused for a withdrawal.
- **Everything decides under the case lock**, after the row is taken `FOR UPDATE`, so a withdrawal
  racing a worker's step serialises against it rather than interleaving with it.
- **A claimed step is left alone.** Only `PENDING` and `RETRYING` steps are stood down; a step a
  worker is running right now settles itself against the case this transaction is about to commit,
  and finds it terminal.
- **A dispatcher mid-claim is left alone.** Queued effects are taken `FOR UPDATE SKIP LOCKED`, so a
  row this misses is one that really is going out — and is counted as applied on the next read
  rather than reported as stopped.
- **Restart.** A drained worker after a withdrawal raises no further effect, across two separate
  worker processes, asserted end to end.

---

## 8. What was proved

| | |
|---|---|
| domain, against real PostgreSQL | 26 tests — both branches, every refusal, physical facts, the customer's decision, selective continuation, replay, conflict, restart, the audit row and the event spine |
| the invariants it lands inside | 11 pure tests, including the partial unique index read off the model |
| intent API | 9 tests — the verb, the refusals, the actor field that cannot be set, the fact field that does not exist, replay, conflict, the credential |
| browser conversation | 6 tests — the session actor, CSRF, the observer refusal, the no-undo wording, the already-finished refusal |
| MCP protocol, offline | 7 tests — discovery is now **five** tools, the argument list, the applied list delivered word for word, the refusal code, the idempotency key |
| end to end over the real transport | 3 tests — the canonical case called off with nothing carried out, restart safety across two worker processes, replay and a fresh key on a finished case |
| frontend | 8 tests — the control exists only where the backend listed the verb, nothing for an observer, nothing optimistic, the applied list rendered, and the panel never says "undone" |

**No live model call. No AWS resource touched. Nothing deployed.** Both holdouts stay sealed.

### The negative proofs

Three assertions carry most of the weight, and each is a negative:

1. **No effect reversal.** A case is driven until real effects are `DELIVERED`, then withdrawn,
   and every delivered row is compared byte for byte — `(id, state, provider_ref)` — before and
   after. They are identical, and the result reports them as applied rather than swallowing them.
2. **No physical reversal.** Every `exception_facts` row and every inventory posting for the
   affected resource is compared before and after. Identical.
3. **No word that reads as an undo.** The rendered speech after an applied effect must contain
   "could not undo what had already happened" and must not contain "undone"; the frontend panel is
   asserted against `/undone|undo|rolled back|reversed|put back/i` after a withdrawal.

---

## 9. What this does not close

- The **case-workspace finishing** beyond P5.4's minimal real-state view is still the other G7
  obligation, and is untouched here.
- **Correcting a physical fact** remains reachable only from the CLI, exactly as P7.1 records it.
  This slice does not move it, and deliberately makes it unreachable from the withdrawal.
- The **"please disregard" customer message** of §23 is not implemented — see §4 above.
- No deployment. The running host is unchanged by this work.
