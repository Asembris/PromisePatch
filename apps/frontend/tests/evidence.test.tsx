/**
 * The four evidence layers: what each one may say, and what it may never say instead.
 *
 * The positive assertions are ordinary. The ones that matter are the negatives, and they are
 * all versions of the same rule: an identifier is an answer to a question nobody asked until
 * they have opened three disclosures, so a fingerprint, a node reference or a rule id appearing
 * in the first layer is a defect even though the value itself is perfectly true.
 *
 * The other rule under test is that depth costs a click and never a request. Every layer is
 * rendered from the case the screen already holds, so a test that counts requests across a
 * full descent is the cheapest proof that the drawer cannot become a second read.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CASES, CASE_ID, PLANNED_CASE, SETTLED_CASE } from './caseFixtures'
import { MAYA, PROMISES, RESOURCES } from './fixtures'
import {
  FakeStream,
  json,
  mockBackend,
  renderApp,
  streamResponse,
  type Backend,
  type Responder,
} from './harness'

const CASE_PATH = `/api/cases/${CASE_ID}`

/** Every identifier the fixtures carry. None of them may be readable above layer 4. */
const IDENTIFIERS = [
  'cl-valley-raspberry',
  'res-raspberry',
  'rv-charlotte-2',
  'ol-pr-a',
  'track-pr-a',
  'R-PREAPPROVED',
  'R-NOSUB',
  'fp-a0011223344556677',
  'pp:amend:track-pr-a:opt:1',
  'amd-58ad55e82e28',
  CASE_ID,
]

afterEach(() => {
  window.history.pushState({}, '', '/')
})

function mountAtCase(
  responder: Responder = () => json(SETTLED_CASE),
): { stream: FakeStream; backend: Backend } {
  window.history.pushState({}, '', `/?case=${CASE_ID}`)
  const stream = new FakeStream()
  const backend = mockBackend({
    '/api/auth/me': () => json(MAYA),
    '/api/promises': () => json(PROMISES),
    '/api/resources': () => json(RESOURCES),
    '/api/cases': () => json(CASES),
    [CASE_PATH]: responder,
    '/events': () => streamResponse(stream),
  })
  renderApp()
  return { stream, backend }
}

async function openEvidence(): Promise<HTMLElement> {
  await userEvent.click(await screen.findByTestId('evidence-toggle'))
  return screen.getByTestId('evidence-drawer')
}

// ------------------------------------------------------------------ the layers, in order

describe('the evidence layers', () => {
  it('asks the question a reader actually has, and answers nothing until asked', async () => {
    const { stream } = mountAtCase()

    const toggle = await screen.findByTestId('evidence-toggle')
    expect(toggle).toHaveTextContent('Why did PromisePatch decide this?')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('evidence-drawer')).not.toBeInTheDocument()
    stream.close()
  })

  it('opens on the plain-language layer, with the three deeper ones still closed', async () => {
    const { stream } = mountAtCase()

    const drawer = await openEvidence()

    expect(within(drawer).getByTestId('evidence-plain')).toBeInTheDocument()
    for (const deeper of ['evidence-path', 'evidence-authority', 'evidence-technical']) {
      expect(screen.getByTestId(deeper)).toHaveAttribute('aria-expanded', 'false')
    }
    stream.close()
  })

  it('puts the four layers in the order a reader descends them', async () => {
    const { stream } = mountAtCase()
    await openEvidence()

    const order = ['evidence-plain', 'evidence-path', 'evidence-authority', 'evidence-technical']
      .map((id) => screen.getByTestId(id))
    for (let index = 0; index + 1 < order.length; index += 1) {
      const position = order[index]!.compareDocumentPosition(order[index + 1]!)
      expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
    stream.close()
  })

  it('reaches every layer without issuing a single request', async () => {
    const { stream, backend } = mountAtCase()
    await screen.findByTestId('evidence-toggle')
    const before = backend.requests.length

    await openEvidence()
    for (const deeper of ['evidence-path', 'evidence-authority', 'evidence-technical']) {
      await userEvent.click(screen.getByTestId(deeper))
    }

    expect(backend.requests.length).toBe(before)
    stream.close()
  })
})

// ----------------------------------------------------------------- 1. the plain-language layer

