import asyncio, json, os, re, asyncpg

LINK = re.compile(r"https?://[^\s\"]+")
TOKEN = re.compile(r"v1\.[A-Za-z0-9_.-]{20,}")


async def main():
    c = await asyncpg.connect(os.environ["PP_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    await c.execute("set search_path to promisepatch")
    addrs = [r[0] for r in await c.fetch(
        "select approval_channel_address from customers union select customer_channel from approval_requests")]
    for r in await c.fetch("select created_at, payload from outbox_messages where kind='MESSAGE_SEND' order by created_at"):
        pl = r["payload"]
        pl = json.loads(pl) if isinstance(pl, str) else pl
        s = json.dumps(pl, sort_keys=True, ensure_ascii=False)
        for a in sorted([a for a in addrs if a and len(a) >= 4], key=len, reverse=True):
            s = s.replace(a, "<address>")
            d = a.split(":")[-1]
            if len(d) >= 6:
                s = s.replace(d, "<digits>")
        s = LINK.sub("<link>", s)
        s = TOKEN.sub("<token>", s)
        print(r["created_at"].isoformat(), s[:1500])
    print("approval_requests", await c.fetchval("select count(*) from approval_requests"))
    await c.close()

asyncio.run(main())
