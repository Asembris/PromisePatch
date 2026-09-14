# A worker can now authorise a plan by saying so

*The decision is [ADR-0015](adr/0015-a-spoken-yes-checked-by-the-server.md). This is the short
record of what changed. **No voice turn has been recorded and no timing is claimed by any of
it.***

---

## What a worker can now do

At `PLANNED`, hold the microphone, say *yes, go ahead*, read the transcript, and send it. The plan
is authorised.

It goes through the same composer `report` and `clarify` already used, the same
`POST /api/conversation/confirm`, the same session-derived actor, and the same `plan_id` the case
response rendered — compared under the confirming lock exactly as
[ADR-0010](adr/0010-plan-bound-worker-confirmation.md) fixes. The existing control is still there
and is unchanged; pressing it and saying yes are two ways of giving the same single explicit
confirmation to the same single plan.

## Where the sentence is read

**On the server, on the route.** The browser forwards the worker's words and never inspects them:
there is nowhere in `Conversation.tsx`, `queries.ts` or `client.ts` that looks at the string. A
sentence a page had interpreted would be that page authorising a plan, and the server would have
no way to tell a spoken yes from a control press from a bug.

The rule is the one that already existed —
`promisepatch.orchestrator.policy.reads_as_worker_confirmation`, imported rather than rewritten,
so the browser and the conversational orchestrator cannot drift into disagreeing about what a yes
is. *yes*, *yep*, *go ahead*, *do it* confirm. *yes but not the strawberries* does not, because
`but` disqualifies a yes wherever it appears.

A sentence that is not a plain yes is refused with `NOT_A_PLAIN_YES`, before the domain is called,
and **nothing else happens to it**: it is not stored as a clarification, not read as a withdrawal
and not answered with a question. The case is exactly as it was, and that is what the panel shows
and the loudspeaker says.

## What did not change

* **Transcript review.** Capture, shown, editable, discardable, then sent — the composer's own
  discipline, reused untouched. A misheard *yes* cannot be sent unseen, which matters more here
  than on any other turn.
* **The plan binding.** A spoken yes against a plan the case has moved past is `PLAN_SUPERSEDED`,
  by the same lock and the same code path a pressed one takes. The literal check is an additional
  gate in front of that one; it can only refuse a confirmation the control could have made, never
  permit one it could not.
* **The authority boundary.** No new actor field, no clock in a request, no domain check relaxed.
  An observer saying a perfectly good yes is still refused by the domain, with the domain's own
  error.
* **The timing instrumentation.** A spoken confirmation leaves the same anchors every other spoken
  turn leaves, because it is the same composer and the same instrumented exit in `queries.ts`.
  Nothing about the recorder changed and nothing was measured.

## Which verbs still cannot be spoken, and why

Two of the five, and this closes one of the three
[`g7-ten-turn-voice-predeclaration.md`](g7-ten-turn-voice-predeclaration.md) §4 recorded as
unreachable.

| verb | spoken? | why |
|---|---|---|
| `report` | yes | `TurnComposer` in `ReportEntry.tsx` |
| `clarify` | yes | `TurnComposer` in `Conversation.tsx` |
| **`confirm`** | **yes, now** | `TurnComposer` in `Conversation.tsx`, with the literal rule on the route |
| `withdraw` | no | still a control. It has its own closed list, `WITHDRAWALS`, matched only at the start of a turn, and giving it a spoken path is the same decision made again rather than this one extended. Deliberately out of scope. |
| `status` | no | not a turn in the browser at all. The workspace already shows the case and the read-aloud control replays it, so there is nothing to send and no speech-end instant to measure from. |

**The predeclaration is not edited by this work.** Its §4 table and its ten utterances describe the
surface as it stood when it was written, and amending a predeclaration is a deliberate act for its
own session — not a side effect of the build that changed what it described.

## What proves it

**14 backend tests** in `test_browser_conversation.py` and **15 frontend tests** in
`spokenConfirmation.test.tsx`.

The backend ones: a spoken plain yes confirms; six kinds of non-yes — a qualification, a question,
a hesitation, a refusal, a withdrawal phrase and an unrelated statement — all reach
`NOT_A_PLAIN_YES` with the case still at `PLANNED`; a good yes against a stale identity is still
`PLAN_SUPERSEDED`; a non-yes carrying a stale identity answers `NOT_A_PLAIN_YES` rather than
`PLAN_SUPERSEDED`, which is the observable proof that nothing reached the domain; a spoken
confirmation cannot name its own worker; the control still carries no words; both shapes reach one
route and one answer; the rule is asserted against the orchestrator's own function rather than
against a copy of its word list; and an observer's perfectly good yes is still refused by the
domain.

The frontend ones: the words and the rendered `plan_id` are what get sent; the worker's own
sentence is what the transcript quotes, never the control's label; a non-yes is *still sent*,
because deciding what it meant is not the screen's to do; the refusal is the backend's, and no
exchange is recorded; the words stay under review when the turn did not happen; the transcript is
on screen with nothing sent until the worker says so; a misheard yes can be discarded without a
request; neither affordance is drawn where `permitted_verbs` does not offer the verb; and a spoken
confirmation leaves both speech-end anchors and both transport instants while a pressed one
correctly says `typed`.

Gates: `pytest` on the three related database-backed suites and the two pure ones, the Hypothesis
CI profile, `mypy` on all 258 source files, `ruff check`, `ruff format`, `lint-imports` (29
contracts kept), frontend `tsc`, `eslint` and `vitest` 290/290.

Nothing was deployed, no AWS resource was touched, no data was reseeded, no model was called and
both holdouts stay sealed.
