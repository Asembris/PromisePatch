source /tmp/pp/lib.sh
echo "STOP_ISSUED=$(now)"
$DC stop worker 2>&1
echo "STOP_RETURNED=$(now) worker_running=$(docker inspect -f '{{.State.Running}}' promisepatch-worker-1)"
docker logs --since 1m promisepatch-worker-1 2>&1 | grep -E '"worker\.stop"' | mask
counters
snap | grep -E '^(cases=|plan_approvals=|requests=|outbox=|orders=|tasks=|timers=|steps=|audit_max=|inbox=|decisions=|revalidation=)'
