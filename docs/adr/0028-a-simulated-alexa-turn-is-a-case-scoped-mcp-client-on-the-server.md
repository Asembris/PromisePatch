# ADR-0028 — A simulated Alexa+ turn is a case-scoped MCP client on the server

**Status:** accepted. Implemented locally in
`apps/backend/src/promisepatch/api/routers/simulated_alexa.py`; not deployed.
**Date:** 2026-10-01
**Phase:** post-G8, before G9
**Supersedes:** nothing. It narrows how ADR-0011's turn budget is counted for one caller and
leaves ADR-0011 standing.
**Related:** [ADR-0011](0011-conversational-orchestrator-authority.md),
[ADR-0013](0013-read-only-observer-principal.md),
[ADR-0015](0015-a-spoken-yes-checked-by-the-server.md),
[ADR-0016](0016-a-judge-principal-stays-read-only.md),
[ADR-0018](0018-a-plan-confirmation-spends-a-human-approval.md),
[ADR-0021](0021-a-customer-answers-on-the-web-and-their-address-stays-in-the-database.md)

## Context

The README describes the Alexa+ experience as simulated by MCP clients that call the real endpoint.
That is true, but the only conversational client that does it is `pp converse`, in a terminal. The
browser's voice composer reaches `/api/conversation/*` directly and never touches MCP. So nobody
watching the product in a browser sees the MCP path the claim is about.

A feasibility audit on 2026-10-01, at `0d8ae42`, found that a bridge needs nothing new from the
parts that hold authority:

- `Orchestrator.take_turn` holds no state between turns. The caller owns the `Conversation`.
- `Conversation.with_case(...).with_reading(...)` rebuilds one entirely from a `status` reading.
- `orchestrator.surface.connect` already speaks MCP 2025-11-25 over Streamable HTTP with a bearer
  credential.
- MCP `confirm` already only *finds* a plan approval (ADR-0018).

The same audit found two risks, both caused by how MCP attributes a statement. Everything arriving
over MCP is attested by `PP_SURFACE_WORKER_ID`, never by whoever is speaking:

- **Observer escalation.** If a bridge admitted any session, the demo observer that ADR-0013 and
  ADR-0016 keep read-only could cause writes attributed to the surface worker.
- **Attribution laundering.** Any other worker's words would be recorded as somebody else's.

## Decision

1. **The browser sends reviewed text and an existing `case_id`, and nothing else.** The request
   schema forbids extra fields, so the browser cannot send an actor, a plan identity, a tool name,
   a clock or a reason. If it tries, the server answers `422`. Speech recognition stays in the
   browser, and the worker reviews the text before it is sent.
2. **A request needs an authenticated worker session and CSRF**, through the same `CsrfPrincipalDep`
   that `/api/conversation/*` uses. No new auth system is introduced.
3. **The session's worker must equal `PP_SURFACE_WORKER_ID`.** If it does not, the server answers
   `403` before any MCP connection is opened. This makes the bridge authority-neutral: it lets a
   person reach, over MCP, only what that same person can already do on `/api/conversation/*`, under
   the identity MCP would record anyway. An observer session, the owner, or any other worker gets
   nothing from it.
4. **The MCP bearer token stays on the server.** The `api` process presents it as an ordinary MCP
   client would. It never appears in a response, a header sent to the browser, the frontend bundle
   or a log line.
5. **The bridge uses the existing `Orchestrator` over the real MCP endpoint**, with
   `build_semantic_provider` and `orchestrator.surface.connect`, exactly as `pp converse` composes
   them. It may not reimplement anything that the policy module, the MCP server, the intent API or
   the domain decides: phases, permitted verbs, the worker's yes, refusal sentences or
   authorization.
6. **The server reads fresh case status before every turn.** Each request opens one MCP session and
   calls `status(case_id)`. It builds the `Conversation` from that reading alone, and only then calls
   `take_turn`.
   - If that read fails, the conversation is `with_case` alone: `UNDERSTANDING`, whose only permitted
     verb is a read.
   - Nothing about the conversation is carried from one request to the next.
7. **No new durable conversation or session memory.** The bridge adds no table, no migration, no
   cache and no server-side session beyond the existing login session. The durable case is the
   conversation's continuity, as the stateless MCP server already assumes.
