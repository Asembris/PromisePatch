#!/bin/bash
# usage: hostrun.sh <script> [extra files staged beside it in /tmp/pp/]
# Runs <script> as root on the host through one non-interactive SSM session.
set -euo pipefail
S="C:/Users/Asembris/AppData/Local/Temp/claude/D--PromisePatch/ba76b5dc-8abb-4b46-86ce-4382022b4e5e/scratchpad"
export AWS_PROFILE=promisepatch AWS_DEFAULT_REGION=us-east-1 AWS_CA_BUNDLE="$S/ca.pem" AWS_MAX_ATTEMPTS=10 AWS_RETRY_MODE=adaptive
main="$(basename "$1")"
tmp=$(cygpath -m "$(mktemp -d)")
mkdir -p "$tmp/pp"
for f in "$@"; do sed 's/\r$//' "$f" > "$tmp/pp/$(basename "$f")"; done
b64=$(tar -C "$tmp" -czf - pp | base64 -w0)
B64="$b64" MAIN="$main" OUT="$tmp/p.json" python -c '
import json, os
cmd = "bash -lc \"rm -rf /tmp/pp && echo %s | base64 -d | tar -C /tmp -xzf - && sudo bash /tmp/pp/%s </dev/null\"" % (os.environ["B64"], os.environ["MAIN"])
json.dump({"command": [cmd]}, open(os.environ["OUT"], "w"))
'
MSYS_NO_PATHCONV=1 aws ssm start-session --target i-087c742587f83d61d \
  --document-name AWS-StartNonInteractiveCommand --parameters "file://$tmp/p.json" 2>&1 | tr -d '\r'
rm -rf "$tmp"
