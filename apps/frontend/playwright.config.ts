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
  timeout: 90_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:55173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
