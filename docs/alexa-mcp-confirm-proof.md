# Simulated Alexa+ via MCP spends a human approval, 2026-10-02

One deployed demonstration that the **Simulated Alexa+ via MCP** path (ADR-0028) takes part in a
consequential action, not only a status read. Frozen product `740a062838e0ea2620499abed27d653c42fc05f7`,
image `740a062838e0`, at `https://184.194.40.87.sslip.io`. This is an additive evidence record. No
product, runtime, frontend or deployment file changed, and every earlier record stands as written.
It closes the limitation [bridge-release.md](bridge-release.md) recorded: "No live `confirm` was
spent through the bridge".

Raw captures: [alexa-mcp-confirm-proof-20261002-740a062838e0](rehearsals/runs/alexa-mcp-confirm-proof-20261002-740a062838e0/),
with `capture-integrity.json` and `* -text`. The host scripts are in `tools/`. `alexa.py` is the
read-only authority reader written for this proof.

## What is constructed and what is real

| | |
|---|---|
| **Constructed** | The demo world: the Hollow Oak fixture, restored by the guarded `pp restore-demo-world` (settings preflight, dry run, three-condition gate, one confirmed run, binding re-verified with no message sent). |
| **Real** | The deployed stack and the frozen image. The project owner, signed in as Maya, pressed "Approve this plan" and then sent a sentence through the deployed panel. The choice of verb was made by Bedrock. The MCP endpoint is the deployed `mcp` container, reached from `api` with the server-held bearer. One real Telegram ask was sent successfully; its arrival on the phone was not separately confirmed in this session. |
| **Not done** | No customer decision. The owner left the Telegram ask unanswered, so request B stayed `SENT`. The human user created the one plan approval, through the browser. Claude and its automation created no approval, customer decision or consent. |

## Procedure and timeline (UTC, 2026-10-02)

| Time | Event |
|---|---|
| 11:55:57 | Restore: case **`621a46a5-79b1-50a6-9956-62dbf897ba3b`** `PLANNED`, 0 approvals/requests/decisions/outbox rows |
| 11:58:10.776 | The owner, as Maya, presses **"Approve this plan"** in the Simulated Alexa+ panel. One `POST /api/conversation/approve` → `201`, from Caddy (`172.29.0.10`). Case still `PLANNED`; no `/confirm`, no MCP request |
| 12:00:01–03 | The owner types **`Yes, go ahead.`** in the panel and presses **"Say it over MCP"**. One `POST /api/conversation/simulated-alexa` → `200` |
| 12:00:02.312 | `PLAN_CONFIRMED`, case `EXECUTING`, then `WAITING` |
| 12:00:04 | A applied (EXT-A v1 → v2), B's ask sent, C/D escalated |
| 12:01:42 | Final restore: case `efa7d70b…` `PLANNED`, world canonical |

Plan: **`plan_id` `7311b4f8a30900fc397b7b8228886a411131177677da88eb555a8f574c3dd367`**. A is
`AUTO_RECOVERABLE`, B is `APPROVAL_REQUIRED`, C and D are `BLOCKED`, E and F are `UNAFFECTED`.

## 1. The human approval existed first

`plan_approvals`, the only row, read at 11:58:41Z (before the utterance) and unchanged at 12:00:20Z:

```
id f5eb7769-5cd1-4ced-af29-3e75ccb3ab74  case 621a46a5…  plan_id 7311b4f8…dd367
approved_by maya  channel BROWSER_SESSION  evidence "<explicit confirmation control>"
approved_at 2026-10-02T11:58:10.776192Z
```

Audit seq 1274 `PLAN_APPROVED`, `WORKER maya`, authority `HUMAN_APPROVAL`, provenance
`approval_id f5eb7769…`, channel `BROWSER_SESSION`. The api logged `conversation.approve.recorded`.

## 2. The bridge turn: Bedrock, then MCP

`simulated_alexa.turn` (12:00:03.47Z): `hydrated: true`, **`selected: CONFIRM`**,
**`calls: ["confirm", "status"]`**, phase `WORKING`.

- **Bedrock.** `semantic.answered`, job `select_tool`, `provider: bedrock`,
  `us.amazon.nova-2-lite-v1:0`, 1 attempt, 1847/28 tokens, 814 ms.
- **MCP.** The `mcp` container logged `POST /mcp` only from `172.29.0.2`, which is `api`. It
  logged three tool events, all from client `bearer:802b52be7f34`, the bearer's digest prefix as
  `mcp` always names its caller:
  1. `mcp.tool.status` 12:00:01.20Z, the hydration read (ADR-0028 decision 12, outside the budget).
  2. **`mcp.tool.confirm` 12:00:02.91Z, `correlation_id 1b6a1f6c-742c-4348-a006-ac9f145b3315`.**
  3. `mcp.tool.status` 12:00:03.46Z, the turn's follow-up read.
- **Intent API.** `api` logged `POST /internal/intents/status` ×2 and `POST /internal/intents/confirm`
  → `202` ×1, all from `172.29.0.5`, which is `mcp`. `intents.confirm.accepted` carries the same
  `correlation_id 1b6a1f6c…`, `worker: maya`, `approved_via: BROWSER_SESSION`, `created: true`.

That is three MCP tool calls in one request, with one of them effecting, as ADR-0028 decision 12
bounds it.

## 3. MCP spent the approval and created none

