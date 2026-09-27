// Layout across the plan §5 width matrix, JavaScript on, production build.
// Structural assertions, not pixel snapshots: no horizontal overflow, nothing
// crossing the viewport, no text under 11px outside the hero stage and the
// architecture diagram, nothing `hidden` rendered, no clipped control text,
// a stable hero stage, and each breakpoint's designed form on its side.

import { test, expect } from '@playwright/test';
import { WIDTHS, openPage, seek, heroLabel, isShown, trackErrors } from './helpers.js';

const heightFor = (w) => (w < 640 ? 800 : 900);

for (const width of WIDTHS) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: heightFor(width) } });

    test('no overflow, no crossing, no tiny text, no leaked hidden content, no clipped control', async ({ page }) => {
      const errors = trackErrors(page);
      await openPage(page);

      const report = await page.evaluate(() => {
        const W = innerWidth;
        const out = { scrollWidth: document.documentElement.scrollWidth, bodyScroll: document.body.scrollWidth, W, crossing: [], tiny: [], leaked: [], clipped: [] };
        const describe = (el) => `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}${el.className && typeof el.className === 'string' ? `.${el.className.trim().split(/\s+/).join('.')}` : ''}`;
        const clippedAway = (el) => {
          const cs = getComputedStyle(el);
          return cs.clip === 'rect(0px, 0px, 0px, 0px)' || cs.clipPath === 'inset(50%)';
        };
        // An element is out of reach only if no ancestor clips it inside the viewport.
        const clippedByAncestor = (el) => {
          for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
            const cs = getComputedStyle(p);
            if (cs.overflowX !== 'visible' || clippedAway(p)) {
              const r = p.getBoundingClientRect();
              if (r.left >= -1 && r.right <= W + 1) return true;
            }
          }
          return false;
        };
        const all = [...document.body.querySelectorAll('*')];
        for (const el of all) {
          if (el.closest('.skip-link') || el.closest('script, style, noscript')) continue;
          const shown = el.checkVisibility({ visibilityProperty: true });
          if (el.hasAttribute('hidden') && shown) out.leaked.push(describe(el));
          if (!shown || clippedAway(el) || el.closest('.visually-hidden')) continue;
          const r = el.getBoundingClientRect();
          if (r.width < 1 || r.height < 1) continue;
          if ((r.left < -1 || r.right > W + 1) && !clippedByAncestor(el)) {
            out.crossing.push(`${describe(el)} [${Math.round(r.left)}, ${Math.round(r.right)}]`);
          }
          const ownText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
          if (ownText && !el.closest('.hero__stage, svg')) {
            const fs = parseFloat(getComputedStyle(el).fontSize);
            if (fs < 11) out.tiny.push(`${describe(el)} ${fs}px "${el.textContent.trim().slice(0, 30)}"`);
          }
          if (el.matches('a.btn, button, .btn') && !el.closest('.hero__stage')) {
            if (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1) {
              out.clipped.push(`${describe(el)} ${el.scrollWidth}x${el.scrollHeight} in ${el.clientWidth}x${el.clientHeight}`);
            }
          }
        }
        return out;
      });

      expect(report.scrollWidth, 'document scrollWidth').toBe(report.W);
      expect(report.bodyScroll, 'body scrollWidth').toBeLessThanOrEqual(report.W);
      expect(report.crossing, 'elements crossing the viewport').toEqual([]);
      expect(report.tiny, 'text under 11px outside the stage and diagram').toEqual([]);
      expect(report.leaked, '[hidden] elements rendered').toEqual([]);
      expect(report.clipped, 'controls whose text overflows').toEqual([]);
      expect(errors).toEqual([]);
    });

    test('hero stage has its designed, stable, nonzero height', async ({ page }) => {
      await page.goto('./');
      const stage = page.locator('.hero__stage');
      const before = await stage.evaluate((el) => el.getBoundingClientRect().height);
      await page.waitForFunction(() => window.__ppHero && window.__ppHero.renderer !== 'none');
      await page.waitForTimeout(300);
      const after = await stage.evaluate((el) => el.getBoundingClientRect().height);
      const inner = await stage.evaluate((el) => el.clientHeight);
      expect(before).toBeGreaterThan(300);
      expect(after).toBe(before);
      const vh = heightFor(width);
      const expected = width < 360 ? Math.min(620, 1.42 * width + 48)
        : width < 640 ? Math.min(620, 1.42 * width)
          : Math.min(640, Math.max(440, 0.62 * vh));
      expect(Math.abs(inner - expected)).toBeLessThanOrEqual(1);
    });

    test('breakpoint forms', async ({ page }) => {
      await openPage(page);
      // Header: icon below 400px, full logo from 400px.
      expect(await isShown(page.locator('.site-header__icon'))).toBe(width < 400);
      expect(await isShown(page.locator('.site-header__logo'))).toBe(width >= 400);
      // Nav from 1000px.
      expect(await isShown(page.locator('.site-nav'))).toBe(width >= 1000);
      await expect(page.locator('.btn--header')).toBeVisible();

      // Hero: the mobile scene (LM) whenever the stage is under 640px wide.
      const stageW = await page.locator('.hero__stage').evaluate((el) => el.clientWidth);
      await seek(page, 8.2);
      const gate = await heroLabel(page, 'gate');
      expect(gate.text).toBe(stageW < 640 ? '10/10 ✓' : '10/10 · still valid');
      const stepName = page.locator('.hero__step-label').first();
      expect(await isShown(stepName)).toBe(width >= 640);
      await expect(page.locator('[data-hero-step="0"]')).toHaveAccessibleName(/Disruption/);

      // Six promises: below 640px only the current stage's cell per order.
      const visibleCells = await page.locator('#story .matrix__cells .cell').evaluateAll(
        (els) => els.filter((e) => e.checkVisibility()).map((e) => e.classList.contains('is-current')),
      );
      if (width < 640) {
        expect(visibleCells).toHaveLength(6);
        expect(visibleCells.every(Boolean)).toBe(true);
      } else {
        expect(visibleCells).toHaveLength(42);
      }

      // Architecture: the full diagram from 1080px, the stacked chain below.
      expect(await isShown(page.locator('.arch-diagram'))).toBe(width >= 1080);
      expect(await isShown(page.locator('.chain'))).toBe(width < 1080);
      if (width < 1080) await expect(page.locator('.chain .chain__item')).toHaveCount(11);
    });
  });
}
