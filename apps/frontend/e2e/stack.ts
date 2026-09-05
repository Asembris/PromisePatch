/**
 * What the browser tests need from the running stack, and where it comes from.
 *
 * These tests run against the real local stack -- a real PostgreSQL, the real migrations, the
 * real fixture, the real API -- so nothing here fakes a response. What it does provide is the
 * two things a browser cannot get for itself: the seeded credentials, and the operator action
 * that makes a durable domain event happen.
 *
 * Credentials are read from the generated `docker/env/migrate.env` rather than duplicated.
 * `bootstrap_local_env.py` generates them, so a copied literal here would be a password that
 * is wrong on every machine but the one it was written on.
 */
import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
const OPERATOR_ENV = resolve(REPOSITORY_ROOT, 'docker', 'env', 'migrate.env')

/** The operator reset, run the way an operator runs it: the privileged container, not the API. */
const DEFAULT_RESET_COMMAND = 'docker compose run --rm seed'

function readOperatorEnv(key: string): string {
  let contents: string
  try {
    contents = readFileSync(OPERATOR_ENV, 'utf8')
  } catch {
    throw new Error(
      `${OPERATOR_ENV} is missing. Run: uv run python scripts/bootstrap_local_env.py`,
    )
  }
  for (const line of contents.split('\n')) {
    const trimmed = line.trim()
    if (trimmed.startsWith('#')) continue
    const separator = trimmed.indexOf('=')
    if (separator === -1) continue
    if (trimmed.slice(0, separator).trim() === key) return trimmed.slice(separator + 1).trim()
  }
  throw new Error(`${key} is not set in ${OPERATOR_ENV}`)
}

export interface Credentials {
  username: string
  password: string
}

export function workerCredentials(): Credentials {
  return {
    username: process.env.E2E_WORKER_USERNAME ?? 'maya',
    password: process.env.E2E_WORKER_PASSWORD ?? readOperatorEnv('PP_DEMO_WORKER_PASSWORD'),
  }
}

/**
 * Reload the fixture, from outside the browser and outside the API.
 *
 * This is the only producer of a durable domain event the system has today, and it is
 * deliberately a privileged operator command: the runtime role cannot truncate, so there is no
 * HTTP endpoint that could do this. It also recreates the fixture workers, which revokes every
 * live session -- see the test that depends on exactly that.
 */
export function resetDemoState(): void {
  const command = process.env.E2E_RESET_COMMAND ?? DEFAULT_RESET_COMMAND
  execSync(command, { cwd: REPOSITORY_ROOT, stdio: 'inherit' })
}

/**
 * The External Order System, which is a different system on a different port.
 *
 * Deliberately not derived from the PromisePatch base URL. The whole claim these tests exist to
 * check is that the two are separate, and a helper that computed one from the other would be
 * quietly asserting the opposite.
 */
export function orderSystemURL(): string {
  return process.env.E2E_ORDER_SYSTEM_URL ?? 'http://localhost:58100'
}

/** PromisePatch's own API, read directly rather than through the browser's proxy. */
export function promisePatchAPI(): string {
  return process.env.E2E_API_URL ?? 'http://localhost:58000'
}

/**
 * Put the order system's book back, through its own admin route.
 *
 * Its reset, not PromisePatch's: this empties the order system's SQLite store and touches no
 * PromisePatch row at all. Nothing here needs a credential, because the order system is a local
 * stand-in on a private network and holds nothing worth protecting.
 */
export function resetOrderSystem(): void {
  const response = execSync(
    `node -e "fetch('${orderSystemURL()}/admin/reset', { method: 'POST' })` +
      `.then(r => process.exit(r.ok ? 0 : 1), () => process.exit(1))"`,
    { cwd: REPOSITORY_ROOT },
  )
  void response
}
