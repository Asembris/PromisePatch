# Can a judge take a turn? — the authority assessment, and why the answer is no

Date: 2026-09-16
Status: **NON-GO.** No code was written. No ADR was recorded. Nothing was deployed.

*The decision this assessment recommends is now recorded as
[ADR-0016](adr/0016-a-judge-principal-stays-read-only.md), which cites §3's measurement as its
evidence. The provisioning defect named in §5 is fixed in [the seeded demo case](seeded-demo-case.md).
Nothing below is edited: it is what that session found, in the words it found it in.*

The complaint this assessment was opened on is real and is stated accurately: the demo session
route mints an observer principal, an observer may read and may say nothing, and so a judge who
follows the judge entry cannot take a single one of the turns
[§5 of the judge UX contract](p7.1-judge-ux-contract.md) designs the conversation panel around.

The assessment was to establish from code whether that is a defect in *authority* — a principal
drawn too narrowly — and, if so, to widen it under a new ADR. It is not. The narrow principal is
load-bearing, for a reason [ADR-0013](adr/0013-read-only-observer-principal.md) did not record and
this assessment establishes by running the system: **the first turn of the journey is a physical
attestation, and a physical attestation is authority over the one shared bakery rather than
authority over the speaker's own case.** Granting it to a visitor puts false claims about
deliveries that have not happened yet onto a ledger that survives every reset.

What follows is what the code showed, what the experiment showed, and what is actually broken —
which is a different thing, in a different place, and is named at the end.

## 1. What the demo session mints, and what that principal may do

`POST /api/auth/demo-session` ([`auth.py`](../apps/backend/src/promisepatch/api/routers/auth.py))
takes **no request model at all**, finds the sole `workers` row holding the `observer` role, and
issues a session naming it with a 60-minute TTL (`sessions.OBSERVER_SESSION_TTL`), an `Origin`
check and its own per-client rate limiter. The row is `judge`, seeded by
[`fixtures/demo.py`](../apps/backend/src/promisepatch/fixtures/demo.py) with
`UNUSABLE_PASSWORD_HASH = "!"`, which Argon2 cannot parse, so `POST /api/auth/login` can never
admit it. The only way to hold the identity is a session the server chose to issue.

What it may do is decided in one module,
[`domain/intake.py`](../apps/backend/src/promisepatch/domain/intake.py), and the three answers are
closed:

| function | admits | the observer |
|---|---|---|
| `require_attestor` | anybody whose `may_attest(role)` is true | **refused** — it is the only role for which `may_attest` is false |
| `require_permitted` | the worker who opened the case, or an owner | **refused first and unconditionally**, before the opener branch |
| `require_readable` | whoever `require_permitted` admits, **or** an observer | **admitted** |

`require_readable` is used by `GET /api/cases/{id}` and by nothing else. Every write in the system
— the CLI, the intent API behind the MCP tools, `/api/conversation/*`, `recovery.confirm_plan`,
`withdrawal` — passes through `require_permitted`, which contains no observer branch to widen. The
read widening cannot reach a write, which is exactly the property ADR-0013 §2 was built to have.

The screen is told rather than left to infer: `may_speak` and `permitted_verbs` are fields on the
case response, `Conversation.tsx` draws controls from them and reads no role, and an observer gets
the sentence *"You are looking at this case. Changing it is the bakery's to do."*
(`conversation-read-only`).

## 2. Why ADR-0013 chose read-only, and whether the reasoning holds

ADR-0013's recorded reasoning is about **impersonation and about not weakening a shared check**. It
rejected published credentials (a standing credential in a public repository), a judge session as
`maya` or `jo` (owner impersonation, and a judge could confirm a plan), a `scope` column on an
ordinary worker session (the session still names a real worker, so a leak of the scope check
becomes an attributed write), and removing the gate from the read path (it is the check P5.1–P5.4
deliberately share with the MCP surface).