describe('the plain-language layer', () => {
  it('says why each promise was decided, in the words the backend composed', async () => {
    const { stream } = mountAtCase()

    const drawer = await openEvidence()

    const rows = within(drawer).getAllByTestId('evidence-plain-row')
    const blocked = rows.find((row) => row.getAttribute('data-promise-id') === 'pr-c')!
    expect(blocked).toHaveTextContent('the order carries a no-substitution constraint')
    expect(within(drawer).getByTestId('evidence-exception')).toHaveTextContent(
      'a supplier delivery did not arrive',
    )
    stream.close()
  })

  it('carries every track, including the ones nothing was done to', async () => {
    const { stream } = mountAtCase()

    const drawer = await openEvidence()

    const ids = within(drawer)
      .getAllByTestId('evidence-plain-row')
      .map((row) => row.getAttribute('data-promise-id'))
    expect(ids).toEqual(SETTLED_CASE.evidence.tracks.map((track) => track.promise_id))
    expect(ids).toContain('pr-e')
    stream.close()
  })

  it('carries no identifier of any kind', async () => {
    const { stream } = mountAtCase()

    const drawer = await openEvidence()

    const text = within(drawer).getByTestId('evidence-plain').textContent ?? ''
    for (const identifier of IDENTIFIERS) expect(text).not.toContain(identifier)
    stream.close()
  })
})

// ------------------------------------------------------------------------- 2. the causal path

describe('the causal-path layer', () => {
  it('writes the stored traversal out in the order it arrived', async () => {
    const { stream } = mountAtCase(() => json(PLANNED_CASE))
    await openEvidence()

    await userEvent.click(screen.getByTestId('evidence-path'))

    const row = screen
      .getAllByTestId('evidence-path-row')
      .find((entry) => entry.getAttribute('data-promise-id') === 'pr-a')!
    const steps = within(row)
      .getAllByRole('listitem')
      .map((item) => item.textContent ?? '')
    expect(steps[0]).toContain('Valley Produce: Raspberries')
    expect(steps[1]).toContain('Raspberries')
    expect(steps.at(-1)).toContain('EXT-A')
    stream.close()
  })

  it('says why nothing reached a promise rather than drawing an empty path', async () => {
    const { stream } = mountAtCase()
    await openEvidence()

    await userEvent.click(screen.getByTestId('evidence-path'))

    const row = screen
      .getAllByTestId('evidence-path-row')
      .find((entry) => entry.getAttribute('data-promise-id') === 'pr-e')!
    expect(within(row).getByTestId('evidence-path-absent')).toHaveTextContent(
      'the exception reaches nothing it depends on',
    )
    stream.close()
  })

  it('never prints a node reference', async () => {
    const { stream } = mountAtCase(() => json(PLANNED_CASE))
    await openEvidence()

    await userEvent.click(screen.getByTestId('evidence-path'))

    const text = screen.getByTestId('evidence-path-section').textContent ?? ''
    for (const reference of ['cl-valley-raspberry', 'res-raspberry', 'rv-charlotte-2']) {
      expect(text).not.toContain(reference)
    }
    stream.close()
  })
})

// ------------------------------------------------------------------ 3. what was checked

describe('the authority layer', () => {
  it('names the authority each promise changes under', async () => {
    const { stream } = mountAtCase()
    await openEvidence()

    await userEvent.click(screen.getByTestId('evidence-authority'))

    const row = screen
      .getAllByTestId('evidence-authority-row')
      .find((entry) => entry.getAttribute('data-promise-id') === 'pr-a')!
    expect(row).toHaveTextContent('standing preference')
    stream.close()
  })

  it('puts expected beside actual on every revalidation check', async () => {
    const { stream } = mountAtCase(() =>
      json({
        ...SETTLED_CASE,
        evidence: {
          ...SETTLED_CASE.evidence,
          tracks: [
            {
              ...SETTLED_CASE.evidence.tracks[0]!,
              revalidation: {
                outcome: 'STALE',
                deciding_check: 2,
                detail: 'the order moved while the promise was waiting',
                fingerprint: 'fp-a0011223344556677',
                checks: [
                  {
                    index: 1,
                    name: 'order version',
                    passed: true,
                    expected: '1',
                    actual: '1',
                  },
                  {
                    index: 2,
                    name: 'reserved quantity',
                    passed: false,
                    expected: '4.000',
                    actual: '1.200',
                  },
                ],
              },
            },
            SETTLED_CASE.evidence.tracks[1]!,
          ],
        },
      }),
    )
    await openEvidence()

    await userEvent.click(screen.getByTestId('evidence-authority'))

    const checks = screen.getAllByTestId('evidence-check')
    expect(checks).toHaveLength(2)
    expect(checks[1]).toHaveTextContent('expected 4.000')
    expect(checks[1]).toHaveTextContent('actual 1.200')
    expect(checks[1]).toHaveAttribute('data-passed', 'false')
    stream.close()
  })

  it('says that nothing was revalidated rather than leaving the space blank', async () => {
    const { stream } = mountAtCase()
    await openEvidence()

    await userEvent.click(screen.getByTestId('evidence-authority'))

    expect(screen.getAllByTestId('evidence-revalidation-absent').length).toBeGreaterThan(0)
    stream.close()
  })
})

