/**
 * The two journeys the conversation surface exists for, through a real browser and a real stack.
 *
 *     browser -> Vite dev server -> FastAPI (as promisepatch_app) -> PostgreSQL -> worker
 *
 * Nothing here is mocked. The case is opened the way the product really opens one — a physical
 * report through the conversational surface — and everything after that happens in the browser,
 * over a session cookie the backend issued, against a case a separate worker process is moving.
 *
 * The two journeys are deliberately different in kind:
 *
 * - **A judge** arrives with nothing, presses one thing, and is looking at a real case. What they
 *   can then do is nothing, and the refusal is proved twice: the screen offers no control, and
 *   the endpoint behind the control that does not exist refuses their session anyway.
 * - **A worker** answers the open question and confirms the plan from inside the workspace, and
 *   what the screen says afterwards is the backend's own sentence about permission rather than
 *   about completion.
 */
import { expect, test, type Page } from '@playwright/test'
import {
  caseStatus,
  promisePatchAPI,
  reportCase,
  resetDemoState,
  waitForHeadline,
  workerCredentials,
} from './stack'

const credentials = workerCredentials()

const CANONICAL_REPORT = "today's raspberry delivery didn't arrive"
const RASPBERRY_ONLY = 'just raspberries - the strawberries came'

test.describe.configure({ mode: 'serial' })

let caseId: string

test.beforeAll(async () => {
  // A known base, then a real case on top of it. The reset is the operator action; the report
  // is the conversational surface's, because a case begins when somebody attests a fact.
  resetDemoState()
  caseId = await reportCase(CANONICAL_REPORT)
  await waitForHeadline(caseId, 'CLARIFYING')
})

async function signIn(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Worker').fill(credentials.username)
  await page.getByLabel('Password').fill(credentials.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Cases' })).toBeVisible()
}

/** The backend's refusal envelope, typed so a test reads a code rather than poking at `any`. */
interface Refusal {
  error: { code: string; message: string }
}

async function refusalCode(response: { json: () => Promise<unknown> }): Promise<string> {
  return ((await response.json()) as Refusal).error.code
}

/** The CSRF token the backend set on this browser, read the way the app reads it. */
async function csrfToken(page: Page): Promise<string> {
  const cookies = await page.context().cookies()
  const token = cookies.find((cookie) => cookie.name === 'pp_csrf')?.value
  expect(token, 'the backend set no CSRF cookie').toBeTruthy()
  return token as string
}

// ---------------------------------------------------------------------------- the judge

test('a judge reaches a real case in one action, with nothing typed', async ({ page }) => {
  await page.goto('/')

  await page.getByRole('button', { name: 'Look around a real case' }).click()

  const workspace = page.getByTestId('case-workspace')
  await expect(workspace).toBeVisible()
  // A case, not a list -- and the case id is in the address bar, so a reload returns to it.
  await expect(page).toHaveURL(/\?case=/)
  await expect(page.getByTestId('band-what-happened')).toBeVisible()
  await expect(page.getByTestId('untouched-proof')).toBeVisible()
  await expect(page.getByTestId('conversation-speech')).not.toBeEmpty()
})

test('a judge is offered no control that would change the case', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Look around a real case' }).click()
  await expect(page.getByTestId('case-workspace')).toBeVisible()

  await expect(page.getByTestId('conversation-read-only')).toBeVisible()
  await expect(page.getByTestId('conversation-confirm')).toHaveCount(0)
  await expect(page.getByLabel('answer in your own words')).toHaveCount(0)
})

test('a judge is refused by the domain even reaching past the screen', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Look around a real case' }).click()
  await expect(page.getByTestId('case-workspace')).toBeVisible()
  const before = await caseStatus(caseId)

  // Past the screen entirely, with this browser's own session and its own CSRF token: the
  // control the judge was not offered, called anyway. What refuses is the domain.
  const refused = await page.request.post('/api/conversation/clarify', {
    headers: { 'X-CSRF-Token': await csrfToken(page) },
    data: { command_id: crypto.randomUUID(), case_id: caseId, text: RASPBERRY_ONLY },
  })

  expect(refused.status()).toBe(403)
  expect(await refusalCode(refused)).toBe('CASE_NOT_PERMITTED')
  expect((await caseStatus(caseId)).headline).toBe(before.headline)
})

