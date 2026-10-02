# Checkpoint read: state, frozen reader, counters and a container-log privacy scan since the
# run's restore. Read-only.
source /tmp/pp/lib.sh
RUN=$(cat /tmp/pp/run_label 2>/dev/null || echo unlabelled)
SINCE=$(cat /tmp/pp/since 2>/dev/null || echo 30m)
echo "CHECK run=$RUN label=$(cat /tmp/pp/check_label 2>/dev/null) at=$(now)"
health
counters
snap
reader
privacy "$SINCE"
