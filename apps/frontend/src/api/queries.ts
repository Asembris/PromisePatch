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
 *
 * There is exactly one timer here and it only runs on a read that is already failing: see
 * `recoverFromFailure`. A succeeding read is never polled, so the rule above is intact.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query'
import {
  ApiError,
  clarifyTurn,
  confirmTurn,
  fetchCase,
  fetchCases,
  fetchMe,
  fetchPromises,
  fetchResources,
  fetchSignInOptions,
  login,
  logout,
  openDemoSession,
  reportTurn,
  withdrawTurn,
} from './client'
import { responseReceived, turnSent, type TurnVerb } from '../instrumentation/turnTiming'
import type {
  CaseListResponse,
  CaseWorkspaceResponse,
  PromisesResponse,
  ResourcesResponse,
  SignInOptions,
  TurnAccepted,
  WithdrawalAccepted,
  WorkerResponse,
} from './types'

export const meKey = ['me'] as const
export const promisesKey = ['promises'] as const
export const resourcesKey = ['resources'] as const
export const casesKey = ['cases'] as const
export const signInOptionsKey = ['sign-in-options'] as const

/** One key per case, so a feed frame refreshes the case being read and not every case ever read. */
export function caseKey(caseId: string): readonly [string, string] {
  return ['case', caseId] as const
}

/** Long enough that the stream is what refreshes the screen, not a timer. */
const OPERATIONAL_STALE_TIME = 60_000

/** How often a read that has already failed tries again. Short, because it has nothing to show. */
const FAILED_READ_RECOVERY_INTERVAL = 2_000

/**
 * Try again, but only while a read is failing.
 *
 * The screen is refreshed by the feed, not by a timer, and this does not change that: a read
 * that is succeeding is never polled, so the "polling is not a substitute for the stream" rule
 * still holds for every healthy path.
 *
 * What it fixes is the unhealthy one. `retryTransportFailures` gives up after three attempts,
 * which is correct, and until now nothing tried again afterwards -- the only things that could
 * were a feed frame and a window focus. A browser that is not being looked at and whose feed is
 * also unhappy therefore sat on an empty screen indefinitely, with the panel heading rendered
 * above it, and one unlucky first read was enough to cause it. That is precisely the shape the
 * roadmap's "fragile demo" risk describes, and it is worse on a screen whose whole job is to
 * say what is actually true right now.
 *
 * A signed-out read cannot be caught in this loop: the cache-level handler forgets the session
 * on the first `401` and the protected queries are removed, so there is nothing left to poll.
 */
function recoverFromFailure(query: { state: { status: string } }): number | false {
  return query.state.status === 'error' ? FAILED_READ_RECOVERY_INTERVAL : false
}

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
    refetchInterval: recoverFromFailure,
  })
}

export function useResources(enabled: boolean): UseQueryResult<ResourcesResponse, Error> {
  return useQuery({
    queryKey: resourcesKey,
    queryFn: ({ signal }) => fetchResources(signal),
    enabled,
    retry: retryTransportFailures,
    staleTime: OPERATIONAL_STALE_TIME,
    refetchInterval: recoverFromFailure,
  })
}

export function useCases(enabled: boolean): UseQueryResult<CaseListResponse, Error> {
  return useQuery({
    queryKey: casesKey,
    queryFn: ({ signal }) => fetchCases(signal),
    enabled,
    retry: retryTransportFailures,
    staleTime: OPERATIONAL_STALE_TIME,
    refetchInterval: recoverFromFailure,
  })
}

/**
 * One case, read by id.
 *
 * `caseId` comes from the URL, so this is also the reload path: mounting the app at a case
 * address issues exactly this read and renders whatever the durable case says. Nothing about
 * the workspace survives in the browser between two visits, which is why the second one cannot
 * disagree with the first.
 */
export function useCase(caseId: string | null): UseQueryResult<CaseWorkspaceResponse, Error> {
  return useQuery({
    queryKey: caseKey(caseId ?? ''),
    queryFn: ({ signal }) => fetchCase(caseId as string, signal),
    enabled: caseId !== null,
    retry: retryTransportFailures,
    staleTime: OPERATIONAL_STALE_TIME,
    refetchInterval: recoverFromFailure,
  })
}

