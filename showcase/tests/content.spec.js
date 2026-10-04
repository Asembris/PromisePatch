// The content rules of tools/content-rules.mjs (the same rules the build gate
// runs over dist/index.html), applied to the live, JavaScript-rendered DOM
// after every interaction state; the runtime network origin; and the
// performance facts the plan asks for (CLS, three.js after first paint).

import { test, expect } from '@playwright/test';
import { checkClaims, checkContent } from '../tools/content-rules.mjs';
import { ORDER_IDS } from '../src/data/rows.js';
import { TRACES } from '../src/data/traces.js';
import { openPage, seek, scrollThrough, trackErrors, waitGateSettled, recordFirstFrame, paintTiming, expectThreeAfterFirstPaint } from './helpers.js';

const liveHtml = (page) => page.evaluate(() => document.documentElement.outerHTML);

test('every interaction state keeps the frozen facts, caveats and boundaries', async ({ page }) => {
  test.setTimeout(120_000);
  const errors = trackErrors(page);
  await openPage(page);
  await scrollThrough(page);
  await waitGateSettled(page);

  const failures = [];
  const snapshots = [];
  const check = async (name, state = 'live') => {
    const html = await liveHtml(page);
    snapshots.push(html);
    for (const f of checkContent({ html, state })) failures.push(`[${name}] ${f}`);
  };

  // The settled default, now JavaScript-rendered, obeys the default-only rules too.
  await check('settled default', 'default');

  for (let i = 0; i < 7; i += 1) {
    await page.locator(`#story [data-stage="${i}"]`).click();
    await check(`stage ${i + 1}`);
  }
  for (const id of ORDER_IDS) {
    await page.locator(`#story [data-order="${id}"]`).click();
    await check(`order ${id}`);
  }
  await page.locator('#story [data-play]').click();
  await page.waitForTimeout(1300);
  await check('play case, mid-run');
  await page.locator('#story [data-play]').click();

  const hypo = page.locator('#revalidate button[data-mode="hypo"]');
  await hypo.click();
  await page.waitForTimeout(250);
  await check('illustration, checks running');
  expect(await page.locator('#revalidate [data-gate-header]').textContent()).toBe('ILLUSTRATION · NOT A RECORDED RUN');
  await waitGateSettled(page, 'STALE');
  await check('illustration, STALE');
  await page.locator('#revalidate button[data-mode="live"]').click();
  await waitGateSettled(page, 'PROCEED');
  await check('R3 again');

  for (const key of Object.keys(TRACES)) {
    await page.locator(`#architecture [data-trace="${key}"]`).click();
    await check(`trace ${key}`);
  }
  for (const t of [0.2, 0.95, 1.8, 3.0, 4.3, 5.8, 6.5, 8.2]) {
    await seek(page, t);
    await check(`hero t=${t}`);
  }
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.locator('#deployment [data-copy="rel"]').click();
  await check('after copy');

  expect(failures).toEqual([]);

  // Across every state: no progression wording, the illustration never without
  // its disclaimer, no live refusal claim, no deferred placeholder left.
  for (const html of snapshots) {
    expect(html).not.toMatch(/·\s*deferred/i);
  }
  expect(errors).toEqual([]);
});

