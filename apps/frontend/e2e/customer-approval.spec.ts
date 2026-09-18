/**
 * The whole loop, in a real browser: worker reports, customer answers, recovery follows.
 *
 *     worker's browser -> API -> PostgreSQL -> worker process -> outbox
 *       -> customer's browser (a signed link, no session) -> inbox
 *       -> worker process (sender check, deadline, literal parser) -> decision
 *       -> revalidation -> order system -> worker's browser again
 *
 * Nothing here is mocked and nothing is arranged that the product would not do. The case is
 * opened by a physical report, the plan is confirmed by a signed-in worker pressing the
 * control, and the answer is given by somebody who has no account and never had one.
 *
 * Three things make this worth running as a browser test rather than only as an API test.
 *
 * **The customer's context is genuinely separate.** They are driven in a second browser
 * context with no storage and no cookies, so nothing the worker's session holds is available
 * to them. What opens the page is the link and only the link.
 *
 * **The link is read where the message went.** `approvalLink()` reads the outbox row queued
 * for the customer's own channel, because that is the only place it exists — there is no
 * worker screen showing it and no endpoint that hands one out. A spec that could ask the
 * product for a link would be proving a product in which possession means nothing.
 *
 * **The two screens are checked against each other.** The customer is told their answer is
 * kept and then what happened; the worker is shown the product's own word for the same thing.
 * Neither is allowed to be ahead of the rows.
 */
import { expect, test, type Page, type Browser } from '@playwright/test'
import {
  answerClarification,
  caseStatus,
  reportCase,
  resetDemoState,
  resetOrderSystem,
  waitForApprovalLink,
  waitForHeadline,
  workerCredentials,
} from './stack'

const credentials = workerCredentials()

const CANONICAL_REPORT = "today's raspberry delivery didn't arrive"
const RASPBERRY_ONLY = 'just raspberries - the strawberries came'

test.describe.configure({ mode: 'serial' })

let caseId: string
let link: string

test.beforeAll(async () => {
  // Both systems, because they are two systems. Resetting PromisePatch alone puts its mirror
  // back at version 1 while the order system still holds whatever a previous run amended it
  // to, and the amendment this spec is waiting for is then refused as a stale version -- a
  // true refusal about an untrue arrangement.
  resetOrderSystem()
  resetDemoState()
  caseId = await reportCase(CANONICAL_REPORT)
  await waitForHeadline(caseId, 'CLARIFYING')
  await answerClarification(caseId, RASPBERRY_ONLY)
  await waitForHeadline(caseId, 'PLANNED')
})

async function signIn(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Worker').fill(credentials.username)
  await page.getByLabel('Password').fill(credentials.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Cases' })).toBeVisible()
}

/**
 * A browser that has never been to this site.
 *
 * The point of the spec: no cookie, no local storage, nothing carried over from the worker.
 * If the customer's page worked only because a worker's session happened to be lying around,
 * this is what would catch it.
 */
async function strangerPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ storageState: undefined })
  return context.newPage()
}

/** The path and query of a link, so it can be opened against Playwright's own `baseURL`. */
function linkPath(url: string): string {
  const parsed = new URL(url)
  return `${parsed.pathname}${parsed.search}`
}

// ------------------------------------------------------------------- the worker asks

test('a worker confirms the plan, and a customer is asked', async ({ page }) => {
  await signIn(page)
  await page.goto(`/?case=${caseId}`)
  await expect(page.getByTestId('conversation-confirm')).toBeVisible()

  await page.getByTestId('conversation-confirm').click()

  await expect(page.getByTestId('conversation-reply')).toContainText('Confirmed')
  // The message is queued to the customer's channel by the worker process, and the link rides
  // with it. Waiting for it is waiting for the product's own asynchrony, not for a timer.
  link = await waitForApprovalLink()
  expect(link).toContain('approve=')
})

// ------------------------------------------------------------------- the customer answers

