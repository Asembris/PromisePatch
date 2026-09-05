"""The operator screen: functional, legible, and unmistakably not PromisePatch.

The visual job here is a single one. A person watching a recording must be able to tell, in the
first second and without narration, that this window belongs to a *different system* -- because
the entire value of Proof A is that the order changed somewhere PromisePatch does not control.
So the palette, the typography and the title are deliberately unlike the PromisePatch UI, the
banner names the system, and a standing notice says what it is authoritative for.

It is otherwise plain on purpose. This slice buys correctness of the boundary, not design: one
table of orders, one obvious control per line, and enough evidence beside it -- version, last
event, delivery state -- to see the mutation leave.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape

from order_contract.events import OrderSnapshot
from order_simulator.seed import CatalogueItem
from order_simulator.store import DeliveryStatus

SYSTEM_NAME = "External Order System — simulator"
STANDING_NOTICE = "Source of truth for demo order state"
HONESTY_NOTICE = (
    "A local stand-in for a point-of-sale or order platform. It is not Square, not a "
    "production POS, and not a real customer system. It exists so an order can be changed "
    "outside PromisePatch and the change can be seen arriving."
)

_STYLE = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0;
  background: #10131a;
  color: #d7dce5;
  font: 15px/1.5 ui-monospace, "SFMono-Regular", "Cascadia Mono", Menlo, Consolas, monospace;
}
header { background: #f2b23c; color: #171a21; padding: 18px 28px; }
header h1 { margin: 0; font-size: 21px; letter-spacing: 0.04em; text-transform: uppercase; }
header p { margin: 6px 0 0; font-size: 13px; font-weight: 700; }
main { padding: 24px 28px 48px; max-width: 1200px; }
.notice {
  border-left: 4px solid #f2b23c;
  background: #1a1f2b;
  padding: 12px 16px;
  margin: 0 0 24px;
  font-size: 13px;
  color: #9aa5b8;
}
table { border-collapse: collapse; width: 100%; margin-bottom: 32px; }
th, td { border-bottom: 1px solid #262c3a; padding: 10px 12px; text-align: left; vertical-align: top; }
th { color: #8d97a9; font-weight: 600; font-size: 12px; text-transform: uppercase; }
td.version { font-size: 20px; color: #f2b23c; }
select, button { font: inherit; padding: 6px 10px; border-radius: 4px; }
select { background: #1a1f2b; color: #d7dce5; border: 1px solid #3a4256; }
button { background: #f2b23c; color: #171a21; border: 1px solid #f2b23c; cursor: pointer; font-weight: 700; }
button.secondary { background: transparent; color: #9aa5b8; border-color: #3a4256; font-weight: 400; }
h2 { font-size: 14px; text-transform: uppercase; letter-spacing: 0.08em; color: #8d97a9; }
.state-DELIVERED { color: #62c37a; }
.state-PENDING, .state-IN_FLIGHT { color: #f2b23c; }
form { display: flex; gap: 8px; align-items: center; margin: 0; }
"""


def _option(item: CatalogueItem, *, selected: bool) -> str:
    flag = " selected" if selected else ""
    return (
        f'<option value="{escape(item.external_item_id)}"{flag}>'
        f"{escape(item.name)} ({escape(item.external_item_id)})</option>"
    )


def _order_row(
    order: OrderSnapshot,
    *,
    catalogue: Mapping[str, CatalogueItem],
    items: Sequence[CatalogueItem],
) -> str:
    line = order.lines[0]
    current = catalogue.get(line.external_item_id)
    offered = None if current is None else current.alternative_item_id
    options = "".join(
        _option(item, selected=item.external_item_id == (offered or line.external_item_id))
        for item in items
    )
    name = "unknown item" if current is None else current.name
    # The order this row is about, named on the row itself. It is what an operator's eye
    # follows down the table, and it is what anything driving this screen addresses -- a
    # locator matching "the row mentioning EXT-D" would also match the event log below.
    return f"""
      <tr data-order-row="{escape(order.external_id)}">
        <td><strong>{escape(order.external_id)}</strong><br><span style="color:#8d97a9">
          {escape(line.external_line_id)}</span></td>
        <td>{escape(order.customer.name)}<br><span style="color:#8d97a9">
          {escape(order.customer.external_id)}</span></td>
        <td>{escape(order.state)}</td>
        <td class="version">{order.version}</td>
        <td>{escape(name)}<br><span style="color:#8d97a9">
          {escape(line.external_item_id)} &times; {line.quantity}</span></td>
        <td>
          <form method="post" action="/ui/orders/{escape(order.external_id)}/lines/{escape(line.external_line_id)}">
            <select name="to_item_id" aria-label="replacement item for {escape(order.external_id)}">
              {options}
            </select>
            <button type="submit">Change item</button>
          </form>
        </td>
      </tr>
    """


def _delivery_row(delivery: DeliveryStatus) -> str:
    error = (
        ""
        if delivery.last_error is None
        else f"<br><span style='color:#8d97a9'>{escape(delivery.last_error)}</span>"
    )
    return f"""
      <tr data-event-row="{escape(str(delivery.event_id))}">
        <td>{escape(delivery.external_order_id)}</td>
        <td>{escape(delivery.type)}</td>
        <td class="version">{delivery.version}</td>
        <td>{escape(delivery.source)}</td>
        <td><span class="state-{escape(delivery.state)}" data-delivery-state>
          {escape(delivery.state)}</span> ({delivery.attempts}){error}</td>
        <td><span style="color:#8d97a9">{escape(str(delivery.event_id))}</span></td>
      </tr>
    """


def render(
    *,
    orders: Sequence[OrderSnapshot],
    catalogue: Sequence[CatalogueItem],
    deliveries: Sequence[DeliveryStatus],
) -> str:
    """The whole operator screen, as one document. No client-side framework and no build step."""
    by_id = {item.external_item_id: item for item in catalogue}
    rows = "".join(_order_row(order, catalogue=by_id, items=catalogue) for order in orders)
    delivery_rows = "".join(_delivery_row(delivery) for delivery in deliveries) or (
        '<tr><td colspan="6" style="color:#8d97a9">no events yet</td></tr>'
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(SYSTEM_NAME)}</title>
  <style>{_STYLE}</style>
</head>
<body>
  <header>
    <h1>{escape(SYSTEM_NAME)}</h1>
    <p>{escape(STANDING_NOTICE)}</p>
  </header>
  <main>
    <p class="notice">{escape(HONESTY_NOTICE)}</p>

    <h2>Orders</h2>
    <table>
      <thead>
        <tr><th>Order</th><th>Customer</th><th>State</th><th>Version</th>
            <th>Item</th><th>Operator action</th></tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>

    <h2>Outbound order events</h2>
    <table>
      <thead>
        <tr><th>Order</th><th>Type</th><th>Version</th><th>Raised by</th>
            <th>Webhook</th><th>Event id</th></tr>
      </thead>
      <tbody>{delivery_rows}</tbody>
    </table>

    <form method="post" action="/ui/reset">
      <button class="secondary" type="submit">Reset demo order book</button>
    </form>
  </main>
</body>
</html>
"""
