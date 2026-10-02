source /tmp/pp/lib.sh
# Read-only proof read for the Simulated Alexa+ via MCP confirmation: database authority trail
# plus the bridge, model, MCP and intent-API log lines since the run's restore.
SINCE=$(cat /tmp/pp/since 2>/dev/null || echo 30m)
echo "ALEXA run=$(cat /tmp/pp/run_label) label=$(cat /tmp/pp/check_label) at=$(now) since=$SINCE"
docker exec -i "$(backend)" python - < $P/alexa.py 2>&1 | mask
echo "--- api: bridge, model, approval and intent lines"
docker logs --since "$SINCE" promisepatch-api-1 2>&1 | grep -E 'simulated_alexa|semantic\.|conversation\.(approve|confirm)|intents\.confirm|"POST /(api/conversation|internal/intents)' | mask | cut -c1-900
echo "--- api: request paths for conversation/intent POSTs"
docker logs --since "$SINCE" promisepatch-api-1 2>&1 | grep -oE '"(method|path|client|client_ip)": ?"[^"]*"|POST /(api/conversation|internal/intents)/[a-z-]+[^"]*' | grep -E 'conversation|intents' | sort | uniq -c
echo "--- mcp: tool and auth lines"
docker logs --since "$SINCE" promisepatch-mcp-1 2>&1 | grep -E 'mcp\.(tool|auth|engine)|POST /mcp' | mask | cut -c1-600
echo "--- container ip of api"
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' promisepatch-api-1
counters
privacy "$SINCE"
