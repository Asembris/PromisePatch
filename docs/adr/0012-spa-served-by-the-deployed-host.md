# ADR-0012 — The deployed host serves the single-page application

Status: accepted
Date: 2026-09-13
Phase: 7

Records the one P7.3 decision that departs from a frozen architecture document. It is an
**extension of the compute decision P6.1 already took**, not a standalone superseding one:
`ARCHITECTURE_PLAN.md` describes a static bundle on S3 behind CloudFront in front of an
ECS/ALB compute topology, P6.1 declined the second half of that sentence with reasons
([p6.1-deployment-preflight.md](../p6.1-deployment-preflight.md)), and this decides the one
piece of it P6.1 left standing.

It moves no authority boundary. Nothing here changes who may read, who may write, what the
domain admits, or what the MCP surface checks. It decides which process hands a browser a
JavaScript file.

## Context

P7.1 locks the case workspace at `/` and `/?case=<id>` as the primary judge surface, reached in
one action with no CLI, no README and no navigation. The deployed stack served neither: `/`
answered a one-line `404` and no bundle existed on the host at all.

Three ways to publish it were available. Two constraints, both measured from the repository
rather than assumed, decided between them.

1. **The deployed composition is 4052 bytes against a hard 4096-byte cap.**
   `deploy/compose/docker-compose.deploy.yml` is uploaded to an SSM standard-tier parameter and
   `deploy/deploy.sh` refuses the upload above 4096 bytes. 44 bytes of headroom. A frontend
   service block is 250–350 bytes; it fits only by deleting the 919 bytes of explanation that
   are the only place the deployed topology is explained.
2. **The instance role's ECR read is enumerated to exactly two repositories** —
   `promisepatch/backend` and `promisepatch/order-simulator` — in
   `deploy/cloudformation/promisepatch.yaml`. A third image is an IAM edit. It is reachable
   without the account owner, and it is not free.

## Decision

**The backend image carries the built bundle, and the API process serves it. No new service, no
new image, no new IAM, no new ECR repository, and no byte added to the composition.**

1. `docker/Dockerfile.backend` gains a Node build stage that runs `npm ci` and `npm run build`
   against `apps/frontend`. The only thing copied into the runtime image is `dist/`. Nothing
   from `node_modules` reaches the runtime layer, and the Python runtime stage is otherwise
   untouched.
2. The API mounts the bundle **last**, after every router, behind a fallback that serves
   `index.html` only for a path that is not owned by the API. `/api`, `/events`, `/internal`,
   `/healthz`, `/readyz`, `/docs` and `/openapi.json` are never answered by the bundle: an
   unknown `/api/...` path returns the API's own JSON `404`, never a page.
3. `/internal*` is refused explicitly, in two independent places — at the API's fallback and in
   the Caddyfile in front of it — because the reverse proxy stops being an allowlist the moment
   a catch-all exists.
4. Hashed assets are `immutable, max-age=31536000`; `index.html` is `no-store`. A cached
   `index.html` pointing at a hashed bundle the next release deleted is the one failure mode
   that makes a deployed judge entry a blank page.
5. `docker/Dockerfile.frontend` stays and is unchanged. Local development keeps the Vite dev
   server and its proxy, which is what hot reload needs. That is the ordinary development /
   production split, not a divergence in runtime behaviour: both serve the same source through
   the same API on the same origin.

## Consequences

- **A frontend release requires a backend image build.** Accepted: `deploy.sh images` already
  builds and pushes both images in one stage, and one image tag now moves the whole surface.
- **The UI is up exactly when the API is up.** There is no second container that can fail on its
  own, and Caddy already gates on `api` being healthy.
- **The API process serves static files.** One static mount on a process that already answers
  every read the page makes.
- **The reverse proxy is no longer an allowlist**, so the refusal of `/internal*` becomes an
  asserted property rather than a consequence of the default. `scripts/deployment_smoke.py`
  asserts it from outside the deployment, against the public hostname.
- **Rollback is a previous image tag**, exactly as it already was: the tag names a commit and the
  stack takes it as a parameter.
- **The departure is recorded, not hidden.** A later slice that wants a CDN in front of this is
  free to take one; nothing here forecloses it, and the bundle is an ordinary directory of
  hashed files.

## Alternatives rejected

| rejected | why |
|---|---|
| A dedicated frontend image and a seventh deployed service | A third ECR repository and an IAM edit, 250–350 bytes into a file with 44 free, and one more container that can fail independently of the API it exists to display. |
| Caddy serving a mounted `dist/` | The bundle still has to reach the host, which means either a new image — the option above — or S3 and new IAM. It buys nothing over serving it from the process that is already there. |
| S3 and CloudFront, as `ARCHITECTURE_PLAN.md` describes | New IAM, a new origin, a second deployment path and a CORS story for a cookie-authenticated API, to publish roughly 400 KB of static files that a running process can serve. P6.1 already declined this section's compute topology; this is the same trade at a smaller scale. |
