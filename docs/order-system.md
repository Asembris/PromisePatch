# The external order system

PromisePatch does not own customer orders. Another system does, and PromisePatch keeps a
*mirror* of what that system says. There is no order editor in this application and there will
not be one: the only write PromisePatch ever makes to an order is a governed recovery
amendment, pushed at the order system and applied by it.

For local development and for the demo, that other system is the **External Order System —
simulator** in [`apps/order-simulator`](../apps/order-simulator).

## What the simulator is, and what it is not

It is a small FastAPI application with its own SQLite database, its own port, its own window
and its own hand-authored order book. It exists so that an order can be changed *outside*
PromisePatch and the change can be watched arriving inside it.

It is **not Square, not a production point of sale, and not a real customer system.** It proves
integration mechanics — a signed contract, idempotent amendments, monotonic versions, durable
delivery, and the effect of an external change on what PromisePatch decides. It proves nothing
whatsoever about third-party product adoption, and no narration should say otherwise. A real
provider would implement the same contract behind the same adapter; that is a later decision,
not a claim this repository makes today.

## The boundary

```
  operator  ─┐
             ├─▶  order system  ──signed order.updated──▶  PromisePatch ingress
 ORDER_AMEND ┘   (SQLite, own process)                     └─▶ inbox_events
                        ▲                                        └─▶ worker ─▶ mirror
                        └────────── amendment (HTTP) ─────────────────┘
```

* **The order system is the source of truth.** Its `version` is its own monotonic counter, and
  it moves once per committed change. PromisePatch mirrors that number and never invents one.
* **PromisePatch learns about ordinary changes only through events.** Nothing else in the
  application writes `orders` or `order_lines`;
  [`promisepatch.domain.order_mirror`](../apps/backend/src/promisepatch/domain/order_mirror.py)
  is the single path, and it runs in the worker.
* **The outbound adapter cannot write the mirror.** `promisepatch.integrations` is forbidden by
  an import contract from importing `promisepatch.db` or SQLAlchemy at all, so an amendment
  physically cannot change PromisePatch's own copy of the order it just asked somebody else to
  change. The mirror moves when the order system says it moved.

## Webhook authentication

Deliveries are authenticated service-to-service, never with a browser session. The order system
signs the exact bytes of the request body together with a timestamp (HMAC-SHA256, shared
secret); PromisePatch verifies before it parses, inside a five-minute replay window, and refuses
missing, expired, forged and tampered deliveries with one indistinguishable answer.

The secret is generated into gitignored environment files by
`scripts/bootstrap_local_env.py` and is shared by both applications
(`PP_ORDER_SYSTEM_WEBHOOK_SECRET` and `OS_WEBHOOK_SECRET`). No secret value appears in this
repository, in a log line or in an error message.

A verified delivery is stored in `inbox_events` and answered. `(source, provider_event_id)` is
unique, so a webhook delivered ten times is one logical record and at most one mirror change.

## Version handling

| Arriving event | What happens |
|---|---|
| the next version in line | applied to the mirror, audited, announced |
| the event the mirror already applied | no-op; the version does not move again |
| an older version | ignored without touching a column; audited as stale |
| a version beyond the next one | the whole order is fetched authoritatively and the mirror is made equal to it |

An order PromisePatch does not mirror, a catalogue item `order_line_mappings` cannot translate,
or a line the order does not have each fail closed: the transaction is rolled back and the
failure is recorded. Nothing invents a `RecipeVersion` because an external system named one.

## Recovery amendments

A confirmed recovery enqueues one `ORDER_AMEND` effect. The dispatcher claims it, commits that
claim, and calls the order system with no transaction open. The request carries the option
planning chose, the version the plan was made against, and a stable idempotency key derived from
persisted identity.

* If the order has moved since, the order system **refuses** rather than overwriting newer
  truth, and the recovery escalates instead of reporting success.
* If the answer is lost, the retry presents the **same key** and the order system replays its
  stored result rather than acting twice.
* A track becomes `RECOVERED` only once the mirror shows the change the order system said it
  made. An acknowledgement is not an observation, and the two orderings — echo before
  acknowledgement, acknowledgement before echo — converge on one finish because both are decided
  from rows.

## Running it

```bash
uv run python scripts/bootstrap_local_env.py     # generates the shared webhook secret
docker compose up --detach --wait
```

| | On the host | Inside the network |
|---|---|---|
| order system UI and API | <http://localhost:58100> | `order-simulator:8100` |

Without Docker: `uv run order-simulator` (it reads `OS_*` from the environment).

```bash
curl -X POST http://localhost:58100/admin/reset     # put the demo order book back
curl http://localhost:58100/orders                  # what the order system currently holds
curl http://localhost:58100/admin/events            # recent events and their delivery state
```

The operator screen at <http://localhost:58100> lists the six demo orders with their version,
their current item and one control per line, and shows the outbound event log with each
delivery's state.

**Reset both, or neither.** Each system's reset is its own and neither tells the other, which
is the point — but it means a half reset leaves them disagreeing: an order system back at
version 1 beside a mirror still at version 2 makes the next change look like an event that has
already been overtaken, and the mirror correctly ignores it. Put both back together, PromisePatch
first:

```bash
docker compose run --rm seed                        # PromisePatch, back to the fixture
curl -X POST http://localhost:58100/admin/reset     # the order system, back to its book
```

## Running Proof A

1. Bring the stack up and open both windows: PromisePatch at <http://localhost:55173> and the
   order system at <http://localhost:58100>.
2. In the order system, change **Lena Fischer**'s order from `Raspberry Lemon Layer v2` to
   `Lemon Curd Layer v1`. The version moves `1 → 2`, an event is recorded, and its delivery
   state becomes `DELIVERED`.
3. In PromisePatch, report the exception (`today's raspberry delivery didn't arrive`) and answer
   the clarification (`just raspberries - the strawberries came`).
4. The analysis concludes `A AUTO_RECOVERABLE`, `B APPROVAL_REQUIRED`, `C BLOCKED`,
   `D UNAFFECTED`, `E UNAFFECTED`, `F UNAFFECTED`.

Without step 2, `D` is `BLOCKED`: there is no authored variant that rescues a Raspberry Lemon
Layer without raspberries. The classification follows the persisted order line and nothing else
— there is no branch anywhere in PromisePatch that mentions this customer, this order or this
variant.

The same proof runs headlessly:

```bash
uv run python scripts/with_local_env.py -- uv run pytest apps/backend/tests/test_order_system_boundary.py
```

## Where each part lives

| | |
|---|---|
| the wire contract | [`packages/order-contract`](../packages/order-contract) |
| the order system | [`apps/order-simulator`](../apps/order-simulator) |
| the ingress | `promisepatch.api.routers.integrations` |
| applying an event to the mirror | `promisepatch.domain.order_mirror` |
| pushing an amendment | `promisepatch.integrations.order_system` |
| finishing a recovery | `promisepatch.domain.recovery` |

See [ADR-0005](adr/0005-order-system-simulator.md) for why the simulator is canonical and a
Square adapter is optional upside.
