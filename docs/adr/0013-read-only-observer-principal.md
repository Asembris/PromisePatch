# ADR-0013 — A read-only observer principal, and the scoped session that names it

Status: accepted
Date: 2026-09-13
Phase: 7

Records the one decision in P7.3 that widens the domain's permission surface. Everything else in
that slice is presentation or transport; this is not, and a change to who the domain admits
belongs in the ADR record rather than only in a router.

It does not reopen [ADR-0009](0009-mcp-transport-spine.md) or
[ADR-0011](0011-conversational-orchestrator-authority.md). The authority boundary they establish
is unchanged: nothing here lets anybody authorise a write, and the new principal is defined
precisely by being unable to.

## Context

The [P7.1 judge-facing UX contract](../p7.1-judge-ux-contract.md) requires a judge to reach a real
case in **one action**, with no CLI, no README and no navigation. The two ways to do that with the
system as it stood were both wrong:

- **Publish read-only credentials on the sign-in screen.** A standing credential in a public
  repository and in a video frame, which also costs the judge typing.
- **Hand the judge a real worker's session.** `maya` can speak on her own cases and `jo` can speak
  on every case. A judge could confirm a plan. Forbidden outright.

A third option — removing the permission check from the read path — was rejected because that
check is the one P5.1–P5.4 deliberately share with the MCP surface.

## Decision

**1. A third worker role, `observer`, that the domain admits to reads and to nothing else.**

`workers.role` admitted `baker` and `owner` under a `CHECK`; migration `0008` widens it by one.
One row is seeded (`judge`) with a stored password hash Argon2 cannot parse, so `POST
/api/auth/login` can never admit it however carefully somebody guesses. The only way to hold this
identity is a session the server chose to issue.

A **role**, not a scope on a session. A session-level scope would still *name* a real worker, so
any leak of the scope check becomes an attributed write, and every transport would have to
remember to look for it — the first one that forgot would fail open. A role makes the refusal the
domain's.

**2. `intake.require_readable`, beside `require_permitted` rather than inside it.**

`require_readable` admits the worker who opened the case, an owner, **or** an observer, and is
used by `GET /api/cases/{id}` alone. `require_permitted` — the function every write in this system
passes through — is a separate function, so the widening cannot reach a write even by mistake, and
a write route added later with no observer check of its own still refuses one. A parameter on one
function would have put the two answers a single call site apart.

**3. Two narrowings came with it, and both are additive.**

Writing the characterisation test for `require_permitted` *before* `require_readable` existed
found the hole the plan's own reasoning had missed: **`open_physical_exception` never calls
`require_permitted` at all**, because there is no case yet to be permitted on. An observer could
therefore have opened a case — and the worker who opens a case is exactly whom `require_permitted`
admits to it afterwards, so it would have granted itself every subsequent write on it.

- `intake.require_attestor` is the new gate on opening a case: who may put a physical claim on the
  record at all. It refuses an observer.
- `require_permitted` additionally refuses the observer role outright, before its opener branch.
  Defence in depth rather than a second answer — `require_attestor` already means no observer can
  be an opener — so that "an observer may write nothing" is a property of the one function every
  write passes through, rather than a conclusion reconstructed from two of them.

Neither narrows anything that was ever admitted. Before this role existed every principal was a
baker or an owner, and each of them gets exactly the answer they got before.

**4. `POST /api/auth/demo-session` issues; it does not authenticate.**

No credentials in, none published, and **no request model at all** — so there is no field a caller
could aim at a worker, and a body naming one is read by nothing. The server chooses the principal
(the one row holding the observer role), the expiry and the CSRF token, exactly as login does.

Four bounds, because "cannot do damage" is not a reason to leave a door open:

- **Off by default.** `PP_DEMO_SESSION_ENABLED` is `false`, so this is a deliberate deployment
  choice and not a standing anonymous-session endpoint in every copy of the repository. Off means
  gone: a `404`, not a distinguishable refusal.
- **Bounded.** A 60-minute TTL rather than the 12-hour worker session.
- **Rate-limited**, per client, by its own limiter, so neither it nor sign-in can exhaust the
  other's allowance.
- **`Origin`-checked** against `PP_CORS_ORIGINS`, exactly as login is.

**5. Fail closed on an ambiguous or absent principal.**

The endpoint issues only when there is **exactly one** observer row. None means the migration ran
and the fixture did not, and inventing a principal would be creating an identity nobody seeded.
More than one is conflicting state about which principal a session names, and this system picks
nothing when the state conflicts — even where every candidate is equally powerless.

**6. The screen is told, never left to infer.**

`may_speak` and `permitted_verbs` are fields on the case response. A surface that read a role and
decided what to offer would be deciding who may act; these make the offer the backend's answer. The
domain checks every call again regardless, so they stop a screen *offering* what would be refused
and do not make an offer binding.

## Consequences

- **This broadens read access to a new principal kind.** It is not a weakening of an existing
  check — nothing admits anybody it did not admit before — but it is a deliberate addition to the
  domain's permission surface, and it is named as one here rather than slipped in as a route.
- **Read-only is structural.** Writes gate on `require_permitted`, which now refuses the role
  explicitly; opening a case gates on `require_attestor`, which refuses it too. A route-level
  allowlist would have failed open the first time somebody forgot it.
- **Revocation and shutdown need no deploy.** The session is an ordinary row, so `revoked_at` ends
  one on the very next request and `pp reset-demo-state` invalidates every session in the database.
  `PP_DEMO_SESSION_ENABLED=false` removes the endpoint on the next process start.
- **The role is now part of the schema's closed vocabulary.** A future principal kind is another
  migration and another ADR, which is the intended cost.
- **Downgrading migration `0008` deletes observer rows**, under an audit event, because `workers`
  is a governed table and a migration is not exempt from the write boundary.

## Alternatives rejected

| rejected | why |
|---|---|
| Published read-only credentials | A standing credential in a public repository and in a video frame, and it costs the judge typing. |
| A judge session as `maya` or `jo` | Owner impersonation with full write authority behind it. A judge could confirm a plan. |
| A `scope` column on an ordinary worker session | The session still names a real worker, so a leak of the scope check becomes an attributed write. |
| No gate at all on reads | Removes the check P5.1–P5.4 deliberately share with the MCP surface. |
| A parameter on `require_permitted` | Puts "may read" and "may write" one argument apart in the function every write in the system calls. |
