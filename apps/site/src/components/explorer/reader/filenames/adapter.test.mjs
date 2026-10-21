import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createFilenameClient} from './client.ts';
import {reviewPublicationUrl, latestReviewUrl} from './publication.ts';

test('published client requires its worker and propagates worker route results', async () => {
  let terminated = false;
  const client = createFilenameClient({
    context: {manifest: 'https://data.test/manifest.json', snapshot: 'a'.repeat(32)},
    createWorker() {
      return {
        onmessage: null,
        onerror: null,
        onmessageerror: null,
        postMessage(msg) {
          queueMicrotask(() => this.onmessage?.({data: {id: msg.id, result: {route: msg.url, catalog_id: 'a'.repeat(32)}}}));
        },
        terminate() { terminated = true; },
      };
    },
  });
  const info = await client.request('/api/info');
  assert.deepEqual(info, {route: '/api/info', catalog_id: 'a'.repeat(32)});
  client.dispose();
  assert.equal(terminated, true);
  await assert.rejects(client.request('/api/info'), /stopped loading/);
});

test('review publication URLs and latest review links preserve stable source identity', () => {
  assert.equal(
    reviewPublicationUrl('/congressional-tech/', 'https://viewer.test'),
    'https://viewer.test/congressional-tech/data/document-reviews/reviews.json',
  );
  const stableId = 'b'.repeat(64);
  const updated = new URL(latestReviewUrl(`https://viewer.test/dashboard/?view=materials&kind=filename_entry&id=${stableId}&catalog=old`, 'c'.repeat(32)));
  assert.equal(updated.searchParams.get('id'), stableId);
  assert.equal(updated.searchParams.get('catalog'), 'c'.repeat(32));
});
