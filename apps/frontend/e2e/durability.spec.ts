/**
 * What survives, and what the screen is allowed to claim while it is not surviving.
 *
 * Two properties, both of them things a screen can fake and this one may not.
 *
 * **The case is in the address bar, and the address bar is the only place it is.** There is no
 * client-side cache of a case to restore, so a reload, a restored tab and a second browser are
 * three cold requests for the same durable row, and all three must land on it. A product whose
 * demo dies when somebody refreshes the page has not deployed a case; it has rendered one.
 *
 * **A feed that is not open must stop the screen saying it is live.** The one failure the
 * freshness contract names is a stale screen that looks current: the reads are authoritative,
 * the stream only tells them when to run again, and an indicator that kept saying `live` with
 * nothing behind it would be asserting the freshness it had just lost. The case stays on the
 * screen -- it is not wrong, it is only no longer known to be current -- and the indicator says
 * so.
 *
 * Nothing here is mocked. The feed is refused at the network rather than faked in the client,
 * and the reads behind the screen are the real ones throughout.
 */
import { expect, test, type Page } from '@playwright/test'
import { analysedCase, lookAroundRealCase } from './stack'

const CANONICAL_REPORT = "today's raspberry delivery didn't arrive"
const RASPBERRY_ONLY = 'just raspberries - the strawberries came'

test.describe.configure({ mode: 'serial' })

test.beforeAll(async () => {
  // Arrangement only: a case far enough along that the bands have something in them. Which
  // case the judge entry then opens is the backend's choice, and these tests are about the
  // case they land on rather than about a case chosen here.
  await analysedCase(CANONICAL_REPORT, RASPBERRY_ONLY)
})

/** Arrive the way a judge arrives: one press, no credentials. */
async function lookAround(page: Page): Promise<void> {
  await lookAroundRealCase(page)
}

/** The case the address bar names. */
function openCase(page: Page): string | null {
  return new URL(page.url()).searchParams.get('case')
}

test('a reload lands on the same durable case', async ({ page }) => {
  await page.goto('/')
  await lookAround(page)
  const opened = openCase(page)
  expect(opened).toBeTruthy()
  const sentence = await page.getByTestId('band-what-happened').innerText()

  await page.reload()

  await expect(page.getByTestId('case-workspace')).toBeVisible()
  expect(openCase(page)).toBe(opened)
  expect(await page.getByTestId('band-what-happened').innerText()).toBe(sentence)
})

test('a restored tab lands on the same durable case', async ({ page, context }) => {
  await page.goto('/')
  await lookAround(page)
  const opened = openCase(page)
  const sentence = await page.getByTestId('band-what-happened').innerText()

  // A tab the browser restores is a cold request for a remembered address, in a session that
  // was already there. Nothing is carried across in memory.
  const restored = await context.newPage()
  await restored.goto(`/?case=${opened}`)

  await expect(restored.getByTestId('case-workspace')).toBeVisible()
  expect(openCase(restored)).toBe(opened)
  expect(await restored.getByTestId('band-what-happened').innerText()).toBe(sentence)
  await restored.close()
})

test('a second browser, with a session of its own, lands on the same durable case', async ({
  page,
  browser,
}) => {
  await page.goto('/')
  await lookAround(page)
  const opened = openCase(page)
  const sentence = await page.getByTestId('band-what-happened').innerText()

  // A different browser: no cookie, no storage, nothing in common but the link.
  const elsewhere = await browser.newContext()
  const second = await elsewhere.newPage()
  await second.goto(`/?case=${opened}`)
  await lookAround(second)

  expect(openCase(second)).toBe(opened)
  expect(await second.getByTestId('band-what-happened').innerText()).toBe(sentence)
  await elsewhere.close()
})

test('the feed opens, and the indicator is not a word written into the page', async ({ page }) => {
  await page.goto('/')
  await lookAround(page)

  await expect(page.getByTestId('stream-status')).toHaveAttribute('data-status', 'live')
})

test('a feed that cannot open leaves the case on screen and never claims to be live', async ({
  page,
}) => {
  // The stream refused at the network, which is what a dropped feed looks like to the client:
  // the connection is not there, and every read behind the screen still is.
  await page.route('**/events*', (route) => route.abort())

  await page.goto('/')
  await lookAround(page)

  // The case is rendered, because the reads are what make it correct and they are unaffected.
  await expect(page.getByTestId('band-what-happened')).toBeVisible()
  await expect(page.getByTestId('untouched-proof')).toBeVisible()
  // And the indicator does not say the feed is open. This is the one failure the freshness
  // contract names: a stale screen that looks current. The word above proves the same element
  // says `live` when a feed really is open, so this is a state and not a constant.
  await expect(page.getByTestId('stream-status')).not.toHaveAttribute('data-status', 'live')
})
