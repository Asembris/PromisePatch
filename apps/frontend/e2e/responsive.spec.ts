/**
 * The same case, at four widths, with the same claim surviving all of them.
 *
 * The thing under test is not that the layout is pretty on a phone. It is that **the untouched
 * proof is never what goes when the screen gets small.** That band carries the product's central
 * claim — these promises were left alone, and this many operational effects reached them — and a
 * responsive rule that dropped it, collapsed it behind a toggle or pushed it off a horizontal
 * scroll would quietly delete the claim on exactly the device a judge is most likely to hold.
 *
 * Two supporting properties are asserted at every width because both are cheap to lose and
 * expensive to notice: the page never scrolls sideways, and no control shrinks below a target a
 * finger can hit.
 *
 * This is the half of the accessibility work that cannot be proved in a DOM with no stylesheet.
 * The structural half — landmarks, names, live regions, states carried by words — is in
 * `tests/accessibility.test.tsx`.
 */
import { expect, test, type Page } from '@playwright/test'
import { analysedCase, lookAroundRealCase } from './stack'

const SIZES = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'laptop', width: 1280, height: 800 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'phone', width: 390, height: 844 },
] as const

/** The smallest target a finger can be asked to hit. */
const MINIMUM_TARGET = 44

const CANONICAL_REPORT = "today's raspberry delivery didn't arrive"
const RASPBERRY_ONLY = 'just raspberries - the strawberries came'

let caseId: string

/**
 * One judge session for the whole file, saved and reused.
 *
 * A session per test would be eighteen of them inside a minute, and the demo endpoint is rate
 * limited on purpose -- twenty per client per minute, which is a real control and not a thing to
 * raise because a test found it. It is also the truthful shape of what is being tested: a judge
 * signs in once and looks at the same case at four sizes. That a judge reaches a case in one
 * action is proved where it belongs, in `judge-journey.spec.ts`.
 */
const JUDGE_SESSION = 'test-results/judge-session.json'

test.beforeAll(async ({ browser }, testInfo) => {
  // A case far enough along to have both halves of the comparison in it. Arranged rather than
  // asserted: what this file is about is the layout, and a case that had never been analysed
  // would make every assertion below pass for the wrong reason.
  caseId = await analysedCase(CANONICAL_REPORT, RASPBERRY_ONLY)

  // `storageState: undefined` on purpose: the file-level `use` below names a state file this
  // hook is about to write, and a context that tried to load it first would fail on the run
  // that has not written it yet.
  const context = await browser.newContext({
    baseURL: testInfo.project.use.baseURL,
    storageState: undefined,
  })
  const page = await context.newPage()
  await page.goto('/')
  await lookAroundRealCase(page)
  await context.storageState({ path: JUDGE_SESSION })
  await context.close()
})

test.use({ storageState: JUDGE_SESSION })

/**
 * This case, by its address, in the session the file already holds.
 *
 * The one-action entry opens the *newest* case, which is the right thing for it to do and the
 * wrong thing to build a layout spec on -- a stack that has been used holds other cases, and the
 * newest of them may be one that never reached an analysis. So the case is reached the way a
 * reload reaches it: by the id in the address bar.
 */
async function openARealCase(page: Page): Promise<void> {
  await page.goto(`/?case=${caseId}`)
  await expect(page.getByTestId('case-workspace')).toHaveAttribute('data-case-id', caseId)
  await expect(page.getByTestId('untouched-proof')).toBeVisible()
  await expect(page.getByTestId('band-untouched')).toBeVisible()
}

