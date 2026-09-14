/**
 * The sign-in screen, and the way in that needs no sign-in at all.
 *
 * The credentials go to the backend and nowhere else: nothing is written to `localStorage` or
 * `sessionStorage`, no password is prefilled, and the session that results is an `HttpOnly`
 * cookie this code cannot read. The two demo usernames are named because they are seeded
 * fixture logins, not because a password is known here.
 *
 * **The first control is not a credential.** Somebody being shown the product reaches a real
 * case in one action: one button, no username, no password, and nothing published anywhere for
 * them to type. What they get back is a session the *server* chose — it names a principal the
 * domain admits to reads and to no write at all, so the refusals a judge meets are the domain's
 * rather than a screen's, and there is nothing on this page for them to hold.
 *
 * It is drawn only where the endpoint behind it is actually served. `useSignInOptions` asks
 * first, so this is a control that exists rather than one that hopes: a deployment with the
 * demo session turned off shows the credentials and nothing else.
 *
 * One action has to end on a *case*, not on a list, so the entry opens one: the case list's own
 * first row, which the backend orders newest first. That is navigation rather than a judgement —
 * the screen chooses nothing about the case, it goes to the one the backend put at the top — and
 * the address bar then carries it, so a reload lands back on the same durable case.
 *
 * Both halves of that live in `useDemoSession`, which is why this screen reads no list itself.
 * The mutation either hands over a case id or fails, so there is no path on which the button is
 * pressed and nothing at all happens: a failure is the mutation's failure and is drawn below,
 * with the retry every other read in this product already has behind it.
 *
 * Errors are the backend's message. A wrong password and an unknown user are one answer by
 * design, and the screen does not try to be more helpful than the endpoint was.
 */
import { useState, type FormEvent, type ReactNode } from 'react'
import { NO_CASE_TO_OPEN, useDemoSession, useLogin, useSignInOptions } from '../../api/queries'
import { ApiError } from '../../api/client'
import { PromisePatchLockup } from '../../components/Brand'

const FIELD =
  'w-full rounded-control border border-edge bg-panel px-3 py-2.5 text-sm text-ink placeholder:text-muted/60'

function messageFor(error: Error): string {
  if (error instanceof ApiError) return error.message
  // Our own sentence, and the one case where this screen has something truthful of its own to
  // say. Everything else is a transport failure whose message is jargon to the person reading
  // it, so it keeps the plain wording rather than leaking one.
  if (error.message === NO_CASE_TO_OPEN) return error.message
  return 'the request could not be completed'
}

export function LoginScreen({
  onEntered,
}: {
  /** Open a case. Owned by the shell, because the address bar is the shell's to move. */
  onEntered: (caseId: string) => void
}): ReactNode {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const signIn = useLogin()
  const options = useSignInOptions()
  const look = useDemoSession()

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    signIn.mutate({ username: username.trim(), password })
  }

  function onLookAround(): void {
    // The case id is the mutation's own result: the session and the list it needs are one
    // action, and a failure in either half is a failure of the press rather than silence.
    look.mutate(undefined, { onSuccess: onEntered })
  }

  return (
    <main className="mx-auto flex min-h-full max-w-sm flex-col justify-center px-6 py-16">
      <h1 className="text-ink">
        <PromisePatchLockup height={34} />
      </h1>

      {options.data?.demo_session === true ? (
        <div className="mt-6 space-y-2" data-testid="judge-entry">
          <button
            type="button"
            onClick={onLookAround}
            disabled={look.isPending}
            className="w-full rounded-control bg-brand px-3 py-2.5 text-sm font-semibold text-brand-ink transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {look.isPending ? 'Opening…' : 'Look around a real case'}
          </button>
          <p className="text-meta text-muted">
            No account needed. You will be able to read everything and change nothing.
          </p>
          {look.isError ? (
            <p
              role="alert"
              data-testid="judge-entry-error"
              className="rounded-control border border-owner/40 bg-owner/10 px-3 py-2 text-sm text-owner"
            >
              {messageFor(look.error)}
            </p>
          ) : null}
        </div>
      ) : null}

      <p className="mt-6 text-sm text-muted">
        Sign in to open the case you are working on. Your name is the one every report is
        recorded against.
      </p>

      <form className="mt-8 space-y-4" onSubmit={onSubmit}>
        <div className="space-y-1.5">
          <label className="block text-sm font-medium" htmlFor="username">
            Worker
          </label>
          <input
            id="username"
            name="username"
            type="text"
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            className={FIELD}
          />
          <p className="text-meta text-muted">Seeded demo logins: maya (baker), jo (owner).</p>
        </div>

        <div className="space-y-1.5">
          <label className="block text-sm font-medium" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className={FIELD}
          />
        </div>

        {signIn.isError ? (
          <p
            role="alert"
            className="rounded-control border border-owner/40 bg-owner/10 px-3 py-2 text-sm text-owner"
          >
            {messageFor(signIn.error)}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={signIn.isPending}
          className="w-full rounded-control bg-brand px-3 py-2.5 text-sm font-semibold text-brand-ink transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          {signIn.isPending ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
