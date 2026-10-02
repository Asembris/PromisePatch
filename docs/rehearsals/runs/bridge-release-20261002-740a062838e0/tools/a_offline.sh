source /tmp/pp/lib.sh
off() { snap | grep -E '^(cases=|tracks=|plan_approvals=|requests=|decisions=|replies=|inbox=|outbox=|orders=|steps=|timers=|audit_max=|revalidation=|hash\.)'; }
echo "OFFLINE_A=$(now) worker_running=$(docker inspect -f '{{.State.Running}}' promisepatch-worker-1)"
off > /tmp/pp/offa.txt; cat /tmp/pp/offa.txt | grep -v '^hash\.'
echo "WAIT_65S"; sleep 65
echo "OFFLINE_B=$(now) worker_running=$(docker inspect -f '{{.State.Running}}' promisepatch-worker-1)"
off > /tmp/pp/offb.txt
diff /tmp/pp/offa.txt /tmp/pp/offb.txt && echo OFFLINE_SNAPSHOTS_IDENTICAL || echo OFFLINE_SNAPSHOTS_DIFFER
counters
