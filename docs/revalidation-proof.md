# Revalidation proof on the frozen release, 2026-10-02

One deployed demonstration of PromisePatch's core claim: **a recovery is applied only if the world
it was approved against is still the world.** It used two runs on the frozen product
`740a062838e0ea2620499abed27d653c42fc05f7`, image `740a062838e0`, at
`https://184.194.40.87.sslip.io`. Both runs used the same steps. They differ only in one
deliberate edit to the external order system. This is an additive evidence record. No product,
runtime, frontend or deployment file changed, and every earlier record stands as written.

Raw captures: [revalidation-proof-20261002-740a062838e0](rehearsals/runs/revalidation-proof-20261002-740a062838e0/).
They come with `capture-integrity.json` and `* -text`, and the host scripts that produced them are
in `tools/`.

## What is constructed and what is real

| | |
|---|---|
| **Constructed** | The demo world: the Hollow Oak fixture, restored by the guarded `pp restore-demo-world` before each run. The order system is the project's own External Order System simulator, not a third-party point of sale. The changed world is one operator edit made by this session, on purpose: EXT-B's quantity 1 → 2, the stipulated fact of effect-set S06. Stopping the worker is what fixes the order "yes, then the change, then revalidation". |
| **Real** | The deployed stack and the frozen image. A real Telegram message reached the project owner's phone. The owner, signed in as Maya, pressed "Yes, go ahead" (`BROWSER_SESSION`) in both runs. The owner, as Tomas, pressed APPROVE on the signed link in both runs. The order system's signed `order.updated` webhook crossed the public endpoint. Every refusal and write below is the product's own, read back from PostgreSQL and the order system. |
| **Not used** | Bedrock and MCP. This proof is about deterministic revalidation, and the model plays no part in it. The fixture's clarification is answered by restore provisioning, as in every rehearsal. |

No approval row, decision or consent was created by this session. Every one of them came from the
owner's two presses per run.

## Procedure (identical in both runs, except step 5)

1. Guarded restore: settings preflight, dry run, three-condition gate, one confirmed run, and the
   Telegram binding re-verified with no message sent. The case is `PLANNED`: A auto, B ask, C/D
   blocked, E/F untouched.
2. Maya presses "Yes, go ahead". The worker auto-recovers A (EXT-A v1 → v2) and sends Tomas one ask
   for B, captured against **EXT-B v1, `rv-raspberry-rose-2`, quantity 1**.
3. `docker compose stop worker`.
4. Tomas presses APPROVE. The press is stored as one `customer-reply` inbox row, `RECEIVED`, and
   nothing else is written.
5. **Run 2 only:** an operator edit in the order system, EXT-B line `ol-b` quantity 1 → 2, item
   unchanged. The order system moves to v2 and delivers its signed `order.updated`.
   PromisePatch's `api` stores it as an inbox row. The mirror stays at v1, because the worker is
   stopped.
6. `docker compose start worker`. The worker applies what is waiting, records the decision, and
   revalidates it against a fresh read.

## Run 1: success (control)

Case `bdcbab25…`, restore 10:41:40Z (attempt 2; attempt 1 is VOID, see below).

| | |
|---|---|
| Originally permitted | Plan approval `maya` / `BROWSER_SESSION` 10:42:31Z; B's ask sent 10:42:32Z against EXT-B v1 |
| Customer | APPROVE stored 10:43:26Z with the worker stopped; `APPROVE` / `LITERAL` recorded 10:44:11Z |
| Revalidation | `REVALIDATE_RECOVERY` → `PROCEED`, **10/10 checks passed**; check 2 expected `ACCEPTED\|AMENDED @ v1`, actual `ACCEPTED @ v1` |
| Effect | `ORDER_AMEND` `pp:amend:b7014bc4…:88e9c311…:1`, `DELIVERED` at attempt 1 |
| Order system | EXT-B **v1 → v2**, `rv-raspberry-rose-2` → `rv-raspberry-rose-3`, note "Amended by PromisePatch — approved by customer". Its event names that idempotency key. Mirror equal |
| End | B `RECOVERED`, case `RESOLVED`; frozen reader exit 0, unrelated attributions 0/0/0/0 |

## Run 2: changed world, refused

Case `d3b3655f…`, restore 10:45:26Z.

