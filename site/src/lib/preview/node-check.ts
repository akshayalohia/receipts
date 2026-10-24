// Tiny type check: imports only the public types (erased at runtime), so it runs under plain Node too.
// Run: node site/src/lib/preview/node-check.ts   (and it is covered by tsconfig.json in this folder)
import type { PreviewHandle, PreviewParams } from './types';

const samples: PreviewParams[] = [
  { product: 'tweet', colour: 'black', author_name: 'Sample Author', handle: 'sample', text: 'Sample tweet text.', likes: 1204, date: 'Oct 24, 2026', founding: '7' },
  { product: 'milestone', colour: 'gold', number: '10,000', label: 'followers', name: 'Sample Name', date: '2026' },
  { product: 'fullcolour', colour: 'white', name: 'Sample Name', image_url: '/sample.png' },
  { product: 'team', colour: 'blue', team: 'Sample Team', subline: 'Series A', date: '2026' },
];

const check = (h: PreviewHandle): Promise<Blob> => h.snapshot();
void check;
console.log(`preview types ok: ${samples.length} sample params`);