Audit seq 1275 `PLAN_CONFIRMED`, 12:00:02.312Z, `WORKER maya`, authority `HUMAN_APPROVAL`:

```
correlation_id 1b6a1f6c-742c-4348-a006-ac9f145b3315        <- the mcp.tool.confirm call
provenance { approval_id f5eb7769-5cd1-4ced-af29-3e75ccb3ab74,   <- the 11:58:10 row
             approved_via BROWSER_SESSION, confirmed_by maya,
             command_id 42ba171d-5305-4e83-a4b0-e37ab7b4b6fc }
after { case_state EXECUTING, applying [A], awaiting_approval [B], escalated {C,D: BLOCKED} }
```

- `plan_approvals` total is **1** before and after the turn. The approval's id and time are
  unchanged.
- There is exactly **one** `PLAN_APPROVED` audit row for the case, seq 1274, written 1 min 52 s
  before the turn by the browser route. The turn wrote no second one.
- The confirmation's correlation id is the MCP tool call's. The approval it spent is the browser
  press's. So the effecting step came over MCP, and its authority is the person's earlier press.
  The ledger attributes the action to Maya under her existing human approval, on
  `BROWSER_SESSION`, the channel used in this proof, and not to the MCP bearer or service
  credential. `ApprovalChannel` has two members, `BROWSER_SESSION` and `OPERATOR_CONSOLE`, and
  none an MCP or service credential could name, so neither can create the human approval
  (ADR-0018).
- No `POST /api/conversation/confirm` appears in the window. The browser's combined
  record-and-confirm route was not used.

## 4. The workflow proceeded

At 12:00:20Z: case `WAITING`, version 12.

- **A** `RECOVERED`. `APPLY_RECOVERY` ran at attempt 1. `ORDER_AMEND` was `DELIVERED` at attempt 1.
  The order system shows EXT-A **v2 `AMENDED`, `rv-raspberry-almond-4`**, and its event names
  PromisePatch's key `pp:amend:f5881e5b…:58cd11e3…:1`. The mirror is equal.
- **B** is `WAITING_FOR_CUSTOMER`. One approval request, `SENT` 12:00:04Z, against
  `captured_order_version 1`. One `MESSAGE_SEND` was `DELIVERED` at attempt 1. `sendMessage` went
  9 → 10. The owner was told to expect one message; its arrival on the phone was not separately confirmed in this session.
- **C, D** are `ESCALATED` (`BLOCKED`).
- **E, F** stay `UNAFFECTED`, and EXT-C to EXT-F stay at v1.
- The frozen reader (sha256 `c9731c8f…`) exited 0 at the `WAITING` checkpoint.

## 5. No customer consent was fabricated

At 12:00:20Z and again at the 12:01:09Z checkpoint:

- `approval_decisions` **0**, `inbound_replies` **0**, and customer inbox rows since the restore **0**.
- Request B is still `SENT` with `decided: false`, and EXT-B is still v1 `rv-raspberry-rose-2` in
  both the mirror and the store.
- `getUpdates` 0.

The bridge reached no customer route. B's ask is the product's own outbound request, and it was
caused by the confirmation. A is applied under its pre-authored `R-PREAPPROVED` rule, not under any
consent from this session. The order system's note "approved by customer" is that rule's existing
amendment text.

## 6. No secret leaked

The container logs of all five services since 11:55:37Z, 188 lines, were scanned on the host. Values
were compared there and never printed.

- MCP bearer **0**, internal service token **0**, bot token **0** and link secret **0**.
- Customer address **0**, token-shaped strings **0**, unredacted link query/path **0**.
- Every reader printed `address_leak_guard=False`.
- `mcp` names its caller only by `bearer:<sha256[:12]>`.
- The bridge response schema (`SimulatedAlexaReply`) has no credential field.
- CloudWatch was not re-scanned for this window.

## Integrity

- Every container ran `740a062838e0` before, during and after. `/healthz` reports `740a062838e0`.
- Host `boot_id` `d0e0f54c…` was unchanged, and every container's start time was unchanged,
  including the worker's.
- No image, template, SSM parameter or host file changed. The only writes were two guarded restores
  and the product's own effects from the owner's two actions.
- **Final restore** at 12:01:42Z left case `efa7d70b-906a-5bdd-a64f-86288bf679af` `PLANNED`.
  Approvals, requests, decisions, replies and outbox rows are all 0. EXT-A to EXT-F are at v1.
  The binding was restored and re-verified (`private`, id matches), with no message sent.

## Anomalies and limitations

- The first baseline read failed on a column this session's own reader wrongly named
  (`approval_requests.plan_id`). It was fixed and re-read 25 s later, and the corrected output
  overwrote `alexa-planned.log`. The traceback lives only in the session transcript. That was a
  tooling error and wrote nothing.
- The panel's spoken reply text was not captured; the logged turn result is what is cited.
- The utterance was typed in the panel, not dictated. Speech recognition is not under test here.
- One run, and one success path. The bridge refusing a confirm when no approval exists is proved
  by the implementation, its tests and CI, not live.
- A different live refusal is recorded in [bridge-release.md](bridge-release.md), R1 attempt 1: a
  browser approval already existed, the utterance "Yes, confirm the plan" failed the closed
  affirmation grammar, Bedrock selected `CONFIRM`, and the server blocked it with
  `NEEDS_THE_WORKERS_YES`. That run did not test a missing approval.
