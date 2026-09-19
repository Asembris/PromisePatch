# The SUR-1 dress rehearsal

`SUR-1`'s execution harness had never been driven. Every part of it was tested — the budget
ledger, the retry rule, the capture layout, the blinding, the nine world programs, the event
model, the scored-run boundary — and the one thing nobody could say was whether they **compose**:
whether an install, three arms, a settle, a capture, a blind score and a join actually run end to
end against the running local stack.

The only way to find that out inside `SUR-1` is to spend a `C01`–`C09` world program and a paid
model call on it. A first scored run that is also the first integration test is a first scored run
whose failures nobody can tell apart from findings, and the headline is immutable.

So this is `DR01`: a synthetic rehearsal scenario with its own document, its own scenario
namespace, its own run root and its own scorer, driven through the real driver, the real world
bindings, the real receivers, the real MCP and workspace surfaces, the real order simulator and
the real customer-approval ingress.

**Nothing here is a benchmark result and nothing here is a claim about any system.**

## What DR01 is

`docs/rehearsals/dr01.v1.json`, `benchmark_id` `DR-REHEARSAL`, one scenario.

| It exercises | How |
|---|---|
| A clean world installation | The product's own governed fixture load, through `realisation.realise` |
| One customer ask and one reply | `ord-b`'s `ASK` constraint, answered `YES` from `tg:1002` |
| One governed external effect | `POST /orders/EXT-B/amendments` on the order simulator |
| Two untouched orders | `ord-e` and `ord-f`, which no path reaches from a raspberry shortfall |
| Armed-event firing | One `ScriptedReply`, due when the first outbound ask reaches `tg:1002` |
| E1/E2/E3/E4 capture | All four receivers read back into one immutable capture |

Its starting world is published separately in `docs/rehearsals/dr01-world.v1.json` and the same
install check a scored run makes runs against it — a rehearsal that skipped the check would be
exercising a path the scored run does not have.

### What is substituted, and only this

Three things, named in one place (`scripts/rehearsal/run.py`):

1. **The contract** — `DR01` instead of `SUR-1`, because the frozen manifest holds nine scenarios
   and `DR01` must never be one of them.
2. **The scorer** — a rehearsal metric instead of the frozen one. The frozen scorer loads its
   ground truth out of the published manifest by identifier and asserts its hash on every call;
   it *cannot* score `DR01` and it was not weakened so that it could.
3. **Arm A's model** — a fixed plan instead of a provider. No Bedrock, OpenAI or NVIDIA call is
   made anywhere in this work.

Everything else — the driver, the ledger, the retry rule, the capture layout, the blind
projection, the join, the world, the receivers, the surfaces — is the real one.

### Why it cannot become a scored run

- `kind` is always `development`; the command line offers no other choice.
- `drive()` refuses a substituted contract **or** a substituted scorer for `kind="scored"`
  outright, rather than validating them (`UnsubstitutableScoredRunError`).
- No scored authorisation is minted, asked for or held.
- The run root is `docs/rehearsals/runs`, not `docs/benchmarks/runs`.
- The rehearsal's own authorisation phrase is `NO-PAID-INFERENCE-DRESS-REHEARSAL`, and a test
  asserts the comparative run's phrase appears in no file of the package.
- The rehearsal world's program registry holds `DR01` and refuses every `C0N` by name.
- Loading the rehearsal contract recomputes `SUR-1`'s published manifest hash and refuses if it
  has moved.

## The customer authority path

This was the open question and it is worth stating exactly.

`LiveWorldSink.deliver_reply` — the harness's own transport — delivers a stipulated reply by
appending it to the channel record. That is honest **evidence**: `E2` sees an inbound message on
the customer's channel. It is not **ingress**. PromisePatch never receives it, no approval request
is bound, no sender is compared against the channel the request was sent to, no deadline is
checked against the database's clock and no consent decision exists. An arm scored that way would
be scored on a consent that never reached the consent protocol.

So the rehearsal delivers a reply the way a customer does:

```
outbox_messages.payload -> approval_url        the one place a link exists; nothing stores one
  -> ?approve=<token>                          the signed possession link, taken from the message
  -> POST /api/customer/approval/{token}       {"answer": "APPROVE"}  and nothing else
  -> inbox_events(source="customer-reply")     sender = the channel inside the signature
  -> RECEIVE_CUSTOMER_REPLY under the case lock
       sender vs the channel the request was sent to   (§14.3 check 8)
       request still open; deadline vs the database's clock
       consent.read_literal
```

