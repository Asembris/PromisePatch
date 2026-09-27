// Progressive enhancement. The HTML already reads completely in its settled
// state; each enhancer takes over one section and reveals its controls only
// once they are wired. If one fails, the others still run and that section
// keeps its settled content.

import { createMotion } from './lib/motion.js';
import { initHero } from './hero/controller.js';
import { initStory } from './sections/story.js';
import { initRevalidate } from './sections/revalidate.js';
import { initArchitecture } from './sections/architecture.js';
import { initDeployment } from './sections/deployment.js';
import { initReveal } from './sections/reveal.js';

const motion = createMotion();

for (const [name, init] of [
  ['hero', initHero],
  ['story', initStory],
  ['revalidate', initRevalidate],
  ['architecture', initArchitecture],
  ['deployment', initDeployment],
  ['reveal', initReveal],
]) {
  try {
    init(motion);
  } catch (error) {
    console.error(`showcase: ${name} enhancement failed; its settled content stays`, error);
  }
}
