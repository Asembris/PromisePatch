/**
 * The answered questions, and the two things the screen must never do with them.
 *
 * The plan below band 1 exists because of an answer somebody gave. If that answer is not on the
 * page, a reader is being asked to take the shape of the plan on trust — so the history is
 * tested for being present, being verbatim, and being attributed.
 *
 * The negatives matter as much: the open question keeps its own prominence and is never drawn
 * twice, and an option code is never printed at a person.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import { CASES, CASE_ID, CLARIFYING_CASE, PLANNED_CASE } from './caseFixtures'
import { MAYA, PROMISES, RESOURCES } from './fixtures'
import {
  FakeStream,
  json,
  mockBackend,
  renderApp,
  streamResponse,
  type Responder,
} from './harness'

const CASE_PATH = `/api/cases/${CASE_ID}`

afterEach(() => {
  window.history.pushState({}, '', '/')
})

function mountAtCase(responder: Responder = () => json(PLANNED_CASE)): FakeStream {
  window.history.pushState({}, '', `/?case=${CASE_ID}`)
  const stream = new FakeStream()
  mockBackend({
    '/api/auth/me': () => json(MAYA),
    '/api/promises': () => json(PROMISES),
    '/api/resources': () => json(RESOURCES),
    '/api/cases': () => json(CASES),
    [CASE_PATH]: responder,
    '/events': () => streamResponse(stream),
  })
  renderApp()
  return stream
}

describe('the clarification history', () => {
  it('keeps an answered question beside the answer that closed it', async () => {
    const stream = mountAtCase()

    const history = await screen.findByTestId('clarification-history')

    const entry = within(history).getByTestId('clarification-answered')
    expect(entry).toHaveTextContent('Which of them did not arrive?')
    expect(entry).toHaveTextContent('just the raspberries, the strawberries came')
    expect(entry).toHaveTextContent('maya')
    stream.close()
  })

  it('quotes the worker word for word rather than the option it resolved to', async () => {
    const stream = mountAtCase()

    const entry = await screen.findByTestId('clarification-answered')

    const quote = within(entry).getByText(/just the raspberries/)
    expect(quote.tagName).toBe('BLOCKQUOTE')
    expect(within(entry).getByTestId('clarification-resolved')).toHaveTextContent(
      'Only the raspberries',
    )
    stream.close()
  })

  it('prints no option code and no slot name at a person', async () => {
    const stream = mountAtCase()

    const history = await screen.findByTestId('clarification-history')

    const text = history.textContent ?? ''
    // The resolved code, the codes it was chosen from, and the slot the question filled. All
    // four are real engine values and none of them is language, so the row shows the option's
    // own label instead and the codes stay on the wire.
    for (const code of PLANNED_CASE.clarifications[0]!.options.map((option) => option.code)) {
      expect(text, code).not.toContain(code)
    }
    expect(text).not.toContain(PLANNED_CASE.clarifications[0]!.resolved_option_code!)
    expect(text).not.toContain(PLANNED_CASE.clarifications[0]!.slot)
    stream.close()
  })

  it('sits above the plan it produced, and inside the band that holds the report', async () => {
    const stream = mountAtCase()

    const history = await screen.findByTestId('clarification-history')

    expect(within(screen.getByTestId('band-what-happened')).getByTestId('clarification-history'))
      .toBe(history)
    const position = history.compareDocumentPosition(screen.getByTestId('band-what-changes'))
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    stream.close()
  })

  it('shows nothing at all for a case nobody was asked anything about', async () => {
    const stream = mountAtCase(() => json({ ...PLANNED_CASE, clarifications: [] }))

    await screen.findByTestId('band-what-happened')

    expect(screen.queryByTestId('clarification-history')).not.toBeInTheDocument()
    stream.close()
  })
})

describe('the question still open', () => {
  it('is not repeated in the history while it is still waiting', async () => {
    const stream = mountAtCase(() => json(CLARIFYING_CASE))

    const question = await screen.findByTestId('case-question')

    expect(question).toHaveTextContent('Which of them did not arrive?')
    expect(screen.queryByTestId('clarification-history')).not.toBeInTheDocument()
    expect(screen.getAllByText('Which of them did not arrive?')).toHaveLength(1)
    stream.close()
  })

  it('keeps its own card once an earlier question has been answered', async () => {
    const stream = mountAtCase(() =>
      json({
        ...PLANNED_CASE,
        question: {
          clarification_id: 'b2c3d4e5-6f70-4a1b-8c2d-3e4f5a6b7c8d',
          question: 'Which line should the substitute go on?',
          options: [{ code: 'LINE_CHARLOTTE', label: 'The charlotte' }],
        },
        clarifications: [
          ...PLANNED_CASE.clarifications,
          {
            clarification_id: 'b2c3d4e5-6f70-4a1b-8c2d-3e4f5a6b7c8d',
            ordinal: 2,
            slot: 'LINE',
            question: 'Which line should the substitute go on?',
            options: [{ code: 'LINE_CHARLOTTE', label: 'The charlotte' }],
            asked_at: '2026-03-04T07:06:00+00:00',
            answered: false,
            answer_text: null,
            answered_by: null,
            answered_at: null,
            resolved_option_code: null,
          },
        ],
      }),
    )

    const history = await screen.findByTestId('clarification-history')

    expect(history).toHaveAttribute('data-count', '1')
    expect(history).not.toHaveTextContent('Which line should the substitute go on?')
    expect(screen.getByTestId('case-question')).toHaveTextContent(
      'Which line should the substitute go on?',
    )
    stream.close()
  })
})
