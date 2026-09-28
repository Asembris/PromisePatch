# Evidence hardening: a genuine `STALE` refusal, captured locally on the frozen code

Date: **2026-09-28**. Branch `evidence/hardening`. This page is additive. It changes no product
code, test, fixture, manifest or earlier record.

**Where this ran:** only in this session's disposable Linux container. The code was a detached
worktree at the frozen repository release SHA `56c302366b3ddc0d824c1588a4a9ddbd193ed891`. Its
deployable product paths are tree-identical to the deployed image `4529a802e34e`
([g8-closeout.md](g8-closeout.md) §3, and re-checked in
[evidence-hardening-v2-clean-replay-2026-09-28.md](evidence-hardening-v2-clean-replay-2026-09-28.md) §3).
It used a fresh local PostgreSQL. **It did not happen on the deployment.** No deployed case, customer,
order, message, host or AWS resource was touched. [g8-closeout.md](g8-closeout.md) §8's caveat
stands unchanged: *no refusal path has been exercised live*.

Labels: **REPRODUCED LOCALLY** for everything in §2 to §4, and **VERIFIED IN THIS SESSION** for
the source reading in §1. Nothing here is **OBSERVED ON THE PUBLIC DEPLOYMENT**.

## 1. What produces a genuine `STALE` (VERIFIED IN THIS SESSION, from source)

`apps/backend/src/promisepatch/domain/revalidation.py` runs the ten §14.3 checks as the durable
step `REVALIDATE_RECOVERY`, against a **fresh** snapshot, after a customer's literal `YES` has
been committed as an `ApprovalDecision`. `_refuse` maps a failure of **checks 2–6** to
`STALE`: order state and version, pinned recipe version, constraint snapshot, substitute stock,
and production task. `_go_stale` then:

- records an audit `RECOVERY_STALE` as `SYSTEM` with authority `NONE`, never as the customer's
  decline;
- sets the track `STALE`;
- keeps the option, request and decision rows;
- enqueues `REPLAN_TRACK`, and sends nothing to the order system.

ADR-0023 then returns the case to `PLANNED` for that track only, so a new plan needs a worker's yes.

The state change is therefore anything that moves one of checks 2–6 between the customer's
`YES` and the revalidation. The most faithful to the real system is the one frozen effect-set
scenario **S06** stipulates: *the customer said yes, then changed the order*. The customer resizes
their own order **in the External Order System's own screen**, and PromisePatch learns of it through
that system's **signed webhook**, the same way it learns of any external edit. No test stand-in
writes to PromisePatch's mirror. The unit test
`test_an_order_amended_while_waiting_makes_the_approval_stale` uses a stand-in instead
(`_intake_support.Intake.bump_order_version`), so it was not used for this capture.

## 2. How it was driven (REPRODUCED LOCALLY)

A scratch pytest module was placed, **untracked and never committed**, in the `56c3023` worktree.
It reuses S06's own fixtures and drive helpers from `apps/backend/tests/test_effect_sets.py`
verbatim. Those helpers run the MCP server over HTTP, the intent API, the order-system simulator
with its HTTP UI and webhook dispatcher, and the product's own `Worker`. The module drives up to
the refusal and dumps the rows. Every field that could hold a channel address is masked before
writing: `customer_channel`, `sender_identity`, `provider_ref`, and check 8's compared values. The
signed approval link is never read. Command:

```bash
PP_STALE_CAPTURE_OUT=<scratch>/stale-capture.json \
  uv run python scripts/with_local_env.py -- \
  uv run pytest apps/backend/tests/test_zz_scratch_stale_capture.py -q -p no:cacheprovider
```

Result: `1 passed`. The database was the compose `postgres` service alone, at
`0009_human_plan_approval (head)`, migrated from the host. No `worker`, `api` or `mcp` container
ran. `PP_LLM_PROVIDER` was `fake`, and no model was reached. The customer channel is the in-process
fake provider, so "delivered" below means delivered **to the fake provider**, not to a phone. The
scratch module was deleted afterwards, and the worktree was removed.

