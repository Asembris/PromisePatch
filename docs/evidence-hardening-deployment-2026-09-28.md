# Evidence hardening: deployment reconciliation, 2026-09-28

Date: **2026-09-28**. Branch `evidence/hardening`, from `origin/main` at
`430a269b6f2a1919233ff7c478cc5dfaa7864f17`. This page is additive and edits no earlier record.

**Result in one sentence.** This session **could not observe the live deployment at all**. Its
network egress refused the host, and the AWS credentials present in the container were rejected.
What it could verify is the repository side of the story: nothing deployable has moved since the
frozen image, and the product gate is green on current `main`. **No `/healthz`, `/readyz`, TLS,
image, readiness or migration fact about the live host was verified today.**

Labels: **VERIFIED IN THIS SESSION**, **OBSERVED ON THE PUBLIC DEPLOYMENT** (nothing on this
page), **SOURCE CLAIM**, **NOT VERIFIED**.

## 1. Public reads: attempted and refused (NOT VERIFIED)

Non-destructive `GET`s only. TLS verification was left on, as it is everywhere.

```bash
H=https://184.194.40.87.sslip.io
for p in /healthz /readyz / ; do curl -sS -o body.txt -w 'http=%{http_code} ssl_verify=%{ssl_verify_result}\n' --max-time 20 "$H$p"; done
```

Each of the three answered `curl: (56) CONNECT tunnel failed, response 403`, `http=000`. The session's
outbound proxy refused the tunnel before any TCP connection to the host, so **no TLS handshake took
place and no byte of the application was read**. A server-side fetch through a second route was
refused by the same policy: `EGRESS_BLOCKED`, *"Access to 184.194.40.87.sslip.io is blocked by the
network egress proxy."* Following the proxy's own guidance, a policy denial was not retried.

`scripts/deployment_smoke.py` was not run, because it would reach the same refused host.

So these are **NOT VERIFIED today**: the host answering, the certificate verifying, `/healthz`'s
`image` and `boot_id`, `/readyz`'s database, migration head and fixture anchor, and the root bundle.

## 2. AWS control plane: credentials rejected (NOT VERIFIED)

The container's environment carries `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. Neither value
was printed. One read-only identity call was made:

```text
boto3.client("sts").get_caller_identity()
-> ClientError InvalidClientTokenId: The security token included in the request is invalid.
```

No other AWS API was called. No stack, parameter, instance, volume, RDS, log group or ECR read
happened. No credential was requested, created or substituted, and no IAM change was attempted.
Bedrock was therefore unreachable too.

## 3. What the repository does verify (VERIFIED IN THIS SESSION)

### 3.1 No deployable path has moved since the frozen image

Git tree and blob ids, from `git rev-parse <sha>:<path>`, after `git fetch --unshallow origin main`:

| path | `4529a802e34e` (deployed image) | `56c3023` (release SHA) | `430a269` (`main` today) |
|---|---|---|---|
| `apps/backend/src` | `d9cfe5103751` | same | same |
| `apps/backend/alembic` | `4ab26dc9cce0` | same | same |
| `apps/backend/alembic.ini` | `60fcf350bb29` | same | same |
| `apps/backend/pyproject.toml` | `82643ac4494e` | same | same |
| `apps/frontend` | `68368bf7d8a4` | same | same |
| `apps/order-simulator` | `35f61166f77b` | same | same |
| `packages` | `b9191b88363c` | same | same |
| `docker` | `100df96036b8` | same | same |
| `.dockerignore` | `6992bd1c91d0` | same | same |
| `deploy` | `2bbb1357a5a4` | same | same |
| `uv.lock` | `ed0dcf1e4910` | same | same |

These are the ids [g8-closeout.md](g8-closeout.md) §3 published. The 37 commits `56c3023..430a269`
touch `showcase/` (64 files), `docs/` (5), `README.md`, `CLAUDE.md` and `.gitignore` only. The
closeout's freeze check,
`git diff --name-only 56c302366b3ddc0d824c1588a4a9ddbd193ed891 HEAD -- apps/backend/src apps/backend/alembic apps/backend/alembic.ini apps/backend/pyproject.toml apps/frontend apps/order-simulator packages docker .dockerignore deploy uv.lock`,
prints nothing. **The feature freeze holds on `main`.**

### 3.2 The product gate on current `main`

Read through the GitHub API:

| workflow | run | `head_sha` | conclusion |
|---|---|---|---|
| `pr` | `36431878406`, run number 173, `push` to `main`, 2026-09-28T13:53:36Z → 14:13:39Z | `430a269b…7f17` | **`success`, 13 of 13 jobs**: whole-stack browser, semantic boundary, mcp protocol, frontend, pytest + coverage, ruff, gitleaks, semantic evaluation, order contract + order system, import-linter, backend + postgres, hypothesis (ci profile), mypy |
| `effect sets (expected red until 16/16)` | `36431878482` | `430a269…` | `failure`, the expected red. It judges v1, and S12 alone fails, on `ord-e/task_hold` at three checkpoints: `1 failed, 15 passed` |

## 4. The last recorded public observation (SOURCE CLAIM)

The most recent committed outside reading of the host is [g8-closeout.md](g8-closeout.md) §3,
read 2026-09-27:

- `/healthz`: `image: 4529a802e34e`, `boot_id 3e90146d-1484-40e9-8ab8-02cda046a664`.
- `/readyz`: ready. Database reachable as `promisepatch_app`, migrations at head
  `0009_human_plan_approval`, fixture `hollow-oak` at R5's anchor `2026-09-24T20:54:53.431361Z`.
- AWS control plane: stack `UPDATE_COMPLETE` with no event after 2026-09-24T16:00:45Z, and
  `ImageTag` `4529a802e34e`.

This session **did not re-observe** any of it. It is what the repository says was true a day earlier.

## 5. Reconciliation

| identity | value | status today |
|---|---|---|
| frozen repository release SHA | `56c302366b3ddc0d824c1588a4a9ddbd193ed891` | VERIFIED: an ancestor of `main`, freeze check empty |
| frozen deployed product / image SHA | `4529a802e34eff02f28fa25e12d382c50bf7cab1` | VERIFIED: product-path tree-identical to `56c3023` and `430a269` |
| image the live host serves | `4529a802e34e` per the 2026-09-27 reading | **NOT VERIFIED today**, SOURCE CLAIM only |
| live readiness, migration head, TLS | per the 2026-09-27 reading | **NOT VERIFIED today** |

So today's evidence supports one statement: *what `main` would build is what the frozen image was
built from.* It does **not** support: *the deployment is up and serving `4529a802e34e` today.*

## 6. How to close the gap without mutating anything

From a network that can reach the host, these reads are enough, and none of them writes:

```bash
curl -sS https://184.194.40.87.sslip.io/healthz
curl -sS https://184.194.40.87.sslip.io/readyz
uv run python scripts/deployment_smoke.py --base-url https://184.194.40.87.sslip.io
```

With the project's read-only role, [g8-closeout.md](g8-closeout.md) §3's Describe, Get and List
reads can be repeated as they are. `/healthz` should still name `4529a802e34e`, and a changed
`boot_id` would mean the `api` restarted. [CLAUDE.md](../CLAUDE.md) explains why smoke from the
owner's machine reads `9/12`.
