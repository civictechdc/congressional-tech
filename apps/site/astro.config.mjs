// @ts-check
import { defineConfig } from 'astro/config';
import react from '@astrojs/react';

// Static Astro site for the congressional-tech initiative, deployed to
// GitHub Pages at https://civictechdc.github.io/congressional-tech/.
// React islands provide the Committee Explorer and the original YouTube report.
export default defineConfig({
  site: 'https://civictechdc.github.io',
  base: '/congressional-tech',
  output: 'static',
  integrations: [react()],
});