Driver, sha256 `35e38681b42a6988879e8a501df5e863d630e691c99cb924c7c06b712838d2f5`:

```python
"""Scratch evidence driver, never committed. Replays S06's drive to the point after the stale
refusal, through the real MCP transport, the External Order System simulator's own HTTP edit and
signed webhook, the mirror and the durable worker, then dumps the rows that show what happened.
Any field that could carry a channel address is masked; nothing is written to the product."""

from __future__ import annotations

import json
import os
from typing import Any

from _intake_support import RASPBERRY_ONLY, Intake
from _intake_support import physical as physical  # noqa: F401  (fixture)
from test_effect_sets import (  # fixtures and drive helpers, reused verbatim
    CONSENT,
    TOMAS,
    TOMAS_ORDER,
    ORDERS,
    answered,
    ask_for,
    chain,  # noqa: F401  (fixture)
    confirmed,
    external_quantity_edit,
    quiescent,
    reported,
    settle,
    worker_for,
    wired,  # noqa: F401  (fixture)
)

from promisepatch.domain import cases, recovery

MASK = ("sender", "channel", "address", "provider_ref", "link", "token", "destination")


def safe(row: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in dict(row._mapping).items():
        if any(word in key.lower() for word in MASK):
            out[key] = "<masked>"
        elif key in ("payload", "result"):
            out[key] = sorted(value) if isinstance(value, dict) else "<omitted>"
        else:
            out[key] = value if isinstance(value, (int, float, bool, type(None))) else str(value)
    return out


def masked_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for check in checks:
        row = dict(check)
        if row.get("index") == 8:  # the sender check compares channel addresses
            row["expected"] = row["actual"] = "<masked: channel address>"
        rows.append(row)
    return rows


async def test_capture_s06_stale_refusal(chain, wired, physical: Intake) -> None:  # noqa: F811
    record: dict[str, Any] = {}
    tomas_promise = ORDERS[TOMAS]["promise"]

    case_id = await reported(chain, physical)
    await answered(chain, physical, case_id, RASPBERRY_ONLY)
    await quiescent(physical, case_id)
    await confirmed(chain, physical, case_id)
    await settle(physical, wired)

    ask = await ask_for(physical, case_id, TOMAS)
    track = await physical.track(case_id, tomas_promise)
    record["1_before_answer"] = {
        "order_system_version": wired.external_order(TOMAS_ORDER).version,
        "order_system_quantity": wired.external_order(TOMAS_ORDER).lines[0].quantity,
        "mirror_external_version": (await wired.mirrored_order(TOMAS_ORDER)).external_version,
        "request": safe(ask),
        "track_state": track.state,
    }

    await physical.deliver_reply(ask.id, CONSENT)
    await physical.drain_until_decided(worker=worker_for(physical, wired))
    record["2_after_literal_yes"] = {
        "decisions": [safe(row) for row in await physical.decisions()],
        "request_state": (await ask_for(physical, case_id, TOMAS)).state,
        "track_state": (await physical.track(case_id, tomas_promise)).state,
        "revalidate_step": safe(
            await physical.step_named(case_id, cases.revalidate_step_key(track.id))
        ),
    }

    await external_quantity_edit(physical, wired, order=TOMAS_ORDER, quantity=2, case_id=case_id)
    record["3_after_customer_edit"] = {
        "order_system_version": wired.external_order(TOMAS_ORDER).version,
        "order_system_quantity": wired.external_order(TOMAS_ORDER).lines[0].quantity,
        "mirror_external_version": (await wired.mirrored_order(TOMAS_ORDER)).external_version,
    }

    await settle(physical, wired)
    await quiescent(physical, case_id)

    step = await physical.step_named(case_id, cases.revalidate_step_key(track.id))
    record["4_revalidation"] = {
        "step_state": step.state,
        "outcome": step.result.get("outcome"),
        "deciding_check": step.result.get("deciding_check"),
        "detail": step.result.get("detail"),
        "checks": masked_checks(list(step.result.get("checks", []))),
    }
    audits = await physical.audits(case_id)
    record["5_audit"] = {
        "recovery_stale": [
            {"actor_kind": a.actor_kind, "authority": a.authority, "after": a.after}
            for a in audits
            if a.type == recovery.AUDIT_RECOVERY_STALE and a.track_id == track.id
        ],
        "revalidation_check_rows_for_track": sum(
            1 for a in audits if a.type == "REVALIDATION_CHECK" and a.track_id == track.id
        ),
        "types_in_order": [a.type for a in audits],
    }
    effects = await physical.effects_for(track.id)
    record["6_effects_for_track"] = [
        {"kind": e.kind, "state": e.state, "attempts": e.attempts} for e in effects
    ]
    record["7_order_after_settle"] = {
        "order_system_version": wired.external_order(TOMAS_ORDER).version,
        "order_system_quantity": wired.external_order(TOMAS_ORDER).lines[0].quantity,
        "order_system_line_item": wired.external_order(TOMAS_ORDER).lines[0].external_item_id,
        "mirror_external_version": (await wired.mirrored_order(TOMAS_ORDER)).external_version,
    }
    requests = [r for r in await physical.requests() if r.track_id == track.id]
    record["8_final"] = {
        "case_state": (await physical.case(case_id)).state,
        "tracks": {t.promise_id: t.state for t in await physical.tracks(case_id)},
        "requests_for_track": [
            {"state": r.state, "captured_order_version": r.captured_order_version,
             "decided": r.decided}
            for r in requests
        ],
        "decisions_total": len(await physical.decisions()),
        "outstanding_steps": len(await physical.outstanding(case_id)),
    }
    with open(os.environ["PP_STALE_CAPTURE_OUT"], "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True, default=str)
```

