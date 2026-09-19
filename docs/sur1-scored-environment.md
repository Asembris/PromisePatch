# The `SUR-1` scored environment: four gaps, closed

**No arm was driven, no model called, no scorer run and no comparative number exists.** `SUR-1`
is still unrun, `AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE` is unspent, both evaluation holdouts
stay sealed, and no `SUR-1` result directory was opened.

[`sur1-execution-bindings.md`](sur1-execution-bindings.md) records the live bindings and the gate
in front of them; [`sur1-dress-rehearsal.md`](sur1-dress-rehearsal.md) records the twelve defects
`DR01` found by driving the whole pipeline at a scenario that is not one of the nine. Four things
were still open afterwards, three of them named in that record as *needing a real answer before a
scored run*. This document is what happened to them.

| | |
|---|---|
| Benchmark | `SUR-1` v1.0.0, manifest SHA `5718340f…e70e84c`, **unchanged** |
| Baseline prompt | SHA `772ba460…9ce47cb1`, **unchanged** |
| Scorer | `scripts/score_safe_useful_recovery.py` v1.0.0, **unchanged** |
| Predeclaration rules | SHA `c53d267a…1d1e1927`, **unchanged** |
| World programs | `program_set_sha` `88db566c…ab1de649`, `implementation_sha` `76eda88e…5300e883`, **both unchanged** |
| Effect sets | `11/16` stands, manifest hash unchanged, `S12` stays committed failing |
| Runs taken | **none** |

Every hash above was recomputed after the work below and agrees with its published value.

## 1 — `E1` is read from the endpoint the contract names

**The gap.** Rule `B2` attributes an amendment to an arm *by the `idempotency_key` on the order
system's own event*. The simulator's `GET /admin/events` published an event's id, order, type,
version, instant and delivery state, and none of the three fields the contract's own `fields_used`
lists — the command key, the previous version, the changed line's item. The receiver therefore
opened the simulator's SQLite store directly. Under `docker-compose.yml` that store lives in a
named volume with **no host path**, so `SUR1_ORDER_SYSTEM_STORE` had nothing to name and the
rehearsal extracted the file with `docker cp` before every read. A scored run whose central
attribution rule rests on copying a file out of a container is resting on something that is not a
supported read path.

**What changed, and it is the smallest thing that closes it.** `GET /admin/events` now publishes
each entry's committed body under `event`: the `order_contract.events.OrderEvent` document the
order system already hands a webhook subscriber, read out of the row it was committed on rather
than re-derived. The endpoint also gained `since`, `limit` and — the part that matters for a
measurement — `truncated`, because a log that stopped early and read as a complete one would let
an attribution conclude an amendment never happened when it simply was not fetched.

`OrderSystemReceiver` reads that endpoint and `GET /orders`, opens no file, and has no
`store_path`. A window the order system says it cut short is
`ReceiverUnreadableError` → `VOID`, never a shorter reading. `SUR1_ORDER_SYSTEM_STORE` is out of
`REQUIRED_FOR_SCORED`; `ContainerOrderReceiver` and the rehearsal's `docker cp` are gone.

