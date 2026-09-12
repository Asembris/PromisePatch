/**
 * What the case workspace must show, and what it must never say on its own authority.
 *
 * The negative assertions are the point. A screen that rendered "changed" for a promise the
 * order system has not confirmed, or that counted the untouched promises itself, or that wrote
 * a friendlier word for `ESCALATED`, would be the product lying in the one place a worker
 * actually looks. So the fixtures give the four outcomes four different phrases, and the tests
 * check that each one arrives on the screen as the backend wrote it.
 *
 * The reload tests mount the app at a case address, which is exactly what a refreshed browser
 * does: the case id is in the URL, so there is no client-side selection to lose, and what
 * appears is the answer to a fresh read of the durable case.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  APPLYING_CASE,
  CASES,
  CASE_ID,
  CLARIFYING_CASE,
  NO_CASES,
  PLANNED_CASE,
  SETTLED_CASE,
} from './caseFixtures'
import { MAYA, PROMISES, RESOURCES } from './fixtures'
import {
  FakeStream,
  apiError,
  json,
  mockBackend,
  renderApp,
  streamResponse,
  type Backend,
  type Responder,
} from './harness'

const CASE_PATH = `/api/cases/${CASE_ID}`

function at(search: string): void {
  window.history.pushState({}, '', `/${search}`)
}

afterEach(() => {
  at('')
})

function mount(
  routes: Record<string, Responder> = {},
): { stream: FakeStream; backend: Backend } {
  const stream = new FakeStream()
  const backend = mockBackend({
    '/api/auth/me': () => json(MAYA),
    '/api/promises': () => json(PROMISES),
    '/api/resources': () => json(RESOURCES),
    '/api/cases': () => json(CASES),
    [CASE_PATH]: () => json(PLANNED_CASE),
    '/events': () => streamResponse(stream),
    ...routes,
  })
  renderApp()
  return { stream, backend }
}

/** Mount already looking at a case, which is what a reload of a case address does. */
function mountAtCase(routes: Record<string, Responder> = {}): {
  stream: FakeStream
  backend: Backend
} {
  at(`?case=${CASE_ID}`)
  return mount(routes)
}

// ------------------------------------------------------------------------ the four bands