test('negative control: the live rules catch a mutated DOM', async ({ page }) => {
  await openPage(page);
  await page.locator('#revalidate button[data-mode="hypo"]').click();
  await waitGateSettled(page, 'STALE');
  await page.evaluate(() => {
    document.querySelector('#revalidate [data-gate-header]').textContent = '';
    document.querySelector('.evidence-cards__pair .caveat strong').textContent = 'The benchmark went up to 16/16.';
    for (const a of document.querySelectorAll('a[href^="https://youtu.be/"]')) a.setAttribute('href', 'https://example.com');
    document.querySelector('.limits__list').insertAdjacentHTML('beforeend', '<li>EXPIRED and UNAUTHORIZED refusals were exercised live on the deployment.</li><li>Every refusal path was exercised live, once.</li>');
  });
  const failures = checkContent({ html: await liveHtml(page), state: 'live' });
  expect(failures.join('\n')).toMatch(/refusal claimed live or on the deployment: "EXPIRED and UNAUTHORIZED/);
  expect(failures.join('\n')).toMatch(/refusal claimed live or on the deployment: "Every refusal path/);
  expect(failures.join('\n')).toMatch(/went up to 16\/16/);
  expect(failures.join('\n')).toMatch(/illustrated STALE outcome is shown without its label/);
  expect(failures.join('\n')).toMatch(/the demo video link to https:\/\/youtu\.be\/ZeXnfcNY1No is missing/);
});

// Each corrected claim, reworded several ways: the rules are semantic shapes,
// so an overclaim cannot come back in new words. The corrected wording passes.
const OVERCLAIMS = [
  ['Customers answer with a literal YES, an option code or NO.', /option code/],
  ['An option-code reply also approves the change.', /option code/],
  ['A worker approves the plan in a signed-in session.', /only from a signed-in session/],
  ['Plan approvals are written solely in the signed-in session.', /only from a signed-in session/],
  ['An MCP confirm can only spend an approval a human wrote in a signed-in session.', /only from a signed-in session/],
  ['session: the only place a plan approval is written', /only from a signed-in session/],
  ['Every effect is applied exactly once.', /exactly once/],
  ['Messages are delivered exactly-once end to end.', /exactly once/],
  ['Telegram never sends duplicate messages.', /duplicate messages ruled out/],
  ['PromisePatch guarantees each message is delivered once.', /duplicate messages ruled out/],
  ['MCP callers have no authority over physical facts.', /no authority at all/],
  ['There is no authority for an AI agent anywhere.', /no authority at all/],
  ['The AI cannot attest a physical fact.', /categorically unable to attest/],
  ['An MCP agent can never attest anything.', /categorically unable to attest/],
  ['CANNOT ✕ write a row ✕ attest a physical fact', /categorically unable to attest/],
  ['Revalidation is atomic with the order system’s acceptance.', /described as atomic/],
  ['The ten checks run atomically before the amendment is sent.', /described as atomic/],
  ['Ten checks run against a fresh snapshot immediately before the order is amended.', /at external execution/],
  ['Before acting, the YES is checked again: ten checks against a fresh snapshot.', /at external execution/],
  ['It is revalidated on every dispatch.', /at external execution/],
  ['That answer is revalidated before the order system is amended.', /at external execution/],
  ['Customer presses APPROVE. Stored; nothing acts on it.', /attributed to a customer/],
  ['Tomas pressed APPROVE on the phone.', /attributed to a customer/],
  ['They answer YES, and the world keeps moving while it waits.', /world that moved/],
  ['The world changed while the answer waited.', /world that moved/],
  ['Every STALE decision is re-planned.', /universal re-plan|every stale finding/],
  ['A STALE change is always re-planned.', /every stale finding/],
  ['Rehearsal R3 was refused as STALE.', /recorded in a rehearsal/],
  ['The recorded run refused the change.', /recorded in a rehearsal/],
  ['Approval deadline check: 20:31:01Z ≤ 01:26:54Z', /crosses midnight/],
  ['STALE, EXPIRED, UNAUTHORIZED and NOOP are proved by tests only.', /STALE listed as proved by tests only/],
  ['Refusal paths (STALE, EXPIRED, UNAUTHORIZED, NOOP) are proved by tests only.', /STALE listed as proved by tests only/],
  ['STALE was reproduced live on the deployment.', /presented as live or on the deployment/],
  ['A STALE refusal was reproduced in production.', /presented as live or on the deployment/],
];
const CORRECTED = [
  'Authorizes an ASK change with a literal YES or NO, trimmed and case-insensitive. Any other reply decides nothing.',
  'The parser implements no option code.',
  'Attests the physical fact, and approves the plan that was read out, in a signed-in browser session or on the operator console.',
  'MCP intake is a trusted reporting channel: its reports are recorded under the server’s configured worker. An MCP confirm can only spend an approval a person already wrote.',
  'session: one of two plan-approval channels',
  'R1–R5: five worker restarts at four points, each PASS, every effect recorded once and delivered on attempt 1.',
  'Telegram’s Bot API has no idempotency key, so a retry after an uncertain send can deliver a duplicate message.',
  'When a customer’s YES arrives, PromisePatch takes a fresh snapshot and runs ten checks before the change may be committed.',
  'A change that is no longer true is refused as STALE, nothing is sent, and that track is re-planned; an expired answer goes to the owner and an unauthorized one is refused.',
  'After it, only the production start is judged again, at the amendment’s first dispatch.',
  'The owner, as the demo customer, presses APPROVE. Stored; nothing acts on it.',
  'One customer is asked and answers YES on a signed link. Conditions can change while an answer waits.',
  'One refusal kind has been exercised live, once.',
  'STALE, through check 2, on 740a062838e0. The other checks refusing, EXPIRED, UNAUTHORIZED, NOOP and the commit-time freshness gate are proved by tests only.',
  'This scenario is illustrative, not a recorded run: the substitute never ran out. The one live STALE, on 740a062838e0, failed check 2 when the order moved to v2, not this check; EXPIRED, UNAUTHORIZED and NOOP are proved by tests only.',
  'Approval deadline not passed, judged at processing time. 24 Sep 20:31:01Z ≤ 25 Sep 01:26:54Z',
];

test('claim scope: every corrected overclaim is caught in other words, and the corrected copy passes', () => {
  for (const [sentence, why] of OVERCLAIMS) {
    const failures = checkClaims(sentence);
    expect(failures.join('\n'), sentence).toMatch(why);
  }
  for (const sentence of CORRECTED) expect(checkClaims(sentence), sentence).toEqual([]);
});

test('negative control: the live claim rules catch the old R3, deadline, consent and approval copy', async ({ page }) => {
  await openPage(page);
  await scrollThrough(page);
  await waitGateSettled(page);
  expect(checkContent({ html: await liveHtml(page), state: 'default' })).toEqual([]);
  await page.evaluate(() => {
    const rows = document.querySelectorAll('#revalidate .timeline li span:last-child');
    rows[2].textContent = 'Customer presses APPROVE. Stored; nothing acts on it.';
    rows[3].textContent = 'Worker starts again, 2 min 29 s later';
    document.querySelectorAll('#revalidate .check__value')[6].textContent = '20:31:01Z ≤ 01:26:54Z';
    const cards = [...document.querySelectorAll('.authority-card p')];
    cards[1].textContent = 'Attests the physical fact, and approves the plan that was read out, in a signed-in session.';
    cards[2].textContent = 'Authorizes an ASK change with a literal YES, an option code or NO.';
  });
  const failures = checkContent({ html: await liveHtml(page), state: 'live' }).join('\n');
  expect(failures).toMatch(/attributed to a customer/);
  expect(failures).toMatch(/owner, as the demo customer/);
  expect(failures).toMatch(/timeline row 20:30:58: "2 min 29 s" does not reach back/);
  expect(failures).toMatch(/crosses midnight without both dates/);
  expect(failures).toMatch(/only from a signed-in session/);
  expect(failures).toMatch(/option code/);
});

test('the demo video and Devpost are real links, and no placeholder is left', async ({ page }) => {
  await openPage(page);
  await expect(page.locator('[aria-disabled="true"]')).toHaveCount(0);
  await expect(page.locator('.hero__aside a[href="https://youtu.be/ZeXnfcNY1No"]')).toHaveCount(1);
  await expect(page.locator('.final-cta a[href="https://youtu.be/ZeXnfcNY1No"]')).toHaveCount(1);
  await expect(page.locator('.final-cta a[href="https://devpost.com/software/promisepatch"]')).toHaveCount(1);
});

test('no credential or token is ever on the page', async ({ page }) => {
  await openPage(page);
  const html = await liveHtml(page);
  for (const re of [/ghp_[A-Za-z0-9]{20,}/, /github_pat_/, /AKIA[0-9A-Z]{16}/, /\b\d{8,10}:[A-Za-z0-9_-]{30,}\b/, /\bsk-[A-Za-z0-9]{20,}/, /-----BEGIN [A-Z ]*PRIVATE KEY/, /[?&](?:token|sig|signature)=/i]) {
    expect(html).not.toMatch(re);
  }
});

test.describe('runtime network', () => {
  for (const js of [true, false]) {
    test(`JavaScript ${js ? 'on' : 'off'}: every request stays on the Pages origin and base`, async ({ browser, baseURL }) => {
      const context = await browser.newContext({ javaScriptEnabled: js, permissions: ['clipboard-read', 'clipboard-write'] });
      const page = await context.newPage();
      const origin = new URL(baseURL).origin;
      const requests = [];
      const failed = [];
      page.on('request', (r) => requests.push(r.url()));
      page.on('response', (r) => { if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`); });
      page.on('requestfailed', (r) => failed.push(`failed ${r.url()}`));
      if (js) {
        await openPage(page);
        await scrollThrough(page);
        await page.locator('#revalidate button[data-mode="hypo"]').click();
        await page.locator('#architecture [data-trace="agent"]').click();
        await page.locator('#story [data-play]').click();
        await page.locator('#deployment [data-copy="prod"]').click();
        await page.waitForTimeout(1500);
      } else {
        await page.goto('./');
        await page.waitForTimeout(1000);
      }
      const foreign = requests.filter((u) => !u.startsWith('data:') && (new URL(u).origin !== origin || !new URL(u).pathname.startsWith('/PromisePatch/')));
      expect(foreign).toEqual([]);
      expect(requests.some((u) => /fonts\.(googleapis|gstatic)\.com|unpkg|jsdelivr|cdnjs|184\.194\.40\.87/.test(u))).toBe(false);
      expect(failed).toEqual([]);
      if (js) expect(requests.some((u) => /three-renderer-/.test(u))).toBe(true);
      else expect(requests.some((u) => /\.js$/.test(u))).toBe(false);
      await context.close();
    });
  }
});

test.describe('performance', () => {
  for (const [width, height] of [[390, 844], [1578, 900]]) {
    test(`${width}px: CLS under 0.05, three.js after first paint, H1 in the first contentful frame`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.addInitScript(() => {
        window.__cls = 0;
        window.__lcp = [];
        new PerformanceObserver((l) => l.getEntries().forEach((e) => { if (!e.hadRecentInput) window.__cls += e.value; }))
          .observe({ type: 'layout-shift', buffered: true });
        new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__lcp.push({
          t: e.startTime, h1: !!e.element?.closest('h1'), tag: e.element ? e.element.tagName + '.' + e.element.className : null,
        }))).observe({ type: 'largest-contentful-paint', buffered: true });
      });
      await recordFirstFrame(page);
      await openPage(page);
      await page.waitForTimeout(1500); // the renderer takeover has happened
      const m = await page.evaluate(() => {
        const paint = Object.fromEntries(performance.getEntriesByType('paint').map((e) => [e.name, e.startTime]));
        const three = performance.getEntriesByType('resource').find((e) => /three-renderer-/.test(e.name));
        return { cls: window.__cls, fcp: paint['first-contentful-paint'], three: three?.startTime, lcp: window.__lcp,
          h1Top: document.querySelector('h1').getBoundingClientRect().top + scrollY };
      });
      test.info().annotations.push({ type: 'metrics', description: JSON.stringify(m) });
      expect(m.cls).toBeLessThan(0.05);
      expectThreeAfterFirstPaint(await paintTiming(page));
      // The largest paint is the lede (narrow) or the settled hero image (wide),
      // not the H1 as the plan's budget line assumed (recorded in the plan). What
      // matters holds: the above-the-fold content, H1 included, lands in the
      // first contentful frame. (Later LCP entries, e.g. a font swap, may come
      // after the three.js request; they do not delay that first frame.)
      expect(m.lcp.length).toBeGreaterThan(0);
      expect(m.lcp[0].t - m.fcp, JSON.stringify(m)).toBeLessThanOrEqual(50);
      expect(m.h1Top).toBeLessThan(height);
    });
  }
});