**Why this is not the "no production file" violation the predeclaration said it would be.** The
frozen contract's constraint is on arm B — *"No production file is modified **for this arm**"*,
beside *"no benchmark-only behaviour and no code path that exists for this measurement"*. That is
a rule about what the **deciding system** is given. The order simulator is not an arm; it is the
world, and `E1` is its own record. The change is a read-only widening of an audit projection the
system already publishes, of bytes it already emits to its integration partner. No arm can reach
it: the endpoint is not one of the eleven frozen actions and `LiveScenarioWorld` does not expose
it. All three arms are measured through one reader. No mutation, no version precondition and no
idempotency behaviour moved, and nothing under `packages/` or `apps/backend/` was touched. The
disclosure is recorded beside the original in
[the predeclaration](benchmarks/sur1-execution-predeclaration.v1.md#3--two-discrepancies-between-the-frozen-contract-and-the-systems-it-names),
which is left standing rather than rewritten.

**The proof.** `scripts/tests/test_sur1_live_bindings.py` starts the **real** order simulator on a
loopback port and reads `E1` back through the receiver — not a temporary table shaped like the
simulator's own, which is what it used to do. An amendment yields its command key, its previous
version and the changed line's item; an operator edit yields no command rather than an invented
one; a pre-incident event is excluded by `since`; a cut-short log is unreadable.

## 2 — the workspace origin is a scored requirement

**The gap.** `BindingConfig.workspace_origin` defaulted to the API's own base URL.
`api/routers/auth.py` matches `Origin` against `PP_CORS_ORIGINS` by exact string and that
allowlist names browser origins, so the default is answered `403`: arms B and C cannot sign in, no
plan can be approved, and `confirm` can never spend an approval — every attempt ends
`HARNESS_FAILURE`. `SUR1_WORKSPACE_ORIGIN` existed and worked, but it was not in
`REQUIRED_FOR_SCORED`, so `configuration()` passed without it and the failure surfaced as an
unreachable workspace rather than as the missing configuration it was.

**What changed.** The fallback is **removed rather than replaced** — there is no default this API
accepts, so there is nothing honest to fall back to. `SUR1_WORKSPACE_ORIGIN` is in
`REQUIRED_FOR_SCORED`, and a new preflight check `workspace_origin` asks three questions:

1. **set** — unset refuses the run, by name;
2. **well formed** — a scheme, a host and an optional port, and nothing else; the allowlist holds
   exact strings, so `http://localhost:55173/` is a different origin from `http://localhost:55173`
   and would be refused on a difference nobody could see in a log;
3. **accepted** — asked of the deployment itself, through an ordinary CORS preflight
   (`OPTIONS /api/auth/login` with the origin and the method a sign-in uses). An allowed origin is
   echoed back in `access-control-allow-origin`; a refused one is not. It is a read: it signs
   nobody in, creates no session and sends no credential.

The third question is asked by the surface that would do the signing in, not by the preflight
reaching for the API itself, for the reason the configuration module already states: *reading
configuration is not reaching a system; the probes that do that live on the bindings*. A surface
that cannot be asked **fails** the check — a scored run may not proceed on the assumption that a
sign-in would have worked.

The preflight is now **thirteen** checks and `REQUIRED_CHECKS` names all thirteen, so a
capability still cannot be minted from a report that is missing one.

## 3 — the nine worlds install into the live systems

**The gap.** The world programs were frozen against their own digests and proved *temporally*
executable at a run-local anchor. Neither is a statement about committed rows: a digest is taken
of the canonical `GraphSnapshot` **before** it is written, so a program that installed nothing at
all would still match one.

**What was done.** `scripts/check_sur1_realisation.py` installs each scenario into the running
local stack at the [ADR-0019](adr/0019-a-benchmark-world-is-installed-at-a-run-local-anchor.md)
run-local anchor, reads it back out of PostgreSQL and the order system's own endpoints, checks the
committed rows against the canonical snapshot the digest is taken of, derives the firing plan —
and stops. **No arm is constructed, no model called, no armed event fired.** An inert sink
satisfies `realise`'s refusal to prepare a world whose events nothing could deliver, and raises if
anything ever reaches it.

The run of 2026-09-19, at anchor `2026-09-19T15:00:00Z` in `Africa/Tunis`:

| scenario | | state | digest | armed, unfired |
|---|---|---|---|---|
| `C01` | auto-consent-block-and-silence | `READY` | `3fba40f0…` | 1 |
| `C02` | apparent-assent-is-not-consent | `READY` | `47754fcf…` | 2 |
| `C03` | the-substitute-exists-and-is-forbidden | `READY` | `561ed3c1…` | 1 |
| `C04` | an-exception-that-threatens-nobody | `READY` | `d19f4c6a…` | 0 |
| `C05` | an-external-change-before-the-incident | `READY` | `ab96bac1…` | 1 |
| `C06` | the-world-moved-between-the-yes-and-the-act | `READY` | `37809b78…` | 2 |
| `C07` | one-decision-delivered-twice | `READY` | `9af2aaa3…` | 1 |
| `C08` | the-oven-is-already-running | `READY` | `434131b8…` | 1 |
| `C09` | two-promises-one-bag-of-strawberries | `READY` | `8396cbda…` | 1 |

Every one agrees with the frozen declaration's published `world_digest`, and six facts are
compared between the canonical snapshot and the committed rows: commitment-line states, attested
stock on hand, the whole inventory ledger posting by posting, each order line's pinned recipe
version, each production task's state, and each order's version in the external order system. All
six agree for all nine.

**Isolation.** Ten residue tables — cases, exceptions, tracks, enqueued steps, plan approvals,
approval requests and decisions, outbox messages, accepted replies, timers — are read at every
scenario and are empty at every one. Then `C01` is installed a **second** time, after the other
eight have each installed and been read back, and its readback is compared with the one taken when
nothing had run before: **byte-identical**. A leak would have to survive a reset and then reproduce
itself exactly, which is not a way a leak behaves.

The benchmark's own `sur1:` inventory postings are deliberately **not** treated as residue. A
stipulated stock fact is part of a scenario's canonical world — it is in the snapshot the digest is
taken of — so such a row after an install is the world, not a leak. Whether the ledger holds
exactly what the scenario declares is asked as one of the six facts above, where it belongs.

The evidence is `docs/sur1-realisation/20260919T165013-realisation.json`, 161 KB, including every
readback. Both systems were put back to the Hollow Oak demo afterwards through each one's own
reset.

## 4 — the 240 seconds were a harness defect, and are gone

**The observation.** `dr01-g` recorded `243.531s` and `244.656s` for two attempts against a frozen
**300s** per-attempt wall-clock ceiling. The binding's own deadline is 240s.

**The cause, and it is one field.** `LiveWorkerSurface._settled` treats a case as stopped when
three consecutive `status` readings are *identical*, and it fingerprinted the whole answer. The MCP
server mints a fresh `correlation_id` per request and returns it on the result. Two readings of a
case that had not moved therefore **never** matched, `QUIET_READINGS` was unreachable, and every
wait ran to its deadline. Measured live: two consecutive `status` reads of one motionless case
differ in exactly `["correlation_id"]` and in nothing else.

It is a **harness defect**, not product latency, not a configuration mismatch, and not a driver
waiting after a terminal state it could have seen — the driver could not see it.

**A second defect in the same place.** The deadline was applied per wait rather than per attempt.
An attempt waits after `report`, after `clarify` and after `confirm`: three waits of 240s is 720s
against a 300s ceiling, so **yes, a valid attempt could exceed the frozen ceiling** while every
individual wait stayed inside a bound that was supposed to sit under it. The rehearsal's 243.5s was
already 81% of the ceiling spent on one wait.

**Both fixed, minimally.** The fingerprint reads the case and not the call — `correlation_id` is
named in `NOT_THE_CASE` as a field belonging to the request rather than to the case. The waiting
budget starts when the attempt opens its case and every later wait spends what is left of it.
Nothing about the settling rule itself changed: three quiet readings is still what *stopped* means.

**Measured, on the ordinary Hollow Oak demo world, both drives from the same reset world**
(`docs/sur1-realisation/20260919T165940-wait-measurement.json`; not a `SUR-1` scenario, no
arm, no model):

| | terminal wait after `confirm` | `status` calls | how it ended | whole attempt |
|---|---|---|---|---|
| with the fix | `6.55s` | 6 | three identical readings | `10.64s` waiting |
| with the fingerprint put back, deadline shortened to 30s | `25.14s` | 16 | the clock ran out | `31.24s` waiting |

The second row's terminal wait is the whole of what was left of its thirty seconds — which is the
attempt-wide deadline doing its job, and at the binding's real 240s it is four minutes, the
rehearsal's number. The first row's whole attempt — report, clarify, approve, confirm — spends
**ten and a half seconds** waiting, against a 300s ceiling.

**What is genuine product latency and is left alone.** The durable worker takes real time to do
real work; the terminal wait's first readings differ because the case is still moving, and the
surface stops three poll-seconds after the last change. That is as early as production truth
allows through this surface: the status projection publishes no terminal flag, so three identical
readings is the honest signal and it is unchanged.

## What this does not do

- **It takes no run.** No arm has been driven at a `SUR-1` scenario, no evidence bundle collected,
  no verdict produced and no number comparing any two arms exists.
- **It calls no model** and reads no AWS resource.
  `AUTHORISE-PAID-INFERENCE-SUR-1-COMPARATIVE` is unspent.
- **It edits no frozen document.** The manifest, the baseline prompt, the scorer and the
  predeclaration's rules are byte-for-byte what they were, and the world-program hashes still
  recompute. The predeclaration's disclosure gained a marked closure note beside the original
  paragraph, which is left standing because it was the reasoning at the time.
- **It authors and tunes no scenario.** The nine world programs are the frozen nine at their
  published digests; nothing about what a scenario stipulates was read, changed or consulted.
- **It touches no effect-set artefact.** `11/16` stands, `S12` stays committed failing.
- **Both evaluation holdouts stay sealed**, and neither was consulted.
- **It sits outside the gate structure.** `G8` is the open gate and this is not one of its
  required artifacts.

## What is still open before a scored `SUR-1` run

1. **A model this account can invoke**, and the spend authorisation, which is unspent.
2. **A different session.** The contract's freeze block is explicit that the building session is
   not the scoring session. This session prepared an environment; it did not score.
3. **The scored preflight has never been run against real bindings with a region set.** Checks 1,
   2 and 5–13 have been exercised; `model_identity` and the AWS half of `configuration` need an
   account this session did not touch.