describe('the case workspace', () => {
  it('shows the worker’s own words and the case sentence', async () => {
    const { stream } = mountAtCase()

    expect(await screen.findByTestId('band-what-happened')).toBeInTheDocument()
    const band = screen.getByTestId('band-what-happened')
    expect(within(band).getByText(/raspberry delivery/)).toBeInTheDocument()
    expect(within(band).getByText(/reported by/)).toHaveTextContent('maya')
    expect(within(band).getByText(PLANNED_CASE.sentence)).toBeInTheDocument()
    stream.close()
  })

  it('shows exactly one next action, with the person it belongs to', async () => {
    const { stream } = mountAtCase()

    const band = await screen.findByTestId('band-next-action')
    expect(within(band).getByTestId('next-action-sentence')).toHaveTextContent(
      PLANNED_CASE.next_action.action,
    )
    expect(within(band).getByText('You')).toBeInTheDocument()
    expect(screen.getAllByTestId('next-action-sentence')).toHaveLength(1)
    stream.close()
  })

  it('groups threatened promises under the backend’s authority bands, in its order', async () => {
    const { stream } = mountAtCase()

    await screen.findByTestId('band-what-changes')
    const bands = screen.getAllByTestId('authority-band')
    expect(bands.map((band) => band.getAttribute('data-authority'))).toEqual([
      'STANDING_PREFERENCE',
      'CUSTOMER',
      'OWNER',
    ])
    expect(within(bands[0]!).getByText('Covered by a standing preference')).toBeInTheDocument()
    expect(within(bands[2]!).getByText('Okafor-Reyes wedding')).toBeInTheDocument()
    stream.close()
  })

  it('shows the untouched promises and the count the backend published', async () => {
    const { stream } = mountAtCase()

    await screen.findByTestId('band-untouched')
    const rows = screen.getAllByTestId('untouched-row')
    expect(rows.map((row) => row.getAttribute('data-promise-id'))).toEqual(['pr-e', 'pr-f'])
    // Both figures are backend integers shown as themselves. The screen publishes no total,
    // because a total is arithmetic and arithmetic here would be a number with no field
    // behind it, sitting beside numbers that have one.
    const counts = within(screen.getByTestId('case-counts'))
    expect(counts.getByText('2')).toBeInTheDocument()
    expect(counts.getByText('left alone')).toBeInTheDocument()
    expect(counts.getByText('3')).toBeInTheDocument()
    expect(counts.getByText('orders affected')).toBeInTheDocument()
    // The domain's sentence for the reason, not the token behind it: a band a baker reads
    // may not print an enum, and the token itself is in the technical record.
    expect(
      within(rows[0]!).getByText('the exception reaches nothing it depends on'),
    ).toBeInTheDocument()
    stream.close()
  })

  it('takes the case’s own universe from the backend’s field, not from the counts beside it', async () => {
    // The denominator used to be forbidden outright, because until the backend published one
    // the only way to show it was to add the two counts together. It publishes one now, so the
    // assertion becomes the stronger of the two available: the figure on the screen follows
    // `promise_count`, and a case whose universe is deliberately not `untouched + threatened`
    // renders the universe.
    const { stream } = mountAtCase({
      [CASE_PATH]: () => json({ ...PLANNED_CASE, promise_count: 9 }),
    })

    const proof = await screen.findByTestId('untouched-proof')
    expect(proof).toHaveAttribute('data-universe', '9')
    expect(within(proof).getByText(/of 9 this case considered/)).toBeInTheDocument()
    expect(screen.queryByText(/of 5 this case considered/)).not.toBeInTheDocument()
    stream.close()
  })

  it('shows an open question as a question rather than as a result', async () => {
    const { stream } = mountAtCase({ [CASE_PATH]: () => json(CLARIFYING_CASE) })

    const question = await screen.findByTestId('case-question')
    expect(within(question).getByText('Which of them did not arrive?')).toBeInTheDocument()
    expect(within(question).getByText('Only the raspberries')).toBeInTheDocument()
    expect(screen.queryByTestId('authority-band')).not.toBeInTheDocument()
    expect(screen.getByTestId('next-action-sentence')).toHaveTextContent('Answer the question')
    stream.close()
  })
})

/**
 * Band order is reading order is screen-reader order.
 *
 * The five bands are one fixed sequence at every viewport: the untouched band in particular is
 * never dropped, reordered or collapsed to save space, because it is the band that carries the
 * product's central claim. DOM order is what a screen reader and a phone both follow, so
 * asserting on it asserts on both.
 */
describe('the band order', () => {
  it('is fixed, and the untouched band is never the one that goes', async () => {
    const { stream } = mountAtCase({ [CASE_PATH]: () => json(SETTLED_CASE) })
    await screen.findByTestId('band-untouched')

    const order = [
      'band-what-happened',
      'band-next-action',
      'band-what-changes',
      'band-untouched',
      'evidence-toggle',
    ].map((id) => screen.getByTestId(id))

    for (let index = 0; index + 1 < order.length; index += 1) {
      const position = order[index]!.compareDocumentPosition(order[index + 1]!)
      expect(position & Node.DOCUMENT_POSITION_FOLLOWING, order[index]!.dataset.testid).toBeTruthy()
    }
    stream.close()
  })
})

// --------------------------------------------------------------- what it must never overstate

