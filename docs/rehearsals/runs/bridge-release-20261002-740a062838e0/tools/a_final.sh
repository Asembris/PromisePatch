source /tmp/pp/lib.sh
echo "FINAL=$(now)"
health
counters
privacy 2026-10-01T21:24:00Z
echo "sha256 compose=$(sha256sum docker-compose.yml | cut -c1-16) caddy=$(sha256sum Caddyfile | cut -c1-16) converge=$(sha256sum converge.sh | cut -c1-16)"
echo "volumes: $(docker volume ls --format '{{.Name}}' | tr '\n' ' ')"
docker exec -i promisepatch-api-1 python -c "
from promisepatch.config.settings import Settings as S; s=S(); print('api bridge: url', s.orchestrator_mcp_url, 'bearer_set', s.mcp_bearer_token is not None)"
