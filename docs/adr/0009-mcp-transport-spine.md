# ADR-0009 — The MCP transport: pinned revision, stateless Streamable HTTP, and a delegating boundary

Status: accepted
Date: 2026-09-10
Phase: 5

Records, in the tracked ADR series, the transport decisions the frozen architecture already
fixes, plus the three this slice had to make on top of them. The local architecture baseline's
own MCP section is unchanged and remains authoritative; nothing here redesigns it.

## Decision

**1. The pin is `mcp==2.2.0`, and the claim is the protocol revision.**

An exact `==`, not a floor. The Alexa+ track's requirement is a *protocol revision* —
`2025-11-25` over Streamable HTTP — and a package version is not that. The pinned release
proves the distinction itself: it speaks `2026-07-28` as well, through a different entry point,
and only `initialize` reaches the handshake era whose newest revision is `2025-11-25`. So the
server is built on the handshake, and `tests/test_mcp_protocol.py` asserts the revision rather
than the version. A minor bump that moved the handshake default would fail a test instead of
quietly changing what a judge finds on the wire.

**2. Stateless, with the cost stated.**

`stateless_http=True`: every request builds its own transport, no `Mcp-Session-Id` is issued,
and none is honoured. Two reasons, in this order. Conversational continuity is supposed to come
from the durable case rather than from anything a server remembers, and a transport that held a
session would make that claim untestable — a reconnect would be indistinguishable from a
session that survived. It is also the AgentCore Runtime contract, so one process runs locally
and hosted with no second code path.

What that costs is real and is not hidden: **there is no `Last-Event-ID` stream resumption**,
because there is no session to resume. A dropped connection is a new handshake, and what
survives it is the case.

**3. Two credentials, and identity behind both of them.**

An MCP client presents a bearer token to `/mcp`; the MCP process presents a service token to
`/internal/intents`. The bearer check is an ASGI middleware **outside** the protocol, so an
unauthenticated caller never reaches JSON-RPC and never learns which tools exist. AgentCore
replaces the bearer with SigV4 at the edge; that changes the credential and nothing else.

The **attesting worker is resolved by the intent API from its own configuration**
(`PP_SURFACE_WORKER_ID`) and appears in no request field anywhere in the chain. The tool
schemas have no actor argument, the intent schemas forbid extra fields, and the clock is the
server's too, because a caller that could set `observed_at` could backdate a physical claim.

**4. The MCP process cannot reach a case except over HTTP.**

An import-linter contract forbids `promisepatch.mcp` from importing `promisepatch.domain`,
`promisepatch.db`, `promisepatch.api`, `promise_graph` or SQLAlchemy. It is the frozen
boundary rule made checkable: without it, the first inconvenient round trip becomes "just read
the row here", and the authority argument the whole conversational surface rests on would exist
only in a paragraph.

**5. `report` and `status` only.**

The finite surface is five verbs; two are implemented here. `clarify`, `confirm` and the
bounded withdrawal are absent rather than stubbed, because a tool that exists and refuses is a
different thing from a tool that does not exist.

## Context

P4.9 established that nothing a model says, fails to say or fails to answer can reach a write, a
consent decision or a physical attestation. A conversational transport is exactly the thing that
could undo that by accident — most easily by letting an argument carry an identity, or by
letting a fluent layer restate a deterministic answer.

The two are addressed structurally rather than by validation. There is no actor field to
validate, and `status` returns sentences the engine has already rendered, so the layer above has
something to deliver rather than something to summarise.

## Alternatives rejected

- **A route on the API process.** Simpler to deploy and it destroys the boundary: the domain
  would be on the MCP code's import path, the contract in §4 could not be written, and the
  endpoint would not be separately reachable — which is the thing a real Alexa+ registration
  needs.
- **Stateful sessions with an event store, for `Last-Event-ID` resumption.** More protocol
  surface, and it contradicts the durable-case design: a client that could resume a *session*
  would be recovering conversation state from the wrong place. Reconsider only if a client
  appears that cannot reconnect cheaply.
- **The SDK's OAuth resource-server auth (`AuthSettings` + `TokenVerifier`).** It advertises
  `/.well-known/oauth-protected-resource` naming an issuer this deployment does not have.
  Publishing a metadata document about an authorization server that does not exist is a false
  statement in a product whose entire argument is that it does not make those. A plain bearer
  challenge is honest and is what the local and self-hosted deployments actually use.
- **A floated `mcp>=2` range.** The revision this entry is about is decided by the release, and
  a range would let a resolver change it.

## Consequences

- The offline protocol suite starts a real server on a loopback socket and drives it with the
  official SDK client. It needs no database, no credential and no model, and it is what would
  catch an SDK bump that changed the wire.
- A new local stack needs two more generated secrets (`PP_INTERNAL_SERVICE_TOKEN`,
  `PP_MCP_BEARER_TOKEN`). Because the service token is *shared* between two files, a machine
  that already has `docker/env/api.env` cannot have `mcp.env` generated for it alone;
  `bootstrap_local_env.py` says so rather than writing a half-matching pair.
- `report` derives its command identity from the authenticated principal and the caller's
  optional `client_request_id`, so an idempotency key is a retry of that client's own call and
  can never address another client's case.
- The intent API answers "no such case" and "not your case" differently. The caller is an
  authenticated internal service and case ids are UUIDs, so this is not an enumeration surface;
  a conversation that could not tell those apart would have to guess which it was, which is how
  a model ends up saying something untrue about a case it never reached.

## Revisit triggers

- A hosted deployment cannot present SigV4 or a JWT to this endpoint, or AgentCore's egress to
  `/internal` is blocked (the frozen architecture already names the ECS fallback for the second).
- A client the product must support requires SSE resumption.
- The MCP SDK moves `initialize` off `2025-11-25`, or the hackathon confirms a later revision as
  the required one.
