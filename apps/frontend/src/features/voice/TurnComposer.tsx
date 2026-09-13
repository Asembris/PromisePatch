/**
 * The one control a worker says something through, whether they type it or speak it.
 *
 * There is deliberately **one** composer and not two. A voice path with its own send would be a
 * second way into the product, and the two would drift: one would gain a trim, a confirmation or
 * a retry the other did not have, and the difference would only ever be discovered by somebody
 * speaking. So a spoken turn sets the text of *this* turn and nothing else — the same `onSend`,
 * the same mutation, the same route, the same server-derived actor.
 *
 * **Nothing is sent because somebody spoke.** Capture ends, the transcript is shown, and it sits
 * there until the person who said it presses send, edits it, or throws it away. That is the
 * whole reason the review step exists: a voice surface that acted on a misheard sentence would
 * have produced a physical attestation nobody made, and no amount of accuracy makes that
 * acceptable.
 *
 * **The text field is the same control, not a degraded one.** A browser with no speech interface
 * renders exactly this panel minus the microphone, and says so once. Nothing about the turn, the
 * route or what the worker is told differs.
 *
 * **No wake word and no always-listening.** Capture is started by a press and is not continuous;
 * between turns this component holds no microphone at all.
 */
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { speechCaptureAvailable, startCapture, type Capture } from './speech'

/**
 * Where capture has got to. Five of the nine voice states the contract fixes live here; the
 * other four are postures of the *case* and are drawn by the panel around this one.
 */
export type CaptureState = 'idle' | 'listening' | 'captured' | 'correcting' | 'unavailable'

export interface TurnComposerProps {
  /** The visible instruction above the field. */
  label: string
  placeholder?: string
  /** What the send button says when it is not busy. */
  sendLabel: string
  /** What it says while the backend has the turn and has not answered. */
  pendingLabel: string
  pending: boolean
  /**
   * Take this turn. Resolves once the backend has accepted it, and rejects when it refused.
   *
   * A promise rather than a callback for one reason: the field is cleared only on a resolution.
   * A composer that emptied itself the moment it handed the words on would throw away a
   * worker's sentence every time the backend said no, and the sentence is theirs.
   */
  onSend: (text: string) => Promise<unknown>
  /** Prefix for this composer's test ids, so two on one screen stay distinguishable. */
  idPrefix: string
}