| | |
|---|---|
| Originally permitted | Plan approval `maya` / `BROWSER_SESSION` 10:48:01Z; B's ask sent 10:48:02Z, `captured_order_version: 1`, `rv-raspberry-rose-2` |
| Customer | APPROVE stored 10:48:48Z with the worker stopped |
| **What changed** | 10:49:18Z, operator edit in the order system: EXT-B `rose-2` ×1 v1 `ACCEPTED` → `rose-2` **×2 v2** `AMENDED`. The event is `order.updated`, `previous_version: 1`, `command: null`, `DELIVERED`. PromisePatch stored it at 10:49:18Z, and the mirror still read v1 ×1 |
| Fresh state observed | Worker started 10:49:48Z. Mirror applied → EXT-B **v2, qty 2**. Decision `APPROVE` / `LITERAL` recorded 10:49:50.317Z |
| **Refusal** | `REVALIDATE_RECOVERY` → **`STALE`, `deciding_check: 2`**. Check 2 `order state and version unchanged`: expected **`ACCEPTED\|AMENDED @ v1`**, actual **`AMENDED @ v2`**, `passed: false`. Checks 1 and 3–10 passed |
| Ledger | `RECOVERY_STALE` (seq 1234, `SYSTEM`, authority **`NONE`**, `track_state: STALE`), then `TRACK_REPLANNED` (seq 1236, `APPROVAL_REQUIRED`, `PENDING`). The customer's decision row is kept, and the request moved to `SUPERSEDED` |
| Customer told | One notice, no link: "Your order changed after we asked you about it, so that request no longer applies, and nothing was done to your order because of it." No new approval request was created, because a re-plan needs a new plan confirmation (ADR-0022/0023) |
| After | No re-confirmation was given. `PLAN_AUTO_ESCALATED` at 10:59:51Z (`PLAN_UNCONFIRMED`): B is `ESCALATED` to the owner, `task-ol-b` is `HELD`, and the case is `RESOLVED` |

### No stale amendment reached the order system

- PromisePatch's outbox for the whole run holds exactly three rows: the first ask, **EXT-A's**
  `ORDER_AMEND`, and the notice. **There is no `ORDER_AMEND` for EXT-B.** There is no
  `APPLY_RECOVERY` step for B and no `RECOVERY_APPLIED` audit for B.
- The order system's own event log for EXT-B holds **one** event, the operator change
  (`command: null`). It has no PromisePatch amendment. Its final record is EXT-B v2, `rose-2` ×2,
  empty note: the operator's truth, not overwritten.
- The owner's approval and the customer's yes were spent on nothing. `plan_approvals` stayed 1.

So the yes Tomas gave, about one cake at v1, authorised nothing once the order named two cakes at
v2. PromisePatch read the moved order before writing and refused. The refusal was decided by
PromisePatch's own revalidation. The order system's stale-version guard was never reached.

## Integrity of the runs

- **Frozen product intact.** All five containers ran `740a062838e0` throughout, and `/healthz`
  reports `740a062838e0`. The only changes were demo-world restores, the one order-system edit, a
  worker stop/start per run, and the timer the product armed itself. No image, template, SSM
  parameter or host file changed, and the host `boot_id` was unchanged.
- **Telegram.** `sendMessage` went 6 → 9: one ask in Run 1, and one ask plus one notice in Run 2.
  `getUpdates` stayed 0.
- **Privacy.** Container-log scans since each run's restore found 0 on every term: address, bot
  token, link secret, MCP bearer, internal token, token-shaped strings and unredacted link paths.
  Every snapshot and reader printed `leak_guard=False`. The proof reader masks the address inside
  check 8 as `<channel-address>` (3 per run).
- **Final restore.** At 11:01:24Z: case `5645dee8…` `PLANNED`, zero outbox rows, requests and plan
  approvals. EXT-A to EXT-F are at v1 in both the mirror and the order system. Binding restored,
  no message sent.

## Anomalies, recorded

- **Run 1 attempt 1, VOID** (10:40:14Z). The restore exited 0, but provisioning reported `STOPPED`:
  "no answerable question was reached". The always-running worker claimed the case's
  interpretation step before the restore's own cycles could, so the case sat at `CLARIFYING`.
  Nothing was confirmed or sent, and the next restore replaced it. This is a restore-tooling race
  and not a revalidation result. Captures: `s1-attempt-1-void-*.log`.
- **S06's wording.** The v1 manifest's S06 rationale says "a fresh ask is sent". Live, the one added
  customer message is the supersession notice, and a fresh ask awaits a new plan confirmation. That
  matches the S06 count of one `customer_message` at `CONSENT_SETTLED`. This run is not a scored
  effect-set run and claims nothing about the manifest.
- `FINALIZE_RECOVERY` retried while waiting for the order system's echo (Run 1 attempts 3, Run 2 A
  attempts 2), as historically documented. No effect repeated.

## What this does not show

It does not exercise the apply-time freshness gate of ADR-0024, a change between `PROCEED` and the
amendment's commit. That remains proved by
`test_a_change_landing_after_a_passing_revalidation_still_stops_the_amendment`. It shows only check
2 live. Checks 3–7 refusing are proved by `test_recovery_revalidation.py`, not here.