Every one of those still holds. **But none of them is the binding reason**, and that matters,
because all four are satisfied by an obvious-looking design that this assessment was opened to
build: a fresh `guest` principal per demo session, admitted to nothing but the case it opens
itself. That design needs **no change to `require_permitted` at all** — its existing opener branch
already refuses one guest another guest's case, and
`test_another_baker_may_not_speak_on_somebody_elses_case` already pins it. It names no real
worker, publishes no credential, and leaves the actor server-derived and the `plan_id` binding
untouched.

It fails on the bar ADR-0013 never wrote down, and §3 is how that was established.

## 3. The experiment: what the second and third judge actually get

The journey's first verb is `report`, and `report` is `intake.open_physical_exception` — a worker
putting a claim about the kitchen on the record. The core invariant is explicit that this is not
case-local: *"Physical facts (received / not received / spoiled / equipment out) are authoritative
independently of recovery authorization... only an explicit correcting attestation reverses a
fact."*

So the question is not whether a guest can be confined to its own case. It is what a guest's
attestation does to everybody else's. Three successive principals were driven through the
canonical journey against one shared Hollow Oak fixture, through the real services and a real
worker process, offline, with the deterministic semantic provider — `report`, drain, the
clarifying answer, drain — and the `commitment_lines` were read between each.

```text
start          cl-vp-today-raspberries EXPECTED      cl-vp-today-strawberries EXPECTED
               cl-vp-tomorrow-raspberries EXPECTED   cl-vp-tomorrow-blueberries EXPECTED

judge 1  asks  "The Valley Produce delivery also includes strawberries.
                Did the whole delivery fail, or just the raspberries?"
         after cl-vp-today-raspberries NOT_RECEIVED  cl-vp-today-strawberries RECEIVED

judge 2  asks  "The Valley Produce delivery also includes BLUEBERRIES.
                Did the whole delivery fail, or just the raspberries?"
         after cl-vp-tomorrow-raspberries NOT_RECEIVED  cl-vp-tomorrow-blueberries RECEIVED

judge 3        state=NEEDS_HUMAN_INTERPRETATION, no question asked
```

Read the middle row carefully, because it is the finding.

**Judge 2 did not get a degraded copy of judge 1's demo. Judge 2 attested that a delivery which
has not happened yet failed.** Today's raspberry line was already settled by judge 1, so the only
open raspberry commitment left was *tomorrow's*; the interpreter resolved "today's raspberry
delivery didn't arrive" against it entirely correctly, asked its scope question about tomorrow's
blueberries, and judge 2's answer settled tomorrow's raspberries `NOT_RECEIVED`.

The classification judge 2 saw was **identical to judge 1's** — `pr-a` `AUTO_RECOVERABLE`, `pr-b`
`APPROVAL_REQUIRED`, `pr-c`/`pr-d` `BLOCKED`, `pr-e`/`pr-f` `UNAFFECTED` — which is precisely what
makes it unsafe. Nothing on the screen distinguishes the real demo from a visitor having condemned
tomorrow's delivery. Run with `confirm` included, judge 2's case reached `RESOLVED` with `pr-a`
`RECOVERED` and `pr-b` merely `LINKED`, because the approval request judge 1 had already sent was
still open and the system correctly declined to send the customer a second message.

**Judge 3 gets nothing.** With no open raspberry commitment left, the sentence resolves to nothing,
the case dead-ends at `NEEDS_HUMAN_INTERPRETATION`, and `answer_clarification` refuses with
`NotAwaitingClarificationError` because there is no question to answer. This is the same dead end
the demo case recipe warns an operator about, reached by a visitor doing nothing wrong.

Dropping `confirm` from the guest's verbs does not save it. The run above was repeated with
`report` and `clarify` only, no confirmation and therefore **zero operational effects**, and the
outcome was the same: judge 1 canonical, judge 2 condemning tomorrow's delivery, judges 3 and 4
dead at `NEEDS_HUMAN_INTERPRETATION`. The damage is done by intake, not by authorisation, because
settling a commitment line *is* the physical record moving.

