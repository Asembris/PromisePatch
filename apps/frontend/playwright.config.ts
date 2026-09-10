/**
 * The browser gate.
 *
 * There is no `webServer` here on purpose: these tests run against the compose stack, which
 * is a real PostgreSQL with the real migrations applied and the real fixture loaded. A server
 * Playwright started for itself would be a different system from the one being proved.
 *
 * One worker, serial: the last test resets the fixture, which revokes every session in the
 * database. Two browsers sharing that would be two tests failing each other at random.
 */
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  // One retry in CI, none locally. A retried pass is still visible in the report, and the
  // alternative -- a flake failing the whole gate on a shared runner -- teaches people to
  // ignore it.
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  timeout: 180_000,
  // Long, and deliberately so. `docker compose up --wait` proves the containers are healthy —
  // PostgreSQL accepting connections, migrations at head, `/readyz` green — and it does not
  // prove the stack answers a whole-graph read promptly. On a two-core runner carrying six
  // containers, a browser and a Vite dev server that transforms modules on demand, it has been
  // observed taking tens of seconds to settle, and then serving the same read in 300ms for the
  // rest of the run.
  //
  // Nothing about what is asserted changes: the order book must still hold exactly six
  // promises, the resource panels must still be populated, and a shortfall must still arrive
  // negative. Only the patience changes, and the extra patience is spent solely when the stack
  // is failing to answer — a passing run is no slower, because these assertions resolve as soon
  // as the rows appear.
  //
  // This is a tolerance, not a diagnosis. The reason a cold CI stack is two orders of magnitude
  // slower than the same stack locally is not established, and the retry policy plus the read
  // recovery in `queries.ts` are what cover the failure rather than this number.
  expect: { timeout: 60_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:55173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
