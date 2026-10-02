source /tmp/pp/lib.sh
echo "IPS at=$(now)"
for c in api worker mcp caddy order-simulator; do echo "ip $c $(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' promisepatch-$c-1)"; done
health
