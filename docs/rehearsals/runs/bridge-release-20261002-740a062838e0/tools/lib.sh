# Shared host-side helpers for the release-revalidation rehearsals. Sourced by every action
# script; runs as root in /opt/promisepatch. Prints counts, digests and states, never a value
# of a secret or an address.
cd /opt/promisepatch
P=/tmp/pp
DC="docker compose --env-file env/stack.env"
N=$(grep '^TLS_HOSTNAME=' env/stack.env | cut -d= -f2-)
now() { date -u +%Y-%m-%dT%H:%M:%S.%NZ | cut -c1-26; }
# Hex-safe mask: a long decimal run that is not part of a hex digest.
mask() { sed -E 's/(^|[^0-9a-fA-F])[0-9]{9,}($|[^0-9a-fA-F])/\1<num>\2/g'; }
running() { [ "$(docker inspect -f '{{.State.Running}}' promisepatch-$1-1 2>/dev/null)" = true ]; }
backend() { if running worker; then echo promisepatch-worker-1; else echo promisepatch-api-1; fi; }

health() {
  echo "healthz=$(curl -s --resolve "$N:443:127.0.0.1" "https://$N/healthz")"
  curl -s --resolve "$N:443:127.0.0.1" "https://$N/readyz" | python3 -c '
import json,sys; d=json.load(sys.stdin); f=d["fixture"]; m=d["migrations"]
print("readyz", d["status"], "migration", m["actual_revision"], "fixture", f["anchor_at"], f["digest"])'
  for c in api worker mcp caddy order-simulator; do
    echo "container $c image=$(docker inspect -f '{{.Config.Image}}' promisepatch-$c-1 | sed 's/.*://') running=$(docker inspect -f '{{.State.Running}}' promisepatch-$c-1) started=$(docker inspect -f '{{.State.StartedAt}}' promisepatch-$c-1) restarts=$(docker inspect -f '{{.RestartCount}}' promisepatch-$c-1)"
  done
  echo "host_boot_id=$(cat /proc/sys/kernel/random/boot_id)"
}

counters() {
  local l; l=$(docker logs promisepatch-worker-1 2>&1)
  echo "counters sendMessage=$(printf '%s\n' "$l" | grep -c 'sendMessage') worker.telegram.sent=$(printf '%s\n' "$l" | grep -c 'worker.telegram.sent') getUpdates=$(printf '%s\n' "$l" | grep -c 'getUpdates') worker.start=$(printf '%s\n' "$l" | grep -c '"worker.start"') worker.stop=$(printf '%s\n' "$l" | grep -c '"worker.stop"')"
}

snap() { docker exec -i "$(backend)" python - < $P/snap.py 2>&1 | mask; }

reader() {
  local c; c=$(backend)
  echo "reader_sha256=$(sha256sum $P/g8ev.py | cut -d' ' -f1) container=${c#promisepatch-}"
  local out; out=$(docker exec -i "$c" python - < $P/g8ev.py 2>&1); local rc=$?
  # In-container leak check: is any stored address inside the reader's output?
  printf '%s' "$out" | docker exec -i "$c" python -c '
import asyncio, os, sys, asyncpg
text = sys.stdin.read()
async def main():
    c = await asyncpg.connect(os.environ["PP_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    rows = await c.fetch("select approval_channel_address from promisepatch.customers")
    await c.close()
    print("reader_leak_guard=" + str(any(r[0] and len(r[0]) >= 6 and r[0] in text for r in rows)))
asyncio.run(main())'
  printf '%s\n' "$out" | mask
  [ $rc -eq 0 ] && echo FROZEN_READER_EXIT_ZERO || echo "FROZEN_READER_EXIT_$rc"
}

# Container-log privacy scan since a timestamp: counts only. Values are read here and compared,
# never printed.
privacy() {
  local since="$1" c="$(backend)"
  local BOT LINK MCPT INT
  BOT=$(grep '^PP_TELEGRAM_BOT_TOKEN=' env/channel.env | cut -d= -f2-)
  LINK=$(grep '^PP_CUSTOMER_LINK_SECRET=' env/channel.env | cut -d= -f2-)
  MCPT=$(grep '^PP_MCP_BEARER_TOKEN=' env/mcp.env | cut -d= -f2-)
  INT=$(grep '^PP_INTERNAL_SERVICE_TOKEN=' env/api.env | cut -d= -f2-)
  local all; all=$(for x in api worker mcp caddy order-simulator; do docker logs --since "$since" promisepatch-$x-1 2>&1; done)
  local addr_hits
  addr_hits=$(printf '%s' "$all" | docker exec -i "$c" python -c '
import asyncio, os, sys, asyncpg
text = sys.stdin.read()
async def main():
    c = await asyncpg.connect(os.environ["PP_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    rows = await c.fetch("select approval_channel_address from promisepatch.customers")
    await c.close()
    print(sum(text.count(r[0]) for r in rows if r[0] and len(r[0]) >= 6))
asyncio.run(main())')
  echo "privacy since=$since lines=$(printf '%s\n' "$all" | wc -l) address=$addr_hits bot_token=$(printf '%s' "$all" | grep -cF "$BOT") link_secret=$(printf '%s' "$all" | grep -cF "$LINK") mcp_bearer=$(printf '%s' "$all" | grep -cF "$MCPT") internal_token=$(printf '%s' "$all" | grep -cF "$INT") token_shaped=$(printf '%s' "$all" | grep -cE 'v1\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}') unredacted_query=$(printf '%s' "$all" | grep -E 'approve=' | grep -vc 'approve=REDACTED') unredacted_path=$(printf '%s' "$all" | grep -E 'approval/' | grep -vc 'approval/REDACTED')"
  unset BOT LINK MCPT INT
}

# The restore env union: the reseed's settings live in env/migrate.env, which no running
# container holds. Read into this shell, passed by NAME with `docker exec -e NAME` so no value
# reaches argv, unset afterwards. PP_ALLOW_FIXTURE_RESET is the literal true the protocol names.
union_load() {
  set -a
  eval "$(grep -E '^(PP_MIGRATION_DATABASE_URL|PP_DB_APP_PASSWORD|PP_DEMO_WORKER_PASSWORD|PP_DEMO_OWNER_PASSWORD)=' env/migrate.env)"
  PP_ALLOW_FIXTURE_RESET=true
  set +a
}
union_unload() { unset PP_MIGRATION_DATABASE_URL PP_DB_APP_PASSWORD PP_DEMO_WORKER_PASSWORD PP_DEMO_OWNER_PASSWORD PP_ALLOW_FIXTURE_RESET; }
UNION="-e PP_MIGRATION_DATABASE_URL -e PP_DB_APP_PASSWORD -e PP_DEMO_WORKER_PASSWORD -e PP_DEMO_OWNER_PASSWORD -e PP_ALLOW_FIXTURE_RESET"
