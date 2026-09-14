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
 *   returned for the turn just accepted — printed verbatim, and read aloud verbatim where a
 *   browser can. A panel that re-worded "planned" is one word away from "done".
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
 * - **A withdrawal is never drawn as an undo.** The control appears only where `permitted_verbs`
 *   says so, it sends a case and nothing else, and what it prints afterwards is the backend's own
 *   two lists — what was stood down, and what had already gone out and therefore stands. The
 *   second list is rendered whenever it is non-empty, because omitting it is how a stopped case
 *   comes to look like a reversed one.
 *
 * A refused turn is shown as what it is, with the backend's own message, and the case is re-read
 * either way — a refusal is information about the case, and the most common one means the case
 * moved while somebody was reading it.
 *
 * **The voice posture is drawn here, and it is about the turn rather than about the case.** Five
 * of the contract's nine voice states belong to capture and live in `TurnComposer`; the four
 * that remain — processing, clarifying, confirming, waiting — are postures of a case, and each
 * one is read off a backend field rather than worked out. The *sentence* under each of them is
 * always the backend's; what this panel chooses is only which of its own already-composed
 * strings to show a worker next.
 */
import { useState, type ReactNode } from 'react'
import { ApiError } from '../../api/client'
import { useClarifyTurn, useConfirmTurn, useWithdrawTurn } from '../../api/queries'
import type {
  CaseWorkspaceResponse,
  TurnAccepted,
  WithdrawalAccepted,
} from '../../api/types'
import { Card, SectionLabel } from '../../components/surfaces'
import { audioStarted } from '../../instrumentation/turnTiming'
import { TurnComposer } from '../voice/TurnComposer'
import { speakAloud, speechPlaybackAvailable, stopSpeaking } from '../voice/speech'
import { announceTurnRefused, announceTurnSent, speakTurnReply } from '../voice/turnVoice'
import { CASE_VOICE_LABEL, caseVoiceState, type CaseVoiceState } from './voiceState'

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
  const [stopped, setStopped] = useState<WithdrawalAccepted | null>(null)
  const clarify = useClarifyTurn()
  const confirm = useConfirmTurn()
  const withdraw = useWithdrawTurn()

  // Straight from the backend. `may_speak` is the domain's answer about this caller; the verbs
  // are the conversation's own closed table, already narrowed by it. Neither is derived here.
  const mayAnswer = view.may_speak && view.permitted_verbs.includes('clarify')
  const mayConfirm =
    view.may_speak && view.permitted_verbs.includes('confirm') && view.plan_id !== null
  // Nothing local decides this. The verb is in the list or it is not, and where it is not there
  // is no control at all — not a disabled one, because an advertised capability the case cannot
  // offer is worse than an absent one.
  const mayWithdraw = view.may_speak && view.permitted_verbs.includes('withdraw')
  const pending = clarify.isPending || confirm.isPending || withdraw.isPending
  const failure = clarify.error ?? confirm.error ?? withdraw.error
  const voiceState = caseVoiceState(view, { pending, refused: failure !== null })

  function record(spoken: string, accepted: TurnAccepted): void {
    setExchanges((previous) => [
      ...previous,
      { id: accepted.statement_id, spoken, speech: accepted.speech },
    ])
  }

  /**
   * What a turn sounds like, in the one place all three of them pass through.
   *
   * Three audible moments and not one more: the acknowledgement when the turn leaves, the
   * backend's own sentence when it comes back, and a statement that nothing happened when it was
   * refused. The middle one is `accepted.spoken` byte for byte — the backend's own short
   * rendering of the same answer (ADR-0014). This panel composes no sentence for a screen and
   * composes none for a loudspeaker either; it chooses which of two server-composed strings
   * goes to which, and can neither shorten nor lengthen either one.
   */
  function reply(accepted: { spoken: string }): void {
    speakTurnReply(accepted.spoken)
  }

  async function onAnswer(text: string): Promise<void> {
    announceTurnSent()
    try {
      const accepted = await clarify.mutateAsync({
        commandId: commandId(),
        caseId: view.case_id,
        text,
      })
      record(text, accepted)
      reply(accepted)
    } catch (failure) {
      announceTurnRefused()
      // Rethrown, because the composer keeps a worker's words on a refusal and only a rejection
      // tells it the turn did not happen.
      throw failure
    }
  }

  function onWithdraw(): void {
    announceTurnSent()
    withdraw.mutate(
      { commandId: commandId(), caseId: view.case_id },
      {
        onSuccess: (accepted) => {
          setStopped(accepted)
          record('Cancel that.', {
            case_id: accepted.case_id,
            statement_id: accepted.command_id,
            state: accepted.state,
            created: accepted.created,
            attested_by: accepted.withdrawn_by,
            speech: accepted.speech,
            spoken: accepted.spoken,
          })
          reply(accepted)
        },
        onError: announceTurnRefused,
      },
    )
  }

  function onConfirm(): void {
    if (view.plan_id === null) return
    announceTurnSent()
    confirm.mutate(
      { commandId: commandId(), caseId: view.case_id, planId: view.plan_id },
      {
        onSuccess: (accepted) => {
          record('Yes, go ahead.', accepted)
          reply(accepted)
        },
        onError: announceTurnRefused,
      },
    )
  }

  return (
    <section aria-label="Talk to this case">
      <Card
        className="space-y-3 px-4 py-3.5 sm:px-5"
        data-testid="conversation-panel"
        data-voice-state={voiceState}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <SectionLabel>talk to this case</SectionLabel>
          <VoiceStateChip state={voiceState} />
        </div>

        {/* The whole case, spoken, exactly as the backend renders it. Never trimmed, never
            summarised, and re-read from the authoritative case on every render — so this line
            is current rather than a memory of what was true when the panel opened. */}
        <p className="text-sm whitespace-pre-line text-ink" data-testid="conversation-speech">
          {view.speech}
        </p>

        <ReadAloud text={view.spoken} />

        {exchanges.length === 0 ? null : (
          <ol className="space-y-2.5" data-testid="conversation-transcript">
            {exchanges.map((exchange) => (
              <li key={exchange.id} className="space-y-1">
                <p className="text-meta text-muted uppercase">you said</p>
                <blockquote className="text-sm font-medium text-ink">
                  &ldquo;{exchange.spoken}&rdquo;
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
            You are looking at this case. Changing it is the bakery&rsquo;s to do.
          </p>
        )}

        {mayAnswer ? (
          <TurnComposer
            idPrefix="answer"
            label="answer in your own words"
            sendLabel="Send"
            pendingLabel="Sending…"
            pending={pending}
            onSend={onAnswer}
          />
        ) : null}
        {stopped === null ? null : <Stopped result={stopped} />}

        {mayConfirm ? <Confirm onConfirm={onConfirm} pending={pending} /> : null}
        {mayWithdraw ? (
          <Withdraw onWithdraw={onWithdraw} pending={pending} sending={withdraw.isPending} />
        ) : null}
      </Card>
    </section>
  )
}

function VoiceStateChip({ state }: { state: CaseVoiceState }): ReactNode {
  return (
    <p
      className="flex items-center gap-2 text-label text-muted uppercase"
      data-testid="conversation-voice-state"
      role="status"
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 rounded-full ${
          state === 'unavailable' ? 'bg-owner' : state === 'waiting' ? 'bg-muted' : 'bg-brand'
        } ${state === 'processing' ? 'motion-safe:animate-pulse' : ''}`}
      />
      {CASE_VOICE_LABEL[state]}
    </p>
  )
}

/**
 * The backend's sentence, out loud, unchanged, whenever a worker asks for it again.
 *
 * Every turn now speaks its own answer as it resolves, so this control is no longer how a
 * worker hears the case — it is stop and replay: interrupt what is being said, or hear the whole
 * standing status again without taking a turn to get it. Both are what the contract means by
 * interruption and retry being available throughout.
 *
 * Offered only where the browser has a voice of its own, because there is nothing to fall back
 * to and a dead control is worse than an absent one. It reads `spoken` — the backend's own
 * short rendering of the same case — and can read nothing else: there is no field here for a
 * summary this screen made, and a spoken paraphrase of a plan is exactly the failure the whole
 * rendering rule exists to prevent.
 */
function ReadAloud({ text }: { text: string }): ReactNode {
  const [available] = useState(() => speechPlaybackAvailable())
  const [speaking, setSpeaking] = useState(false)
  if (!available) return null

  return (
    <button
      type="button"
      data-testid="conversation-read-aloud"
      aria-pressed={speaking}
      onClick={() => {
        if (speaking) {
          stopSpeaking()
          setSpeaking(false)
          return
        }
        speakAloud(text, {
          onStart: () => {
            audioStarted('replay')
          },
          // So the control tells the truth about itself once the sentence has finished, rather
          // than offering to stop something nobody is saying any more.
          onDone: () => {
            setSpeaking(false)
          },
        })
        setSpeaking(true)
      }}
      className="min-h-11 rounded-control border border-edge-strong bg-panel px-3 py-2 text-meta font-medium text-muted transition-colors hover:text-ink"
    >
      {speaking ? 'Stop reading' : 'Read this aloud'}
    </button>
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
        className="min-h-11 rounded-control bg-brand px-4 py-2.5 text-sm font-semibold text-brand-ink transition-opacity hover:opacity-90 disabled:opacity-60"
      >
        {pending ? 'Sending…' : 'Yes, go ahead'}
      </button>
      <p className="text-meta text-muted">
        This confirms the plan above. Nothing is carried out until it is.
      </p>
    </div>
  )
}

/**
 * What a withdrawal stopped, and what it could not.
 *
 * Both lists are sentences the backend composed, printed verbatim. `applied` is rendered
 * whenever it is non-empty and is never folded into the other list or summarised into a count:
 * every entry in it is something a customer or the order system already has, and a screen that
 * showed only what was stopped would be describing a rollback nobody performed.
 *
 * It also draws no physical claim, because a withdrawal makes none. The ingredient that did not
 * arrive still did not arrive.
 */
function Stopped({ result }: { result: WithdrawalAccepted }): ReactNode {
  return (
    <div className="space-y-2" data-testid="withdrawal-result">
      {result.reversed_writes.length === 0 ? null : (
        <ul className="space-y-1" data-testid="withdrawal-reversed">
          {result.reversed_writes.map((line) => (
            <li key={line} className="text-sm text-muted">
              {line}
            </li>
          ))}
        </ul>
      )}
      {result.applied.length === 0 ? null : (
        <div
          className="rounded-quiet border border-owner/40 bg-owner/10 px-3 py-2"
          data-testid="withdrawal-applied"
        >
          <p className="text-meta text-owner uppercase">this was not undone</p>
          <ul className="mt-1 space-y-1">
            {result.applied.map((line) => (
              <li key={line} className="text-sm text-owner">
                {line}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/**
 * Stop the work this case has not carried out yet.
 *
 * The button says what it does and refuses to suggest more. It stops what has not happened; it
 * does not put anything back, and the sentence under it says so before anybody presses it —
 * because the moment to learn that a withdrawal is not an undo is before the withdrawal, not
 * after it.
 */
function Withdraw({
  onWithdraw,
  pending,
  sending,
}: {
  onWithdraw: () => void
  /** Any turn is in flight, so no second one may be started. */
  pending: boolean
  /** *This* turn is in flight. Only that may change what the button says about itself. */
  sending: boolean
}): ReactNode {
  return (
    <div className="space-y-1.5">
      <button
        type="button"
        onClick={onWithdraw}
        disabled={pending}
        data-testid="conversation-withdraw"
        className="min-h-11 rounded-control border border-edge-strong bg-panel px-4 py-2.5 text-sm font-semibold text-ink transition-colors hover:border-owner hover:text-owner disabled:opacity-60"
      >
        {sending ? 'Stopping…' : 'Call this off'}
      </button>
      <p className="text-meta text-muted">
        This stops what has not happened yet. Anything already sent or changed stays as it is.
      </p>
    </div>
  )
}