And it is not erasable. `audit_events` and `domain_events` are outside the reset set and are
refused truncation by trigger regardless
([`fixtures/reset.py`](../apps/backend/src/promisepatch/fixtures/reset.py)) — which is the right
design and exactly why this matters: a visitor's false claim about tomorrow's delivery is in the
ledger of record permanently, attributed to a worker identity, and reversible only by an explicit
correcting attestation that is reachable only from the CLI.

## 4. The NON-GO, stated against the bar it fails

The bar included: *a judge cannot act on anything but their own case*, and *one judge cannot leave
the product broken for the next*. A physical attestation is, by the core invariant, authority over
the shared bakery and not over the speaker's case. So letting a judge take the journey's first turn
**is** widening what a principal may do beyond its own case — which is the stated NON-GO condition,
reached from a frozen invariant and a measurement rather than from preference.

The only designs that would close it require per-visitor isolation of the *physical* data, not of
the case:

- **A namespaced universe per visitor.** The projection is id-driven and could emit prefixed rows,
  but every read above it is whole-table and unscoped: `graph/loader.py` builds the snapshot with
  `select(table)` per table, and the interpreter's own commitment read is
  `select(CommitmentLine).order_by(CommitmentLine.id)` with no filter
  ([`physical.py`](../apps/backend/src/promisepatch/domain/physical.py)). A second universe in the
  same tables would be loaded into the same snapshot, two visitors' identically-worded reports
  would cross, and every classification would run over a doubled graph. Scoping that is tenancy
  across the domain, in a system frozen as one bakery with one store.
- **A reset on session issue.** Destroys a concurrent visitor's live case, or, if guarded on "no
  live session", degrades to a probabilistic guarantee. The measurement above says the shared
  fixture tolerates exactly two journeys, and two is an accident of this dataset, not a bound.
- **A pool of pre-built cases.** Each one is built by attesting the same fact again, which is the
  thing that broke at three.

None of these is a widening of a principal. All of them are a change to the frozen architecture,
and CLAUDE.md is explicit that such a change amends an ADR before it is built, in a session scoped
to it. **So this closes with the recommendation ADR-0013 already implies: the judge principal stays
read-only, and its reasoning is now recorded with the evidence it was missing.**

## 5. Isolation today, and what the tenth judge sees

**Isolation today is trivially total, because nothing can interfere.** Every demo visitor holds a
*distinct session row* naming the *same* `judge` principal. `GET /api/cases` applies no permission
filter at all — every authenticated caller sees every case, newest first — and `require_readable`
admits an observer to any of them, so every visitor sees the same cases as every other. None of
that is a leak, because the principal can write nothing and there is no per-visitor state to leak.
It survives any number of visitors: the rate limiter is keyed per client address, so two judges do
not contend unless they share one address, and the only shared resource is the read path.

**The tenth judge sees exactly what the first judge saw** — and that is the actual problem, because
what the first judge sees may well be nothing.

`GET /api/cases` is **empty after `pp reset-demo-state`**: the fixture seeds orders, promises,
resources and staff, but **no case**. A case exists only once somebody reports an exception, and
nothing in the product does that — it is the CLI recipe, run by hand, and any `docker compose up`
re-runs the seed service and erases it. The judge entry's own frontend already has a test for the
outcome, `says there is nothing to look at rather than pressing into an empty list`.

So the judge entry is one deliberate action that reaches a real case **only if an operator
happened to build one beforehand and nothing has reset the deployment since**. That is a
provisioning defect, not an authority defect, it is squarely within "let a judge actually operate
the deployed product", and it is the thing worth fixing next. Fixing it needs no new principal and
no widening of anything: it is the question of how the demo deployment comes up with a case already
open, under an identity that is already allowed to attest — which is what `maya` is for.

## 6. What this assessment did not do

Nothing was deployed, no AWS resource was read or mutated, and the live host was not touched. No
authority check was changed, weakened or added. No test was weakened, skipped or deleted, and no
test was added — the runs above were a throwaway file, deleted, and are reproducible from the
description in §3. No model was called; the semantic provider was the deterministic fake. The
effect-set scenarios, the manifest and every frozen document are untouched. The local demo database
was restored with `pp reset-demo-state` after the experiment.
