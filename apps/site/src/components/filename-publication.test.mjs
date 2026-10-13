import assert from 'node:assert/strict';
import {test} from 'node:test';
import {loadPublication, watchPublication, latestReviewUrl} from './filename-publication.mjs';

test('review links select an archived immutable publication and validate its identity', async () => {
  const old = 'a'.repeat(32), latest = 'b'.repeat(32), release = 'c'.repeat(32);
  const root = 'https://data.test/manifest.json';
  const requests = [];
  const fetcher = async (url, options) => {
    assert.equal(options.cache, 'no-store'); requests.push(String(url));
    return Response.json(String(url) === root ? {version: 1, catalog_id: latest, manifest: `releases/${latest}/manifest.json`}
      : String(url).includes('/catalogs/') ? {version: 1, catalog_id: old, manifest: `releases/${release}/manifest.json`}
      : {version: 2, info: {catalog_id: old}});
  };
  const result = await loadPublication(root, fetcher, old);
  assert.equal(result.manifest.info.catalog_id, old);
  assert.equal(result.url, `https://data.test/releases/${release}/manifest.json`);
  assert.deepEqual(requests, [root, `https://data.test/catalogs/${old}.json`, result.url]);
  await assert.rejects(loadPublication(root, fetcher, '../private'), /Invalid catalog/);
  await assert.rejects(loadPublication(root, async () => new Response('', {status: 404}), old), /not available/);
});

test('freshness checks notify on a new catalog, preserve the current reader, and stop cleanly', async () => {
  const win = new EventTarget(), doc = new EventTarget();
  let tick, clears = 0, current = 'one', calls = 0;
  win.setInterval = fn => { tick = fn; return 1; }; win.clearInterval = () => clears++;
  doc.visibilityState = 'visible';
  const updates = [];
  const stop = watchPublication({url: 'https://data.test/manifest.json', current: 'one', window: win, document: doc,
    fetcher: async (_url, options) => {calls++; assert.equal(options.cache, 'no-store'); return Response.json({catalog_id: current});},
    onUpdate: value => updates.push(value.catalog_id)});
  await new Promise(setImmediate);
  assert.deepEqual(updates, []);
  current = 'two'; win.dispatchEvent(new Event('focus'));
  await new Promise(setImmediate);
  assert.deepEqual(updates, ['two']);
  doc.visibilityState = 'hidden'; const before = calls; await tick(); assert.equal(calls, before);
  stop(); doc.visibilityState = 'visible'; win.dispatchEvent(new Event('focus')); await tick();
  assert.equal(calls, before); assert.equal(clears, 1);
});

test('opening latest keeps filters and stable source identity but drops positional rows', () => {
  const url = new URL(latestReviewUrl('https://site.test/filenames/?q=hearing&source=stable&catalog=old&row=5', 'new'));
  assert.equal(url.searchParams.get('q'), 'hearing');
  assert.equal(url.searchParams.get('source'), 'stable');
  assert.equal(url.searchParams.get('catalog'), 'new');
  assert.equal(url.searchParams.has('row'), false);
  assert.equal(new URL(latestReviewUrl(url)).searchParams.has('catalog'), false);
});
