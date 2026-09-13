/**
 * A worker with nothing open yet, saying what happened, through the browser.
 *
 * Until this existed the only way to start a case on the web surface was to have one already:
 * the workspace could answer and confirm, and the thing a baker actually does first — walk in and
 * say the delivery did not arrive — had nowhere to happen. So this is the whole of the worker's
 * `NO_CASE` phase, proved end to end against the real stack:
 *
 *     browser -> Vite dev server -> FastAPI (session, CSRF) -> PostgreSQL -> worker
 *
 * Three claims, and each fails differently:
 *
 * - **It is the real route.** The case that appears afterwards is read back from the API and its
 *   stored sentence is compared byte for byte with what was typed. A screen that tidied the words
 *   on the way in would be editing a physical attestation, and this is what catches it.
 * - **The actor is the server's.** The case records `maya` because the session says so. Nothing
 *   in the browser named her.
 * - **A judge is offered none of it.** The observer's landing surface carries no report control,
 *   and the route refuses their session anyway — the refusal is the domain's, not a hidden
 *   button's.
 */
import { expect, test, type Page } from '@playwright/test'
import { workerCredentials } from './stack'

const credentials = workerCredentials()

const SPOKEN = "the oven in the back is out, it won't hold temperature"

test.describe.configure({ mode: 'serial' })

async function signIn(page: Page): Promise<void> {
  await page.goto('/')
  await page.getByLabel('Worker').fill(credentials.username)
  await page.getByLabel('Password').fill(credentials.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Cases' })).toBeVisible()
}

interface StoredCase {
  reported_text: string | null
  reported_by: string | null
  case_id: string
}

test('a worker with no case open reports what happened, and the case is the backend’s', async ({
  page,
}) => {
  await signIn(page)

  const entry = page.getByTestId('report-entry')
  await expect(entry).toBeVisible()
  await page.getByTestId('report-text').fill(SPOKEN)
  await page.getByTestId('report-send').click()

  // The case id in the address bar is the one the backend derived. Nothing was opened before it.
  await expect(page).toHaveURL(/\?case=/)
  const caseId = new URL(page.url()).searchParams.get('case')
  expect(caseId).toBeTruthy()
  await expect(page.getByTestId('case-workspace')).toBeVisible()

  // Read back from the API, past the screen: the stored sentence is the typed one, and the
  // worker it is attributed to is the session's rather than anything the browser sent.
  const stored = (await (await page.request.get(`/api/cases/${caseId}`)).json()) as StoredCase
  expect(stored.reported_text).toBe(SPOKEN)
  expect(stored.reported_by).toBe(credentials.username)

  // Band 1 quotes it, unedited, which is what it will go on quoting for the life of the case.
  await expect(page.getByTestId('band-what-happened')).toContainText(SPOKEN)
})

test('the landing surface offers a judge no way to report anything', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Look around a real case' }).click()
  await expect(page.getByTestId('case-workspace')).toBeVisible()

  // Back to the surface that carries the control, as the observer.
  await page.getByRole('button', { name: '← All cases' }).click()
  await expect(page.getByRole('heading', { name: 'Cases' })).toBeVisible()

  await expect(page.getByTestId('report-entry')).toHaveCount(0)
  await expect(page.getByTestId('report-send')).toHaveCount(0)
})

test('a judge reaching past the screen is refused the report by the domain', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Look around a real case' }).click()
  await expect(page.getByTestId('case-workspace')).toBeVisible()

  const cookies = await page.context().cookies()
  const csrf = cookies.find((cookie) => cookie.name === 'pp_csrf')?.value
  expect(csrf, 'the backend set no CSRF cookie').toBeTruthy()

  const refused = await page.request.post('/api/conversation/report', {
    headers: { 'X-CSRF-Token': csrf as string },
    data: { command_id: crypto.randomUUID(), text: SPOKEN },
  })

  expect(refused.status()).toBe(403)
  const body = (await refused.json()) as { error: { code: string } }
  expect(body.error.code).toBe('CASE_NOT_PERMITTED')
})
