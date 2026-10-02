source /tmp/pp/lib.sh
# The changed world: one operator edit in the External Order System's own screen route,
# EXT-B line ol-b quantity 1 -> 2, item unchanged. The same route the effect-set S06 uses.
# Taken while the PromisePatch worker is stopped, after the customer's press is stored.
echo "EDIT run=$(cat /tmp/pp/run_label) at=$(now) worker_running=$(docker inspect -f '{{.State.Running}}' promisepatch-worker-1)"
running worker && { echo "REFUSED: worker is running"; exit 1; }
docker exec -i promisepatch-api-1 python - <<'PY'
import json, time, urllib.parse, urllib.request
B = "http://order-simulator:8100"
def get(path):
    with urllib.request.urlopen(B + path, timeout=15) as r:
        return json.load(r)
def show(tag):
    o = get("/orders/EXT-B")
    print(tag, "EXT-B", json.dumps(o, sort_keys=True))
show("STORE_BEFORE")
body = urllib.parse.urlencode({"to_item_id": "rv-raspberry-rose-2", "quantity": "2"}).encode()
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
req = urllib.request.Request(B + "/ui/orders/EXT-B/lines/ol-b", data=body, method="POST")
try:
    urllib.request.build_opener(NoRedirect).open(req, timeout=15)
    status = 200
except urllib.error.HTTPError as e:
    status = e.code
print("OPERATOR_CHANGE_STATUS", status, "at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
show("STORE_AFTER")
for _ in range(20):
    ev = get("/admin/events")
    rows = ev.get("events", ev) if isinstance(ev, dict) else ev
    mine = [e for e in rows if json.dumps(e).find("EXT-B") >= 0]
    if mine and json.dumps(mine[-1]).find("DELIVERED") >= 0:
        break
    time.sleep(1.5)
print("EXT_B_EVENTS", json.dumps(mine, sort_keys=True))
PY
echo "--- PromisePatch side, worker stopped: the event is stored, the mirror has not moved"
docker exec -i promisepatch-api-1 python - <<'PY'
import asyncio, os, asyncpg
async def main():
    c = await asyncpg.connect(os.environ["PP_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    await c.execute("set search_path to promisepatch")
    fx = await c.fetchval("select loaded_at from fixture_state")
    for r in await c.fetch("select source, state, received_at from inbox_events where received_at >= $1 order by received_at", fx):
        print("inbox", r["source"], r["state"], r["received_at"].isoformat())
    for r in await c.fetch("select o.external_id, o.external_version, l.recipe_version_id, l.quantity from orders o join order_lines l on l.order_id=o.id where o.external_id in ('EXT-A','EXT-B') order by 1"):
        print("mirror", r["external_id"], f"v{r['external_version']}", r["recipe_version_id"], "qty", r["quantity"])
    await c.close()
asyncio.run(main())
PY
