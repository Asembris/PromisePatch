source /tmp/pp/lib.sh
h() { printf '%s' "$1" | sha256sum | cut -c1-16; }
BOT=$(grep '^PP_TELEGRAM_BOT_TOKEN=' env/channel.env | cut -d= -f2-)
LINK=$(grep '^PP_CUSTOMER_LINK_SECRET=' env/channel.env | cut -d= -f2-)
MCPT=$(grep '^PP_MCP_BEARER_TOKEN=' env/mcp.env | cut -d= -f2-)
INT=$(grep '^PP_INTERNAL_SERVICE_TOKEN=' env/api.env | cut -d= -f2-)
ADDR=$(docker exec -i promisepatch-worker-1 python -c '
import asyncio, os, asyncpg
async def m():
    c = await asyncpg.connect(os.environ["PP_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    print(await c.fetchval("select approval_channel_address from promisepatch.customers where id=$1", "cus-tomas")); await c.close()
asyncio.run(m())')
D=${ADDR##*:}
for pair in "address:$(h "$ADDR")" "address_digits:$(h "$D")" "bot_token:$(h "$BOT")" "link_secret:$(h "$LINK")" "mcp_bearer:$(h "$MCPT")" "internal_token:$(h "$INT")"; do
  echo "cloudwatch_match ${pair%%:*}=$(grep -c "^${pair#*:}$" /tmp/pp/cwh16.txt)"
done
echo "candidate_hashes=$(wc -l < /tmp/pp/cwh16.txt)"
unset BOT LINK MCPT INT ADDR D
