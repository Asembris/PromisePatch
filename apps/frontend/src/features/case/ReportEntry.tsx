/**
 * The first thing anybody says to this product, said from the screen that has no case open yet.
 *
 * A worker standing in the bakery at six in the morning has no case id, no list row and nothing
 * to click into. What they have is a sentence — "today's raspberry delivery didn't arrive" — and
 * until this existed there was nowhere on the web surface to say it. It is one input and a send,
 * which is exactly what the worker's interaction contract fixes for the `NO_CASE` phase: no
 * form, no dropdown, no category picker. Choosing a category would be the screen doing the
 * interpreting, and the interpreting is the worker process's.
 *
 * Four rules, each one a thing this panel deliberately does not do:
 *
 * - **It is not offered to everybody, and the screen does not decide who.** `may_report` is the
 *   backend's answer, from the rule the write itself enforces. An observer is not shown a
 *   disabled control either: a capability this principal does not have is drawn not at all.
 * - **It creates nothing optimistically.** No row, no placeholder case, no "opening…" case in
 *   the list. The case id this navigates to is the one the backend returned, so a case that
 *   failed to open is a case that never appeared.
 * - **It sends the words byte for byte.** Not trimmed of its inner punctuation, not
 *   sentence-cased, not tidied. The stored sentence is a physical attestation and band 1 quotes
 *   it for the life of the case.
 * - **It names no actor.** Who is speaking is the session cookie's answer, decided by the server
 *   from the row it wrote. There is no field here for a worker, and the request model would
 *   reject one.
 */
import { useState, type FormEvent, type ReactNode } from 'react'
import { ApiError } from '../../api/client'
import { useMe, useReportTurn } from '../../api/queries'
import { Card, SectionLabel } from '../../components/surfaces'

/** A fresh command identity, so a retry of one turn is that turn arriving twice. */
function commandId(): string {
  return crypto.randomUUID()
}

function messageFor(error: Error): string {
  if (error instanceof ApiError) return error.message
  return 'that could not be sent, so nothing has been written down'
}

export function ReportEntry({ onOpened }: { onOpened: (caseId: string) => void }): ReactNode {
  const me = useMe()
  const report = useReportTurn()
  const [text, setText] = useState('')

  // The backend's answer about this caller, never a role compared here. Absent while the
  // session is still being read, which is the honest state: nobody has been told yes yet.
  if (me.data?.worker.may_report !== true) return null

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    if (text.trim().length === 0 || report.isPending) return
    report.mutate(
      { commandId: commandId(), text },
      {
        onSuccess: (accepted) => {
          setText('')
          // The id the backend derived, not one composed here. Navigation is the only thing
          // that happens on success: the case it opens is read from the server like any other.
          onOpened(accepted.case_id)
        },
      },
    )
  }

  return (
    <section aria-label="Report what happened">
      <Card className="space-y-3 px-4 py-4 sm:px-5" data-testid="report-entry">
        <SectionLabel>say what happened</SectionLabel>
        <p className="text-sm text-muted">
          In your own words. It is written down exactly as you say it, and nothing changes until
          it has been worked out.
        </p>

        <form className="space-y-3" onSubmit={onSubmit}>
          <label className="block text-label text-muted uppercase" htmlFor="report-text">
            what happened
          </label>
          <textarea
            id="report-text"
            name="report"
            rows={3}
            value={text}
            disabled={report.isPending}
            onChange={(event) => {
              setText(event.target.value)
            }}
            placeholder="Today’s raspberry delivery didn’t arrive."
            className="w-full rounded-control border border-edge bg-panel px-3 py-2.5 text-sm text-ink placeholder:text-muted/60 disabled:opacity-60"
            data-testid="report-text"
          />
          <button
            type="submit"
            disabled={report.isPending || text.trim().length === 0}
            data-testid="report-send"
            className="min-h-11 rounded-control bg-brand px-4 py-2.5 text-sm font-semibold text-brand-ink transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {report.isPending ? 'Writing it down…' : 'Report this'}
          </button>
        </form>

        {report.error ? (
          <p
            role="alert"
            data-testid="report-refusal"
            className="rounded-quiet border border-owner/40 bg-owner/10 px-3 py-2 text-sm text-owner"
          >
            {messageFor(report.error)}
          </p>
        ) : null}
      </Card>
    </section>
  )
}
