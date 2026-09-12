/**
 * A sweep of the rendered surface for words the product may not put in front of a person.
 *
 * Every test above this one asserts that a particular sentence appears. This one asserts the
 * complement, over the whole document, because that is the failure mode a targeted test cannot
 * catch: a token leaks not where somebody wrote an assertion but where nobody thought to look.
 *
 * The tokens are real values from the engine's own vocabularies — `promise_graph.model`'s
 * `ReasonDetail`, `RuleId` and `ExceptionCategory`, and the classifications and track states
 * `analysis` reads back. Every one of them is true. None of them is language. The rule they
 * break is P7.1's: a worker reads sentences, and a judge opens the drawer.
 *
 * Two scopes are checked separately and deliberately.
 *
 * - **The case workspace with the drawer shut** may contain none of them at all.
 * - **The plain-words and causal-path layers**, once opened, may contain none of them either,
 *   because the first two layers of the evidence are still sentences. Only the technical record
 *   is allowed identifiers, and a separate test asserts it actually carries them — a screen that
 *   passed this sweep by showing nothing anywhere would be worse than one that leaked.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { APPLYING_CASE, CASES, CASE_ID, PLANNED_CASE, SETTLED_CASE } from './caseFixtures'
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

/** Engine vocabulary. Every one of these is a real value, and none of them is a sentence. */
const INTERNAL_TOKENS = [
  // ReasonDetail
  'PREAPPROVAL_COVERS',
  'NOSUB_CONSTRAINT',
  'NO_PREAUTHORED_VARIANT',
  'VISIBLE_CHANGE_ASK',
  'NOT_VISIBLE_NO_ASK',
  'NOT_PREAPPROVED',
  'SHORTFALL_COVERED',
  'NOT_REACHABLE',
  'EXCLUDED_SUBSTITUTE',
  'INSUFFICIENT_SUBSTITUTE_STOCK',
  'EQUIPMENT_REASSIGNED',
  'NO_ALTERNATIVE_EQUIPMENT',
  'NO_CONSTRAINT_SNAPSHOT',
  'UNKNOWN_QUANTITY',
  'CONFLICTING_CONSTRAINTS',
  // ExceptionCategory
  'SUPPLY_NOT_RECEIVED',
  'STOCK_UNUSABLE',
  'EQUIPMENT_UNAVAILABLE',
  // Classification, and the durable track states behind the product's own words
  'AUTO_RECOVERABLE',
  'APPROVAL_REQUIRED',
  'UNAFFECTED',
  'WAITING_FOR_CUSTOMER',
  // Rule ids
  'R-PREAPPROVED',
  'R-NOSUB',
  'R-VISIBLE-ASK',
  'R-UNREACH',
  // Identifiers from the fixture universe
  'cl-valley-raspberry',
  'res-raspberry',
  'rv-charlotte-2',
  'track-pr-a',
  'fp-a0011223344556677',
  'pp:amend:track-pr-a:opt:1',
  CASE_ID,
]

afterEach(() => {
  window.history.pushState({}, '', '/')
})

function mountAtCase(responder: Responder): FakeStream {
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

function assertNoTokensIn(text: string): void {
  for (const token of INTERNAL_TOKENS) {
    expect(text, `"${token}" reached a surface a person reads`).not.toContain(token)
  }
}

describe('the bands a person reads', () => {
  for (const [name, fixture] of [
    ['planned', PLANNED_CASE],
    ['settled', SETTLED_CASE],
    ['applying', APPLYING_CASE],
  ] as const) {
    it(`carries no engine token on a ${name} case`, async () => {
      const stream = mountAtCase(() => json(fixture))

      await screen.findByTestId('case-workspace')

      assertNoTokensIn(screen.getByTestId('case-workspace').textContent ?? '')
      stream.close()
    })
  }

  it('says what happened in words rather than in the category the engine filed', async () => {
    const stream = mountAtCase(() => json(PLANNED_CASE))

    const band = await screen.findByTestId('band-what-happened')

    expect(band).toHaveTextContent('a supplier delivery did not arrive')
    expect(within(screen.getByTestId('incident-source')).getByText(
      'a supplier delivery did not arrive',
    )).toBeInTheDocument()
    stream.close()
  })

  it('shows nothing at all where the domain publishes no words for a reason', async () => {
    // Understating: a token this build has no phrase for is not printed at a person. It is
    // still on the wire and still in the technical record, so nothing is lost — only moved.
    const stream = mountAtCase(() =>
      json({
        ...PLANNED_CASE,
        authority_bands: PLANNED_CASE.authority_bands.map((band) => ({
          ...band,
          promises: band.promises.map((promise) => ({
            ...promise,
            reason: 'SOMETHING_THIS_BUILD_HAS_NO_WORDS_FOR',
            reason_phrase: null,
          })),
        })),
      }),
    )

    const map = await screen.findByTestId('band-what-changes')

    expect(map.textContent ?? '').not.toContain('SOMETHING_THIS_BUILD_HAS_NO_WORDS_FOR')
    expect(screen.getAllByTestId('promise-row')).toHaveLength(3)
    stream.close()
  })
})

describe('the first evidence layers', () => {
  it('keep the plain-language and path layers free of engine tokens', async () => {
    const stream = mountAtCase(() => json(SETTLED_CASE))
    await userEvent.click(await screen.findByTestId('evidence-toggle'))

    await userEvent.click(screen.getByTestId('evidence-path'))

    assertNoTokensIn(screen.getByTestId('evidence-plain').textContent ?? '')
    assertNoTokensIn(screen.getByTestId('evidence-path-section').textContent ?? '')
    stream.close()
  })

  it('name the authority group in the backend’s own title, not in its token', async () => {
    const stream = mountAtCase(() => json(SETTLED_CASE))
    await userEvent.click(await screen.findByTestId('evidence-toggle'))

    await userEvent.click(screen.getByTestId('evidence-authority'))

    const row = screen
      .getAllByTestId('evidence-authority-row')
      .find((entry) => entry.getAttribute('data-promise-id') === 'pr-b')!
    expect(row).toHaveTextContent('Needs the customer')
    expect(row.textContent ?? '').not.toContain('CUSTOMER')
    stream.close()
  })

  it('do not pass by hiding everything: the technical record still carries the tokens', async () => {
    const stream = mountAtCase(() => json(SETTLED_CASE))
    await userEvent.click(await screen.findByTestId('evidence-toggle'))

    await userEvent.click(screen.getByTestId('evidence-technical'))

    const panel = screen.getByTestId('evidence-technical-panel').textContent ?? ''
    for (const token of ['NOSUB_CONSTRAINT', 'R-NOSUB', 'UNAFFECTED', CASE_ID]) {
      expect(panel).toContain(token)
    }
    stream.close()
  })
})
