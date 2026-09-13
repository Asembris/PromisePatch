/**
 * Every resource quantity, pinned to the field it actually is.
 *
 * The engine keeps four numbers per ingredient apart on purpose, and two of them are one
 * careless heading away from meaning something else. `expected` is supply still owed by an open
 * commitment line — not an order, and emphatically not a delivery that arrived, because a
 * settled line contributes zero to it. `available_by` is a statement about a moment, and a
 * column headed "Available" invites a reader to take it as a stock level that will still be
 * true in an hour.
 *
 * So this suite asserts the *labels*, cell by cell, against the values the fixture put in each
 * field. A mislabelled column is a worse failure than a missing one: nothing on the screen
 * looks wrong, and somebody plans a bake against a figure that does not mean what they read.
 */
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { RESOURCES } from './fixtures'
import { IngredientTable } from '../src/features/live-ops/ResourcePanel'

/** The column position of each API field, taken from the heading's own marker. */
function columnOf(field: string): number {
  const headers = Array.from(document.querySelectorAll('th'))
  const index = headers.findIndex((header) => header.dataset.field === field)
  expect(index, `no column is marked as ${field}`).toBeGreaterThan(0)
  return index
}

function mount(): void {
  render(<IngredientTable ingredients={RESOURCES.ingredients} at={RESOURCES.at} />)
}

describe('the ingredient quantities', () => {
  it('puts each of the four figures under the heading for its own field', () => {
    mount()
    const raspberries = screen
      .getAllByTestId('ingredient-row')
      .find((row) => row.getAttribute('data-resource-id') === 'in-raspberry')!
    const cells = Array.from(raspberries.querySelectorAll('td'))
    const fixture = RESOURCES.ingredients.find((item) => item.id === 'in-raspberry')!

    for (const [field, value] of [
      ['on_hand', fixture.on_hand],
      ['expected', fixture.expected],
      ['reserved', fixture.reserved],
      ['available_by', fixture.available_by],
    ] as const) {
      expect(cells[columnOf(field)], field).toHaveTextContent(value!)
    }
  })

  it('names the horizon in the availability heading, not only in the panel around it', () => {
    mount()

    const heading = document.querySelector('th[data-field="available_by"]')!

    // The panel's subtitle can be scrolled away from, cropped out of a video frame, or simply
    // not read. The column that carries the figure says what moment it is about.
    expect(heading.textContent).toMatch(/^Available by /)
    expect(heading.textContent).not.toBe('Available')
  })

  it('does not call still-owed supply a delivery, an order or an arrival', () => {
    mount()

    const heading = document.querySelector('th[data-field="expected"]')!

    expect(heading).toHaveTextContent('Still expected')
    for (const wrong of ['Delivered', 'Ordered', 'Received', 'Arrived', 'Incoming']) {
      expect(heading.textContent).not.toContain(wrong)
    }
  })

  it('keeps a reserved quantity out of the availability column', () => {
    mount()
    const raspberries = screen
      .getAllByTestId('ingredient-row')
      .find((row) => row.getAttribute('data-resource-id') === 'in-raspberry')!

    // 3.2 reserved, -2.7 available by the horizon. Two different facts about one ingredient,
    // and the row shows each of them once, in its own column.
    expect(within(raspberries).getByTestId('reserved')).toHaveTextContent('3.2')
    expect(within(raspberries).getByTestId('available-by')).toHaveTextContent('-2.7')
    expect(within(raspberries).getByTestId('available-by')).not.toHaveTextContent('3.2')
  })

  it('labels an unknown quantity as unknown in every one of the four columns', () => {
    mount()
    const vanilla = screen
      .getAllByTestId('ingredient-row')
      .find((row) => row.getAttribute('data-resource-id') === 'in-vanilla')!

    for (const cell of ['on-hand', 'expected', 'reserved', 'available-by']) {
      expect(within(vanilla).getByTestId(cell)).toHaveTextContent('unknown')
    }
  })
})