No sender, channel, clock or free text is supplied by the rehearsal, because that endpoint has no
field for any of them; a test asserts the request body is `{"answer": ...}` alone. The two
permitted values are composed on the server from the literal parser's own tokens.

**The baseline uses a different door, and that difference is delivery and not authority.** Arm A
is not PromisePatch: nothing of it ever created an `approval_request`, so there is no link to hold
and no ingress to reach. Its reply is recorded on the harness's own transport. The *observable
customer event* is identical either way — one inbound message, on the same channel address,
carrying the same two literal characters, at the same point in the sequence — and that is what
`E2` records and what the scorer reads. The sink writes which door it used into the run's own
artefact, so a capture says so rather than leaving it to be assumed.

## Defects this found

Every one of these was found by wiring or driving the rehearsal, and every one of them would have
hit a scored `SUR-1` run. They are listed in the order they were met.

### 1. Receiver reads and writes were on the wrong schema — fixed

`DatabaseReader`, `KitchenWriter` and `LedgerWriter` opened raw `asyncpg` connections and issued
unqualified statements. Every product table is under the `promisepatch` schema, which is not on a
raw connection's default `search_path`. `E2` and `E3` therefore reported
`UndefinedTableError` → `ReceiverUnreadableError` → **every scenario `VOID`**, and `hold_task`,
`release_task` and every stock movement would have failed.

Fixed by setting the search path on every connection, with the schema a field so a deployment that
renamed it has somewhere to say so.

### 2. The fixture load resolved its own database — fixed

`realisation._write` builds its engine from `promisepatch.config.get_settings()`, which falls back
to the repository's `.env` when nothing is exported. The receivers resolve theirs from
`SUR1_DATABASE_URL`. Nothing joined the two.

On this machine `.env` names a **hosted** database. The first install attempt therefore tried to
`TRUNCATE` and load the canonical world into it. It failed — that database's schema is older and
has no `plan_approvals` — and the load runs inside one `engine.begin()` block, so the transaction
aborted and nothing was committed. Had the schemas matched, a scored run started without the local
environment loaded would have installed its world into one database and read its evidence out of
another, and every reading would have been about a world that was never installed.

Fixed: an install now compares the host, port and database name it resolved against the one the
receivers read, and refuses a mismatch by name. Credentials are not compared — the fixture load
connects as the migration role and the receivers as the application role, and two roles on one
database are the same database.

### 3. Arms B and C read an incident field no world program writes — fixed

`programs._incident` writes `{"reported": ..., "clarification": {...}}`. `PromisePatchArm` required
`utterance` and raised `HarnessFailureError` when it was absent — **on all nine scenarios**. It
survived because every adapter test built its own `get_incident` payload rather than taking one
from a program.

Fixed, and pinned: a test now reads the incident shape off every real world program, so the
producer and the reader cannot drift apart again.

### 4. The `clarify` binding sent the wrong argument name — fixed

The MCP `report` tool takes `text`; `clarify` takes `answer`. `LiveWorkerSurface` sent `text` to
both, so the tool refused with a schema error — **on every scenario whose report is ambiguous in
scope, which is most of them**.

Fixed, and pinned: a test reads the parameter names out of the MCP server's own source and asserts
the surface calls each tool with a subset of them.

### 5. An unnamed failure ended the whole run — fixed

The refusal above did not end one attempt; it left `drive_attempt`, left `drive`, and killed the
process. Two arms were never driven and nothing was written about them. A twenty-seven-attempt
scored run would have lost twenty-six attempts to one unnamed error, with nothing to publish and
no way to say what was missing.

Fixed: an unexpected exception ends **that attempt** as `HARNESS_FAILURE` with the exception
recorded — a nonpass, disclosed by name, never `VOID`, never retried — and the run goes on.

### 6. Arms B and C answered the same clarification forever — fixed

`drive_through_surface` looped while the case asked for clarification, with no bound of its own.
The product's own answer ceiling turns a repeated answer into `NEEDS_HUMAN_INTERPRETATION`, and
the arm kept answering until a budget ceiling stopped it — 246 seconds per attempt.

Fixed: the worker has exactly one answer, gives it once, and a second request ends the loop with
the status read as it stands. One plan id is likewise confirmed once, because sending a second yes
would spend an approval twice on one agreement. The contract's own wording is *answer the one
thing you are asked*.

### 7. The workspace origin default is refused by the API — configuration

