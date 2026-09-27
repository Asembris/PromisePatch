// Copy buttons for the two public SHAs. The value copied comes from facts.js,
// never from the page, so only the release and deployed SHAs can be copied.

import { COPYABLE } from '../data/facts.js';

const NAMES = { prod: 'Deployed product SHA', rel: 'Repository release SHA' };
const COPIED_MS = 1600;

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Clipboard API missing or refused (e.g. an insecure origin): fall back.
  }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return ok;
  } catch {
    return false;
  }
}

export function initDeployment() {
  const section = document.getElementById('deployment');
  const status = section?.querySelector('[data-copy-status]');
  const buttons = section ? [...section.querySelectorAll('[data-copy]')] : [];
  if (!section || !status || !buttons.length) return;

  for (const btn of buttons) {
    const key = btn.dataset.copy;
    const value = COPYABLE[key];
    if (!value) continue;
    let timer = 0;
    btn.addEventListener('click', async () => {
      const ok = await copyText(value);
      clearTimeout(timer);
      btn.textContent = ok ? 'Copied ✓' : 'Copy';
      status.textContent = ok ? `${NAMES[key]} copied.` : `Could not copy. Select the ${NAMES[key]} text instead.`;
      timer = setTimeout(() => {
        btn.textContent = 'Copy';
        status.textContent = '';
      }, COPIED_MS);
    });
    btn.hidden = false;
  }
}
