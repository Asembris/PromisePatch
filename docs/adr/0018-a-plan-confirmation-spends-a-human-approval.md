# ADR-0018 — A plan confirmation spends a human approval it cannot write

**Status:** accepted
**Date:** 2026-09-17
**Supersedes:** nothing. It narrows ADR-0010 and leaves it standing.
**Related:** [ADR-0010](0010-plan-bound-worker-confirmation.md),
[ADR-0011](0011-conversational-orchestrator-authority.md),
[ADR-0015](0015-a-spoken-yes-checked-by-the-server.md)

## Context

ADR-0010 bound a confirmation to a plan. ADR-0015 moved the reading of a spoken yes from the
browser to the server. Both are about *which* plan a yes is for and *whether the words were a
yes*. Neither asks the prior question: **what established that a human said anything at all.**

Until now the answer depended entirely on which transport asked, and only one of the two answers
was true.

- **Browser.** A signed, `HttpOnly` session cookie naming a row this server wrote; a CSRF token
  compared against that row; an actor read from the row rather than from the request. A person
  authenticated. The durable audit row saying `authority = HUMAN_APPROVAL` said something that
  had happened.
- **MCP.** A shared service token on the `mcp` process's HTTP call to `/internal/intents/confirm`,
  and an attesting worker taken from `PP_SURFACE_WORKER_ID` — this server's own configuration.
  Nothing anywhere in that chain established that a human was present, still less that they had
  been read a plan and agreed to it. The same `HUMAN_APPROVAL` row was written, naming a person
  who had done nothing.

So an authenticated MCP caller — and therefore a model driving one, since in the MCP architecture
the model *is* the client — could produce durable evidence that a named baker had approved a plan
they had never heard. The case moved to `EXECUTING`, tracks were escalated with their production
tasks held, amendments were enqueued against real orders and approval requests were enqueued to
real customers, on the strength of a secret in an environment file.

The existing defences were real and were all client-side or orthogonal:

- `reads_as_worker_confirmation` in `promisepatch.orchestrator.policy` stops *our* loop confirming
  on an agreeable turn. It is in a client. A different MCP host, or a direct call, never runs it.
- `ToolSelection` has no field for a plan, a case or a person, so the model cannot fabricate a
  plan identity. It can still choose the verb, and the host fills the identity in from `status`.
- The `plan_id` binding stops a yes landing on the wrong plan. It says nothing about whose yes it
  is.

The claim in `docs/p5-product-contract.md` — *"a model cannot confirm a plan, cannot confirm on a
worker's behalf"* — and `docs/g8-adversarial-proof-map.md` §1.3's **PROVEN** were therefore true of
the orchestrator and not of the surface. Host authentication is not human consent.

## Decision

**A plan confirmation carries out a durable human approval, and the surfaces that may write one
are exactly the surfaces on which PromisePatch authenticates a person.**

1. **A new governed, append-only table, `plan_approvals`**, keyed unique on `(case_id, plan_id)`:
   who approved, through which channel, on what evidence, when. Governed, so writing one requires
   the audit event that authorises it. Append-only, because it is an authored record of what
   somebody claimed; a plan that should no longer execute is *withdrawn*, which is its own
   authority with its own row.

2. **`ApprovalChannel` is closed at two members** — `BROWSER_SESSION` and `OPERATOR_CONSOLE` —
   and the column's `CHECK` admits exactly those. There is deliberately **no member for a service
   surface**. This is the boundary as a constraint rather than as a convention: the MCP path
   cannot record an approval even by calling the function that records them, because there is no
   value it could put in the column.

3. **`recovery.confirm_plan` loses its `worker_id` parameter and gains `approval_id`.** Who
   confirmed is read from the approval row under the confirming lock and from nowhere else. There
   is now no parameter, on any function or any request model on any transport, through which a
   caller can name the person whose yes it is. A refusal can be forgotten by a caller written
   later; a parameter that does not exist cannot be filled in by one.