## 3. What happened, step by step

| # | moment | evidence (from the capture below) |
|---|---|---|
| 1 | **approval asked** | Order system `EXT-B` at version **1**, quantity 1. The mirror is at `external_version` 1. The approval request for `pr-b` is `SENT` and captured `captured_order_version: 1` and `rv-raspberry-rose-2`. Track `WAITING_FOR_CUSTOMER` |
| 2 | **literal yes committed** | Exactly one decision: `APPROVE`, parser `LITERAL`, `raw_text` `YES`. The request is `ANSWERED`, and `REVALIDATE_RECOVERY` is `PENDING`, not yet run |
| 3 | **the world changed** | The customer's own edit in the order system. `EXT-B` is now version **2**, quantity **2**. The signed webhook moved the mirror to `external_version` 2 |
| 4 | **fresh revalidation** | The step is `DONE` with outcome **`STALE`**. All ten checks were evaluated. Check 1 passed. **Check 2, *order state and version unchanged*, failed: expected `ACCEPTED\|AMENDED @ v1`, actual `AMENDED @ v2`**. Checks 3–10 passed. **Deciding check: 2** |
| 5 | **refusal, attributed** | One `RECOVERY_STALE` audit for the track: `actor_kind` `SYSTEM`, `authority` `NONE`, `after` `{deciding_check: 2, track_state: STALE}`. Ten `REVALIDATION_CHECK` audit rows for the track |
| 6 | **no unauthorised amendment** | The track's effects are two `MESSAGE_SEND`, both `DELIVERED` at attempt 1, and **zero `ORDER_AMEND`**. The order system still shows version 2, quantity 2, line item **`rv-raspberry-rose-2`**, the original, not the approved substitute. The whole outbox holds 3 rows: those 2 messages and **one** `ORDER_AMEND`, `pr-a`'s pre-authorised recovery (its `RECOVERY_APPLIED` audit names track `pr-a`), which is not this track |
| 7 | **what the customer was told** | The second message tells the customer the request no longer applies: *"Your order changed after we asked you about it, so that request no longer applies, and nothing was done to your order because of it."* It is read from the fake provider's outbox row, with the link redacted, and it names the superseded request |
| 8 | **final posture** | Case **`PLANNED`**, following ADR-0023, and awaiting a worker's yes on the re-plan. Tracks: `pr-a` `RECOVERED`, `pr-b` `PENDING`, `pr-c` and `pr-d` `ESCALATED`, `pr-e` and `pr-f` `UNAFFECTED`. The one request for `pr-b` is `SUPERSEDED` and still carries `captured_order_version: 1` and `decided: true`. Decisions total **1**, kept. Outstanding steps **0** |