/**
 * What ways in exist, read before the sign-in screen draws them.
 *
 * Unauthenticated and cached for the session: it is one boolean about this deployment's own
 * configuration, it cannot change between two renders of a page, and a screen that re-read it
 * would be polling a constant.
 */
export function useSignInOptions(): UseQueryResult<SignInOptions, Error> {
  return useQuery({
    queryKey: signInOptionsKey,
    queryFn: ({ signal }) => fetchSignInOptions(signal),
    retry: retryTransportFailures,
    staleTime: Infinity,
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

/**
 * What the judge entry says when the deployment has no case to open.
 *
 * A real answer rather than a dead press: the button cannot honour its promise, and the reason
 * is that nothing has been reported, which is not a fault.
 */
export const NO_CASE_TO_OPEN =
  'there is no case to look at yet. Nothing has gone wrong; nothing has been reported here.'

/**
 * One action, and somebody is looking at a real case.
 *
 * Nothing is sent and nothing comes back but the principal the server chose. The response is the
 * same shape `me` returns, so it seeds the cache directly rather than causing a second round trip
 * to ask who is now signed in.
 *
 * **Both halves of the action are in the mutation, and that is the point.** Opening the session
 * is not the thing somebody asked for -- arriving at a case is -- so the case list is read here,
 * through `fetchQuery` with the same `retry` and `staleTime` every other read in this file uses.
 * Reading it in the screen instead left the one read that starts the whole product as the only
 * read with no retry behind it: a cold backend that answered the second request and not the
 * first would strand a judge on the sign-in screen with the button enabled, no error and nothing
 * happening, which is exactly the silent failure `recoverFromFailure` above exists to prevent.
 *
 * It also throws rather than resolving to nothing when there is no case to open. A deployment
 * with an empty list cannot honour this button, and saying so is the only honest answer -- the
 * alternative is a press that visibly does nothing, which reads as a broken product rather than
 * as an empty one.
 */
export function useDemoSession(): UseMutationResult<string, Error, void> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const worker = await openDemoSession()
      // The list is read before the principal is seeded, and the order is the whole behaviour.
      // Seeding `me` is what moves the shell off this screen, so doing it first would carry a
      // judge away from the only place the failure below can be drawn -- and strand them on a
      // signed-in shell with no case and no explanation. The session cookie is already set by
      // the call above, so this read is authenticated either way.
      //
      // Seeded under the list's own key, so the workspace this is about to open does not
      // immediately ask for the same rows a second time.
      const list = await client.fetchQuery({
        queryKey: casesKey,
        queryFn: ({ signal }) => fetchCases(signal),
        retry: retryTransportFailures,
        staleTime: OPERATIONAL_STALE_TIME,
      })
      const newest = list.cases[0]
      if (newest === undefined) throw new Error(NO_CASE_TO_OPEN)
      client.setQueryData(meKey, worker)
      return newest.case_id
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
  client.removeQueries({ queryKey: casesKey })
  client.removeQueries({ queryKey: ['case'] })
  client.setQueryData(meKey, null)
}

/** Refetch the authoritative reads. The one thing a domain event is allowed to cause. */
export async function refreshOperationalState(client: QueryClient): Promise<void> {
  await Promise.all([
    client.invalidateQueries({ queryKey: promisesKey }),
    client.invalidateQueries({ queryKey: resourcesKey }),
    client.invalidateQueries({ queryKey: casesKey }),
    // Every open case, by prefix. A reconnecting browser is exactly the case that must not be
    // left showing a plan the case has already moved past, and the case being read is the one
    // thing on the screen a stale frame would misrepresent as current.
    client.invalidateQueries({ queryKey: ['case'] }),
  ])
}

// ------------------------------------------------------------------- saying something to a case

/**
 * The three turns a person can take: one that opens a case, and two that a case can be given.
 *
 * All three follow the same rule and it is the important one: **nothing changes on screen until
 * the backend says it did.** There is no optimistic update, no pre-applied state and no local
 * copy of the case — the mutation settles, the case query is invalidated, and the next render draws
 * whatever the authoritative read then returns. A panel that moved a promise forward while the
 * request was in flight would be showing an outcome nobody had committed.
 *
 * `onSettled` rather than `onSuccess`, for the same reason `useLogout` uses it: a refusal is also
 * information about the case. A stale `plan_id` in particular means the case moved, and the
 * honest response to that is to re-read it and show the plan that is really on offer.
 */
export interface ReportTurnInput {
  commandId: string
  text: string
}

/**
 * One turn, with the two transport instants written down around it.
 *
 * Here rather than at the four call sites because this is the one place every turn actually
 * leaves the browser: a verb instrumented at its button would be an anchor somebody has to
 * remember to add, and the first one forgotten would be discovered as a hole in a measurement
 * that had already been published.
 *
 * The send is stamped *before* the request is issued and the response *whichever way it went* —
 * a refusal is a response and is timed like one. It records and it does not interpret: no
 * duration is computed here and no claim about latency exists anywhere in this build.
 */
async function timed<T>(verb: TurnVerb, send: () => Promise<T>): Promise<T> {
  turnSent(verb)
  try {
    const answer = await send()
    responseReceived('accepted')
    return answer
  } catch (failure) {
    responseReceived('refused')
    throw failure
  }
}

/**
 * The first thing anybody says to this product: what happened, in their own words.
 *
 * It carries no case id because there is no case yet — the backend derives one from the command
 * and returns it, and the screen navigates to whatever it returned. Nothing is created here
 * optimistically: until this resolves there is no row, no case and nothing on screen claiming
 * one, because a case that turned out not to exist would be the screen having invented an
 * attestation.
 *
 * `casesKey` is invalidated on settle rather than on success, for the same reason the two turns
 * below do it: a refusal is also information about what is on record.
 */
export function useReportTurn(): UseMutationResult<TurnAccepted, Error, ReportTurnInput> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ commandId, text }: ReportTurnInput) =>
      timed('report', () => reportTurn({ command_id: commandId, text })),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: casesKey })
    },
  })
}

