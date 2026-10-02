#!/bin/bash
# usage: rr.sh <action> <run> <since> <check_label> <logname>
S="C:/Users/Asembris/AppData/Local/Temp/claude/D--PromisePatch/ba76b5dc-8abb-4b46-86ce-4382022b4e5e/scratchpad"; H="$S/host"
printf '%s' "$2" > "$H/run_label"; printf '%s' "$3" > "$H/since"; printf '%s' "$4" > "$H/check_label"
mkdir -p "$S/ev/rehearsals"
bash "$S/hostrun.sh" "$H/$1.sh" "$H/lib.sh" "$H/snap.py" "$H/g8ev.py" "$H/run_label" "$H/since" "$H/check_label" | tee "$S/ev/rehearsals/$5.log"
