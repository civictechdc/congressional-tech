import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {loadArchiveFixture} from './archive-test-fixture.mjs';
import {openArchive} from '../src/components/explorer/reader/archive.ts';

// The fixture release carries witnesses.parquet and witness_key_map.parquet;
// witness_map_expected.json names its cases.
const fixture = await loadArchiveFixture();
const fetcher = fixture.fetcher;
const localFetch = fixture.fetcher;
const expected = JSON.parse(await readFile(fixture.files['witness_map_expected.json']));

test('/witness/<earlier key> opens the current witness; ambiguous and unresolved keys say so', async()=>{
  const reader = await openArchive('https://fixture.test/manifest.json', {fetcher: localFetch, heapBytes:64*1024*1024});
  const live = await reader.getWitness(expected.live.key);
  assert.equal(live.name, expected.live.name);
  assert.equal(live.redirected_from, null);

  const moved = await reader.getWitness(expected.redirect.key);
  assert.equal(moved.witness_key, expected.live.key);
  assert.equal(moved.name, expected.live.name);
  assert.equal(moved.redirected_from, expected.redirect.key);

  // Two current witnesses fit: both are listed, neither is opened.
  assert.deepEqual(await reader.getWitness(expected.ambiguous.key), {witness_key: expected.ambiguous.key,
    retired: {key: expected.ambiguous.key, status: 'ambiguous', successor: null, basis: 'content', candidates: expected.ambiguous.candidates}});
  assert.deepEqual(await reader.getWitness(expected.unresolved.key), {witness_key: expected.unresolved.key,
    retired: {key: expected.unresolved.key, status: 'unresolved', successor: null, basis: null, candidates: []}});
  assert.equal(await reader.getWitness('00000000000000ff'), null);
});
