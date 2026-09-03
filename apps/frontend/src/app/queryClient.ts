/**
 * The query client, built by a function so a test gets a fresh cache per case.
 *
 * A module-level singleton would let one test's order book survive into the next, which is
 * exactly the class of bug the "protected data is cleared after sign-out" behaviour exists to
 * prevent — a shared cache would make that test pass for the wrong reason.
 *
 * The cache-level error handler is where a mid-session 401 is dealt with, once, for every
 * protected read. Handling it per query would mean each new read had to remember to, and the
 * one that forgot would leave a worker looking at a stale order book behind a revoked session.
 * `/api/auth/me` is unaffected: signed out is a normal answer there, returned as `null` rather
 * than raised, so it never routes through here.
 */
import { QueryCache, QueryClient } from '@tanstack/react-query'
import { ApiError } from '../api/client'
import { forgetSession } from '../api/queries'

export function createQueryClient(): QueryClient {
  // The handler has to reach the client it is installed on, and the client cannot exist before
  // the cache it is built with. One small holder resolves the cycle explicitly rather than
  // reaching into the cache's internals after the fact.
  const holder: { client: QueryClient | null } = { client: null }
  const queryCache = new QueryCache({
    onError: (error) => {
      if (holder.client !== null && error instanceof ApiError && error.isUnauthenticated) {
        forgetSession(holder.client)
      }
    },
  })

  const client = new QueryClient({
    queryCache,
    defaultOptions: {
      queries: {
        // The event stream is what makes this screen live. Polling on an interval would be a
        // second, weaker answer to the same question and would keep working just well enough
        // to hide a broken feed.
        refetchInterval: false,
        refetchOnWindowFocus: true,
        refetchOnReconnect: true,
      },
    },
  })
  holder.client = client
  return client
}
