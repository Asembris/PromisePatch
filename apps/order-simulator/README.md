# External Order System — simulator

A separate application that owns customer orders for the PromisePatch demo.

**It is a simulator.** It is not Square, not a production point of sale, and not a real
customer system. It proves integration mechanics — that an order changed *outside* PromisePatch
reaches PromisePatch through a signed contract and changes what PromisePatch decides. It proves
nothing about third-party product adoption, and the narration never says otherwise.

## Why it exists

Proof A requires an order mutation made outside PromisePatch, on camera, arriving as a change
event within seconds. That is only meaningful if the mutation genuinely happens somewhere else,
so this runs as its own process, on its own port, in its own window, over its own SQLite file.
It shares no database, no models and no code with PromisePatch; between them sit the
`order-contract` distribution and two HTTP calls.

## What it holds

`orders`, `order_lines`, `catalogue_items`, `customers`, `order_events`, `webhook_deliveries`
and `idempotent_commands` — in `OS_DATABASE_PATH`. The order's `version` is this system's own
monotonic counter, and it is the number PromisePatch mirrors.

## What it exposes

| Route | For |
|---|---|
| `GET /` | the operator screen: order list, one-click item change, event and delivery state |
| `GET /orders`, `GET /orders/{id}` | the authoritative current state of an order |
| `POST /orders/{id}/amendments` | one governed recovery amendment, keyed by `Idempotency-Key` |
| `POST /admin/reset` | put the demo order book back |
| `GET /admin/events` | recent events and where each delivery got to |
| `GET /healthz`, `GET /readyz` | liveness, and whether the store is open and seeded |

Every committed mutation writes its order change, its version bump and its event in one SQLite
transaction, and a durable delivery loop signs and posts the event afterwards — retrying for as
long as it takes, resuming after a restart, and never minting a second event id for a retry.

## Configuration

`OS_DATABASE_PATH`, `OS_WEBHOOK_URL`, `OS_WEBHOOK_SECRET`, `OS_LOG_LEVEL`,
`OS_WEBHOOK_TIMEOUT_SECONDS`, `OS_WEBHOOK_MAX_BACKOFF_SECONDS`. Secrets are generated into
gitignored files by `scripts/bootstrap_local_env.py`; none is ever committed.

## Running it

```
docker compose up --detach --wait      # http://localhost:58100
uv run order-simulator                 # without Docker
```
