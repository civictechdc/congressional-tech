import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

test('dashboard mounts the filename catalog bootstrap without standalone prototype markup', async () => {
  const dashboard = await readFile(new URL('../../../../pages/dashboard.astro', import.meta.url), 'utf8');
  const header = await readFile(new URL('../../../Header.astro', import.meta.url), 'utf8');
  assert(dashboard.includes("import '../components/explorer/reader/filenames/bootstrap.ts'"));
  assert(dashboard.includes('data-catalog-update'));
  assert(!header.includes('/filenames/'));
  assert(!dashboard.includes('filename-viewer-body.html?raw'));
});
