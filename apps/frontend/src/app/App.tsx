/**
 * The shell: bootstrap the session, then show one screen or the other.
 *
 * There are exactly three states, and the middle one is the reason this is a component rather
 * than a ternary. Until `/api/auth/me` has answered, the app does not know whether anyone is
 * signed in, and rendering the login form during that gap would flash a sign-in screen at a
 * worker who is already signed in on every reload.
 *
 * The feed is opened only when there is a session, and closed when there is not. That is not a
 * cosmetic detail: the stream is a session endpoint, so keeping one open across a sign-out
 * would be retrying an authenticated read on a session the server has revoked.
 *
 * Which case is open is read from the address bar rather than held here. That is the reload
 * guarantee stated as code: there is no in-memory selection to lose, so a refresh mounts the
 * app already pointing at the same case and renders whatever the durable case then says.
 */
import type { ReactNode } from 'react'
import { useMe } from '../api/queries'
import { useEventStream } from '../api/useEventStream'
import { LoginScreen } from '../features/auth/LoginScreen'
import { CaseWorkspace } from '../features/case/CaseWorkspace'
import { LiveOperations } from '../features/live-ops/LiveOperations'
import { Header } from './Header'
import { useCaseRoute } from './useCaseRoute'

export function App(): ReactNode {
  const me = useMe()
  const worker = me.data?.worker ?? null
  const stream = useEventStream(worker !== null)
  const route = useCaseRoute()

  if (me.isPending) {
    return (
      <main className="flex min-h-full items-center justify-center px-6">
        <p className="text-sm text-muted" role="status">
          Checking your session…
        </p>
      </main>
    )
  }

  if (me.isError) {
    return (
      <main className="mx-auto flex min-h-full max-w-sm flex-col justify-center gap-3 px-6 text-center">
        <p className="text-sm text-muted" role="alert">
          The API could not be reached. Check that the backend is running, then reload.
        </p>
      </main>
    )
  }

  if (worker === null) return <LoginScreen />

  return (
    <div className="min-h-full">
      <Header worker={worker} stream={stream} />
      {route.caseId === null ? (
        <LiveOperations stream={stream} onOpenCase={route.open} />
      ) : (
        <CaseWorkspace
          caseId={route.caseId}
          onClose={() => {
            route.open(null)
          }}
        />
      )}
    </div>
  )
}