// ------------------------------------------------------------------- 4. the technical record

describe('the technical layer', () => {
  it('is the one place the identifiers live', async () => {
    const { stream } = mountAtCase()
    await openEvidence()

    await userEvent.click(screen.getByTestId('evidence-technical'))

    const panel = screen.getByTestId('evidence-technical-panel')
    expect(panel).toHaveTextContent(CASE_ID)
    expect(panel).toHaveTextContent('track-pr-a')
    expect(panel).toHaveTextContent('R-PREAPPROVED')
    expect(panel).toHaveTextContent('fp-a0011223344556677')
    expect(panel).toHaveTextContent('pp:amend:track-pr-a:opt:1')
    stream.close()
  })

  it('shows a fingerprint in full rather than shortened to look tidy', async () => {
    const { stream } = mountAtCase()
    await openEvidence()

    await userEvent.click(screen.getByTestId('evidence-technical'))

    expect(screen.getByTestId('evidence-technical-panel')).toHaveTextContent(
      'fp-a0011223344556677',
    )
    stream.close()
  })

  it('carries the node references of a chain, which no layer above it may', async () => {
    const { stream } = mountAtCase(() => json(PLANNED_CASE))
    await openEvidence()

    await userEvent.click(screen.getByTestId('evidence-technical'))

    expect(screen.getAllByTestId('evidence-node-refs')[0]).toHaveTextContent('cl-valley-raspberry')
    stream.close()
  })

  it('shows the external order version and the versions the case mirrored', async () => {
    const { stream } = mountAtCase()
    await openEvidence()

    await userEvent.click(screen.getByTestId('evidence-technical'))

    const row = screen
      .getAllByTestId('evidence-row')
      .find((entry) => entry.getAttribute('data-promise-id') === 'pr-a')!
    expect(row).toHaveTextContent('EXT-A · v1')
    expect(row).toHaveTextContent('ol-a → rv-raspberry-almond-3')
    stream.close()
  })
})

// --------------------------------------------------------------------------- keyboard focus

describe('closing a layer', () => {
  it('gives focus back to the control that closed it', async () => {
    const { stream } = mountAtCase()
    await openEvidence()
    const technical = screen.getByTestId('evidence-technical')
    await userEvent.click(technical)
    // Focus is inside the panel that is about to be unmounted, which is the case where a
    // disclosure loses a keyboard reader entirely if it does nothing about it.
    const inside = within(screen.getByTestId('evidence-technical-panel')).getAllByRole('cell')[0]!
    inside.setAttribute('tabindex', '-1')
    inside.focus()

    await userEvent.click(technical)

    expect(technical).toHaveFocus()
    expect(screen.queryByTestId('evidence-technical-panel')).not.toBeInTheDocument()
    stream.close()
  })

  it('leaves the layers below a closed one closed when it is reopened', async () => {
    const { stream } = mountAtCase()
    await openEvidence()
    await userEvent.click(screen.getByTestId('evidence-technical'))
    expect(screen.getByTestId('evidence-technical-panel')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('evidence-toggle'))
    await userEvent.click(screen.getByTestId('evidence-toggle'))

    expect(screen.getByTestId('evidence-technical')).toHaveAttribute('aria-expanded', 'false')
    stream.close()
  })
})
