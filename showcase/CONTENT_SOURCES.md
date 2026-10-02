# Content sources

Every claim and number the showcase displays, and the committed repository record it comes from.
This ledger adds no claim; it points to where each one already lives. Paths are relative to the
repository root on `main`; the product is frozen at release `740a062`, image `740a062838e0`. "README §X" is the heading of that name
in `README.md`.

The frozen facts are typed once, in [`src/data/facts.js`](src/data/facts.js), each with its
`source`; `tools/verify-content.mjs` checks every value appears in the built page with its caveat
nearby and that every cited path exists. Links are listed once, in
[`src/data/links.js`](src/data/links.js), and checked offline by `tools/verify-links.mjs`.

## Frozen facts

| On the page | Value | Caveat shown with it | Source |
|---|---|---|---|
| Release SHA (AWS, CI card, footer) | `740a062838e0ea2620499abed27d653c42fc05f7` · `740a062` | the image tag is the commit's first twelve characters; earlier releases (`283f63f2845f`, the G8 freeze `56c3023` / `4529a802e34e`) are historical | `docs/bridge-release.md`; README §The release that runs now |
| Deployed product/image SHA | `740a062838e0` | reported by `GET /healthz` | `docs/bridge-release.md` §Deployment; README §The release that runs now |
| v1 effect-set headline | 11/16, PERMANENT HEADLINE | first scored run, frozen v1, hand-labelled, five failed, never replaced | `docs/effect-set-first-scored-run.md`; `docs/g8-effect-set-release-condition.md` §1; the "hand-labelled before the runner existed" caveat: README §Measured evidence and `docs/effect-set-manifest.md` ("Authored in P5, before the runner exists"), not the run protocol, whose own "before the runner existed" `docs/claims-audit.md` shows to be false |
| v2 release condition | 16/16, SEPARATE RELEASE CONDITION | separately versioned label correction; one label moved (S12's hold); taken once on the current release; the original benchmark did not become 16/16 | `docs/g8-effect-set-release-condition.md` §5–7; `docs/bridge-release.md` §Release checks; `docs/adr/0017-a-blocked-promise-does-not-hold-a-started-task.md` |
| Effect-set scope | developer-authored, finite and public, not an independent benchmark; the effect-set CI stays red on purpose | — | README §Measured evidence |
| Rehearsals | 5/5 on `740a062838e0` | one fixture measured five times; not a reliability rate | `docs/bridge-release.md` §R1–R5; `docs/g8-demo-funnel.md` §2, §3; the first five, historical: `docs/g8-rehearsal-r1.md` … `r5.md` |
| Untouched orders | 0/2 in each of five | per rehearsal 2 amendments · 1 message · 2 task holds · 3 outbox rows, attempt 1 | `docs/g8-demo-funnel.md` (effect counts); README §Measured evidence |
| Funnel | 6 promises → 1 auto-recovered · 1 customer-approved · 2 owner-escalated · 2 untouched | — | `docs/g8-demo-funnel.md` §1 |
| Voice | 9/10 | run 2; run 1 (1/10) voided after computation; best-of-two; local stack; not a latency SLA | `docs/g7-ten-turn-voice-measurement.md`; README §Measured evidence; "best-of-two": `docs/claims-audit.md` (F2) |
| Release CI | 13/13, `pr` run `36925136266` | whole-stack browser job included | `docs/bridge-release.md` §Release and CI; README §The release that runs now |
| MCP | revision `2025-11-25`, Streamable HTTP, five intent tools; one live MCP `confirm` spent a browser approval and created none | not a native Alexa+ integration | `docs/p5.1-mcp-transport-spine.md`; `docs/alexa-mcp-confirm-proof.md`; README §Alexa+, Bedrock and MCP |
| Zero model calls | the canonical report costs zero model calls, and a test asserts it | — | README §How authority works; `docs/semantic-boundary.md` |
| AWS stack | EC2 `t4g.small`, `us-east-1`, Caddy + Let's Encrypt, private encrypted RDS, Bedrock Nova 2 Lite via instance role, IMDSv2, no AWS key | — | README §AWS deployment; `docs/p6.2-first-deployment.md`; `docs/adr/0007-runtime-semantic-model-nova-2-lite.md` |
| Feature freeze | declared 2026-10-02 | a later product-path change voids it | `docs/bridge-release.md` §Verdict; README §License |

## Product boundaries

| On the page | Source |
|---|---|
| Telegram is outbound only; one message per rehearsal | `docs/deployed-customer-channel.md`; README §AWS deployment; the per-rehearsal count: `docs/g8-demo-funnel.md` §1–2 |
| Customers answer through the signed web link; it proves possession, not identity | `docs/customer-approval-link.md`; `docs/adr/0021-a-customer-answers-on-the-web-and-their-address-stays-in-the-database.md` |
| Telegram inbound is deliberately not built | `docs/customer-message-transport.md`; README §Honest limitations |
| The Alexa+-style experience is simulated: a panel drives a case-scoped MCP client on the server; not native | README §Alexa+, Bedrock and MCP; `docs/adr/0028-a-simulated-alexa-turn-is-a-case-scoped-mcp-client-on-the-server.md` |
| Customers, recipes and the order system are fixtures and a simulator; the Telegram message and web approval are real | README §Honest limitations; `docs/order-system.md`; `docs/seeded-demo-case.md` |
| One refusal kind exercised live, once: `STALE`, through check 2, on `740a062838e0`, with no amendment for that order; the other checks refusing, EXPIRED, UNAUTHORIZED, NOOP and the commit-time freshness gate proved by tests only | README §Honest limitations; `docs/revalidation-proof.md` |
| Telegram's Bot API has no idempotency key; a retry can deliver a duplicate message, never a second amendment | `docs/customer-message-transport.md` ("`sendMessage` has no idempotency key"); `apps/backend/src/promisepatch/domain/recovery.py` module docstring (at-least-once under a stable key) |
| MCP intake is a trusted reporting channel: a report is attested as the server's configured worker (`PP_SURFACE_WORKER_ID`), not by an authenticated person | `docs/p5.1-mcp-transport-spine.md` (Identity; "One surface worker"); `apps/backend/src/promisepatch/api/routers/intents.py` module docstring (`attested_by=worker_id`) |
| "If the substitute had run out" is an illustration, not a recorded run | design copy, labelled on the page; the substitute check refusing is covered only by tests, and the one live STALE failed check 2, not this check (row above) |

## Sections

| Section | What it shows | Source |
|---|---|---|
| 01 Hero | thesis, subhead, eyebrow; "Look around a real case" is read-only | README title block; `brand/promisepatch-brand-sheet.svg`; README §60-second judge path; `docs/adr/0016-a-judge-principal-stays-read-only.md` |
| 01 Hero subhead | the customer-level lede: only a swap the customer already agreed to, or one they approve now; the rest to the owner; unreached orders untouched | design copy summarising README §What PromisePatch does and §The canonical scenario (lanes AUTO, ASK, BLOCKED, UNAFFECTED); no new claim |
| 01 Hero captions | step 5 "Conditions can change while an answer waits"; step 6 "Before the change is committed" | design copy for why revalidation exists (`apps/backend/src/promisepatch/domain/revalidation.py` docstring: "the customer approved what used to be true"), not a statement about R3: the recorded run shows durable waiting, not a changed world (`docs/deployed-customer-channel.md` §11; `docs/g8-rehearsal-r3.md` §8) |
| 02 Problem | the bakery, the missing raspberries, four questions | README §The problem |
| 03 Six promises | seven stages (`src/data/stages.js`), the 6 × 7 matrix (`rows.js`), order details (`detail.js`), the clarification "just raspberries — the strawberries came" | README §What PromisePatch does, §The canonical scenario; `docs/seeded-demo-case.md`; `docs/g8-demo-funnel.md` §1; `docs/g8-rehearsal-r3.md` §6–9 |
| 03 Stages 4–5 | the plan approved in a signed-in browser session or on the operator console (the G8 rehearsals used the console, the current release's the browser); the owner acted as the demo customer | `docs/g8-rehearsal-r3.md` §2 ("the owner presses APPROVE on the signed link"), §6 ("exactly one, `channel=OPERATOR_CONSOLE`"); `docs/adr/0018-a-plan-confirmation-spends-a-human-approval.md` |
| 03 Untouched effects | no message, no write, no reservation change, no task hold, no audit event | README §What PromisePatch does |
| 04 Authority | the model proposes interpretations only and cannot write a row, record consent, approve a plan or choose a recovery; a fact it helps read is recorded as the reporting worker's; two approvals never interchange; pre-authored recipes; fail closed to BLOCKED; import-linter contracts | README §How authority works; `docs/semantic-boundary.md` §Who attested what; `docs/adr/0018-a-plan-confirmation-spends-a-human-approval.md` |
| 04 Plan approval channels | a signed-in browser session or the operator console; never MCP | `apps/backend/src/promisepatch/domain/plan_approval.py` (`ApprovalChannel`: `BROWSER_SESSION`, `OPERATOR_CONSOLE`); `docs/adr/0018-a-plan-confirmation-spends-a-human-approval.md` |
| 04 Customer consent | a literal `YES` or `NO`, trimmed and case-insensitive; any other reply decides nothing. No option code: the parser deliberately does not implement one | `apps/backend/src/promisepatch/domain/consent.py` (`read_literal`, and its docstring on the option code); `docs/adr/0008-remove-runtime-customer-intent-classifier.md` |
| 04 MCP rule | MCP intake is a trusted reporting channel under the configured worker; an MCP confirm spends an approval a person already wrote | `docs/p5.1-mcp-transport-spine.md`; `docs/mcp-human-confirmation-boundary.md`; `apps/backend/src/promisepatch/api/routers/intents.py` |
| 05 Revalidation | historical: rehearsal R3 of the G8 freeze on `4529a802e34e`, labelled as such; R3 timeline 20:27:10 → 20:31:03; "3 min 35 s after it stopped" is the stopped window (container `FinishedAt` 20:27:23.607 → `StartedAt` 20:30:58.991); "2 min 29 s after the press" is how long the stored answer waited (20:28:31.492 → taken up 20:31:00.972); the owner pressed APPROVE as the demo customer; ten checks and values (`src/data/checks.js`), the deadline shown with both dates (`20:31:01Z ≤ 2026-09-25T01:26:54Z`); AUDIT 503–512, snapshot 20:31:01.207Z | `docs/g8-rehearsal-r3.md` §2, §4, §9 |
| 05 "A yes is perishable" | the ten checks run on arrival and guard the commit; checks 2–6 failing is `STALE`, nothing sent, that track re-planned; an expired answer escalates to the owner, an unauthorized one is refused; after the commit only the production start is judged again, at the amendment's first dispatch | `apps/backend/src/promisepatch/domain/revalidation.py` (module docstring and the outcome mapping); `docs/adr/0024-freshness-is-judged-where-the-effect-is-committed.md`; `docs/adr/0025-an-answer-is-revalidated-when-it-arrives.md`; `docs/adr/0026-a-first-dispatch-that-provably-sends-nothing-is-judged-again.md` |
| 05 Live STALE | on the current release a v1 yes was refused as `STALE` at check 2 once the order was at v2; no amendment reached that order | `docs/revalidation-proof.md` |
| 06 Evidence | the facts above; R1–R5 restart points (`src/data/rehearsals.js`) | `docs/bridge-release.md` §R1–R5; `docs/g8-demo-funnel.md` §2 |
| 07 Architecture | nodes, edges and traces (`src/data/arch.js`, `traces.js`); solid = authority, dashed = understanding | README §Architecture |
| 08 AWS | spec list, the release and image SHAs, the earlier releases named as historical | README §The release that runs now; `docs/bridge-release.md`; `docs/g8-closeout.md` |
| 09 Proof index | thirteen rows (`src/data/proofs.js`), claims lightly shortened; "every effect recorded once and delivered on attempt 1" is the rehearsals' recorded result, not a delivery guarantee | README §Proof index; `docs/g8-demo-funnel.md` ("outbox exactly 3, attempt 1, 3 keys") |
| 09 Limitations | "What the numbers do not say" | README §Honest limitations; `docs/claims-audit.md` |
| 10 Final CTA | "When reality changes, permission must be checked again." | design copy summarising README §How authority works; no new claim |
| Footer | Apache-2.0; freeze from `740a062` | `LICENSE`; README §License |

## Deferred

The demo video and Devpost have no URL. They appear only as `aria-disabled` placeholders with no
`href` (Devpost not at all), and `verify-content` / `verify-links` fail if either gains a link.
