# Documented restart (g8-rehearsal-preparation.md 3.2): `docker compose ... restart worker`,
# with stability compared immediately and after more than 90 s.
source /tmp/pp/lib.sh
stable() { snap | grep -E '^(fixture=|cases=|tracks=|plan_approvals=|requests=|decisions=|replies=|outbox=|orders=|tasks=|timers=|steps=|audit_max=|bound_customers=|hash\.)'; }
echo "PRE_RESTART=$(now)"
echo "BEFORE worker started=$(docker inspect -f '{{.State.StartedAt}}' promisepatch-worker-1) restarts=$(docker inspect -f '{{.RestartCount}}' promisepatch-worker-1)"
counters
stable > /tmp/pp/before.txt; cat /tmp/pp/before.txt
reader | grep -E '^(reader_|unrelated_digest|ef_digest|attributed|FROZEN)' > /tmp/pp/rbefore.txt; cat /tmp/pp/rbefore.txt
echo "RESTART_ISSUED=$(now)"
$DC restart worker 2>&1
echo "RESTART_RETURNED=$(now)"
echo "AFTER worker started=$(docker inspect -f '{{.State.StartedAt}}' promisepatch-worker-1) restarts=$(docker inspect -f '{{.RestartCount}}' promisepatch-worker-1)"
sleep 4
docker logs --since 2m promisepatch-worker-1 2>&1 | grep -E '"worker\.(stop|start|demo_case)"' | mask
stable > /tmp/pp/after0.txt
diff /tmp/pp/before.txt /tmp/pp/after0.txt && echo RESTART_IMMEDIATE_STATE_IDENTICAL || echo RESTART_IMMEDIATE_STATE_DIFFERS
echo "WAITING_95S_FROM=$(now)"
sleep 95
echo "STABILITY_CHECK=$(now)"
stable > /tmp/pp/after95.txt
diff /tmp/pp/before.txt /tmp/pp/after95.txt && echo RESTART_STABLE_AFTER_95S || echo RESTART_STATE_DIFFERS_AFTER_95S
reader | grep -E '^(reader_|unrelated_digest|ef_digest|attributed|FROZEN)' > /tmp/pp/rafter.txt
diff /tmp/pp/rbefore.txt /tmp/pp/rafter.txt && echo READER_IDENTICAL_ACROSS_RESTART || echo READER_DIFFERS
counters
echo "errors_since_restart=$(docker logs --since 3m promisepatch-worker-1 2>&1 | grep -ciE '"level": ?"error"|traceback')"
health