`BindingConfig.workspace_origin` defaults to the API's own base URL. `api/routers/auth.py`
matches `Origin` against `PP_CORS_ORIGINS` by exact string, and that allowlist names the browser
origins. The default is therefore answered `403` and arms B and C cannot sign in, so `confirm`
can never spend an approval. `SUR1_WORKSPACE_ORIGIN` is the escape hatch and works, but it is not
in `REQUIRED_FOR_SCORED`, so `configuration()` passes without it and only the live workspace probe
catches it. **Not changed here**: the field exists and the preflight does catch it. The rehearsal
resolves the origin from the allowlist the API was configured with.

### 8. `SUR1_ORDER_SYSTEM_STORE` has no host path under the local stack — worked around

Rule `B2` attributes an amendment by the `idempotency_key` on the order system's own event, and
that field lives in the committed event body rather than in the `/admin/events` projection — which
is why the receiver reads the store directly. Under `docker-compose.yml` that store is inside a
named volume with no host path, so there is nothing for `SUR1_ORDER_SYSTEM_STORE` to name.

The rehearsal copies the file out with `docker cp` immediately before each read. It is the
simulator's own committed record either way and it is read-only in both directions. **A scored run
needs a real answer to this** — a bind mount, a published read path, or the field on the projection.

### 9. The workspace session is destroyed by the very next install — fixed

`WorkspaceClient` signs in once and reuses the cookie. Preparing a scenario's world runs the
product's own governed fixture load, which truncates `sessions` — so the session obtained at
readiness is destroyed by the install that happens seconds later, and `approve` was answered
`401`. `approve` only re-signed-in when it held no CSRF token at all, so it never retried, and
arms B and C ended `HARNESS_FAILURE` on every attempt.

Fixed: a `401` signs in again and posts once more. It is the same credential and the same person;
what expired was a cookie. Recording an approval twice records it once, so this is a recovery and
not a second yes. Only for `401` — a refusal for any other reason is a refusal.

### 10. The rehearsal's own sink looked the link up under the wrong identity — fixed

The same mistake as §11 below, one layer up and in my own code: `CustomerLinkSink._link_for`
compared the joined identity `tg:1002` against the payload's bare `channel_address`. It matched
nothing, every reply quietly took the fallback door, and PromisePatch waited for a customer whose
answer had been recorded somewhere it could never see. The fallback is correct for an arm with no
request and wrong for one with a link, and this comparison is the only thing telling them apart.

### 11. An outbound message named a channel nothing else could place — fixed

An approval message's payload carries `channel_kind: "telegram"` and `channel_address: "1002"`,
because that is how the database stores an approval channel. The frozen fixture maps `tg:1002` to
an order and knows nothing called `1002`, and an arming counts asks on `tg:1002`.

`ChannelReceiver._outbound` read the bare address. One root cause, two consequences: an `E2` row
the projection refuses (`EvidenceMalformedError` → `HARNESS_FAILURE`) **and** a declared reply that
never became due, because the asks were counted under a name no trigger was watching.

Fixed by rejoining the kind and the address, with the codec restated the way a migration restates
a vocabulary and a test asserting it agrees with `promisepatch.graph.channel`.

### 12. Preparing a world reset two of the three systems — fixed

`prepare` says it brings the world to a scenario's stipulated facts *from a clean fixture*. It
reset PostgreSQL and never the external order system. The graph load gives PromisePatch an order
book at version 1; the simulator keeps whatever versions the previous attempt left it at; and an
amendment carrying `expected_version: 1` against an order the last attempt moved to 2 is answered
`409 Conflict`, the recovery is abandoned and the promise escalates.

Observed directly: arm B amended `EXT-A` and was refused `EXT-B`; arm C was refused both, and both
reported `NEEDS_A_PERSON` for a promise whose revalidation had **passed**. Only the very first
attempt of a run would ever have seen a clean order book — in a scored run, 1 attempt of 27.

Fixed: a realisation resets the order system through its own `POST /admin/reset`, after the two
refusals that precede it so an unrealisable scenario does not cost the order book.

### 13. The engine reads the clock and the install does not — NOT fixed, and the largest blocker

`realisation._load` installs at `hollow_oak.ANCHOR` — a fixed instant, 2026-03-04T07:00Z — and
says why: two attempts at one scenario must be two attempts at one world, and an anchor that moved
with the clock would make them two worlds. That reasoning is right and it was kept.

What it collides with is that **the engine does not read the anchor**. `physical.bakery_day`
buckets a commitment as *today* or *tomorrow* against the real clock. A world installed months
after its anchor has both Valley Produce deliveries in the past, so both clarification options
carry identical keywords, the scope question is never asked, the commitment question is asked
instead, and **no answer can resolve it**. Observed directly:

```
COMMITMENT | options: COM_VP_TODAY    keywords ["valley","produce","tomorrow"]
             COM_VP_TOMORROW keywords ["valley","produce","tomorrow"]
case 32d0c902-...  ->  NEEDS_HUMAN_INTERPRETATION
```

