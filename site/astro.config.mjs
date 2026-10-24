import { defineConfig } from 'astro/config';

// Static output to site/dist. Pages Functions live in site/functions/ (not built by Astro).
export default defineConfig({
  output: 'static',
  build: { format: 'directory' },
  trailingSlash: 'ignore',
});
