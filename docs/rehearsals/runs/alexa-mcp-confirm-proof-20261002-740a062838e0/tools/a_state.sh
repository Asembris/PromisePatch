source /tmp/pp/lib.sh
echo "STATE run=$(cat /tmp/pp/run_label) at=$(now) worker_running=$(docker inspect -f '{{.State.Running}}' promisepatch-worker-1)"
snap | grep -E '^(cases=|tracks=|plan_approvals=|requests=|decisions=|inbox=|outbox=|orders=)'
counters
