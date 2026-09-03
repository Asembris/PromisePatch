/**
 * Query keys, the reads behind them, and how a signed-out answer is handled.
 *
 * Server state is the state: there is no client store, and nothing here derives a value the
 * backend already returned. The three keys are flat because the three reads are flat — the
 * order book and the resource panel are whole-screen reads, and inventing a finer key would
 * only invite a partial invalidation the backend does not support.
 *
 * Staleness is generous on purpose. The feed is what makes this screen live; a short stale
 * time would be polling wearing a disguise, and the brief is explicit that polling is not a
 * substitute for the stream. `refetchOnWindowFocus` stays on because returning to a tab is a
 * cheap, human-initiated moment to be sure.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query'
import { ApiError, fetchMe, fetchPromises, fetchResources, login, logout } from './client'
import type { PromisesResponse, ResourcesResponse, WorkerResponse } from './types'

export const meKey = ['me'] as const
export const promisesKey = ['promises'] as const
export const resourcesKey = ['resources'] as const

/** Long enough that the stream is what refreshes the screen, not a timer. */
const OPERATIONAL_STALE_TIME = 60_000

/**
 * Do not retry a request the server answered.
 *
 * A 401 is a decision, not a blip: retrying it delays the return to the login screen and
 * spends three requests confirming what the first one said. Anything below 500 is the same
 * argument.
 */
function retryTransportFailures(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.status < 500) return false
  return failureCount < 2
}

export function useMe(): UseQueryResult<WorkerResponse | null, Error> {
  return useQuery({
    queryKey: meKey,
    queryFn: ({ signal }) => fetchMe(signal),
    retry: retryTransportFailures,
    staleTime: OPERATIONAL_STALE_TIME,
  })
}

/** `enabled` is the caller's answer to "is anyone signed in": a read is not attempted otherwise. */
export function usePromises(enabled: boolean): UseQueryResult<PromisesResponse, Error> {
  return useQuery({
    queryKey: promisesKey,
    queryFn: ({ signal }) => fetchPromises(signal),
    enabled,
    retry: retryTransportFailures,
    staleTime: OPERATIONAL_STALE_TIME,
  })
}

export function useResources(enabled: boolean): UseQueryResult<ResourcesResponse, Error> {
  return useQuery({
    queryKey: resourcesKey,
    queryFn: ({ signal }) => fetchResources(signal),
    enabled,
    retry: retryTransportFailures,
    staleTime: OPERATIONAL_STALE_TIME,
  })
}

export interface Credentials {
  username: string
  password: string
}

export function useLogin(): UseMutationResult<WorkerResponse, Error, Credentials> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ username, password }: Credentials) => login(username, password),
    onSuccess: (worker) => {
      // The login response is the same shape `me` returns, so it seeds the cache directly
      // rather than causing a second round trip to ask who just signed in.
      client.setQueryData(meKey, worker)
    },
  })
}

export function useLogout(): UseMutationResult<void, Error, void> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: logout,
    // `onSettled`, not `onSuccess`: if the call failed the browser is in an unknown state, and
    // holding on to the order book of a session that may already be revoked is the worse of
    // the two mistakes.
    onSettled: () => {
      forgetSession(client)
    },
  })
}

/**
 * Drop every protected read and record that nobody is signed in.
 *
 * `removeQueries` rather than `invalidateQueries`: invalidation marks data stale but leaves it
 * in the cache, where the next mount would render one frame of the previous worker's order
 * book before the refetch replaced it. Removal means there is nothing to render.
 */
export function forgetSession(client: QueryClient): void {
  client.removeQueries({ queryKey: promisesKey })
  client.removeQueries({ queryKey: resourcesKey })
  client.setQueryData(meKey, null)
}

/** Refetch the authoritative reads. The one thing a domain event is allowed to cause. */
export async function refreshOperationalState(client: QueryClient): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: promisesKey }),
    client.invalidateQueries({ queryKey: resourcesKey }),
  ])
}