test('a stranger holding the link sees the exact change and nothing else', async ({ browser }) => {
  const page = await strangerPage(browser)

  await page.goto(linkPath(link))

  const view = page.getByTestId('customer-approval')
  await expect(view).toHaveAttribute('data-phase', 'OPEN')
  await expect(page.getByTestId('proposed-change')).toBeVisible()
  // No price anywhere, because PromisePatch holds none. A page with a money line would be
  // showing a number nothing in this system computed.
  await expect(page.locator('body')).not.toContainText(/price/i)
  // And no sign-in: there is no account behind a bakery customer, and offering one would be
  // asking for something that does not exist.
  await expect(page.getByRole('button', { name: 'Sign in' })).toHaveCount(0)
  await page.close()
})

test('the answer is recorded, and the page does not claim a decision before there is one', async ({
  browser,
}) => {
  const page = await strangerPage(browser)
  await page.goto(linkPath(link))
  await expect(page.getByTestId('customer-approval')).toHaveAttribute('data-phase', 'OPEN')

  await page.getByRole('button', { name: 'Approve this change' }).click()

  // Whatever the page says next, it may not be a decision it has not been told about. Both
  // `RECEIVED` and `APPROVED` are truthful readings depending on how fast the worker got
  // there; neither is written by the browser.
  const view = page.getByTestId('customer-approval')
  await expect(view).not.toHaveAttribute('data-phase', 'OPEN')
  await expect(view).toHaveAttribute('data-phase', /RECEIVED|APPROVED/)
  await page.close()
})

test('the page settles on the decision the protocol wrote, with the real outcome', async ({
  browser,
}) => {
  await waitForHeadline(caseId, 'SETTLED')
  const page = await strangerPage(browser)

  await page.goto(linkPath(link))

  await expect(page.getByTestId('customer-approval')).toHaveAttribute('data-phase', 'APPROVED')
  await expect(page.getByText('You approved this change')).toBeVisible()
  await expect(page.getByTestId('outcome-sentence')).toBeVisible()
  // The question is over: a settled page offers nothing to press.
  await expect(page.getByRole('button', { name: 'Approve this change' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Decline' })).toHaveCount(0)
  await page.close()
})

test('pressing again changes nothing', async ({ browser }) => {
  const page = await strangerPage(browser)
  const token = new URL(link).searchParams.get('approve')
  expect(token).toBeTruthy()

  // Straight at the endpoint, because a settled page offers no control to press twice. This is
  // the replay a retrying phone or a re-opened tab performs, and it is answered rather than
  // refused: the record was already stored, so saying so is the truth. A decline arriving here
  // now would write nothing at all -- the id is derived from the request and the channel, not
  // from the answer, so the database has it already.
  const replayed = await page.request.post(`/api/customer/approval/${token}`, {
    data: { answer: 'DECLINE' },
    failOnStatusCode: false,
  })
  expect(replayed.status()).toBe(200)
  expect(((await replayed.json()) as { phase: string }).phase).toBe('APPROVED')

  expect((await caseStatus(caseId)).headline).toBe('SETTLED')
  await page.close()
})

// ------------------------------------------------------------------- the worker is told

test('the worker workspace tells the truth about what the customer did', async ({ page }) => {
  await signIn(page)

  await page.goto(`/?case=${caseId}`)

  await expect(page.getByTestId('case-workspace')).toBeVisible()
  // The product's own vocabulary for a promise whose customer said yes and whose order then
  // carried the change. Printed by the backend; the screen holds no synonym for it.
  await expect(page.getByTestId('case-workspace')).toContainText('changed')
})

test('the promises the exception never reached are still untouched afterwards', async ({
  page,
}) => {
  await signIn(page)

  await page.goto(`/?case=${caseId}`)

  const proof = page.getByTestId('untouched-proof')
  await expect(proof).toBeVisible()
  // The one number on this screen that was counted rather than asserted. A customer answering
  // on a web page must not have caused an effect on a promise nothing reached.
  await expect(proof).toHaveAttribute('data-effects', '0')
})