Row 3's edit was made with the case's own work held still (`work_held`, as S06 does). So "between
the yes and the revalidation" is a fact about the sequence, not about which of two workers won a
race.

## 4. The capture (REPRODUCED LOCALLY)

sha256 `621c084f69d451f4172fbbd30260088992f727d3e84fb1073ce39686e19f25f6`. Identifiers are local
UUIDs from a disposable database. Timestamps are this container's clock, and the fixture is anchored
to it. Masked fields show `<masked>`.

```json
{
  "1_before_answer": {
    "mirror_external_version": 1,
    "order_system_quantity": 1,
    "order_system_version": 1,
    "request": {
      "captured_constraint_hash": "7efeb5f7900ae53e45cfefcc30393ee1bbd54b591594cd6ff4c748d1a2176641",
      "captured_fingerprint": "89342887a10da08e0c7d5dce4fcfbb85ab05e7933c31b82bd11f0da4b0be8273",
      "captured_order_version": 1,
      "captured_recipe_version_id": "rv-raspberry-rose-2",
      "customer_channel": "<masked>",
      "deadline": "2026-09-28 17:21:51.498201+00:00",
      "decided": false,
      "id": "25a3be29-792a-5a5f-8896-233b293f6731",
      "option_code": "OPT-21C4C6",
      "option_id": "21c4c6f2-7c85-5424-8386-4b7f227d2da0",
      "order_id": "ord-b",
      "order_line_id": "ol-b",
      "promise_id": "pr-b",
      "provider_ref": "<masked>",
      "sent_at": "2026-09-28 14:21:54.462116+00:00",
      "state": "SENT",
      "track_id": "5f00bdc1-e38a-5f21-82f1-4cafb1c23958"
    },
    "track_state": "WAITING_FOR_CUSTOMER"
  },
  "2_after_literal_yes": {
    "decisions": [
      {
        "decision": "APPROVE",
        "id": "d7b71c5a-b6eb-44e2-9dbf-ab40a8d4efe8",
        "parser": "LITERAL",
        "provider_message_id": "msg-3dfa7a63-eba6-483f-a1c3-930abaddb553",
        "raw_text": "YES",
        "received_at": "2026-09-28 14:21:54.968393+00:00",
        "request_id": "25a3be29-792a-5a5f-8896-233b293f6731",
        "sender_identity": "<masked>"
      }
    ],
    "request_state": "ANSWERED",
    "revalidate_step": {
      "attempts": 0,
      "case_id": "23bc4b03-b6ba-57ff-873b-1fbda8ad4662",
      "created_at": "2026-09-28 14:21:54.968393+00:00",
      "done_at": null,
      "error": null,
      "id": "24884aab-c81c-4f2f-b35c-1cb4ff25d655",
      "idempotency_key": null,
      "kind": "REVALIDATE_RECOVERY",
      "lease_expires_at": null,
      "lease_owner": null,
      "next_attempt_at": null,
      "provider_ref": "<masked>",
      "request_hash": null,
      "result": "<omitted>",
      "started_at": null,
      "state": "PENDING",
      "step_key": "revalidate:5f00bdc1-e38a-5f21-82f1-4cafb1c23958",
      "track_id": null
    },
    "track_state": "WAITING_FOR_CUSTOMER"
  },
  "3_after_customer_edit": {
    "mirror_external_version": 2,
    "order_system_quantity": 2,
    "order_system_version": 2
  },
  "4_revalidation": {
    "checks": [
      {
        "actual": "track=WAITING_FOR_CUSTOMER case=WAITING",
        "expected": "track=WAITING_FOR_CUSTOMER case=WAITING",
        "index": 1,
        "name": "track and case are waiting",
        "passed": true
      },
      {
        "actual": "AMENDED @ v2",
        "expected": "ACCEPTED|AMENDED @ v1",
        "index": 2,
        "name": "order state and version unchanged",
        "passed": false
      },
      {
        "actual": "rv-raspberry-rose-2",
        "expected": "rv-raspberry-rose-2",
        "index": 3,
        "name": "pinned recipe version unchanged",
        "passed": true
      },
      {
        "actual": "7efeb5f7900ae53e45cfefcc30393ee1bbd54b591594cd6ff4c748d1a2176641",
        "expected": "7efeb5f7900ae53e45cfefcc30393ee1bbd54b591594cd6ff4c748d1a2176641",
        "index": 4,
        "name": "constraint snapshot unchanged",
        "passed": true
      },
      {
        "actual": "3.200",
        "expected": ">= 2.200",
        "index": 5,
        "name": "substitute still available",
        "passed": true
      },
      {
        "actual": "SCHEDULED and start 2026-09-28T18:21:51.498201+00:00",
        "expected": "SCHEDULED|HELD by 23bc4b03-b6ba-57ff-873b-1fbda8ad4662 and start > 2026-09-28T14:21:55.184825+00:00",
        "index": 6,
        "name": "production task not started and still ahead",
        "passed": true
      },
      {
        "actual": "2026-09-28T14:21:55.184825+00:00",
        "expected": "now <= 2026-09-28T17:21:51.498201+00:00",
        "index": 7,
        "name": "approval deadline not passed",
        "passed": true
      },
      {
        "actual": "<masked: channel address>",
        "expected": "<masked: channel address>",
        "index": 8,
        "name": "sender is the order's approval channel",
        "passed": true
      },
      {
        "actual": "LITERAL",
        "expected": "LITERAL",
        "index": 9,
        "name": "decision came from the literal parser",
        "passed": true
      },
      {
        "actual": "1 decision(s) for 25a3be29-792a-5a5f-8896-233b293f6731 on track 5f00bdc1-e38a-5f21-82f1-4cafb1c23958 option 21c4c6f2-7c85-5424-8386-4b7f227d2da0",
        "expected": "one decision for 25a3be29-792a-5a5f-8896-233b293f6731 on track 5f00bdc1-e38a-5f21-82f1-4cafb1c23958 option 21c4c6f2-7c85-5424-8386-4b7f227d2da0",
        "index": 10,
        "name": "one unspent decision, bound to this plan",
        "passed": true
      }
    ],
    "deciding_check": 2,
    "detail": "check 2: ACCEPTED|AMENDED @ v1 != AMENDED @ v2",
    "outcome": "STALE",
    "step_state": "DONE"
  },
  "5_audit": {
    "recovery_stale": [
      {
        "actor_kind": "SYSTEM",
        "after": {
          "deciding_check": 2,
          "track_state": "STALE"
        },
        "authority": "NONE"
      }
    ],
    "revalidation_check_rows_for_track": 10,
    "types_in_order": [
      "CASE_OPENED",
      "WORKFLOW_STEP_EXECUTED",
      "CLARIFICATION_REQUESTED",
      "WORKFLOW_STEP_EXECUTED",
      "CLARIFICATION_ANSWERED",
      "WORKFLOW_STEP_EXECUTED",
      "PHYSICAL_FACT_RECORDED",
      "WORKFLOW_STEP_EXECUTED",
      "IMPACT_ANALYZED",
      "WORKFLOW_STEP_EXECUTED",
      "RECOVERY_PLANNED",
      "WORKFLOW_STEP_EXECUTED",
      "PLAN_APPROVED",
      "PLAN_CONFIRMED",
      "APPROVAL_REQUESTED",
      "WORKFLOW_STEP_EXECUTED",
      "RECOVERY_APPLIED",
      "WORKFLOW_STEP_EXECUTED",
      "APPROVAL_SENT",
      "WORKFLOW_STEP_EXECUTED",
      "RECOVERY_COMPLETED",
      "WORKFLOW_STEP_EXECUTED",
      "APPROVAL_DECISION_RECORDED",
      "WORKFLOW_STEP_EXECUTED",
      "REVALIDATION_CHECK",
      "REVALIDATION_CHECK",
      "REVALIDATION_CHECK",
      "REVALIDATION_CHECK",
      "REVALIDATION_CHECK",
      "REVALIDATION_CHECK",
      "REVALIDATION_CHECK",
      "REVALIDATION_CHECK",
      "REVALIDATION_CHECK",
      "REVALIDATION_CHECK",
      "RECOVERY_STALE",
      "WORKFLOW_STEP_EXECUTED",
      "TRACK_REPLANNED",
      "WORKFLOW_STEP_EXECUTED"
    ]
  },
  "6_effects_for_track": [
    {
      "attempts": 1,
      "kind": "MESSAGE_SEND",
      "state": "DELIVERED"
    },
    {
      "attempts": 1,
      "kind": "MESSAGE_SEND",
      "state": "DELIVERED"
    }
  ],
  "7_order_after_settle": {
    "mirror_external_version": 2,
    "order_system_line_item": "rv-raspberry-rose-2",
    "order_system_quantity": 2,
    "order_system_version": 2
  },
  "8_final": {
    "case_state": "PLANNED",
    "decisions_total": 1,
    "outstanding_steps": 0,
    "requests_for_track": [
      {
        "captured_order_version": 1,
        "decided": true,
        "state": "SUPERSEDED"
      }
    ],
    "tracks": {
      "pr-a": "RECOVERED",
      "pr-b": "PENDING",
      "pr-c": "ESCALATED",
      "pr-d": "ESCALATED",
      "pr-e": "UNAFFECTED",
      "pr-f": "UNAFFECTED"
    }
  }
}
```