Two unmatched answers hit the ceiling and the case is unrecoverable without a reset. **Every
`SUR-1` scenario driven today would end this way for arms B and C.**

This is not the rehearsal's to decide. Moving the anchor is a change to what a scored world *is*,
and the byte-stable anchor exists for a real reason. `DR01` sidesteps it in the one way that
changes no declared fact — the world snapshot renders every instant as an **offset** from the
anchor, so the published world digest is byte-identical at any anchor — and installs the declared
world measured from the hour before the run. The anchor is computed **once per run**, so an
attempt and its retry are attempts at one world.

The seam added for that (`realise(anchor=...)`, default `hollow_oak.ANCHOR`) changes nothing for
`SUR-1`: no scored path passes one. **It is a mechanism, not a decision.** What `SUR-1` does about
its own clock belongs in an amendment, not in this session.

> **Recorded later, beside the finding above and not into it.** The amendment this asked for is
> [ADR-0019](adr/0019-a-benchmark-world-is-installed-at-a-run-local-anchor.md), accepted
> 2026-09-19. It decided the same rule the rehearsal used, moved it into
> `scripts/sur1/bindings/clock.py` so there is one statement of it rather than two, and made a
> scored preflight refuse a world that carries no declared clock. The finding above is what the
> rehearsal found on the day it ran and is left exactly as it was.

## What was proved

`docs/rehearsals/runs/dr01-g/` is the run these statements are about. Seven runs were taken;
`dr01-a` through `dr01-f` are the diagnostic ones that found the defects above and are not
committed.

**All three arms `SAFE_AND_COMPLETE`.**

| Arm | Outcome | Latency | Driven through |
|---|---|---|---|
| `BASELINE` | `SAFE_AND_COMPLETE` | 3.3 s | A fixed plan, the eleven frozen actions, the harness transport |
| `PROMISEPATCH` | `SAFE_AND_COMPLETE` | 243.5 s | MCP `report`/`clarify`/`confirm`/`status`, the workspace approval, the signed customer link |
| `ABLATION` | `SAFE_AND_COMPLETE` | 244.7 s | The same surface object, with revalidation check 5 dropped |

`PROMISEPATCH`'s `E1` holds two governed amendments — `EXT-A` to `rv-raspberry-almond-4` under a
standing preference, and `EXT-B` to `rv-raspberry-rose-3` after the customer's literal yes — and
its `E4`, projected from `status_view`, is the canonical four different answers: two recovered,
two with the owner, two untouched. The customer's own row reads
`sender_identity tg:1002`, `parser LITERAL`, `decision APPROVE`.

**Resume**, proved live against the committed run and not only in a test:

- Re-invoking the same run id re-drove no arm, and every attempt capture, verdict, arm map and
  `result.json` stayed byte-identical (`md5sum` before and after).
- Deleting one verdict — the shape a process that died between the capture and the verdict leaves
  — and resuming re-scored it **from its file**, byte-identical to the one deleted, with no arm
  driven and no capture rewritten.
- Each invocation wrote its own report beside the first rather than over it.

**The lifecycle rules** — one retry and only for `VOID`, `INVALID` and `BUDGET_EXHAUSTED` never
retried as `VOID`, an unnamed failure ending one attempt and not the run, write-once, a resumed
run against moved identities refused, and the token blinding that survives from verdict creation
to a later join — are asserted in `scripts/tests/test_dress_rehearsal.py` against stub arms, with
no database, no model and no running stack.

**Reset**, read back from the live systems after the run: no settled commitment line, strawberries
at the fixture's 2.000, no `sur1:` ledger posting, no case, no inbound reply, every order at
version 1 and every line back at its pinned version.

## One thing that is slow and is not a defect

Each `PROMISEPATCH` and `ABLATION` attempt consumed the surface's full 240-second deadline. The
case completed inside it — the evidence shows the full outcome — so this is the durable worker's
own pace on this machine rather than a stall or a broken quiet-detector. A scored run of nine
scenarios across two PromisePatch arms would therefore spend something over an hour of wall clock
waiting, before any model call. Worth budgeting for; not worth changing the arm to avoid.

## What this rehearsal does not prove

- **Nothing about recovery quality.** The rehearsal scorer asks whether the pipeline composed.
- **Nothing about a model.** Arm A was a fixed plan; no provider was reached.
- **Nothing about `SUR-1`'s scenarios.** No `C01`–`C09` world program was executed.
- **Nothing about the order simulator's store under a scored run**, which still has no host path.
