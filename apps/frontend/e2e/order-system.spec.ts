/**
 * Proof A, in a browser, across two systems.
 *
 * The point of this file is what a judge sees rather than what an assertion computes: one
 * window belongs to the External Order System, a person changes an order in it, and PromisePatch
 * — which never sees that window and shares no storage with it — ends up describing the changed
 * order. If these two applications shared a table, the middle step of this test would be
 * impossible to write.
 *
 * It is deterministic without sleeping. The order system's own screen shows each event's
 * delivery state, so "the webhook got there" is something to wait *for* rather than to hope has
 * happened by now; and PromisePatch's mirror is read back through its API, which is the state
 * every later decision is made from.
 */
import { expect, test } from '@playwright/test'

import {
  orderSystemURL,
  promisePatchAPI,
  resetDemoState,
  resetOrderSystem,
  workerCredentials,
} from './stack'

interface MirroredLine {
  recipe_version: { id: string }
}

interface MirroredPromise {
  external_id: string
  external_version: number
  lines: MirroredLine[]
}

interface PromisesResponse {
  promises: MirroredPromise[]
}

interface ExternalOrder {
  version: number
  lines: { external_line_id: string; external_item_id: string }[]
}

const LENA_ORDER = 'EXT-D'
const LENA_LINE = 'ol-d'
const RASPBERRY_LEMON = 'rv-raspberry-lemon-2'
const LEMON_CURD = 'rv-lemon-curd-1'

test.describe.configure({ mode: 'serial' })

test.beforeAll(() => {
  // Both, and in this order. Each system's reset is its own, and neither tells the other: an
  // order system put back to version 1 beside a mirror still at version 2 is two systems that
  // disagree, and the next change would arrive looking like an event that had been overtaken.
  // Resetting the mirror first and the order system second leaves both at the seeded book.
  resetDemoState()
  resetOrderSystem()
})

test('the order system is visibly a different system', async ({ page }) => {
  await page.goto(orderSystemURL())

  await expect(page).toHaveTitle(/External Order System/)
  await expect(page.getByRole('heading', { name: /External Order System/i })).toBeVisible()
  await expect(page.getByText('Source of truth for demo order state')).toBeVisible()
  // Said out loud on the page itself, so nobody watching has to take it on trust.
  await expect(page.getByText(/not Square/i)).toBeVisible()
})

test('an operator changes an order, and PromisePatch ends up describing the change', async ({
  page,
  request,
}) => {
  await page.goto(orderSystemURL())

  const row = page.locator(`tr[data-order-row="${LENA_ORDER}"]`)
  await expect(row).toContainText('Lena Fischer')
  await expect(row).toContainText(RASPBERRY_LEMON)

  const versionBefore = Number(await row.locator('td.version').innerText())

  await row.getByRole('combobox').selectOption(LEMON_CURD)
  await row.getByRole('button', { name: 'Change item' }).click()

  // The order system's own account of what it did: a new version, and an event on its way out.
  const changed = page.locator(`tr[data-order-row="${LENA_ORDER}"]`)
  await expect(changed).toContainText(LEMON_CURD)
  await expect
    .poll(async () => Number(await changed.locator('td.version').innerText()))
    .toBe(versionBefore + 1)

  await expect
    .poll(
      async () => {
        await page.reload()
        return page.locator('[data-delivery-state]').first().innerText()
      },
      { message: 'the order event was never delivered to PromisePatch', timeout: 30_000 },
    )
    .toContain('DELIVERED')

  // And PromisePatch's own account, read from PromisePatch. Nothing in this block touched it.
  const { username, password } = workerCredentials()
  const login = await request.post(`${promisePatchAPI()}/api/auth/login`, {
    data: { username, password },
    headers: { Origin: 'http://localhost:55173' },
  })
  expect(login.ok()).toBeTruthy()

  await expect
    .poll(
      async () => {
        const response = await request.get(`${promisePatchAPI()}/api/promises`)
        if (!response.ok()) return null
        const body = (await response.json()) as PromisesResponse
        const promise = body.promises.find((entry) => entry.external_id === LENA_ORDER)
        return promise?.lines[0]?.recipe_version.id ?? null
      },
      {
        message: 'the mirrored order line never caught up with the order system',
        timeout: 30_000,
      },
    )
    .toBe(LEMON_CURD)
})

test('the change survives being read back from the order system itself', async ({ request }) => {
  const response = await request.get(`${orderSystemURL()}/orders/${LENA_ORDER}`)

  expect(response.ok()).toBeTruthy()
  const order = (await response.json()) as ExternalOrder
  expect(order.lines[0].external_line_id).toBe(LENA_LINE)
  expect(order.lines[0].external_item_id).toBe(LEMON_CURD)
})