export function TurnComposer({
  label,
  placeholder,
  sendLabel,
  pendingLabel,
  pending,
  onSend,
  idPrefix,
}: TurnComposerProps): ReactNode {
  const [text, setText] = useState('')
  const [heard, setHeard] = useState<string | null>(null)
  const [listening, setListening] = useState(false)
  const [correcting, setCorrecting] = useState(false)
  const [trouble, setTrouble] = useState<string | null>(null)
  const capture = useRef<Capture | null>(null)
  const field = useRef<HTMLTextAreaElement | null>(null)
  // Asked once, at mount, so the control does not appear and disappear between renders.
  const [available] = useState(() => speechCaptureAvailable())

  useEffect(() => {
    return () => {
      capture.current?.abort()
      capture.current = null
    }
  }, [])

  const state: CaptureState = !available
    ? 'unavailable'
    : listening
      ? 'listening'
      : heard !== null
        ? 'captured'
        : correcting
          ? 'correcting'
          : 'idle'

  function beginListening(): void {
    setTrouble(null)
    setHeard(null)
    const started = startCapture({
      onTranscript: (spoken) => {
        setHeard(spoken)
      },
      onEnd: () => {
        capture.current = null
        setListening(false)
      },
      onError: (reason) => {
        capture.current = null
        setListening(false)
        setHeard(null)
        setTrouble(reason)
      },
    })
    if (started === null) {
      setTrouble('unavailable')
      return
    }
    capture.current = started
    setListening(true)
  }

  function stopListening(): void {
    capture.current?.stop()
    capture.current = null
    setListening(false)
  }

  /** Move the transcript into the field, where it can be corrected before it is sent. */
  function editHeard(): void {
    setText(heard ?? '')
    setHeard(null)
    setCorrecting(true)
    window.setTimeout(() => field.current?.focus(), 0)
  }

  /** Throw the transcript away. Nothing was sent, so nothing has to be undone. */
  function discardHeard(): void {
    setHeard(null)
    setCorrecting(false)
  }

  function send(value: string): void {
    if (value.trim().length === 0 || pending) return
    void onSend(value).then(
      () => {
        setText('')
        setHeard(null)
        setCorrecting(false)
      },
      () => {
        // Kept, deliberately. The turn did not happen, the words are still the worker's, and
        // the panel around this one shows the backend's own refusal.
      },
    )
  }

  function onSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    send(text)
  }

  return (
    <div className="space-y-3" data-testid={`${idPrefix}-composer`} data-capture-state={state}>
      {/* One live region for the whole composer, so a screen reader is told capture started,
          stopped and what was heard, in the order it happened. */}
      <p className="sr-only" role="status" data-testid={`${idPrefix}-voice-state`}>
        {VOICE_STATE_SENTENCE[state]}
      </p>

      <form className="space-y-2.5" onSubmit={onSubmit}>
        <label className="block text-label text-muted uppercase" htmlFor={`${idPrefix}-text`}>
          {label}
        </label>
        <textarea
          id={`${idPrefix}-text`}
          ref={field}
          name={idPrefix}
          rows={3}
          value={text}
          disabled={pending}
          placeholder={placeholder}
          onChange={(event) => {
            setText(event.target.value)
          }}
          className="w-full rounded-control border border-edge bg-panel px-3 py-2.5 text-sm text-ink placeholder:text-muted/60 disabled:opacity-60"
          data-testid={`${idPrefix}-text`}
        />

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="submit"
            disabled={pending || text.trim().length === 0}
            data-testid={`${idPrefix}-send`}
            className="min-h-11 rounded-control bg-brand px-4 py-2.5 text-sm font-semibold text-brand-ink transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {pending ? pendingLabel : sendLabel}
          </button>

          {available ? (
            <button
              type="button"
              aria-pressed={listening}
              disabled={pending}
              onClick={listening ? stopListening : beginListening}
              data-testid={`${idPrefix}-talk`}
              className={`min-h-11 rounded-control border px-4 py-2.5 text-sm font-semibold transition-colors disabled:opacity-60 ${
                listening
                  ? 'border-brand bg-brand/20 text-ink'
                  : 'border-edge-strong bg-panel text-ink hover:bg-card-hover'
              }`}
            >
              {listening ? (
                <span className="flex items-center gap-2">
                  <span
                    aria-hidden="true"
                    className="h-2.5 w-2.5 rounded-full bg-brand motion-safe:animate-pulse"
                  />
                  Stop and read it back
                </span>
              ) : (
                'Press and speak'
              )}
            </button>
          ) : null}
        </div>
      </form>

      {available ? null : (
        <p className="text-meta text-muted" data-testid={`${idPrefix}-voice-unavailable`}>
          This browser offers no microphone to PromisePatch, so the turn is typed. It is the same
          turn: the same words, written down the same way.
        </p>
      )}

      {listening ? (
        <div className="space-y-1.5" data-testid={`${idPrefix}-listening`}>
          <p className="text-sm text-muted">
            Listening. Nothing is sent until you have read it back.
          </p>
          {/* What the browser has heard so far, shown while it is still hearing it. There is
              deliberately no send here: a half-finished sentence is not a turn, and a control
              that could take one would make the microphone the thing that decides when a
              worker has finished speaking. */}
          {heard === null ? null : (
            <p className="text-sm text-muted italic" data-testid={`${idPrefix}-interim`}>
              {heard}
            </p>
          )}
        </div>
      ) : null}

      {listening || heard === null ? null : (
        <div
          className="space-y-2.5 rounded-quiet border border-brand/40 bg-brand/8 px-3 py-3"
          data-testid={`${idPrefix}-transcript`}
        >
          <p className="text-label text-muted uppercase">what was heard — nothing is sent yet</p>
          <blockquote className="text-sm font-medium text-ink">&ldquo;{heard}&rdquo;</blockquote>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={pending || heard.trim().length === 0}
              onClick={() => {
                send(heard)
              }}
              data-testid={`${idPrefix}-transcript-send`}
              className="min-h-11 rounded-control bg-brand px-4 py-2.5 text-sm font-semibold text-brand-ink transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {pending ? pendingLabel : sendLabel}
            </button>
            <button
              type="button"
              onClick={editHeard}
              data-testid={`${idPrefix}-transcript-edit`}
              className="min-h-11 rounded-control border border-edge-strong bg-panel px-4 py-2.5 text-sm font-semibold text-ink hover:bg-card-hover"
            >
              Fix the wording
            </button>
            <button
              type="button"
              onClick={discardHeard}
              data-testid={`${idPrefix}-transcript-discard`}
              className="min-h-11 rounded-control border border-edge-strong bg-panel px-4 py-2.5 text-sm font-semibold text-muted hover:bg-card-hover"
            >
              Throw it away
            </button>
          </div>
        </div>
      )}

      {trouble === null ? null : (
        <p
          role="alert"
          data-testid={`${idPrefix}-voice-trouble`}
          className="rounded-quiet border border-owner/40 bg-owner/10 px-3 py-2 text-sm text-owner"
        >
          That turn was not heard, so nothing was said and nothing has changed. Type it instead,
          or try speaking again.
        </p>
      )}
    </div>
  )
}

/**
 * What each capture state is, said once, for anybody not looking at the screen.
 *
 * Deliberately about the microphone and never about a case: this component knows nothing about
 * a case, and a sentence here that implied an outcome would be a claim composed on a screen.
 */
const VOICE_STATE_SENTENCE: Record<CaptureState, string> = {
  idle: 'Ready. Type your turn, or press and speak.',
  listening: 'Listening. Nothing is sent until you have read it back.',
  captured: 'Heard. Read it back, then send it, fix it or throw it away.',
  correcting: 'Fix the wording, then send it.',
  unavailable: 'This browser offers no microphone, so the turn is typed.',
}
