import {test} from 'node:test';
import assert from 'node:assert/strict';
import {loadArchiveFixture} from './archive-test-fixture.mjs';
import {openArchive} from '../src/components/explorer/reader/archive.ts';
const fixture = await loadArchiveFixture();
const fetcher = fixture.fetcher;

test('nonzero detail shards and cross-shard source ranges preserve attachments',async()=>{
  const reader=await openArchive('https://fixture.test/manifest.json',{fetcher});
  const entry=await reader.entry(4);assert.equal(entry.document.filename,'Record.pdf');assert.equal(entry.sources.length,2);assert(entry.sources.every(source=>source.list_row===4));
  const cross=await reader.entry(1);assert.equal(cross.sources.length,2);assert.deepEqual(cross.sources.map(source=>source.ordinal),[0,1]);assert(cross.sources.every(source=>source.list_row===1));
});
