source /tmp/pp/lib.sh
# Read-only proof read for the revalidation demonstration: B's checklist, the authority trail,
# every effect PromisePatch queued, and the order system's own record of EXT-A and EXT-B.
echo "PROOF run=$(cat /tmp/pp/run_label) label=$(cat /tmp/pp/check_label) at=$(now)"
docker exec -i "$(backend)" python - <<'PY'
import asyncio, json, os, urllib.request, asyncpg

def get(path):
    with urllib.request.urlopen("http://order-simulator:8100" + path, timeout=15) as r:
        return json.load(r)

async def main():
    out = []
    p = out.append
    c = await asyncpg.connect(os.environ["PP_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    await c.execute("set search_path to promisepatch")
    async with c.transaction(readonly=True, isolation="repeatable_read"):
        case = await c.fetchval("select id from cases order by opened_at desc limit 1")
        p(f"case={case} state={await c.fetchval('select state from cases where id=$1', case)}")
        for r in await c.fetch("select promise_id, state, classification, rule_id from tracks where case_id=$1 order by promise_id", case):
            p(f"track {r['promise_id']} {r['state']} {r['classification']} {r['rule_id']}")
        for r in await c.fetch("select to_jsonb(a) - 'customer_channel' - 'provider_ref' as r from approval_requests a order by sent_at nulls last, id"):
            d = json.loads(r["r"])
            p("request " + json.dumps({k: d.get(k) for k in ("promise_id", "state", "decided", "captured_order_version", "captured_recipe_version_id", "plan_id", "sent_at", "deadline") if k in d}, sort_keys=True))
        for r in await c.fetch("select decision, parser, received_at from approval_decisions order by received_at"):
            p(f"decision {r['decision']} {r['parser']} {r['received_at'].isoformat()}")
        p("plan_approvals=" + str(await c.fetchval("select count(*) from plan_approvals")))
        for r in await c.fetch("select s.kind, s.state, s.attempts, s.result, s.created_at, t.promise_id from case_steps s left join tracks t on t.id=s.track_id where s.case_id=$1 and s.kind in ('PLAN_RECOVERY','REQUEST_APPROVAL','RECEIVE_CUSTOMER_REPLY','REVALIDATE_RECOVERY','APPLY_RECOVERY','FINALIZE_RECOVERY') order by s.created_at", case):
            res = r["result"]
            if isinstance(res, str):
                res = json.loads(res)
            res = res or {}
            brief = {k: res.get(k) for k in ("outcome", "deciding_check", "classification", "rule_id", "promise_id") if k in res}
            p(f"step {r['created_at'].isoformat()} {r['promise_id']} {r['kind']} {r['state']} attempts={r['attempts']} {json.dumps(brief, sort_keys=True)}")
            for ch in res.get("checks", []) or []:
                p("  check " + json.dumps({k: ch.get(k) for k in ("index", "name", "passed", "expected", "actual")}, sort_keys=True))
        for r in await c.fetch("select a.seq, a.type, a.actor_kind, a.authority, a.after, a.occurred_at, t.promise_id from audit_events a left join tracks t on t.id=a.track_id where a.case_id=$1 and a.type not in ('WORKFLOW_STEP_EXECUTED','REVALIDATION_CHECK') order by a.seq", case):
            after = r["after"]
            if isinstance(after, str):
                after = json.loads(after)
            keep = {k: after.get(k) for k in ("deciding_check", "track_state", "state", "decision", "reason", "outcome", "classification", "external_version", "request_state") if isinstance(after, dict) and k in after}
            p(f"audit {r['seq']} {r['promise_id']} {r['type']} {r['actor_kind']} {r['authority']} {r['occurred_at'].isoformat()} {json.dumps(keep, sort_keys=True)}")
        for r in await c.fetch("select kind, state, attempts, idempotency_key, created_at, delivered_at, case when kind='ORDER_AMEND' then payload else null end as payload from outbox_messages order by created_at"):
            pl = r["payload"]
            if isinstance(pl, str):
                pl = json.loads(pl)
            target = None
            if isinstance(pl, dict):
                target = {k: pl.get(k) for k in pl if k in ("external_order_id", "external_line_id", "to_item_id", "base_version", "expected_version", "option_id")}
            p(f"outbox {r['kind']} {r['state']} attempts={r['attempts']} key={r['idempotency_key'] if r['kind']=='ORDER_AMEND' else '-'} created={r['created_at'].isoformat()} target={json.dumps(target, sort_keys=True)}")
        for r in await c.fetch("select o.external_id, o.external_version, o.state, l.recipe_version_id, l.quantity from orders o join order_lines l on l.order_id=o.id order by 1"):
            p(f"mirror {r['external_id']} v{r['external_version']} {r['state']} {r['recipe_version_id']} qty={r['quantity']}")
        addresses = [r[0] for r in await c.fetch(
            "select approval_channel_address from customers union select customer_channel from approval_requests "
            "union select sender_identity from approval_decisions union select sender_identity from inbound_replies")]
    await c.close()
    def brief(o):
        return {"version": o.get("version", o.get("external_version")), "state": o.get("state"),
                "lines": [{"item": l.get("external_item_id"), "qty": l.get("quantity"), "note": (l.get("note") or "")[:48]} for l in o.get("lines", [])]}
    for e in ("EXT-A", "EXT-B"):
        p(f"store {e} " + json.dumps(brief(get(f"/orders/{e}")), sort_keys=True))
    ev = get("/admin/events")
    rows = ev.get("events", ev) if isinstance(ev, dict) else ev
    for e in rows:
        s = json.dumps(e, sort_keys=True)
        if "EXT-A" in s or "EXT-B" in s:
            ev_ = e.get("event", {})
            cmd = ev_.get("command")
            p("store_event " + json.dumps({"order": ev_.get("order", {}).get("external_id"), "version": brief(ev_.get("order", {}))["version"],
                "occurred_at": ev_.get("occurred_at"), "origin": "PromisePatch amendment " + cmd.get("idempotency_key", "") if cmd else "operator change in the order system",
                "lines": brief(ev_.get("order", {}))["lines"], "delivery": e.get("delivery_state"), "attempts": e.get("attempts")}, sort_keys=True))
    text = "\n".join(out)
    secrets = [a for a in addresses if a and len(a) >= 6]
    digits = [a.split(":")[-1] for a in secrets]
    needles = secrets + [d for d in digits if len(d) >= 6]
    masked = 0
    for i, line in enumerate(out):
        if line.startswith("  check "):
            for sec in sorted(secrets, key=len, reverse=True):
                if sec in line:
                    masked += line.count(sec)
                    line = line.replace(sec, "<channel-address>")
            out[i] = line
    out.append(f"masked_check_addresses={masked}")
    text = chr(10).join(out)
    if any(s in text for s in needles):
        print("PROOF_WITHHELD: an address appeared in the output")
        for i, line in enumerate(out):
            if any(s in line for s in needles):
                print("  hit_line", i, " ".join(line.split(" ")[:3])[:60], "whole_address" if any(s in line for s in secrets) else "digits_only")
    else:
        print(text)
        print("address_leak_guard=False")

asyncio.run(main())
PY