test('a judge holding no CSRF token is refused before the domain is asked', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Look around a real case' }).click()
  await expect(page.getByTestId('case-workspace')).toBeVisible()

  const refused = await page.request.post('/api/conversation/clarify', {
    data: { command_id: crypto.randomUUID(), case_id: caseId, text: RASPBERRY_ONLY },
  })

  expect(refused.status()).toBe(403)
  expect(await refusalCode(refused)).toBe('CSRF_TOKEN_INVALID')
})

test('the internal intent API is not published on the origin a browser is sent to', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Look around a real case' }).click()
  await expect(page.getByTestId('case-workspace')).toBeVisible()

  const refused = await page.request.post('/internal/intents/report', {
    headers: { 'X-CSRF-Token': await csrfToken(page) },
    data: { command_id: crypto.randomUUID(), text: CANONICAL_REPORT },
  })

  // Not a refusal by the intent API: the origin the browser is served from does not forward
  // `/internal` at all, so there is nothing there to refuse. The deployed stack says the same
  // thing with a Caddy rule; this is the local half of the same claim.
  expect(refused.status()).toBe(404)
})

test('a browser session is not a service token, at the API itself', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Look around a real case' }).click()
  await expect(page.getByTestId('case-workspace')).toBeVisible()

  // Straight at the API, where `/internal` genuinely is served, carrying this browser's own
  // session cookie -- cookies ignore ports, so it really does arrive. The two doors stay
  // separate: a cookie is not the credential this one wants.
  const refused = await page.request.post(`${promisePatchAPI()}/internal/intents/report`, {
    headers: { 'X-CSRF-Token': await csrfToken(page) },
    data: { command_id: crypto.randomUUID(), text: CANONICAL_REPORT },
  })

  expect(refused.status()).toBe(401)
  expect(await refusalCode(refused)).toBe('SERVICE_TOKEN_INVALID')
})

// --------------------------------------------------------------------------- the worker

test('a worker answers the open question from inside the workspace', async ({ page }) => {
  await signIn(page)
  await page.goto(`/?case=${caseId}`)
  await expect(page.getByTestId('case-workspace')).toBeVisible()

  await page.getByLabel('answer in your own words').fill(RASPBERRY_ONLY)
  await page.getByRole('button', { name: 'Send' }).click()

  // The backend's own receipt, verbatim, and nothing the screen wrote.
  await expect(page.getByTestId('conversation-reply')).toContainText(
    'Nothing has changed yet',
  )
  const planned = await waitForHeadline(caseId, 'PLANNED')
  expect(planned.awaiting_confirmation).toBe(true)
})

test('a worker confirms the plan, and the screen claims no completion', async ({ page }) => {
  const planned = await waitForHeadline(caseId, 'PLANNED')
  await signIn(page)
  await page.goto(`/?case=${caseId}`)
  await expect(page.getByTestId('conversation-confirm')).toBeVisible()

  await page.getByTestId('conversation-confirm').click()

  const reply = page.getByTestId('conversation-reply')
  await expect(reply).toContainText('Confirmed')
  await expect(reply).toContainText('Nothing has been changed yet')
  // A permission, not an outcome: what was confirmed is the plan that was read out.
  expect(planned.plan_id).toBeTruthy()
  const after = await caseStatus(caseId)
  expect(['WORKING', 'WAITING', 'SETTLED']).toContain(after.headline)
})

test('a confirmation quoting a plan the case has moved past is refused', async ({ page }) => {
  await signIn(page)
  await page.goto(`/?case=${caseId}`)
  await expect(page.getByTestId('case-workspace')).toBeVisible()

  const refused = await page.request.post('/api/conversation/confirm', {
    headers: { 'X-CSRF-Token': await csrfToken(page) },
    data: {
      command_id: crypto.randomUUID(),
      case_id: caseId,
      plan_id: '0000000000000000',
    },
  })

  expect(refused.status()).toBe(409)
  expect(['PLAN_SUPERSEDED', 'PLAN_NOT_CONFIRMABLE']).toContain(await refusalCode(refused))
})
