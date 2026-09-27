// Accessibility: axe (zero serious or critical) at 390 and 1440, JavaScript
// on and off; document structure; the skip link; a full keyboard walk with a
// visible focus ring and no trap; pressed state on toggles; the R1–R5 table;
// 44px targets under a coarse pointer; and state never carried by colour alone.
// No axe rule is disabled and nothing is excluded.

import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { openPage, scrollThrough, waitGateSettled } from './helpers.js';

async function axe(page) {
  const results = await new AxeBuilder({ page }).analyze();
  return results.violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.impact} ${v.id}: ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`);
}

// axe runs in the page, so "JavaScript off" is the page with its own script
// blocked: the same DOM a no-JS reader gets (the page has no <noscript>).
for (const js of [true, false]) {
  test.describe(`axe, JavaScript ${js ? 'on' : 'off'}`, () => {
    for (const width of [390, 1440]) {
      test(`${width}px: zero serious or critical`, async ({ page }) => {
        await page.setViewportSize({ width, height: 900 });
        if (js) {
          await openPage(page);
          await scrollThrough(page);
          await waitGateSettled(page);
          // Let one-shot reveals finish so contrast is judged on the settled page.
          await page.waitForFunction(() => !document.querySelector('.reveal-pending'));
          await page.waitForTimeout(800);
        } else {
          await page.route('**/assets/index-*.js', (route) => route.abort());
          await page.goto('./');
          await expect(page.locator('noscript')).toHaveCount(0);
          await expect(page.locator('[data-hero-controls]')).toBeHidden();
        }
        expect(await axe(page)).toEqual([]);
      });
    }
  });
}

test('axe on the illustration state and a non-default stage, trace and order', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await openPage(page);
  await page.locator('#revalidate button[data-mode="hypo"]').click();
  await page.locator('#story [data-stage="2"]').click();
  await page.locator('#story [data-order="E"]').click();
  await page.locator('#architecture [data-trace="model"]').click();
  expect(await axe(page)).toEqual([]);
});

test.describe('structure', () => {
  test('landmarks, one h1, one h2 per section, no skipped heading level', async ({ page }) => {
    await openPage(page);
    await expect(page.locator('h1')).toHaveCount(1);
    await expect(page.getByRole('banner')).toHaveCount(1);
    await expect(page.getByRole('navigation', { name: 'Sections' })).toHaveCount(1);
    await expect(page.getByRole('main')).toHaveCount(1);
    await expect(page.getByRole('contentinfo')).toHaveCount(1);
    const sections = await page.locator('main > section').evaluateAll((els) => els.map((s) => ({
      id: s.id || s.className,
      h1: s.querySelectorAll('h1').length,
      h2: s.querySelectorAll('h2').length,
      labelledBy: s.getAttribute('aria-labelledby'),
      labelTarget: !!document.getElementById(s.getAttribute('aria-labelledby') || '-'),
    })));
    expect(sections).toHaveLength(10);
    sections.forEach((s, i) => {
      expect(s.labelTarget, `${s.id} is labelled by its heading`).toBe(true);
      if (i === 0) expect([s.h1, s.h2]).toEqual([1, 0]);
      else expect([s.h1, s.h2], s.id).toEqual([0, 1]);
    });
    const levels = await page.locator('h1, h2, h3, h4, h5, h6').evaluateAll((hs) => hs.map((h) => Number(h.tagName[1])));
    levels.forEach((l, i) => { if (i) expect(l - levels[i - 1], `heading level jump at ${i}`).toBeLessThanOrEqual(1); });
  });

  test('the R1–R5 table has a caption and scoped headers', async ({ page }) => {
    await openPage(page);
    const table = page.locator('#evidence table.rehearsals');
    await expect(table.locator('caption')).not.toBeEmpty();
    await expect(table.locator('thead th[scope="col"]')).toHaveCount(4);
    await expect(table.locator('tbody th[scope="row"]')).toHaveCount(5);
  });

  test('toggles expose pressed state; changing-label buttons do not', async ({ page }) => {
    await openPage(page);
    for (const sel of ['#story [data-stage]', '#story [data-order]', '#revalidate button[data-mode]', '#architecture [data-trace]', '[data-hero-step]']) {
      const values = await page.locator(sel).evaluateAll((els) => els.map((e) => e.getAttribute('aria-pressed')));
      expect(values.length, sel).toBeGreaterThan(1);
      expect(values.every((v) => v === 'true' || v === 'false'), sel).toBe(true);
    }
    await expect(page.locator('#story [data-play]')).not.toHaveAttribute('aria-pressed');
    await expect(page.locator('[data-hero-pause]')).not.toHaveAttribute('aria-pressed');
    await expect(page.locator('[data-hero-replay]')).not.toHaveAttribute('aria-pressed');
  });

  test('every visible button and link has an accessible name', async ({ page }) => {
    await openPage(page);
    const unnamed = [];
    for (const loc of await page.locator('button, a[href]').all()) {
      if (!(await loc.isVisible())) continue;
      const name = await loc.evaluate((el) => (el.getAttribute('aria-label') || el.textContent || el.querySelector('img')?.alt || '').trim());
      if (!name) unnamed.push(await loc.evaluate((el) => el.outerHTML.slice(0, 80)));
    }
    expect(unnamed).toEqual([]);
  });

  test('state is never carried by colour alone', async ({ page }) => {
    await openPage(page);
    // Lane cells lead with their glyph; every other cell says its state in words.
    const GLYPH = { auto: '●', ask: '◆', wait: '◆', blk: '■', done: '✓' };
    for (const i of [2, 3, 6]) {
      await page.locator(`#story [data-stage="${i}"]`).click();
      const cells = await page.locator('#story .cell:not(.is-future)').evaluateAll((els) => els.map((e) => ({
        kind: [...e.classList].find((c) => c.startsWith('cell--')).slice(6), text: e.textContent,
      })));
      for (const c of cells) {
        expect(/[A-Za-z]/.test(c.text), `${c.kind}: ${c.text}`).toBe(true);
        if (GLYPH[c.kind]) expect(c.text.startsWith(GLYPH[c.kind]), `${c.kind}: ${c.text}`).toBe(true);
        if (c.kind === 'un' && /UN/.test(c.text)) expect(c.text.startsWith('○'), c.text).toBe(true);
      }
    }
    await page.locator('#revalidate button[data-mode="hypo"]').click();
    await waitGateSettled(page, 'STALE');
    const marks = await page.locator('#revalidate .check').evaluateAll((els) => els.map((e) => [
      e.querySelector('.check__mark').textContent, e.querySelector('.check__text .visually-hidden').textContent.trim(),
    ]));
    marks.forEach(([mark, spoken], i) => expect([mark, spoken]).toEqual(i === 4 ? ['✕', 'Failed.'] : ['✓', 'Passed.']));
    await expect(page.locator('#problem .lane')).toHaveText(['AUTO', 'ASK', 'BLOCKED', 'UNAFFECTED']);
    await expect(page.locator('#story .legend')).toContainText('● AUTO◆ ASK■ BLOCKED○ UNAFFECTED✓ settled');
  });
});

