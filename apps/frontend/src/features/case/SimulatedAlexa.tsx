/**
 * Simulated Alexa+ via MCP (ADR-0028): the same worker, the same case, over the real MCP path.
 *
 * Deliberately a panel of its own, beside the conversation panel and never merged with it. That
 * panel calls `/api/conversation/*` directly; this one sends reviewed words to the server, which
 * reads the case fresh over MCP, lets PromisePatch's orchestrator choose a verb with a model, and
 * calls the authenticated MCP 2025-11-25 Streamable HTTP endpoint. It is not Alexa+, an Alexa
 * skill or Amazon's agent, and it says so.
 *
 * Three things it does not do:
 *
 * - **It sends a case and the words, nothing else.** No plan, no tool, no actor. The server
 *   decides what the words may do, from the case's own state.
 * - **It never folds the worker's approval into speech.** A spoken yes over MCP can only spend an
 *   approval this worker recorded; the explicit "Approve this plan" control is how they record
 *   it, on their own session, and it carries nothing out.
 * - **It composes no sentence about a case.** The reply is the server's, printed verbatim.
 */
import { useState, type ReactNode } from 'react'
import { ApiError } from '../../api/client'
import { useApprovePlan, useSimulatedAlexaTurn } from '../../api/queries'
import type { CaseWorkspaceResponse } from '../../api/types'
import { Card, SectionLabel } from '../../components/surfaces'
import { TurnComposer } from '../voice/TurnComposer'
import { speakTurnReply } from '../voice/turnVoice'

export const SIMULATED_ALEXA_LABEL = 'Simulated Alexa+ via MCP'

interface Exchange {
  id: number
  said: string
  reply: string
  calls: string[]
}

function messageFor(error: Error): string {
  if (error instanceof ApiError) return error.message
  return 'that could not be sent, so nothing has changed'
}

export function SimulatedAlexa({ view }: { view: CaseWorkspaceResponse }): ReactNode {
  const [exchanges, setExchanges] = useState<Exchange[]>([])
  const turn = useSimulatedAlexaTurn()
  const approve = useApprovePlan()

  if (!view.may_speak) return null
  const mayApprove = view.permitted_verbs.includes('confirm') && view.plan_id !== null
  const failure = turn.error ?? approve.error
  const pending = turn.isPending || approve.isPending

  async function onSend(text: string): Promise<void> {
    const answered = await turn.mutateAsync({ caseId: view.case_id, text })
    setExchanges((previous) => [
      ...previous,
      { id: previous.length, said: text, reply: answered.reply, calls: answered.calls },
    ])
    speakTurnReply(answered.reply)
  }

  function onApprove(): void {
    const planId = view.plan_id
    if (planId === null) return
    approve.mutate({ caseId: view.case_id, planId })
  }

  return (
    <section aria-label={SIMULATED_ALEXA_LABEL}>
      <Card className="space-y-3 px-4 py-3.5 sm:px-5" data-testid="simulated-alexa-panel">
        <SectionLabel>{SIMULATED_ALEXA_LABEL}</SectionLabel>
        <p className="text-meta text-muted" data-testid="simulated-alexa-disclosure">
          Not Alexa+ and not an Alexa skill. Your browser&rsquo;s speech, PromisePatch&rsquo;s own
          orchestrator choosing a step with a model, and its authenticated MCP 2025-11-25
          Streamable HTTP endpoint. Separate from the panel above, which does not use MCP.
        </p>

        {exchanges.length === 0 ? null : (
          <ol className="space-y-2.5" data-testid="simulated-alexa-transcript">
            {exchanges.map((exchange) => (
              <li key={exchange.id} className="space-y-1">
                <blockquote className="text-sm font-medium text-ink">
                  &ldquo;{exchange.said}&rdquo;
                </blockquote>
                <p className="text-sm whitespace-pre-line text-muted">{exchange.reply}</p>
                <p className="text-meta text-muted" data-testid="simulated-alexa-calls">
                  MCP: status{exchange.calls.length ? `, ${exchange.calls.join(', ')}` : ''}
                </p>
              </li>
            ))}
          </ol>
        )}

        {failure ? (
          <p role="alert" data-testid="simulated-alexa-refusal" className="text-sm text-owner">
            {messageFor(failure)}
          </p>
        ) : null}

        <TurnComposer
          idPrefix="simulated-alexa"
          label="say it to the case over MCP"
          sendLabel="Say it over MCP"
          pendingLabel="Carrying it over MCP…"
          pending={pending}
          onSend={onSend}
        />

        {mayApprove ? (
          <div className="space-y-1.5">
            <button
              type="button"
              onClick={onApprove}
              disabled={pending}
              data-testid="simulated-alexa-approve"
              className="min-h-11 rounded-control border border-edge-strong bg-panel px-4 py-2.5 text-sm font-semibold text-ink disabled:opacity-60"
            >
              {approve.isPending ? 'Recording…' : 'Approve this plan'}
            </button>
            <p className="text-meta text-muted">
              Records your approval of the plan above and carries nothing out. A spoken yes over
              MCP can only use an approval you recorded here.
            </p>
            {approve.data ? (
              <p className="text-sm text-muted" data-testid="simulated-alexa-approved">
                {approve.data.speech}
              </p>
            ) : null}
          </div>
        ) : null}
      </Card>
    </section>
  )
}
