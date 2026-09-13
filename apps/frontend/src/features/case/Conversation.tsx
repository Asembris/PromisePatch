/**
 * The conversation panel, inside the case workspace rather than on a route of its own.
 *
 * This is not a chatbot. It is the one place a worker says something to the case they are
 * looking at, and it sits beside the case rather than replacing it: the bands stay on screen,
 * authoritative, and this panel is how they change.
 *
 * Four rules, and each one is a thing the panel deliberately does *not* do:
 *
 * - **It composes no sentence about a case.** Everything a person reads here is `speech` — the
 *   whole status as `promisepatch.domain.status_view` renders it, or the receipt the backend
 *   returned for the turn just accepted — printed verbatim. A panel that re-worded "planned" is
 *   one word away from "done".
 * - **It decides nothing about authority.** Which controls exist comes from `may_speak` and
 *   `permitted_verbs`, both backend fields. There is no role read here, no state compared, and
 *   no table of what a phase allows. The domain checks every call again regardless, so what
 *   these fields buy is that the screen never *offers* what would be refused.
 * - **Nothing appears until the backend has said it.** A turn joins the transcript only once the
 *   request has been accepted, together with the backend's own reply. While it is in flight the
 *   composer says so and the transcript is untouched — there is no optimistic turn, no
 *   pre-applied state and no local copy of the case.
 * - **A confirmation quotes a plan.** The `plan_id` sent is the one the case response presented,
 *   passed through unchanged. This panel cannot describe a plan, only name the one it was given,
 *   and a yes that quotes a plan the case has moved past is refused by the domain.
 *
 * A refused turn is shown as what it is, with the backend's own message, and the case is re-read
 * either way — a refusal is information about the case, and the most common one means the case
 * moved while somebody was reading it.
 */
import { useState, type FormEvent, type ReactNode } from 'react'
import { ApiError } from '../../api/client'
import { useClarifyTurn, useConfirmTurn } from '../../api/queries'
import type { CaseWorkspaceResponse, TurnAccepted } from '../../api/types'
import { Card, SectionLabel } from '../../components/surfaces'

/**
 * One accepted exchange: what a person said, and what the backend said back.
 *
 * Held in the component because a transcript is a record of an exchange rather than a claim
 * about the case — the case beside it is read from the server on every render. Nothing is added
 * here that the backend has not already accepted, so the transcript cannot show a turn that did
 * not happen.
 */
interface Exchange {
  id: string
  spoken: string
  speech: string
}

/** A fresh command identity, so a retry of one turn is that turn arriving twice. */
function commandId(): string {
  return crypto.randomUUID()
}

function messageFor(error: Error): string {
  if (error instanceof ApiError) return error.message
  return 'that could not be sent, so nothing has changed'
}

