import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {loadArchiveFixture} from './archive-test-fixture.mjs';
import {openArchive} from '../src/components/explorer/reader/archive.ts';

// The fixture release carries retired_links.parquet; ARCHIVE_EXPECTED_FILE names its cases.
const fixture = await loadArchiveFixture();
const fetcher = fixture.fetcher;
const localFetch = fixture.fetcher;
if(!process.env.ARCHIVE_EXPECTED_FILE)throw new Error('ARCHIVE_EXPECTED_FILE is required for retired-link expectations.');
const expected = JSON.parse(await readFile(process.env.ARCHIVE_EXPECTED_FILE));

test('a live key opens, a retired key redirects or shows a notice, an unknown key is not found', async()=>{
  const reader = await openArchive('https://fixture.test/manifest.json', {fetcher: localFetch, heapBytes:64*1024*1024});
  assert.deepEqual(await reader.locate(expected.live.key), {index: expected.live.index, redirectedFrom: null});
  assert.deepEqual(await reader.locate(expected.redirect.key), {index: expected.live.index, redirectedFrom: expected.redirect.key});
  // A removal notice lists the other editions published at the same address.
  assert.deepEqual(await reader.locate(expected.removed.key), {removed: {key: expected.removed.key, successor: null,
    lastRelease: expected.removed.last_release_id, lastFilename: expected.removed.last_filename, versions: expected.removed.versions}});
  assert.equal(await reader.locate('00000000000000ff'), null);
});
