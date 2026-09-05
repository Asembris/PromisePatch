# order-contract

The wire contract between PromisePatch and the external order system that owns customer
orders. One distribution, imported by both sides, so the two implementations of the same
message cannot drift apart.

It holds three things and nothing else:

* `events` — the `order.updated` / `order.cancelled` envelope the order system emits, carrying
  the authoritative snapshot of the order it is about.
* `amendments` — the governed recovery amendment PromisePatch pushes, and what the order
  system answers with.
* `signing` — the HMAC-SHA256 signature and timestamp window that authenticate a webhook.

Pydantic and the standard library. No I/O, no database models, no HTTP client, and no
knowledge of either application. That is what lets the order system depend on it without
depending on PromisePatch.
