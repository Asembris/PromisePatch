/**
 * Speech capture, as much of it as a browser actually offers and not one claim more.
 *
 * **What this is.** A thin wrapper over the browser's own `SpeechRecognition`. No Amazon
 * Transcribe, no Polly, no Alexa skill, no wake-word engine and no audio leaving this module to
 * anywhere PromisePatch operates. Where the browser has no such interface, `create` returns
 * `null` and the surface says the microphone is not available here — it does not fall back to a
 * simulation, because a transcript nobody spoke is an attestation nobody made.
 *
 * **It is push-to-talk and nothing else.** `start` is called from a person pressing a control
 * and `continuous` is off, so the recogniser stops when they stop speaking or when they press
 * stop. Nothing here listens between turns, and no part of the product claims it does.
 *
 * **It produces text and never a decision.** The transcript is handed back to the caller, which
 * shows it to the person who spoke before anything is sent. This module issues no request,
 * touches no case and knows nothing about one.
 */

/** The one shape this module needs from the browser's recogniser. */
interface BrowserRecognition {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((event: SpeechResultEvent) => void) | null
  onerror: ((event: { error?: string }) => void) | null
  onend: (() => void) | null
}

interface SpeechResultEvent {
  resultIndex: number
  results: {
    length: number
    [index: number]: { isFinal: boolean; 0: { transcript: string } }
  }
}

type RecognitionConstructor = new () => BrowserRecognition

function constructorFor(): RecognitionConstructor | null {
  const scope = window as unknown as {
    SpeechRecognition?: RecognitionConstructor
    webkitSpeechRecognition?: RecognitionConstructor
  }
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null
}

/** Whether this browser can capture speech at all. The only thing that decides voice is offered. */
export function speechCaptureAvailable(): boolean {
  return constructorFor() !== null
}

export interface CaptureHandlers {
  /** Everything heard so far, final and interim together, so a person can see it landing. */
  onTranscript: (text: string, final: boolean) => void
  /** Capture stopped, for any reason. The caller decides what the transcript is now worth. */
  onEnd: () => void
  /** The browser refused or failed. Carries its own word for it, never a sentence about a case. */
  onError: (reason: string) => void
}

export interface Capture {
  stop: () => void
  abort: () => void
}

/**
 * Begin one turn of capture, or return `null` where the browser cannot.
 *
 * Interim results are on so the person watching sees words appear as they say them — that is
 * feedback about the microphone, not a result, and it is never sent anywhere. Only the caller's
 * explicit send does that.
 */
export function startCapture(handlers: CaptureHandlers): Capture | null {
  const Recognition = constructorFor()
  if (Recognition === null) return null

  const recognition = new Recognition()
  recognition.continuous = false
  recognition.interimResults = true
  recognition.maxAlternatives = 1
  recognition.lang = navigator.language || 'en-GB'

  recognition.onresult = (event) => {
    let heard = ''
    let final = false
    for (let index = 0; index < event.results.length; index += 1) {
      const result = event.results[index]
      if (result === undefined) continue
      heard += result[0].transcript
      if (result.isFinal) final = true
    }
    handlers.onTranscript(heard, final)
  }
  recognition.onerror = (event) => {
    handlers.onError(event.error ?? 'unknown')
  }
  recognition.onend = () => {
    handlers.onEnd()
  }

  recognition.start()
  return {
    stop: () => {
      recognition.stop()
    },
    abort: () => {
      recognition.abort()
    },
  }
}
