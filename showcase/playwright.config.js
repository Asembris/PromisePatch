// Playwright runs against the production build, served by `vite preview`
// under the Pages base `/PromisePatch/`, never against the dev server.
// `npm run check` builds first; `npm test` alone expects an existing dist/.
// Chromium only.

import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.SHOWCASE_TEST_PORT || 4317);
const ORIGIN = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: 'tests',
  globalSetup: './tests/global-setup.js',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  // Serial locally: on the development machine, concurrent browsers stall
  // loopback asset requests for 20–60 s (reproduced against a plain static
  // server too, so it is the machine, not the site). PW_WORKERS overrides.
  workers: Number(process.env.PW_WORKERS || (process.env.CI ? 2 : 1)),
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['list'], ['github']] : [['list']],
  use: {
    baseURL: `${ORIGIN}/PromisePatch/`,
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // SwiftShader gives the same WebGL path locally and on a GPU-less runner.
        launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
      },
    },
  ],
  webServer: {
    command: `npx vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `${ORIGIN}/PromisePatch/`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