4. **The internal intent API may only consume.** It calls `plan_approval.find`, never
   `plan_approval.record`, and passes `None` when there is nothing to spend. Its configured
   `PP_SURFACE_WORKER_ID` still attests what a worker *said* — a report, a clarification — and
   buys nothing whatever when the question is who agreed to a plan. `confirmed_by` in its answer
   is the approving human, never the surface worker, and `approved_via` names the channel that
   authenticated them.

5. **The browser keeps both halves and gains a way to separate them.**
   `POST /api/conversation/confirm` records the approval and carries it out in one request,
   because the person is on that request — unchanged behaviour, unchanged status code, unchanged
   speech, unchanged ADR-0015 parsing. `POST /api/conversation/approve` records it and stops, so
   a worker can agree on their own screen and have a conversation on another transport carry it
   out. That is the production path by which an MCP `confirm` can legitimately succeed.

6. **The refusal order is fixed and is part of the decision.** A caller is told that a case does
   not exist, that it is offering no plan, and that the plan it quoted is superseded, *before* it
   is told anything about approvals. The authority check is last and most specific, so a caller
   that has not got the case and the plan right learns nothing about who has agreed to what.

## Consequences

**What is now true rather than asserted.** An authenticated MCP caller holding a valid service
token, a real case in `PLANNED`, and the exact plan identity the surface itself rendered is
refused `403 HUMAN_APPROVAL_REQUIRED`, writes nothing, and leaves the case where it was. The
audit row that says `HUMAN_APPROVAL` is now preceded by a separate row that establishes it.

**The MCP `confirm` contract changed and no misleading version was kept.** The arguments are the
same three, but the meaning is not: the tool spends a worker's agreement and can never create
one. The tool description, the server `INSTRUCTIONS` a model reads at `initialize`, and the
result schema all say so, and `ConfirmResult` gained `approved_via` so a conversation cannot
report a confirmation without reporting where the authority came from.

**The canonical conversation gained a step that is not a tool call**, and that is the honest
shape of it: the worker approves on their own workspace, and the conversation carries it out.
Every end-to-end suite that drives a confirmation over MCP now performs that step, including the
frozen effect-set harness — which changes how a worker's agreement reaches a case and changes no
partition, effect or refusal any scenario is labelled on.

**One conflict became unreachable, and unreachable is stronger than refused.** The same command
id carrying two different *workers* used to be a `ConfirmationConflictError`. It is no longer
expressible, because a confirmation names nobody. The conflict guard remains live and is proved
against a withdrawal and a confirmation claiming one identity.

**What this does not touch.** Customer consent is untouched: it is still a literal `YES` / option
code / `NO` on that customer's own channel, produced by a different person under a different
authority, and nothing here can record one. Physical attestation is untouched. The orchestrator's
own literal rule is kept as defence in depth and is now correctly described as the client half of
a gate whose other half is not in that process.

## Alternatives rejected

**Carry the worker's verbatim words in the `confirm` tool call and read them server-side.** This
is what `report` and `clarify` do, and it would have been a real improvement in provenance: the
record would hold the exact sentence the host claimed. It fails the actual requirement, because
the model can supply `"yes"`. It moves the gate from a trusted client to the server while leaving
the thing on the other side of it entirely within the caller's gift.

**Bind the MCP principal to a worker and treat a live session as presence.** A per-principal
worker binding, admitted only while that worker holds an authenticated session. This is a general
identity mechanism, which this change deliberately is not, and it still proves only that somebody
is signed in somewhere — not that they were read this plan and agreed to it.

**Leave it, and correct the documents instead.** Defensible, and it was weighed: the deployment is
a demo, the MCP credential is not public, and the sentence in the product contract could simply
have been narrowed to "the orchestrator cannot self-confirm." It was rejected because the claim
the product is *for* is that the deterministic protocol authorises. A protocol whose strongest
authority is minted by whichever service calls it is not authorising anything; it is trusting a
transport and writing a person's name on the result.
