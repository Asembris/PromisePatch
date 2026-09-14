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
import type { ReactNode } from 'react'
import { ApiError } from '../../api/client'
import { useMe, useReportTurn } from '../../api/queries'
import { Card, SectionLabel } from '../../components/surfaces'
import { TurnComposer } from '../voice/TurnComposer'
import { announceTurnRefused, announceTurnSent, speakTurnReply } from '../voice/turnVoice'

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

  // The backend's answer about this caller, never a role compared here. Absent while the
  // session is still being read, which is the honest state: nobody has been told yes yet.
  if (me.data?.worker.may_report !== true) return null

  async function onSend(text: string): Promise<void> {
    // A worker who spoke this one is holding a crate and not looking at a screen, so the turn
    // is acknowledged out loud the moment it leaves — about the turn, never about a case.
    announceTurnSent()
    let accepted
    try {
      accepted = await report.mutateAsync({ commandId: commandId(), text })
    } catch (failure) {
      announceTurnRefused()
      throw failure
    }
    // The backend's receipt for the statement it wrote down, byte for byte. It is spoken before
    // the case opens because it is this turn's answer, and the workspace that follows says
    // nothing aloud of its own accord.
    speakTurnReply(accepted.speech)
    // The id the backend derived, not one composed here. Navigation is the only thing that
    // happens on success: the case it opens is read from the server like any other.
    onOpened(accepted.case_id)
  }

  return (
    <section aria-label="Report what happened">
      <Card className="space-y-3 px-4 py-4 sm:px-5" data-testid="report-entry">
        <SectionLabel>say what happened</SectionLabel>
        <p className="text-sm text-muted">
          In your own words. It is written down exactly as you say it, and nothing changes until
          it has been worked out.
        </p>

        <TurnComposer
          idPrefix="report"
          label="what happened"
          placeholder="Today’s raspberry delivery didn’t arrive."
          sendLabel="Report this"
          pendingLabel="Writing it down…"
          pending={report.isPending}
          onSend={onSend}
        />

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
