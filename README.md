# PromisePatch

When a delivery does not arrive, the expensive problem is not the inventory — it is the
customer promises somebody already made. PromisePatch lets a frontline bakery worker report
one physical-world exception by voice, then identifies every accepted customer promise that
exception threatens, coordinates bounded recovery, obtains customer approval through the
customer's own channel where that order's recorded constraints require it, resumes
asynchronously, revalidates against the current state, and reconciles the affected systems —
while leaving every unaffected promise untouched.

## Status

An active hackathon build. What exists today is the deterministic engine
(`packages/promise-graph`), the backend with its audited PostgreSQL write boundary, and the
Live Operations screen. There is no case engine, no order-system integration, no LLM and no
deployment yet.

## The deterministic engine

`promise_graph` is a separate, pure package on purpose. It owns reachability, temporal
availability, allocation, impact classification, recovery-option validation, snapshot
fingerprinting and the revalidation checklist. It performs no I/O, reads no environment, and
never calls the wall clock — time is passed in explicitly — so every decision that could
affect a customer is testable with zero cloud access.

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Docker with Compose v2, for the local stack
- Node.js 24, for the frontend

## Run the local stack

The stack is a disposable PostgreSQL 16 in a Docker volume, the repository's own migrations,
the Hollow Oak fixture, the API and the frontend. It needs no hosted database and no cloud
account.

```bash
uv run python scripts/bootstrap_local_env.py
```

That generates `docker/env/*.env` with fresh credentials. The files are never committed, and
there are no default passwords: read the seeded demo logins out of `docker/env/migrate.env`.

```bash
docker compose up --detach --wait
```

`--wait` returns only once PostgreSQL is healthy, the migrations have exited zero, the fixture
has loaded, `/readyz` reports ready and the frontend is serving. Then open
<http://localhost:55173> and sign in as `maya` with `PP_DEMO_WORKER_PASSWORD`.

```bash
docker compose run --rm seed        # reload the fixture
docker compose down                 # stop, keeping the database
docker compose down --volumes       # stop and discard the database
```

| Service | On the host | Inside the network |
|---|---|---|
| frontend | <http://localhost:55173> | `frontend:5173` |
| api | <http://localhost:58000> | `api:8000` |
| postgres | `127.0.0.1:55432` | `postgres:5432` |

The host ports are deliberately not 5173, 8000 and 5432: those are usually already taken on a
machine that develops this project, and a stack that quietly attached to something else would
be a confusing way to find out.

Two properties are worth knowing before you use it:

- **The API holds no administrative credential.** It connects as `promisepatch_app`, which
  owns nothing, migrates nothing and cannot truncate a table. Migrations and
  `pp reset-demo-state` run in separate containers with the administrative connection. That is
  why there is no HTTP reset endpoint.
- **`pp reset-demo-state` recreates the fixture workers, so it signs everyone out.** It is an
  operator command that replaces every domain row PromisePatch owns, and the sessions go with
  them. A browser watching the live feed will see the resulting domain event, refetch, be told
  its session is gone, and return to the sign-in screen. That is current, intended behaviour.

Behind an antivirus or corporate proxy that terminates TLS, put that root certificate in
`docker/env/extra-ca.crt` before building; the file is created empty and is otherwise ignored.

## Choosing a database for the repository tooling

`.env` at the repository root points Alembic, the CLI and the integration suite at whichever
database you configured — typically a hosted developer project. `docker/env/host.env` points
them at the disposable local one instead, and `scripts/with_local_env.py` runs a single command
with it, so switching to the local stack never means editing `.env`:

```bash
uv run python scripts/with_local_env.py -- uv run pytest apps/backend
```

## Tests

The engine suite needs nothing at all:

```bash
uv run pytest packages/promise-graph
```

The backend suite needs a database. With the local stack running:

```bash
uv run python scripts/with_local_env.py -- uv run pytest apps/backend
```

The frontend gates:

```bash
cd apps/frontend && npm ci && npm run typecheck && npm run lint && npm test && npm run build
```

The browser suite runs against the local stack, not against mocks. It reloads the fixture, so
expect the stack's demo data to be replaced:

```bash
cd apps/frontend && npx playwright install chromium && npm run e2e
```

## License

Apache-2.0. See [LICENSE](LICENSE).

---

The full product is under active hackathon development; this repository grows one phase at a
time.