## 5. What this does and does not claim

It claims that the frozen implementation, run locally, refused a customer's literal `YES` because
the order it was given about had moved. It names check 2 as the deciding check, wrote the refusal as
the system's rather than the customer's, sent no amendment, kept the customer's words, told them
nothing was done, and left the case at `PLANNED` for a person.

It does **not** claim:

- that this happened on the deployment or in any of rehearsals R1–R5. It did not;
- live delivery. The customer channel was the fake provider;
- anything about `EXPIRED`, `UNAUTHORIZED` or `NOOP`. Those remain proved by their tests only;
- anything new about S06's labels. This is the same drive the effect-set suite already runs. It is
  a development activity and not a score.

## 6. Why a live `STALE` was not taken on the deployment

Doing so would mean a real plan confirmation on the shared judge case, a real message to the one
bound Telegram chat, a real customer `YES`, and a real edit to the deployed order system's
`EXT-B`. It would also leave the canonical case in a re-plan and not in the state the demo and
rehearsals describe. Undoing that needs `pp restore-demo-world`, which is destructive. That is
shared-state mutation and an irreversible external message, and this session was forbidden
both. It could also not reach the host at all (see
[evidence-hardening-deployment-2026-09-28.md](evidence-hardening-deployment-2026-09-28.md)).
[g8-remaining-gaps-audit.md](g8-remaining-gaps-audit.md) already records that a live STALE is not
owed.
