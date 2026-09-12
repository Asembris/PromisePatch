/**
 * The whole stack, through a real browser.
 *
 *     browser -> Vite dev server -> FastAPI (as promisepatch_app) -> PostgreSQL
 *
 * Nothing here is mocked. There is no route interception, no stubbed fetch and no fixture
 * JSON: every number on the screen came out of a migrated database that `pp reset-demo-state`
 * seeded, through the read APIs, over a session cookie the backend issued. The suite is
 * deliberately small -- it is proof that the parts are connected, not a second copy of the
 * component tests, which already cover rendering in isolation.
 */
import { expect, test, type Page } from '@playwright/test'
import { resetDemoState, workerCredentials } from './stack'

const credentials = workerCredentials()

/** The Hollow Oak order book: promises A through F. */
const EXPECTED_PROMISES = 6

test.describe.configure({ mode: 'serial' })

async function signIn(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Worker').fill(credentials.username)
  await page.getByLabel('Password').fill(credentials.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByTestId('case-list')).toBeVisible()
}

/**
 * Ask for the order book.
 *
 * A signed-in worker lands on the cases now; the order book is the context underneath them.
 * The reads are unchanged — the hooks run on mount either way — so what follows still proves
 * the same path from the browser to PostgreSQL, one click further in.
 */
async function openOrderContext(page: Page): Promise<void> {
  await page.getByTestId('order-context').click()
  await expect(page.getByRole('heading', { name: 'Customer promises' })).toBeVisible()
}

test('a signed-in worker sees the order book the database holds', async ({ page }) => {
  await signIn(page)
  await openOrderContext(page)

  await expect(page.getByText(credentials.username, { exact: false }).first()).toBeVisible()
  await expect(page.getByTestId('promise-row')).toHaveCount(EXPECTED_PROMISES)

  // The resource panels are read from the same transaction as the order book; asserting they
  // are populated is asserting the second read path works, not re-testing the first.
  // `not.toHaveCount(0)` rather than a counted assertion: the panels are a separate query and
  // land a moment later, and a bare `count()` would read whatever was on screen at the time.
  await expect(page.getByTestId('ingredient-row')).not.toHaveCount(0)
  await expect(page.getByTestId('equipment-row')).not.toHaveCount(0)
})

test('a shortfall reaches the screen as a shortfall', async ({ page }) => {
  await signIn(page)
  await openOrderContext(page)

  // Negative availability is the one number a well-meaning UI is most likely to quietly clamp
  // to zero, and clamping it would hide the exact condition this product exists to surface.
  // The assertion is that a negative figure survives the whole path, not that it is any
  // particular figure: the fixture's quantities are the fixture's business.
  const rows = page.getByTestId('ingredient-row')
  // Wait for the panel before reading it. `allInnerTexts` does not wait, and an empty list
  // would satisfy "every value is a number" and fail "one of them is negative" -- which is a
  // loading race wearing the costume of a real regression.
  await expect(rows).not.toHaveCount(0)

  const values = (await rows.getByTestId('available-by').allInnerTexts()).map((text) =>
    Number.parseFloat(text.trim()),
  )
  expect(values.every((value) => Number.isFinite(value))).toBe(true)
  expect(values.some((value) => value < 0)).toBe(true)
})

test('the event stream reaches live over the real backend', async ({ page }) => {
  await signIn(page)

  // `live` is only ever set by the stream itself: on the open, or on a frame. Reaching it
  // means an authenticated `text/event-stream` response is open through the dev server proxy
  // and the API's session auth, which no amount of successful read requests would show.
  await expect(page.getByTestId('stream-status')).toHaveAttribute('data-status', 'live')
})

test('an operator reset reaches the browser and returns it to the sign-in screen', async ({
  page,
}) => {
  await signIn(page)
  await expect(page.getByTestId('stream-status')).toHaveAttribute('data-status', 'live')

  // The reset is the system's only durable-event producer today, and it is destructive by
  // design: it recreates the fixture workers, which revokes every live session. So the honest
  // end-to-end assertion is the whole chain, not a pretty one --
  //
  //     reset -> domain event -> NOTIFY -> listener -> SSE frame -> refetch -> 401 -> login
  //
  // Returning to the sign-in screen is proof the frame arrived: the reads are cached for a
  // minute, polling is switched off, and the browser is never focused, so nothing else in the
  // application would have asked the API anything.
  resetDemoState()

  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible({ timeout: 60_000 })
  await expect(page.getByTestId('case-row')).toHaveCount(0)
})
