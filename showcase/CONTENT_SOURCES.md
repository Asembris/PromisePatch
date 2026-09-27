# Content sources

Every claim and number the showcase displays, and the committed repository record it comes from.
This ledger adds no claim; it points to where each one already lives. Paths are relative to the
repository root on `main`, frozen at release `56c3023`. "README §X" is the heading of that name
in `README.md`.

The frozen facts are typed once, in [`src/data/facts.js`](src/data/facts.js), each with its
`source`; `tools/verify-content.mjs` checks every value appears in the built page with its caveat
nearby and that every cited path exists. Links are listed once, in
[`src/data/links.js`](src/data/links.js), and checked offline by `tools/verify-links.mjs`.

## Frozen facts

| On the page | Value | Caveat shown with it | Source |
|---|---|---|---|
| Release SHA (AWS, CI card, footer) | `56c302366b3ddc0d824c1588a4a9ddbd193ed891` · `56c3023` | two different commits; deployable product paths tree-identical | `docs/g8-closeout.md` §2, §3, §5; README §AWS deployment |
| Deployed product/image SHA | `4529a802e34e` | reported by `GET /healthz` | `docs/g8-closeout.md` §3; `docs/phase7-approval-log-privacy-repair.md` |
| v1 effect-set headline | 11/16, PERMANENT HEADLINE | first scored run, frozen v1, hand-labelled, five failed, never replaced | `docs/effect-set-first-scored-run.md`; `docs/g8-effect-set-release-condition.md` §1 |
| v2 release condition | 16/16, SEPARATE RELEASE CONDITION | separately versioned label correction; one label moved (S12's hold); product-identical; the original benchmark did not become 16/16 | `docs/g8-effect-set-release-condition.md` §5–7; `docs/adr/0017-a-blocked-promise-does-not-hold-a-started-task.md` |
| Effect-set scope | developer-authored, finite and public, not an independent benchmark; the effect-set CI stays red on purpose | — | README §Measured evidence |
| Rehearsals | 5/5 on `4529a802e34e` | one fixture measured five times; not a reliability rate | `docs/g8-rehearsal-r1.md` … `r5.md`; `docs/g8-demo-funnel.md` §2, §3 |
| Untouched orders | 0/2 in each of five | per rehearsal 2 amendments · 1 message · 2 task holds · 3 outbox rows, attempt 1 | `docs/g8-demo-funnel.md` (effect counts); README §Measured evidence |
| Funnel | 6 promises → 1 auto-recovered · 1 customer-approved · 2 owner-escalated · 2 untouched | — | `docs/g8-demo-funnel.md` §1 |
| Voice | 9/10 | run 2; run 1 (1/10) voided after computation; best-of-two; local stack; not a latency SLA | `docs/g7-ten-turn-voice-measurement.md`; README §Measured evidence |
| Release CI | 13/13, `pr` run `36310794944` | whole-stack browser job included | `docs/g8-closeout.md` §2; README §Measured evidence |
| MCP | revision `2025-11-25`, Streamable HTTP, five intent tools | not a native Alexa+ integration | `docs/p5.1-mcp-transport-spine.md`; README §Alexa+ and MCP |
| Zero model calls | the canonical report costs zero model calls, and a test asserts it | — | README §How authority works; `docs/semantic-boundary.md` |
| AWS stack | EC2 `t4g.small`, `us-east-1`, Caddy + Let's Encrypt, private encrypted RDS, Bedrock Nova 2 Lite via instance role, IMDSv2, no AWS key | — | README §AWS deployment; `docs/p6.2-first-deployment.md`; `docs/adr/0007-runtime-semantic-model-nova-2-lite.md` |
| Feature freeze | declared 2026-09-27 | a later product-path change voids it | `docs/g8-closeout.md` §5; README §License |

## Product boundaries

| On the page | Source |
|---|---|
| Telegram is outbound only; one message per rehearsal | `docs/deployed-customer-channel.md`; README §AWS deployment |
| Customers answer through the signed web link; it proves possession, not identity | `docs/customer-approval-link.md`; `docs/adr/0021-a-customer-answers-on-the-web-and-their-address-stays-in-the-database.md` |
| Telegram inbound is deliberately not built | `docs/customer-message-transport.md`; README §Honest limitations |
| The Alexa+-style experience is simulated by MCP clients; not native | README §Alexa+ and MCP |
| Customers, recipes and the order system are fixtures and a simulator; the Telegram message and web approval are real | README §Honest limitations; `docs/order-system.md`; `docs/seeded-demo-case.md` |
| No refusal path exercised live; STALE, EXPIRED, UNAUTHORIZED, NOOP proved by tests only | README §Honest limitations; `docs/deployed-customer-channel.md` §11 |
| "If the substitute had run out" is an illustration, not a recorded run | design copy, labelled on the page; the refusal it depicts is covered only by tests (row above) |

## Sections

| Section | What it shows | Source |
|---|---|---|
| 01 Hero | thesis, subhead, eyebrow; "Look around a real case" is read-only | README title block; `brand/promisepatch-brand-sheet.svg`; README §60-second judge path; `docs/adr/0016-a-judge-principal-stays-read-only.md` |
| 02 Problem | the bakery, the missing raspberries, four questions | README §The problem |
| 03 Six promises | seven stages (`src/data/stages.js`), the 6 × 7 matrix (`rows.js`), order details (`detail.js`), the clarification "just raspberries — the strawberries came" | README §What PromisePatch does, §The canonical scenario; `docs/seeded-demo-case.md`; `docs/g8-demo-funnel.md` §1; `docs/g8-rehearsal-r3.md` §6–9 |
| 03 Untouched effects | no message, no write, no reservation change, no task hold, no audit event | README §What PromisePatch does |
| 04 Authority | model cannot write, record consent, attest or choose; two approvals never interchange; pre-authored recipes; fail closed to BLOCKED; import-linter contracts | README §How authority works; `docs/semantic-boundary.md`; `docs/adr/0018-a-plan-confirmation-spends-a-human-approval.md` |
| 05 Revalidation | R3 timeline 20:27:10 → 20:31:03, "2 min 29 s"; ten checks and values (`src/data/checks.js`); AUDIT 503–512, snapshot 20:31:01.207Z | `docs/g8-rehearsal-r3.md` §4, §9 |
| 05 "A yes is perishable" | a stale change is refused and re-planned | README §How authority works |
| 06 Evidence | the facts above; R1–R5 restart points (`src/data/rehearsals.js`) | `docs/g8-demo-funnel.md` §2; `docs/g8-rehearsal-r1.md` … `r5.md` |
| 07 Architecture | nodes, edges and traces (`src/data/arch.js`, `traces.js`); solid = authority, dashed = understanding | README §Architecture |
| 08 AWS | spec list and the two SHAs | README §AWS deployment; `docs/g8-closeout.md` §3 |
| 09 Proof index | ten rows (`src/data/proofs.js`), claims lightly shortened | README §Proof index |
| 09 Limitations | "What the numbers do not say" | README §Honest limitations; `docs/claims-audit.md` |
| 10 Final CTA | "When reality changes, permission must be checked again." | design copy summarising README §How authority works; no new claim |
| Footer | Apache-2.0; freeze from `56c3023` | `LICENSE`; README §License |

## Deferred

The demo video and Devpost have no URL. They appear only as `aria-disabled` placeholders with no
`href` (Devpost not at all), and `verify-content` / `verify-links` fail if either gains a link.
