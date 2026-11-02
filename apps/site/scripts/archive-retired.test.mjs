import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {openArchive} from '../src/components/explorer/reader/archive.ts';

// The fixture release carries retired_links.parquet; expected.json names its cases.
const folder = process.env.ARCHIVE_FIXTURE;
const manifest = JSON.parse(await readFile(join(folder, 'manifest.json')));
const expected = JSON.parse(await readFile(join(folder, 'retired-expected.json')));
async function localFetch(url, options={}) {
  const path = new URL(url).pathname;
  if (path === '/manifest.json') return Response.json({release_id: manifest.release_id, previous_release_id:null});
  const bytes = await readFile(join(folder, path.split('/').at(-1)));
  const range = options.headers?.Range;
  if (!range) return new Response(bytes);
  const [start,end] = range.slice(6).split('-').map(Number);
  return new Response(bytes.subarray(start,end+1), {status:206, headers:{'Content-Range':`bytes ${start}-${end}/${bytes.length}`}});
}

test('a live key opens, a retired key redirects or shows a notice, an unknown key is not found', async()=>{
  const reader = await openArchive('https://fixture.test/manifest.json', {fetcher: localFetch, heapBytes:64*1024*1024});
  assert.deepEqual(await reader.locate(expected.live.key), {index: expected.live.index, redirectedFrom: null});
  assert.deepEqual(await reader.locate(expected.redirect.key), {index: expected.live.index, redirectedFrom: expected.redirect.key});
  // A removal notice lists the other editions published at the same address.
  assert.deepEqual(await reader.locate(expected.removed.key), {removed: {key: expected.removed.key, successor: null,
    lastRelease: expected.removed.last_release_id, lastFilename: expected.removed.last_filename, versions: expected.removed.versions}});
  assert.equal(await reader.locate('00000000000000ff'), null);
});