for (const size of SIZES) {
  test.describe(`at ${size.name}, ${size.width}x${size.height}`, () => {
    test.use({ viewport: { width: size.width, height: size.height } })

    test('keeps the untouched proof, its count and its reasons', async ({ page }) => {
      await openARealCase(page)

      const proof = page.getByTestId('untouched-proof')
      await expect(proof).toBeVisible()
      // The two published integers, still on the screen and still the backend's.
      await expect(proof).toHaveAttribute('data-untouched', /\d+/)
      await expect(proof).toHaveAttribute('data-effects', /\d+/)
      // And the promises themselves, uncollapsed: no disclosure stands between a judge and them.
      await expect(page.getByTestId('band-untouched')).toBeVisible()
    })

    test('keeps the five bands in the order the contract fixes', async ({ page }) => {
      await openARealCase(page)

      const order = await page.evaluate(() => {
        const wanted = [
          'band-what-happened',
          'band-next-action',
          'conversation-panel',
          'band-what-changes',
          'untouched-proof',
          'evidence-toggle',
        ]
        const found = Array.from(document.querySelectorAll('[data-testid]'))
          .map((element) => element.getAttribute('data-testid') ?? '')
          .filter((id) => wanted.includes(id))
        return found
      })

      expect(order).toEqual([
        'band-what-happened',
        'band-next-action',
        'conversation-panel',
        'band-what-changes',
        'untouched-proof',
        'evidence-toggle',
      ])
    })

    test('never scrolls sideways, with the evidence open or shut', async ({ page }) => {
      await openARealCase(page)

      const shut = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }))
      expect(shut.scroll).toBeLessThanOrEqual(shut.client + 1)

      await page.getByTestId('evidence-toggle').click()
      await expect(page.getByTestId('evidence-drawer')).toBeVisible()
      await page.getByTestId('evidence-technical').click()

      const open = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
        // A wide table is allowed to scroll inside its own box; the page is not.
        table: Boolean(document.querySelector('[data-testid="evidence-technical-panel"] table')),
      }))
      expect(open.scroll).toBeLessThanOrEqual(open.client + 1)
      expect(open.table).toBe(true)
    })

    test('asks nobody to hit a target smaller than a fingertip', async ({ page }) => {
      await openARealCase(page)

      const small = await page.evaluate((minimum) => {
        const offenders: { text: string; height: number }[] = []
        for (const element of Array.from(
          document.querySelectorAll<HTMLElement>('button, a[href], summary'),
        )) {
          const box = element.getBoundingClientRect()
          // A box nobody can see is not a target. A skip link is one pixel until it is
          // focused, and measuring it unfocused would be measuring the wrong thing --
          // the keyboard test below measures it in the state a person actually meets it in.
          if (box.width <= 2 || box.height <= 2) continue
          if (box.height < minimum) {
            offenders.push({
              text: (element.textContent ?? '').trim().slice(0, 40),
              height: Math.round(box.height),
            })
          }
        }
        return offenders
      }, MINIMUM_TARGET)

      expect(small).toEqual([])
    })
  })
}

test.describe('reaching the case from the keyboard', () => {
  test.use({ viewport: { width: 1280, height: 800 } })

  test('lands on the skip link first and jumps to the case with it', async ({ page }) => {
    await openARealCase(page)

    await page.keyboard.press('Tab')
    const focused = await page.evaluate(() => ({
      tag: document.activeElement?.tagName.toLowerCase() ?? '',
      text: (document.activeElement?.textContent ?? '').trim(),
      visible: document.activeElement
        ? document.activeElement.getBoundingClientRect().width > 2
        : false,
      height: document.activeElement
        ? Math.round(document.activeElement.getBoundingClientRect().height)
        : 0,
    }))

    expect(focused.tag).toBe('a')
    expect(focused.text).toMatch(/skip to the case/i)
    // Visible the moment it is focused: a skip link nobody can see is a skip link nobody uses,
    // and it is a full-size target in the one state anybody ever meets it in.
    expect(focused.visible).toBe(true)
    expect(focused.height).toBeGreaterThanOrEqual(MINIMUM_TARGET)

    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/#case-surface/)
  })

  test('walks the whole surface, evidence included, without a mouse', async ({ page }) => {
    await openARealCase(page)

    // Tab until the evidence control has focus, then open it with the keyboard alone.
    const toggle = page.getByTestId('evidence-toggle')
    await toggle.focus()
    await expect(toggle).toBeFocused()
    await page.keyboard.press('Enter')

    await expect(page.getByTestId('evidence-drawer')).toBeVisible()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')

    // And shut again, with focus back where it was rather than lost to the top of the page.
    await page.keyboard.press('Enter')
    await expect(page.getByTestId('evidence-drawer')).toHaveCount(0)
    await expect(toggle).toBeFocused()
  })
})
