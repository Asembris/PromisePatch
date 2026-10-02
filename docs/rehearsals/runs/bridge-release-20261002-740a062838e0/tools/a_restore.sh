# Protocol step 1: guarded restore through the env union (g8-rehearsal-preparation.md 3.1, 4).
source /tmp/pp/lib.sh
RUN=$(cat /tmp/pp/run_label 2>/dev/null || echo unlabelled)
echo "RESTORE_ENTRY run=$RUN at=$(now)"
health
counters
running worker || { echo "REFUSED: worker is not running"; exit 1; }
W=promisepatch-worker-1
union_load
echo "--- (a) settings preflight under the union"
docker exec -i $UNION $W python - <<'PY'
from promisepatch.config.settings import Settings
s = Settings()
for name in ("require_migration_database_url", "require_db_app_password",
             "require_demo_worker_password", "require_demo_owner_password",
             "require_order_system_base_url", "require_customer_link_secret",
             "require_telegram_bot_token"):
    try:
        getattr(s, name)(); print(name, "ok")
    except Exception as e:
        print(name, "REFUSED", type(e).__name__)
print("allow_fixture_reset", s.allow_fixture_reset, "demo_session_enabled", s.demo_session_enabled,
      "provider", s.customer_channel_provider)
PY
echo "--- (b) dry run under the union"
DRY=$(docker exec $UNION $W pp restore-demo-world --dry-run 2>&1); DRC=$?
printf '%s\n' "$DRY" | mask
echo "dry_run_exit=$DRC"
GATE=ok
[ $DRC -eq 0 ] || GATE="dry-run exit $DRC"
printf '%s' "$DRY" | grep -q '^binding: *restored' || GATE="binding not restored"
printf '%s' "$DRY" | grep -q 'unsettled=0' || GATE="unsettled not 0"
printf '%s' "$DRY" | grep -q 'fixture=hollow-oak' || GATE="fixture not hollow-oak"
echo "gate=$GATE"
if [ "$GATE" != ok ]; then union_unload; echo "RESTORE_NOT_RUN"; exit 1; fi
echo "--- confirmed restore, once"
echo "RESTORE_START=$(now)"
docker exec $UNION $W pp restore-demo-world --confirm destroy-and-restore 2>&1 | mask
RC=${PIPESTATUS[0]}
echo "RESTORE_END=$(now) exit=$RC"
union_unload
[ $RC -eq 0 ] && echo RESTORE_EXIT_ZERO || echo "RESTORE_EXIT_$RC"
echo "--- destination verified, no message sent"
docker exec -i $W python - <<'PY'
import asyncio, os, asyncpg
from promisepatch.config.settings import Settings
from promisepatch.cli import _verify_destination
async def main():
    c = await asyncpg.connect(os.environ["PP_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    addr = await c.fetchval("select approval_channel_address from promisepatch.customers where id='cus-tomas'")
    await c.close()
    v = await _verify_destination(Settings(), addr)
    print("returned_id_matches_stored", str(v.chat_id) == addr.split(":")[-1], "chat_type", v.chat_type, "bot", v.bot_username)
asyncio.run(main())
PY
counters
snap
reader
