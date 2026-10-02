"""Release-revalidation snapshot, read-only. Runs inside a deployed backend container.

One READ ONLY transaction. Prints the current case's checkpoint state, counts, ledger maxima and
per-table digests. Address-bearing columns (customer channel address, request channel, decision
and reply sender, provider_ref) are excluded from every digest and never printed; the sender
check is an aggregate count. Before printing, the whole output is checked in-process against
every stored address, and the guard result is printed instead of anything that would leak.
"""

import asyncio
import hashlib
import json
import os

import asyncpg

URL = os.environ["PP_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
EXCLUDED = {
    "customers": {"approval_channel_address"},
    "approval_requests": {"customer_channel", "provider_ref"},
    "approval_decisions": {"sender_identity", "raw_text"},
    "inbound_replies": {"sender_identity", "raw_text"},
    "outbox_messages": {"payload", "provider_ref", "result"},
    "case_steps": {"provider_ref", "result"},
}
TABLES = [
    ("fixture_state", "id"), ("cases", "id"), ("tracks", "id"), ("timers", "id"),
    ("case_steps", "id"), ("customers", "id"), ("orders", "id"), ("order_lines", "id"),
    ("production_tasks", "id"), ("outbox_messages", "id"), ("approval_requests", "id"),
    ("approval_decisions", "id"), ("inbound_replies", "id"), ("plan_approvals", "id"),
    ("inbox_events", "id"),
]


def j(rows):
    return json.dumps([dict(r) for r in rows], default=str, separators=(", ", ": "))


async def main():
    c = await asyncpg.connect(URL)
    await c.execute("set search_path to promisepatch")
    out = []
    p = out.append
    async with c.transaction(readonly=True, isolation="repeatable_read"):
        p(f"db_now={(await c.fetchval('select now()')).isoformat()}")
        fx = await c.fetchrow("select fixture_name, anchor_at, loaded_at, fixture_digest from fixture_state")
        p(f"fixture={fx['fixture_name']} anchor={fx['anchor_at'].isoformat()} digest={fx['fixture_digest']}")
        cases = await c.fetch("select id, state, version, needs_owner_attention from cases order by opened_at")
        p(f"cases={j(cases)}")
        case = cases[-1]["id"] if cases else None
        p("tracks=" + j(await c.fetch(
            "select promise_id, state, classification, rule_id from tracks where case_id=$1 order by promise_id", case)))
        p("plan_approvals=" + j(await c.fetch(
            "select approved_by, channel, approved_at, left(plan_id, 12) as plan from plan_approvals")))
        p("requests=" + j(await c.fetch(
            "select promise_id, state, decided, sent_at, deadline from approval_requests")))
        p("decisions=" + j(await c.fetch(
            "select decision, parser, received_at from approval_decisions")))
        p("sender_match_count=" + str(await c.fetchval(
            "select count(*) from approval_decisions d join approval_requests r on r.id=d.request_id "
            "where d.sender_identity = r.customer_channel")))
        p("replies=" + str(await c.fetchval("select count(*) from inbound_replies")))
        p("inbox=" + j(await c.fetch(
            "select source, state, received_at, processed_at from inbox_events "
            "where received_at >= $1 order by received_at", fx["loaded_at"])))
        p("outbox=" + j(await c.fetch(
            "select kind, state, attempts, idempotency_key, delivered_at from outbox_messages order by created_at")))
        p("outbox_distinct_keys=" + str(await c.fetchval("select count(distinct idempotency_key) from outbox_messages")))
        p("orders=" + j(await c.fetch(
            "select o.external_id, o.external_version, o.state, l.recipe_version_id from orders o "
            "join order_lines l on l.order_id=o.id order by o.external_id")))
        p("tasks=" + j(await c.fetch(
            "select id, state, held_by_case_id is not null as held from production_tasks order by id")))
        p("timers=" + j(await c.fetch(
            "select kind, due_at, claimed_by is not null as claimed, fired_at from timers order by due_at")))
        p("steps=" + j(await c.fetch(
            "select kind, state, attempts from case_steps where case_id=$1 order by created_at", case)))
        p(f"audit_max={await c.fetchval('select max(seq) from audit_events')} "
          f"events_max={await c.fetchval('select max(seq) from domain_events')}")
        p("authority=" + j(await c.fetch(
            "select seq, type, actor_kind, actor_id, authority, occurred_at from audit_events "
            "where case_id=$1 and type not in ('WORKFLOW_STEP_EXECUTED','REVALIDATION_CHECK') order by seq", case)))
        p("revalidation=" + j(await c.fetch(
            "select count(*) as n, count(*) filter (where (after->>'passed')::boolean) as passed, "
            "min(seq) as first_seq, min(occurred_at) as at, array_agg(distinct actor_id) as workers "
            "from audit_events where case_id=$1 and type='REVALIDATION_CHECK'", case)))
        p("step_workers=" + j(await c.fetch(
            "select actor_id, count(*) as n, min(seq) as first_seq, max(seq) as last_seq from audit_events "
            "where case_id=$1 and type='WORKFLOW_STEP_EXECUTED' group by actor_id order by min(seq)", case)))
        p("bound_customers=" + j(await c.fetch(
            "select id, length(approval_channel_address) as address_length from customers "
            "where approval_channel_address !~ '^100[1-6]$' order by id")))
        for table, key in TABLES:
            cols = [r["column_name"] for r in await c.fetch(
                "select column_name from information_schema.columns where table_schema='promisepatch' "
                "and table_name=$1 order by ordinal_position", table)]
            keep = [x for x in cols if x not in EXCLUDED.get(table, set())]
            rows = await c.fetch(f"select {', '.join(keep)} from {table} order by {key}")
            blob = json.dumps([dict(r) for r in rows], default=str, sort_keys=True).encode()
            p(f"hash.{table}={len(rows)}:{hashlib.sha256(blob).hexdigest()[:16]}")
        addresses = [r[0] for r in await c.fetch(
            "select approval_channel_address from customers union select customer_channel from approval_requests "
            "union select sender_identity from approval_decisions union select sender_identity from inbound_replies")]
    await c.close()
    text = "\n".join(out)
    secrets = [a for a in addresses if a and len(a) >= 6]
    digits = [a.split(":")[-1] for a in secrets]
    leak = any(s in text for s in secrets + [d for d in digits if len(d) >= 6])
    if leak:
        print("SNAPSHOT_WITHHELD: an address appeared in the output")
    else:
        print(text)
        print("address_leak_guard=False")


asyncio.run(main())
