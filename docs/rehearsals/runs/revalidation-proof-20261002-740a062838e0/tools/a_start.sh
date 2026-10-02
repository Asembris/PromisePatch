source /tmp/pp/lib.sh
echo "PRE_START=$(now)"
snap | grep -E '^(cases=|plan_approvals=|requests=|decisions=|outbox=|orders=|steps=|audit_max=|inbox=|revalidation=)'
echo "START_ISSUED=$(now)"
$DC start worker 2>&1
echo "START_RETURNED=$(now) started=$(docker inspect -f '{{.State.StartedAt}}' promisepatch-worker-1)"
sleep 20
docker logs --since 2m promisepatch-worker-1 2>&1 | grep -E '"worker\.(start|demo_case)"|worker.step.executed' | mask | cut -c1-300
counters
