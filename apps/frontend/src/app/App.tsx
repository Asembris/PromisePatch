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
import { PromisePatchLockup } from '../components/Brand'
import { Header } from './Header'
import { useCaseRoute } from './useCaseRoute'

export function App(): ReactNode {
  const me = useMe()
  const worker = me.data?.worker ?? null
  const stream = useEventStream(worker !== null)
  const route = useCaseRoute()

  if (me.isPending) {
    return (
      <Boot role="status">
        <PromisePatchLockup height={30} />
        <p className="text-sm text-muted">Opening your session…</p>
      </Boot>
    )
  }

  if (me.isError) {
    return (
      <Boot role="alert">
        <PromisePatchLockup height={30} />
        <p className="text-sm text-muted">
          PromisePatch cannot be reached from this device right now. Nothing about your cases
          has changed; this screen simply cannot read them. Try again in a moment.
        </p>
      </Boot>
    )
  }

  // The shell owns the address bar, so the sign-in screen asks it to open a case rather
  // than moving the URL under a component that does not own it.
  if (worker === null) return <LoginScreen onEntered={route.open} />

  return (
    <div className="min-h-full">
      {/* First in the tab order, visible the moment it is focused, and pointing at the one
          landmark on the page. A judge or a worker arriving by keyboard should not have to walk
          the header to reach the case. */}
      <a
        href="#case-surface"
        className="sr-only rounded-control bg-brand px-4 py-2.5 text-sm font-semibold text-brand-ink focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-30"
      >
        Skip to the case
      </a>
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

/**
 * The two screens that exist before there is a session to show.
 *
 * Both carry the mark, because the alternative is a bare sentence on a dark page that reads as
 * a crash. Neither instructs anybody to run a command: a shell that told a baker to start a
 * backend would be the product speaking as its own build system.
 */
function Boot({ role, children }: { role: 'status' | 'alert'; children: ReactNode }): ReactNode {
  return (
    <main className="mx-auto flex min-h-full max-w-sm flex-col items-center justify-center gap-4 px-6 text-center">
      <div className="flex flex-col items-center gap-4 text-ink" role={role}>
        {children}
      </div>
    </main>
  )
}
