source /tmp/pp/lib.sh
# Read-only: wait (worker stopped) until the customer's press is stored as one inbox row.
echo "WATCH_START=$(now) worker_running=$(docker inspect -f '{{.State.Running}}' promisepatch-worker-1)"
for i in $(seq 1 150); do
  n=$(docker exec -i promisepatch-api-1 python - <<'PY'
import asyncio, os, asyncpg
async def main():
    c = await asyncpg.connect(os.environ["PP_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    fx = await c.fetchval("select loaded_at from promisepatch.fixture_state")
    print(await c.fetchval("select count(*) from promisepatch.inbox_events where received_at >= $1 and source <> 'external-order-system'", fx))
    await c.close()
asyncio.run(main())
PY
)
  if [ "$n" -ge 1 ]; then echo "PRESS_STORED=$(now) customer_inbox_rows=$n"; break; fi
  sleep 6
done
echo "WATCH_END=$(now)"
snap | grep -E '^(cases=|tracks=|requests=|decisions=|replies=|inbox=|outbox=|orders=|audit_max=|revalidation=)'