describe('truthfulness', () => {
  it('renders each of the four outcomes in the backend’s own words', async () => {
    const { stream } = mountAtCase({ [CASE_PATH]: () => json(SETTLED_CASE) })

    await screen.findByTestId('band-what-changes')
    const rows = screen.getAllByTestId('promise-row')
    const states: Record<string, string | null> = {}
    for (const row of rows) states[row.getAttribute('data-promise-id') ?? ''] = row.getAttribute('data-state')
    expect(states).toEqual({ 'pr-a': 'RECOVERED', 'pr-b': 'REQUESTED', 'pr-c': 'ESCALATED' })
    expect(within(rows[0]!).getByText('changed')).toBeInTheDocument()
    expect(within(rows[1]!).getByText('asked')).toBeInTheDocument()
    expect(within(rows[2]!).getByText('needs you')).toBeInTheDocument()
    stream.close()
  })

  it('never shows an effect still in flight as a completed one', async () => {
    const { stream } = mountAtCase({ [CASE_PATH]: () => json(APPLYING_CASE) })

    await screen.findByTestId('band-what-changes')
    const applying = screen
      .getAllByTestId('promise-row')
      .find((row) => row.getAttribute('data-promise-id') === 'pr-a')
    expect(applying).toHaveAttribute('data-state', 'APPLYING')
    expect(within(applying!).getByText('changing the order now')).toBeInTheDocument()
    expect(screen.queryByText('changed')).not.toBeInTheDocument()
    stream.close()
  })

  it('gives every blocked promise an owner, a reason and a next action', async () => {
    const { stream } = mountAtCase({ [CASE_PATH]: () => json(SETTLED_CASE) })

    await screen.findByTestId('band-what-changes')
    const blocked = screen
      .getAllByTestId('promise-row')
      .find((row) => row.getAttribute('data-promise-id') === 'pr-c')!
    expect(
      within(blocked).getByText('the order carries a no-substitution constraint'),
    ).toBeInTheDocument()
    expect(within(blocked).getByTestId('promise-next-action')).toHaveTextContent(
      'The owner handles this one by hand',
    )
    expect(screen.getByTestId('next-action-sentence')).toHaveTextContent('needs the owner')
    stream.close()
  })

  it('states every promise as text as well as colour', async () => {
    const { stream } = mountAtCase({ [CASE_PATH]: () => json(SETTLED_CASE) })

    await screen.findByTestId('band-what-changes')
    for (const row of screen.getAllByTestId('promise-row')) {
      // The state name is present as a readable string, so the row survives being greyscale.
      expect(row.textContent).toContain(row.getAttribute('data-state'))
    }
    stream.close()
  })

  it('draws every threatened promise its own path out of the one incident', async () => {
    const { stream } = mountAtCase()

    const map = await screen.findByTestId('band-what-changes')
    const rows = within(map).getAllByTestId('promise-row')
    expect(rows).toHaveLength(3)
    for (const row of rows) {
      // Each row carries the whole traversal it was handed: the source is drawn once per row
      // rather than once per case, because three promises reached is three paths.
      expect(within(row).getByText('Valley Produce: Raspberries')).toBeInTheDocument()
      expect(within(row).getAllByTestId('chain-column')).toHaveLength(4)
    }
    // The fixture's chain visits the version column twice, and both nodes are drawn there.
    const columns = within(rows[0]!).getAllByTestId('chain-column')
    expect(columns[2]!).toHaveAttribute('data-occupied', '2')
    expect(screen.getByTestId('incident-source')).toBeInTheDocument()
    stream.close()
  })

  it('carries no node reference into the bands a worker reads', async () => {
    const { stream } = mountAtCase()

    await screen.findByTestId('band-what-changes')
    const text = document.body.textContent ?? ''
    for (const reference of ['cl-valley-raspberry', 'res-raspberry', 'rv-charlotte-2', 'ol-pr-a']) {
      expect(text).not.toContain(reference)
    }
    expect(text).not.toContain('R-PREAPPROVED')
    stream.close()
  })

  it('puts no completion treatment anywhere on a planned case', async () => {
    const { stream } = mountAtCase()

    await screen.findByTestId('band-what-changes')
    for (const status of screen.getAllByTestId('promise-status')) {
      expect(status).toHaveAttribute('data-finished', 'false')
    }
    expect(screen.queryByText('changed')).not.toBeInTheDocument()
    stream.close()
  })

  it('reports a failed read as a failure to read, not as a case with nothing in it', async () => {
    const { stream } = mountAtCase({
      [CASE_PATH]: () => apiError(500, 'INTERNAL', 'boom'),
    })

    // Generous, because a 5xx is retried: the assertion is about what is finally shown, not
    // about how quickly the client gives up.
    expect(await screen.findByText(/could not be loaded/, {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByTestId('band-untouched')).not.toBeInTheDocument()
    expect(screen.queryByText(/left alone/)).not.toBeInTheDocument()
    stream.close()
  })
})

// ------------------------------------------------------------------- the evidence drawer

describe('the evidence drawer', () => {
  it('is collapsed until it is asked for', async () => {
    const { stream } = mountAtCase({ [CASE_PATH]: () => json(SETTLED_CASE) })

    const toggle = await screen.findByTestId('evidence-toggle')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('evidence-drawer')).not.toBeInTheDocument()
    stream.close()
  })

  it('shows identifiers and provider references, and needs no second request', async () => {
    // The identifiers moved one layer deeper when the evidence became progressive: they are
    // the technical record, not the first answer. The assertion is unchanged — only the number
    // of clicks that reaches it, which is the point of the layering.
    const { stream, backend } = mountAtCase({ [CASE_PATH]: () => json(SETTLED_CASE) })
    const toggle = await screen.findByTestId('evidence-toggle')
    const before = backend.countOf(CASE_PATH)

    await userEvent.click(toggle)
    await userEvent.click(screen.getByTestId('evidence-technical'))

    const drawer = screen.getByTestId('evidence-drawer')
    expect(within(drawer).getByText(CASE_ID)).toBeInTheDocument()
    expect(within(drawer).getByText('ac1f2b3c4d5e6f70')).toBeInTheDocument()
    expect(within(drawer).getByTestId('evidence-effect')).toHaveTextContent('amd-58ad55e82e28')
    // Opening a drawer is not a read: everything in it arrived with the case.
    expect(backend.countOf(CASE_PATH)).toBe(before)
    stream.close()
  })

  it('shows an untouched promise as having caused nothing', async () => {
    const { stream } = mountAtCase({ [CASE_PATH]: () => json(SETTLED_CASE) })
    await userEvent.click(await screen.findByTestId('evidence-toggle'))
    await userEvent.click(screen.getByTestId('evidence-technical'))

    const row = screen
      .getAllByTestId('evidence-row')
      .find((entry) => entry.getAttribute('data-promise-id') === 'pr-e')!
    expect(within(row).getByText('none')).toBeInTheDocument()
    expect(row).toHaveTextContent('UNAFFECTED')
    stream.close()
  })
})

// --------------------------------------------------------------- reload, reconnect, navigation

describe('reload and reconnect', () => {
  it('mounting at a case address reads that case', async () => {
    const { stream, backend } = mountAtCase()

    await screen.findByTestId('case-workspace')
    expect(screen.getByTestId('case-workspace')).toHaveAttribute('data-case-id', CASE_ID)
    expect(backend.countOf(CASE_PATH)).toBe(1)
    stream.close()
  })

  it('a feed frame refetches the case being read', async () => {
    const { stream, backend } = mountAtCase()
    await screen.findByTestId('case-workspace')
    expect(backend.countOf(CASE_PATH)).toBe(1)

    backend.on(CASE_PATH, () => json(SETTLED_CASE))
    await stream.opened
    stream.push('domain', { type: 'track.recovered' }, 41)

    await waitFor(() => {
      expect(backend.countOf(CASE_PATH)).toBe(2)
    })
    expect(await screen.findByText('changed')).toBeInTheDocument()
    stream.close()
  })

  it('opening a case from the list puts it in the address bar', async () => {
    const { stream } = mount()

    await userEvent.click(await screen.findByText(/raspberry delivery/))

    await screen.findByTestId('case-workspace')
    expect(new URLSearchParams(window.location.search).get('case')).toBe(CASE_ID)
    stream.close()
  })

  it('leaving a case returns to the list and clears the address', async () => {
    const { stream } = mountAtCase()
    await screen.findByTestId('case-workspace')

    await userEvent.click(screen.getByRole('button', { name: /All cases/ }))

    expect(await screen.findByTestId('case-list')).toBeInTheDocument()
    expect(new URLSearchParams(window.location.search).get('case')).toBeNull()
    stream.close()
  })

  it('says so when there is no case rather than showing an empty workspace', async () => {
    const { stream } = mount({ '/api/cases': () => json(NO_CASES) })

    expect(await screen.findByText(/No case has been opened/)).toBeInTheDocument()
    expect(screen.queryByTestId('case-workspace')).not.toBeInTheDocument()
    stream.close()
  })
})
