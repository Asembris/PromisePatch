/**
 * Dev server, build, and test configuration.
 *
 * The proxy is the load-bearing part. The backend issues a `SameSite=Lax`, `HttpOnly` session
 * cookie and authenticates the event stream with it, so the browser has to regard the API as
 * the same origin as the page. Proxying `/api` and `/events` through Vite achieves that
 * exactly: there is no cross-origin request to grant credentials to, no preflight, and no CORS
 * allowlist involved in local development at all. It is also the topology the frozen
 * architecture describes for the dev stack.
 *
 * `VITE_API_BASE_URL` is left empty by default for that reason. Setting it points the client
 * at a different origin, which then genuinely needs `PP_CORS_ORIGINS` to name this one.
 */
import { defineConfig, loadEnv, type ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const DEFAULT_BACKEND = 'http://127.0.0.1:8000'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const target = env.VITE_DEV_API_PROXY_TARGET || DEFAULT_BACKEND

  const proxy: ProxyOptions = {
    target,
    changeOrigin: false,
    // `ws: false` and no buffering: `/events` is a long-lived text/event-stream response and
    // must be piped straight through rather than accumulated.
    ws: false,
    configure: (instance) => {
      instance.on('proxyRes', (upstream, _request, response) => {
        // End the browser's response when the backend's ends.
        //
        // The proxy does not propagate a lost upstream to the client on a response that is
        // still streaming. Restart the API and the browser is left holding an open
        // `text/event-stream` with nothing behind it: no end, no error, so the stream client's
        // reconnect never fires and the feed goes on reporting itself live while it is dead. A
        // direct connection to the API ends the instant the process does -- but the proxied
        // one is what every local browser actually uses.
        //
        // The `writableEnded` guard is what keeps this narrow. On an ordinary request the pipe
        // has already ended the client response by the time this fires, so there is nothing to
        // do; it acts only on a response the client is still reading, which is precisely the
        // case that would otherwise hang.
        upstream.on('close', () => {
          if (!response.writableEnded) response.destroy()
        })
      })
    },
  }

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: { '/api': proxy, '/events': proxy },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./tests/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
      restoreMocks: true,
    },
  }
})
