# Read-only authority read for the Simulated Alexa+ via MCP confirmation proof. Prints the
# latest case, its plan approvals, the PLAN_APPROVED / PLAN_CONFIRMED audit rows with their
# provenance and correlation ids, the customer-consent tables and every effect queued. Never
# prints a customer address: the output is withheld if one would appear.
import asyncio, json, os, asyncpg

async def main():
    out = []
    p = out.append
    c = await asyncpg.connect(os.environ["PP_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    await c.execute("set search_path to promisepatch")
    async with c.transaction(readonly=True, isolation="repeatable_read"):
        fx = await c.fetchval("select loaded_at from fixture_state")
        p(f"fixture_loaded_at={fx.isoformat()} db_now={(await c.fetchval('select now()')).isoformat()}")
        case = await c.fetchval("select id from cases order by opened_at desc limit 1")
        cr = await c.fetchrow("select state, version from cases where id=$1", case)
        p(f"case={case} state={cr['state']} version={cr['version']} cases_total={await c.fetchval('select count(*) from cases')}")
        for r in await c.fetch("select promise_id, state, classification, rule_id from tracks where case_id=$1 order by promise_id", case):
            p(f"track {r['promise_id']} {r['state']} {r['classification']} {r['rule_id']}")
        p("plan_approvals_total=" + str(await c.fetchval("select count(*) from plan_approvals")))
        for r in await c.fetch("select id, case_id, plan_id, approved_by, channel, evidence, approved_at from plan_approvals order by approved_at"):
            p("plan_approval " + json.dumps({"id": str(r["id"]), "case_id": str(r["case_id"]), "plan_id": r["plan_id"],
              "approved_by": r["approved_by"], "channel": r["channel"], "evidence": r["evidence"],
              "approved_at": r["approved_at"].isoformat()}, sort_keys=True))
        for r in await c.fetch("select seq, type, actor_kind, actor_id, authority, before, after, provenance, correlation_id, occurred_at from audit_events where case_id=$1 and type in ('PLAN_APPROVED','PLAN_CONFIRMED','PLAN_AUTO_ESCALATED') order by seq", case):
            def j(v):
                return json.loads(v) if isinstance(v, str) else v
            p("authority_audit " + json.dumps({"seq": r["seq"], "type": r["type"], "actor_kind": r["actor_kind"], "actor_id": r["actor_id"],
              "authority": r["authority"], "after": j(r["after"]), "provenance": j(r["provenance"]),
              "correlation_id": str(r["correlation_id"]) if r["correlation_id"] else None,
              "occurred_at": r["occurred_at"].isoformat()}, sort_keys=True, default=str))
        for r in await c.fetch("select a.seq, a.type, a.actor_kind, a.authority, a.occurred_at, t.promise_id from audit_events a left join tracks t on t.id=a.track_id where a.case_id=$1 and a.type not in ('WORKFLOW_STEP_EXECUTED','REVALIDATION_CHECK') order by a.seq", case):
            p(f"audit {r['seq']} {r['promise_id']} {r['type']} {r['actor_kind']} {r['authority']} {r['occurred_at'].isoformat()}")
        for r in await c.fetch("select s.kind, s.state, s.attempts, s.created_at, t.promise_id from case_steps s left join tracks t on t.id=s.track_id where s.case_id=$1 and s.created_at >= (select coalesce(min(approved_at), now()) from plan_approvals where case_id=$1) order by s.created_at", case):
            p(f"step {r['created_at'].isoformat()} {r['promise_id']} {r['kind']} {r['state']} attempts={r['attempts']}")
        for r in await c.fetch("select promise_id, state, captured_order_version, sent_at from approval_requests order by sent_at nulls last"):
            p(f"approval_request {r['promise_id']} {r['state']} captured_v={r['captured_order_version']} sent_at={r['sent_at'].isoformat() if r['sent_at'] else None}")
        p("approval_requests_total=" + str(await c.fetchval("select count(*) from approval_requests")))
        p("approval_decisions_total=" + str(await c.fetchval("select count(*) from approval_decisions")))
        p("inbound_replies_total=" + str(await c.fetchval("select count(*) from inbound_replies")))
        p("customer_inbox_since_fixture=" + str(await c.fetchval("select count(*) from inbox_events where received_at >= $1 and source <> 'external-order-system'", fx)))
        for r in await c.fetch("select kind, state, attempts, created_at from outbox_messages order by created_at"):
            p(f"outbox {r['kind']} {r['state']} attempts={r['attempts']} created={r['created_at'].isoformat()}")
        for r in await c.fetch("select o.external_id, o.external_version, o.state, l.recipe_version_id from orders o join order_lines l on l.order_id=o.id order by 1"):
            p(f"mirror {r['external_id']} v{r['external_version']} {r['state']} {r['recipe_version_id']}")
        addresses = [r[0] for r in await c.fetch(
            "select approval_channel_address from customers union select customer_channel from approval_requests")]
    await c.close()
    text = "\n".join(out)
    needles = [a for a in addresses if a and len(a) >= 6]
    needles += [a.split(":")[-1] for a in needles if len(a.split(":")[-1]) >= 6]
    if any(s in text for s in needles):
        print("PROOF_WITHHELD: an address appeared in the output")
    else:
        print(text)
        print("address_leak_guard=False")

asyncio.run(main())