export function Conversation({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  const [exchanges, setExchanges] = useState<Exchange[]>([])
  const clarify = useClarifyTurn()
  const confirm = useConfirmTurn()

  // Straight from the backend. `may_speak` is the domain's answer about this caller; the verbs
  // are the conversation's own closed table, already narrowed by it. Neither is derived here.
  const mayAnswer = view.may_speak && view.permitted_verbs.includes('clarify')
  const mayConfirm =
    view.may_speak && view.permitted_verbs.includes('confirm') && view.plan_id !== null
  const pending = clarify.isPending || confirm.isPending
  const failure = clarify.error ?? confirm.error

  function record(spoken: string, accepted: TurnAccepted): void {
    setExchanges((previous) => [
      ...previous,
      { id: accepted.statement_id, spoken, speech: accepted.speech },
    ])
  }

  function onAnswer(text: string): void {
    clarify.mutate(
      { commandId: commandId(), caseId: view.case_id, text },
      { onSuccess: (accepted) => record(text, accepted) },
    )
  }

  function onConfirm(): void {
    if (view.plan_id === null) return
    confirm.mutate(
      { commandId: commandId(), caseId: view.case_id, planId: view.plan_id },
      { onSuccess: (accepted) => record('Yes, go ahead.', accepted) },
    )
  }

  return (
    <section aria-label="Talk to this case">
      <Card className="space-y-3 px-4 py-3.5 sm:px-5" data-testid="conversation-panel">
        <SectionLabel>talk to this case</SectionLabel>

        {/* The whole case, spoken, exactly as the backend renders it. Never trimmed, never
            summarised, and re-read from the authoritative case on every render — so this line
            is current rather than a memory of what was true when the panel opened. */}
        <p className="text-sm text-ink" data-testid="conversation-speech">
          {view.speech}
        </p>

        {exchanges.length === 0 ? null : (
          <ol className="space-y-2.5" data-testid="conversation-transcript">
            {exchanges.map((exchange) => (
              <li key={exchange.id} className="space-y-1">
                <p className="text-meta text-muted uppercase">you said</p>
                <blockquote className="text-sm font-medium text-ink">
                  “{exchange.spoken}”
                </blockquote>
                <p className="text-sm text-muted" data-testid="conversation-reply">
                  {exchange.speech}
                </p>
              </li>
            ))}
          </ol>
        )}

        {failure ? (
          <p
            role="alert"
            data-testid="conversation-refusal"
            className="rounded-quiet border border-owner/40 bg-owner/10 px-3 py-2 text-sm text-owner"
          >
            {messageFor(failure)}
          </p>
        ) : null}

        {view.may_speak ? null : (
          <p className="text-sm text-muted" data-testid="conversation-read-only">
            You are looking at this case. Changing it is the bakery’s to do.
          </p>
        )}

        {mayAnswer ? <Answer onSend={onAnswer} pending={pending} /> : null}
        {mayConfirm ? <Confirm onConfirm={onConfirm} pending={pending} /> : null}
      </Card>
    </section>
  )
}

/**
 * The one open question, answered in a person's own words.
 *
 * The text is sent byte for byte: it is stored as evidence and resolved by the worker process
 * against the options the question was asked with, so nothing here tidies, trims or interprets
 * it. The field is cleared only after the backend has accepted the turn.
 */
function Answer({
  onSend,
  pending,
}: {
  onSend: (text: string) => void
  pending: boolean
}): ReactNode {
  const [text, setText] = useState('')

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    if (!text.trim() || pending) return
    onSend(text)
    setText('')
  }

  return (
    <form className="space-y-2" onSubmit={onSubmit}>
      <label className="block text-meta text-muted uppercase" htmlFor="conversation-answer">
        answer in your own words
      </label>
      <textarea
        id="conversation-answer"
        name="answer"
        rows={2}
        value={text}
        disabled={pending}
        onChange={(event) => setText(event.target.value)}
        className="w-full rounded-control border border-edge bg-panel px-3 py-2 text-sm text-ink placeholder:text-muted/60 disabled:opacity-60"
      />
      <button
        type="submit"
        disabled={pending || text.trim().length === 0}
        className="rounded-control bg-brand px-3 py-2 text-sm font-semibold text-brand-ink transition-opacity hover:opacity-90 disabled:opacity-60"
      >
        {pending ? 'Sending…' : 'Send'}
      </button>
    </form>
  )
}

/**
 * A yes to the plan on the screen, and nothing else.
 *
 * The button says what it authorises and does not say what it completes: pressing it permits the
 * recoveries the bands above already describe, and the case reports what actually happened
 * afterwards. It is also not a customer's consent, which is a literal reply on that customer's
 * own channel and cannot be produced by anybody pressing a button in this building.
 */
function Confirm({
  onConfirm,
  pending,
}: {
  onConfirm: () => void
  pending: boolean
}): ReactNode {
  return (
    <div className="space-y-1.5">
      <button
        type="button"
        onClick={onConfirm}
        disabled={pending}
        data-testid="conversation-confirm"
        className="rounded-control bg-brand px-3 py-2 text-sm font-semibold text-brand-ink transition-opacity hover:opacity-90 disabled:opacity-60"
      >
        {pending ? 'Sending…' : 'Yes, go ahead'}
      </button>
      <p className="text-meta text-muted">
        This confirms the plan above. Nothing is carried out until it is.
      </p>
    </div>
  )
}
