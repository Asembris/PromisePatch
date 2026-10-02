#!/bin/bash
# usage: go.sh <action> <run> <check_label> <logname>
S="C:/Users/Asembris/AppData/Local/Temp/claude/D--PromisePatch/528eb924-892e-4e1e-bd34-d8578efe8e5e/scratchpad"; H="$S/host"
printf '%s' "$2" > "$H/run_label"; printf '%s' "$3" > "$H/check_label"
[ -f "$H/since" ] || printf '30m' > "$H/since"
bash "$S/hostrun.sh" "$H/$1.sh" "$H/lib.sh" "$H/snap.py" "$H/g8ev.py" "$H/alexa.py" "$H/run_label" "$H/since" "$H/check_label" | grep -v 'Session' | tee "$S/ev/$4.log"