export interface ClarifyTurnInput {
  commandId: string
  caseId: string
  text: string
}

export function useClarifyTurn(): UseMutationResult<TurnAccepted, Error, ClarifyTurnInput> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ commandId, caseId, text }: ClarifyTurnInput) =>
      timed('clarify', () => clarifyTurn({ command_id: commandId, case_id: caseId, text })),
    onSettled: (_result, _error, variables) => {
      void client.invalidateQueries({ queryKey: caseKey(variables.caseId) })
      void client.invalidateQueries({ queryKey: casesKey })
    },
  })
}

export interface ConfirmTurnInput {
  commandId: string
  caseId: string
  /** The plan identity the case response presented, quoted back. The screen never composes one. */
  planId: string
}

export function useConfirmTurn(): UseMutationResult<TurnAccepted, Error, ConfirmTurnInput> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ commandId, caseId, planId }: ConfirmTurnInput) =>
      timed('confirm', () =>
        confirmTurn({ command_id: commandId, case_id: caseId, plan_id: planId }),
      ),
    onSettled: (_result, _error, variables) => {
      void client.invalidateQueries({ queryKey: caseKey(variables.caseId) })
      void client.invalidateQueries({ queryKey: casesKey })
    },
  })
}

export interface WithdrawTurnInput {
  commandId: string
  caseId: string
}

/**
 * Withdraw one case.
 *
 * No plan identity, because a withdrawal is not about a plan: it stops the case, and what that
 * means for each promise is decided by the domain from rows under the case lock. The case is
 * re-read either way, so what the screen shows afterwards is the durable case rather than a
 * guess at what the withdrawal produced.
 */
export function useWithdrawTurn(): UseMutationResult<
  WithdrawalAccepted,
  Error,
  WithdrawTurnInput
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ commandId, caseId }: WithdrawTurnInput) =>
      timed('withdraw', () => withdrawTurn({ command_id: commandId, case_id: caseId })),
    onSettled: (_result, _error, variables) => {
      void client.invalidateQueries({ queryKey: caseKey(variables.caseId) })
      void client.invalidateQueries({ queryKey: casesKey })
    },
  })
}
