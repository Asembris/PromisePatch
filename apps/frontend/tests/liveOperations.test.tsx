/**
 * What the screen must show, and what it must never invent.
 *
 * The negative assertions carry as much weight as the positive ones. A screen that renders an
 * unknown quantity as `0`, or clamps a shortfall to zero, or sorts the order book into an
 * order the backend did not choose, is not a display problem — it is the UI disagreeing with
 * the engine about what is true.
 */
import { describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import { CASES } from './caseFixtures'
import { MAYA, PROMISES, RESOURCES } from './fixtures'
import { FakeStream, apiError, json, mockBackend, renderApp, streamResponse } from './harness'

function mountSignedIn(): FakeStream {
  const stream = new FakeStream()
  mockBackend({
    '/api/auth/me': () => json(MAYA),
    '/api/promises': () => json(PROMISES),
    '/api/resources': () => json(RESOURCES),
    '/api/cases': () => json(CASES),
    '/events': () => streamResponse(stream),
  })
  renderApp()
  return stream
}

describe('promises', () => {
  it('renders every row the API returned, in the API order', async () => {
    const stream = mountSignedIn()
    await screen.findByText('Amara Fell')

    const rows = screen.getAllByTestId('promise-row')
    expect(rows).toHaveLength(6)
    expect(rows.map((row) => row.getAttribute('data-promise-id'))).toEqual([
      'pr-a',
      'pr-b',
      'pr-c',
      'pr-d',
      'pr-e',
      'pr-f',
    ])
    stream.close()
  })

  it('shows the pinned recipe version and its author', async () => {
    const stream = mountSignedIn()
    await screen.findByText('Amara Fell')

    const rowA = screen.getAllByTestId('promise-row')[0]!
    expect(within(rowA).getByText('Raspberry Lemon Layer')).toBeInTheDocument()
    expect(within(rowA).getByText('v2')).toBeInTheDocument()
    expect(within(rowA).getByText('by jo')).toBeInTheDocument()
    stream.close()
  })

  it('shows production task state', async () => {
    const stream = mountSignedIn()
    await screen.findByText('Caleb North')

    const rowC = screen.getAllByTestId('promise-row')[2]!
    expect(within(rowC).getByText('STARTED')).toBeInTheDocument()
    stream.close()
  })

  it('shows an unscheduled task as unknown rather than as a zero or a blank', async () => {
    const stream = mountSignedIn()
    await screen.findByText('Lena Okoye')

    const rowD = screen.getAllByTestId('promise-row')[3]!
    // Start, end, equipment name and the reserved quantity are all null on this fixture row.
    expect(within(rowD).getAllByText('unknown').length).toBeGreaterThanOrEqual(4)
    expect(within(rowD).queryByText('0')).not.toBeInTheDocument()
    stream.close()
  })

  it('says "no open case" for a promise no case has touched, and never "UNAFFECTED"', async () => {
    const stream = mountSignedIn()
    await screen.findByText('Amara Fell')

    const rows = screen.getAllByTestId('promise-row')
    expect(within(rows[0]!).getByText('no open case')).toBeInTheDocument()
    expect(screen.queryByText('UNAFFECTED')).not.toBeInTheDocument()

    // The one promise a case did reach shows the persisted classification verbatim.
    const rowF = rows[5]!
    expect(within(rowF).getByText('BLOCKED')).toBeInTheDocument()
    expect(within(rowF).getByText('ESCALATED')).toBeInTheDocument()
    stream.close()
  })

  it('reports a failed read without exposing anything internal', async () => {
    const stream = new FakeStream()
    mockBackend({
      '/api/auth/me': () => json(MAYA),
      '/api/promises': () => apiError(500, 'INTERNAL_ERROR', 'quote the correlation id'),
      '/api/resources': () => json(RESOURCES),
    '/api/cases': () => json(CASES),
      '/events': () => streamResponse(stream),
    })
    renderApp()

    expect(
      await screen.findByText(/The order book could not be loaded/, undefined, { timeout: 8000 }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/correlation id/)).not.toBeInTheDocument()
    stream.close()
  })
})

describe('resources', () => {
  it('renders ingredients and equipment in separate sections', async () => {
    const stream = mountSignedIn()
    await screen.findByText('Raspberries')

    const ingredients = screen.getAllByTestId('ingredient-row')
    const equipment = screen.getAllByTestId('equipment-row')
    expect(ingredients).toHaveLength(2)
    expect(equipment).toHaveLength(2)
    // Separate sections, not one merged list: neither kind appears among the other's rows.
    expect(ingredients.map((row) => row.getAttribute('data-resource-id'))).toEqual([
      'in-raspberry',
      'in-vanilla',
    ])
    expect(equipment.map((row) => row.getAttribute('data-resource-id'))).toEqual([
      'eq-deck-oven',
      'eq-convection',
    ])
    expect(within(equipment[1]!).getByText('Convection oven')).toBeInTheDocument()
    stream.close()
  })

  it('keeps a negative availability visible and unclamped', async () => {
    const stream = mountSignedIn()
    await screen.findByText('Raspberries')

    const raspberries = screen
      .getAllByTestId('ingredient-row')
      .find((row) => row.getAttribute('data-resource-id') === 'in-raspberry')!
    expect(within(raspberries).getByTestId('available-by')).toHaveTextContent('-2.7')
    stream.close()
  })

  it('renders the backend decimal strings verbatim rather than reformatted numbers', async () => {
    const stream = mountSignedIn()
    await screen.findByText('Raspberries')

    const raspberries = screen
      .getAllByTestId('ingredient-row')
      .find((row) => row.getAttribute('data-resource-id') === 'in-raspberry')!
    expect(within(raspberries).getByTestId('on-hand')).toHaveTextContent('0.5')
    expect(within(raspberries).getByTestId('reserved')).toHaveTextContent('3.2')
    stream.close()
  })

  it('renders an unknown quantity as unknown and never as zero', async () => {
    const stream = mountSignedIn()
    await screen.findByText('Raspberries')

    const vanilla = screen
      .getAllByTestId('ingredient-row')
      .find((row) => row.getAttribute('data-resource-id') === 'in-vanilla')!
    for (const cell of ['on-hand', 'expected', 'reserved', 'available-by']) {
      expect(within(vanilla).getByTestId(cell)).toHaveTextContent('unknown')
      expect(within(vanilla).getByTestId(cell)).not.toHaveTextContent('0')
    }
    stream.close()
  })

  it('shows an outage with no recorded end as open-ended', async () => {
    const stream = mountSignedIn()
    await screen.findByText('Raspberries')

    const deckOven = screen
      .getAllByTestId('equipment-row')
      .find((row) => row.getAttribute('data-resource-id') === 'eq-deck-oven')!
    expect(within(deckOven).getByText('OUT_OF_SERVICE')).toBeInTheDocument()
    expect(within(deckOven).getByText('— no end recorded')).toBeInTheDocument()
    stream.close()
  })
})