test.describe('keyboard', () => {
  test('the skip link is first and moves to main', async ({ page }) => {
    await openPage(page);
    await page.keyboard.press('Tab');
    const skip = page.locator('.skip-link');
    await expect(skip).toBeFocused();
    const box = await skip.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/#main$/);
    await page.keyboard.press('Tab');
    const inMain = await page.evaluate(() => !!document.activeElement.closest('main'));
    expect(inMain).toBe(true);
  });

  for (const width of [390, 1440]) {
    test(`${width}px: a full Tab walk reaches every control with a visible ring and no trap`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await openPage(page);
      const expected = await page.evaluate(() => [...document.querySelectorAll('a[href], button, [tabindex]:not([tabindex="-1"])')]
        .filter((e) => e.checkVisibility() && !e.closest('[hidden]')).length);
      const seen = new Set();
      const problems = [];
      for (let i = 0; i < expected + 5; i += 1) {
        await page.keyboard.press('Tab');
        const f = await page.evaluate(() => {
          const el = document.activeElement;
          if (!el || el === document.body) return null;
          el.dataset.pwWalk ||= String(Math.random());
          const cs = getComputedStyle(el);
          const r = el.getBoundingClientRect();
          return {
            key: el.dataset.pwWalk, tag: el.outerHTML.slice(0, 70),
            ring: el.matches(':focus-visible') && cs.outlineStyle === 'solid' && parseFloat(cs.outlineWidth) >= 2,
            onScreen: r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth,
            deferred: el.getAttribute('aria-disabled') === 'true',
          };
        });
        if (!f) break; // left the document: no trap
        if (seen.has(f.key)) break;
        if (!f.onScreen) {
          // Focus scrolling follows the page's smooth scroll-behavior; let it land.
          await page.waitForTimeout(700);
          f.onScreen = await page.evaluate(() => {
            const r = document.activeElement.getBoundingClientRect();
            return r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
          });
        }
        seen.add(f.key);
        if (!f.ring) problems.push(`no ring: ${f.tag}`);
        if (!f.onScreen) problems.push(`off screen: ${f.tag}`);
        if (f.deferred) problems.push(`deferred placeholder focusable: ${f.tag}`);
      }
      expect(problems).toEqual([]);
      expect(seen.size).toBe(expected);
    });
  }
});

test.describe('coarse pointer', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test('every visible button and button-styled link is at least 44px tall', async ({ page }) => {
    await openPage(page);
    expect(await page.evaluate(() => matchMedia('(pointer: coarse)').matches)).toBe(true);
    const small = await page.locator('button, a.btn').evaluateAll((els) => els
      .filter((e) => e.checkVisibility())
      .map((e) => ({ h: e.getBoundingClientRect().height, w: e.getBoundingClientRect().width, tag: e.outerHTML.slice(0, 80) }))
      .filter((b) => b.h < 44 - 0.5 || b.w < 44 - 0.5)
      .map((b) => `${Math.round(b.w)}x${Math.round(b.h)} ${b.tag}`));
    expect(small).toEqual([]);
  });
});
