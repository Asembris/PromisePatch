source /tmp/pp/lib.sh
echo "EXTRA run=$(cat /tmp/pp/run_label) at=$(now)"
docker exec -i "$(backend)" python - <<'PY'
import asyncio, json, os, urllib.request, asyncpg
async def main():
    with urllib.request.urlopen("http://order-simulator:8100/orders", timeout=15) as r:
        store = json.load(r)
    rows = store.get("orders", store) if isinstance(store, dict) else store
    s = {o.get("external_id", o.get("id")): o for o in rows}
    c = await asyncpg.connect(os.environ["PP_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    await c.execute("set search_path to promisepatch")
    m = {r["external_id"]: r for r in await c.fetch("select o.external_id, o.external_version, o.state, l.recipe_version_id from orders o join order_lines l on l.order_id=o.id")}
    for e in ("EXT-A", "EXT-B"):
        o = s.get(e, {}); line = (o.get("lines") or [{}])[0]
        sv = o.get("version", o.get("external_version")); sr = line.get("external_item_id")
        print(f"{e} store=v{sv} {o.get('state')} {sr} mirror=v{m[e]['external_version']} {m[e]['state']} {m[e]['recipe_version_id']} match={sv==m[e]['external_version'] and sr==m[e]['recipe_version_id']}")
    case = await c.fetchval("select id from cases order by opened_at desc limit 1")
    dec = await c.fetchval("select seq from audit_events where case_id=$1 and type='APPROVAL_DECISION_RECORDED'", case)
    first = await c.fetchval("select min(seq) from audit_events where case_id=$1 and type='REVALIDATION_CHECK'", case)
    print(f"decision_seq={dec} first_check_seq={first} checks_after_decision={first is not None and dec is not None and first > dec}")
    for r in await c.fetch("select type, actor_kind, actor_id, authority from audit_events where case_id=$1 and type in ('PLAN_APPROVED','PLAN_CONFIRMED','APPROVAL_DECISION_RECORDED','RECOVERY_REVALIDATED','RECOVERY_APPLIED','RECOVERY_COMPLETED','PLAN_AUTO_ESCALATED') order by seq", case):
        print("audit", r["type"], r["actor_kind"], r["actor_id"], r["authority"])
    print("cases_total", await c.fetchval("select count(*) from cases"))
    await c.close()
asyncio.run(main())
PY
