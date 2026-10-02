source /tmp/pp/lib.sh
docker exec -i "$(backend)" python - <<'PY'
import asyncio, os, asyncpg
async def main():
    c = await asyncpg.connect(os.environ["PP_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    for t in ("approval_requests","outbox_messages","order_lines","case_steps","audit_events"):
        cols=[r[0] for r in await c.fetch("select column_name from information_schema.columns where table_schema='promisepatch' and table_name=$1 order by ordinal_position",t)]
        print(t, cols)
    print(await c.fetch("select distinct type from promisepatch.audit_events order by 1"))
    print(await c.fetch("select distinct kind from promisepatch.case_steps order by 1"))
    await c.close()
asyncio.run(main())
PY