8. **The bridge never reports.** It is case-scoped: `case_id` is required, and `PERMITTED` offers
   `REPORT` only in `NO_CASE`, a phase a conversation with a case can never be in. No physical
   exception and no physical attestation is reachable through it. Opening a case remains the
   existing intake paths' job.
9. **MCP may spend an existing human plan approval and can never create one** (ADR-0018, unchanged).
   A spoken yes through the bridge reaches MCP `confirm`. That call is refused unless a plan approval
   row already exists for exactly that case and plan.
10. **Worker plan approval remains `/api/conversation/approve`**, a session plus CSRF, on the
    `BROWSER_SESSION` channel. The bridge must show that press as its own explicit control. It must
    not fold it into a spoken turn.
11. **Customer consent remains the separate signed customer-link path** (ADR-0021). The bridge
    reaches no customer, writes no approval request and no decision, and has no route to the
    consent parser.
12. **The fresh status read is not counted in ADR-0011's budget.** That budget allows at most two
    tool calls caused by one utterance, at most one of them effecting. The hydration read is outside
    it, for three reasons:
    - **The utterance does not cause it.** The server makes the read for every request, before the
      model sees the text, and the same read would happen for any text at all. ADR-0011 counts what
      one thing a worker said may cause. The hydration read is the transport rebuilding the state
      that `pp converse` keeps in memory between turns, and a stateless caller has to read it back.
    - **It cannot change anything.** It is a `status` call, and `status` is excluded from
      `EFFECTING`.
    - **It narrows what the turn may do rather than widening it.** The phase and the plan identity
      it supplies come from the server's own rendering of the case at that moment. This makes the
      budget's purpose stricter: a model cannot keep calling until something works.

    `MAX_TOOL_CALLS_PER_TURN` and its meaning inside `take_turn` are unchanged. A request through the
    bridge therefore makes at most three MCP calls: one hydration read, at most one effecting call,
    and one follow-up read.
13. **The product is labelled "Simulated Alexa+ via MCP".** It is never presented as Alexa+, an
    Alexa skill or Amazon's agent. The README's statement that this is not a native Alexa+
    integration stands.
    - The panel names what is real: the browser's speech recognition and synthesis, PromisePatch's
      own orchestrator choosing a verb with a model, and a self-hosted, authenticated MCP 2025-11-25
      Streamable HTTP endpoint.
    - It must be visibly separate from the existing voice composer, which does not use MCP, so the
      two are not read as one path or as duplicates.

## Consequences

- The `api` process becomes an MCP bearer holder. That is a new place where the secret lives, and
  every test of the bridge has to prove the token does not leave it.
- A request costs one model call and up to three MCP round trips, and each MCP call is also an
  intent-API call. The route needs a rate limit. Against the fake provider, the default locally and
  in CI, every turn chooses nothing, so a demonstration needs Bedrock configured. Tests need a
  scripted provider.
- Between hearing a plan and answering it, the plan may change. Decision 9 covers that: the
  approval was given for one plan identity, so a confirm against another one finds no approval and
  is refused.
- Only the surface worker can use the bridge to change anything. A judge on the demo observer
  session cannot drive it. That is ADR-0016's position, and a visitor who speaks would need
  tenancy, not this bridge.

## Deployment, deferred

Deployment changes are acknowledged here and left to the later release session. This ADR authorises
none of them.

- `api.env` would need `PP_MCP_BEARER_TOKEN` and `PP_ORCHESTRATOR_MCP_URL`.
- `mcp.env` would need to accept the `Host` the `api` process presents. The alternative is calling
  the public URL through Caddy, which is unverified.
- Both files are written only at bootstrap and are not rewritten by `converge.sh`. Under
  [non-destructive-release.md](../non-destructive-release.md) §10.1 the bridge therefore needs either
  host replacement or a separately authorised in-place migration.
- The bridge changes deployable product paths, so it belongs, together with `caf8064`, to the next
  final release and revalidation cycle: a new release SHA with green `pr`, a new deployment and
  five new rehearsals. It must not add a second round.
- If that release cannot carry it, the bridge stays local, and the deployed Alexa+ story remains
  `pp converse` against the deployed MCP endpoint.
