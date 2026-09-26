# G8 demo funnel — measured, from the five deployed rehearsals

Date: **2026-09-26**. This page reports the funnel G8 asks for: *"total orders -> threatened [auto
/ consent / blocked] + untouched -> actually recovered / waiting / escalated … 0/U untouched
orders receiving incident-caused operational effects, plus effect counts (amendments, messages,
reservations, task holds)."*

Every number below is copied from the five committed rehearsal records. All five ran on the
deployed release candidate `4529a802e34e` and read the untouched state through the frozen
evidence reader `c9731c8f…0dd4`. **Nothing was run, restored, sent or measured to write this
page.** No count is averaged, summed across rehearsals, estimated or inferred.

## 1. The funnel, per rehearsal

All five rehearsals recorded identical counts, so one column serves for all of them. §2 shows
where each count is recorded, rehearsal by rehearsal.

```text
total orders                         6      ord-a … ord-f  (EXT-A … EXT-F)

threatened                           4
  auto-repairable                    1      pr-a  AUTO_RECOVERABLE   R-PREAPPROVED
  consent-required                   1      pr-b  APPROVAL_REQUIRED  R-VISIBLE-ASK
  blocked                            2      pr-c  BLOCKED  R-NOSUB (NOSUB_CONSTRAINT)
                                            pr-d  BLOCKED  R-NOSUB (NO_PREAUTHORED_VARIANT)
untouched (U)                        2      pr-e, pr-f  UNAFFECTED  R-UNREACH

at CONFIRMED                                 at SETTLED (case RESOLVED)
  recovered   1   pr-a                         recovered   2   pr-a, pr-b
  waiting     1   pr-b  WAITING_FOR_CUSTOMER    waiting     0
  escalated   2   pr-c, pr-d                   escalated   2   pr-c, pr-d
```

**Untouched: 0/2.** No order in the predeclared case-baseline untouched set `{pr-e, pr-f}`
received an incident-caused operational effect, in any of the five rehearsals.

### Effect counts, per rehearsal

| effect | count | identity |
|---|---|---|
| recovery amendments | **2** | `ORDER_AMEND` ×2: `EXT-A` v1 → v2 (`almond-4`, under `CONSTRAINT`) and `EXT-B` v1 → v2 (`rose-3`, under `HUMAN_APPROVAL`) |
| customer messages | **1** | `MESSAGE_SEND` ×1 to the one bound customer, Telegram `sendMessage` +1 |
| task holds | **2** | `task-ol-c`, `task-ol-d` `HELD`; `task-ol-e` `STARTED` and **never held** |
| outbox rows in total | **3** | all `DELIVERED` at attempt 1, 3 distinct idempotency keys |
| on untouched orders (`pr-e`/`pr-f`) | **0 / 0 / 0 / 0** | attributed audit rows / domain events / outbox rows / approval requests |
| reservation changes on untouched orders | **0** | reservations are a component of the untouched digest, equal from `PLANNED` to `SETTLED` |
| reservation changes on threatened orders | **not recorded** | the frozen reader does not scope `pr-a`–`pr-d` reservations, and no record counts them. They are not reported here |

**Attribution.** Effects are attributed by the case's own track, command and idempotency identity
through the frozen reader:

- audit rows on the untouched tracks;
- domain events whose `entity_refs` name any untouched promise, order, line, task or customer id;
- outbox payloads naming them;
- approval requests on their promises.

Two things are excluded:

- the fixture's own load, since each count runs from the fixture's `loaded_at`;
- the independent External Order System, whose store is read directly. `EXT-C`…`EXT-F` stayed at
  v1 `ACCEPTED` in the mirror and in the store.

Analysis and audit writes on the threatened tracks are permitted, and they are not the claim.

## 2. Where each count is recorded

| | R1 | R2 | R3 | R4 | R5 |
|---|---|---|---|---|---|
| record | [r1](g8-rehearsal-r1.md) | [r2](g8-rehearsal-r2.md) | [r3](g8-rehearsal-r3.md) | [r4](g8-rehearsal-r4.md) | [r5](g8-rehearsal-r5.md) |
| verdict | PASS 1/5 | PASS 2/5 | PASS 3/5 | PASS 4/5 | PASS 5/5 |
| restart point | waiting for consent | across confirmation | across the answer | after `RESOLVED` | waiting for consent |
| case | `e66069d7-…` | `75dd110e-…` | `7654d9d7-…` | `43b75690-…` | `714aafc6-…` |
| partition at `PLANNED` 1/1/2 + 2 | §6 | §6 | §6 | §6 | §6 |
| `pr-a`, `pr-b` `RECOVERED`; case `RESOLVED` | §9 | §10 | §9 | §7 | §8 |
| `pr-c`/`pr-d` `ESCALATED`, `task-ol-c`/`-d` `HELD` | §7 | §8 | §6 | §6 | §6 |
| outbox exactly 3, attempt 1, 3 keys | §10 | §11 | §10 | §10 | §9 |
| `sendMessage` +1 | 1 → 2 | 2 → 3 | 3 → 4 | 4 → 5 | 5 → 6 |
| untouched digest, `PLANNED` = `SETTLED` | `ef_digest` `22982845…` | `ef_digest` `4819055d…` | `ef_digest` `a0290acc…` | `pr-e`/`pr-f` digest `adfa6ac1…` | `ef_digest` `be01fc89…` |
| attribution to `pr-e`/`pr-f` | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 | 0/0/0/0 |
| `EXT-C`…`EXT-F` v1 in mirror and store | yes | yes | yes | yes | yes |

Section numbers refer to each rehearsal record's own headings. The worker's lifetime `sendMessage`
counter rises by exactly one per rehearsal, from 1 to 6. No run is hidden, and none failed or was
voided ([g8-remaining-gaps-audit.md](g8-remaining-gaps-audit.md) §6).

## 3. What this is, and what it is not

- **The canonical six-order demo world, measured five times.** It is one fixture, the Hollow Oak
  bakery, restored from clean before each rehearsal. It is not a population, and "five times"
  supports repeatability of the demo, not a reliability percentage.
- **Real transport, labelled fixtures.** Each rehearsal delivered one real Telegram message, and
  the owner answered it on the web through the signed link. The orders, recipes and order system
  are the labelled demo fixture and simulator.
- **Settled outcomes, not plans.** "Recovered" means the external order system's own store holds
  the amendment and the mirror converged. "Escalated" means the track went to the owner with its
  scheduled kitchen work held. Started work is never held
  ([started-work-contract.md](started-work-contract.md)).
- **The effect-set suite measures the same funnel shape locally.** Its S16 scenario is this
  world's checkpoints, and it passed both scored runs. That is separate, local evidence.
  [g8-effect-set-release-condition.md](g8-effect-set-release-condition.md) has it. This page
  reports only the deployed rehearsals.
