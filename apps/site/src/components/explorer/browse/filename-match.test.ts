import test from 'node:test';
import assert from 'node:assert/strict';
import { catalogMatchFiles } from './filename-match.ts';
import { documentKindLabel, pretty } from './filename-presentation.ts';

test('catalog matching keeps a recording file digest even when its URL is not public', () => {
  const files = catalogMatchFiles({
    type: 'recording',
    recording_url: 'https://www.youtube.com/watch?v=abc',
    files: [
      { url: 'https://docs.house.gov/meetings/notice.pdf', saved_copy_sha256: 'ab'.repeat(32) },
      { saved_copy_sha256: 'cd'.repeat(32) },
      { url: 'javascript:bad()' },
    ],
  });
  assert.deepEqual(files, [
    { url: 'https://docs.house.gov/meetings/notice.pdf', saved_copy_sha256: 'ab'.repeat(32) },
    { saved_copy_sha256: 'cd'.repeat(32) },
    { url: 'https://www.youtube.com/watch?v=abc' },
  ]);
});

test('filename labels speak in words', () => {
  assert.equal(pretty('url_path'), 'Url path');
  assert.equal(documentKindLabel({ video_reference: { provider: 'YouTube', id: 'abc' } }), 'Video reference');
  assert.equal(documentKindLabel({ document_kind: ['witness-statement'] }), 'Witness statement');
  assert.equal(documentKindLabel({}), 'Unclassified');
});
