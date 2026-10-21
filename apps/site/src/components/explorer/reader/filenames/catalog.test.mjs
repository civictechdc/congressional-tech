import assert from 'node:assert/strict';
import { test } from 'node:test';
import { brotliCompressSync } from 'node:zlib';
import { createFilenameCatalog, rangeFile, sourceContext, savedCopyUrl, videoReference } from './catalog.ts';
import { observationReader } from './observations.ts';
import { byteCache, retainedBytes } from './cache.ts';

test('saved-copy links prefer accepted recoveries and preserve the original record', () => {
  const manifest = 'https://data.test/releases/catalog/manifest.json';
  const body = hash => `bodies/sha256/${hash.slice(0, 2)}/${hash}.gz`;
  const originalHash = 'a'.repeat(64), recoveredHash = 'b'.repeat(64);
  const record = {filename: 'Hearing #1.pdf', body_key: body(originalHash)};
  const recovered = {recovery_status: 'recovered', body_key: body(recoveredHash)};
  assert.equal(savedCopyUrl(record, null, manifest), `https://data.test/saved/${originalHash}/Hearing%20%231.pdf`);
  assert.match(savedCopyUrl({...record, recovery: recovered}, null, manifest), new RegExp('/saved/' + recoveredHash + '/'));
  assert.match(savedCopyUrl(record, recovered, manifest), new RegExp('/saved/' + recoveredHash + '/'));
  assert.equal(record.body_key, body(originalHash));
  assert.equal(savedCopyUrl({body_key: null}, null, manifest), null);
  assert.equal(savedCopyUrl({body_key: 'receipts/private.json'}, null, manifest), null);
  assert.equal(savedCopyUrl({body_key: `bodies/sha256/ff/${originalHash}.gz`}, null, manifest), null);
  assert.equal(savedCopyUrl(record, null, 'file:///manifest.json'), null);
});

test('createFilenameCatalog rejects non-v6 catalog manifests', async () => {
  for (const version of [1, 2, 5]) {
    await assert.rejects(
      createFilenameCatalog('https://data.test/manifest.json', async () => Response.json({version, info: {catalog_id: 'a'.repeat(32)}, files: {}})),
      /Unsupported filename catalog version/,
    );
  }
});

test('video references recognize exact YouTube providers, not incidental URL text', () => {
  for (const url of ['https://youtu.be/-oNSVIeynzI', 'https://www.youtube.com/watch?v=-oNSVIeynzI&feature=shared',
    'https://www.youtube.com/live/-oNSVIeynzI', 'https://www.youtube-nocookie.com/embed/-oNSVIeynzI']) {
    assert.deepEqual(videoReference(url), {provider:'YouTube',id:'-oNSVIeynzI'});
  }
  for (const url of ['https://youtube.com.evil.test/watch?v=-oNSVIeynzI', 'https://committee.test/a.pdf?video=-oNSVIeynzI',
    'https://youtube.com/watch?v=invalid', 'https://user:password@youtube.com/watch?v=-oNSVIeynzI']) assert.equal(videoReference(url), null);
});

test('bounded observation parts preserve large values, UTF-8, nulls, duplicates and ordering', async () => {
  function packed(rows) {
    const raw = Buffer.from(JSON.stringify(rows)), chunks = [], parts = [];
    let offset = 0;
    for (let start = 0; start < raw.length; start += 71) {
      const piece = raw.subarray(start, start + 71), compressed = brotliCompressSync(piece);
      chunks.push(compressed); parts.push([offset, compressed.length, piece.length]); offset += compressed.length;
    }
    const bytes = Buffer.concat(chunks);
    return { descriptor: {rows:rows.length, blocks:[{start:0,count:rows.length,parts}]},
      file: {slice: async (start, end) => bytes.buffer.slice(bytes.byteOffset + start, bytes.byteOffset + end)} };
  }
  const label = 'Witness 🏛️ José '.repeat(300);
  const data = packed([{label:[label], empty:[]}, null, {label:['Second']}]);
  const refs = packed([[2,0,2,1], [], null]);
  const index = {version:1,max_part_bytes:71,fields:['label','empty','missing'],observations:data.descriptor,references:refs.descriptor};
  const reader = observationReader(index, data.file, refs.file);
  assert.deepEqual(await reader.read(0), [
    {label:['Second'],empty:null,missing:null}, {label:[label],empty:[],missing:null},
    {label:['Second'],empty:null,missing:null}, null,
  ]);
  assert.deepEqual(await reader.read(1), []);
  assert.equal(await reader.read(2), null);
  await assert.rejects(reader.read(3), /Invalid observation reference/);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(reader.read(0, controller.signal), {name:'AbortError'});
  const bad = observationReader({...index, max_part_bytes:70}, data.file, refs.file);
  await assert.rejects(bad.read(0), /block size/);
});

test('range reads reject full-file fallbacks, incorrect ranges and truncated bytes', async () => {
  for (const response of [new Response(new Uint8Array(4)), new Response(new Uint8Array(4), {status:206, headers:{'Content-Range':'bytes 0-3/99'}}), new Response(new Uint8Array(2), {status:206, headers:{'Content-Range':'bytes 0-3/10'}})]) {
    await assert.rejects(rangeFile('https://test/file', 10, async () => response).slice(0, 4), /range/i);
  }
  let calls = 0;
  const file = rangeFile('https://test/file', 10, async () => { calls++; return new Response(new Uint8Array([0,1,2,3,4,5,6,7,8,9]), {status:206,headers:{'Content-Range':'bytes 0-9/10'}}); });
  await file.slice(0, 10);
  assert.deepEqual([...new Uint8Array(await file.slice(2, 4))], [2,3]); assert.equal(calls, 1);
});

test('source provenance preserves multi-value associations and rejects unsafe URLs', () => {
  const result = sourceContext({ source_url: 'javascript:bad()', source_occurrences: [{ source_page_url:['https://a.test/','https://b.test/'],source_page_title:['A','B'],source_occurrence_scope:['anchor'] }] });
  assert.equal(result.file_url, null); assert.equal(result.pages.length, 1); assert.deepEqual(result.pages[0].titles, ['A','B']);
});

test('inherited provenance retains hearing evidence without inventing a file redirect', () => {
  const result = sourceContext({source_url:'https://files.test/programme.pdf', source_occurrences:[{
    source_original_page_url:['https://committee.test/hearing'],
    source_link_url:['https://news.test/article'], source_link_label:['Yemen'],
    source_page_type:['hearing notice'], source_page_date:['2022-04-12'],
    source_occurrence_scope:['linked_ancestor'],
    source_association_basis:['linked_page','publisher_redirect'],
    source_associated_url:['https://news.test/old-article'],
  }]});
  assert.equal(result.pages[0].relationship, 'Linked through');
  assert.deepEqual(result.pages[0].types, ['hearing notice']);
  assert.deepEqual(result.pages[0].dates, ['2022-04-12']);
  assert.deepEqual(result.pages[0].link_urls, ['https://news.test/article']);
  assert.deepEqual(result.redirects, []);
});

test('relative source aliases link through the verified body without changing source text', () => {
  const record = {filename:'statement.pdf', source_url:'../docs/statement.pdf', body_key:null};
  const before = structuredClone(record);
  const recovery = {original_url:record.source_url, recovered_url:'https://committee.test/docs/statement.pdf',
    body_key:`bodies/sha256/aa/${'a'.repeat(64)}.gz`, recovery_status:'recovered', recovery_basis:'resolved_source_url'};
  assert.equal(savedCopyUrl(record, recovery, 'https://data.test/manifest.json'),
    `https://data.test/saved/${'a'.repeat(64)}/statement.pdf`);
  assert.deepEqual(record, before);
});

test('streamed logical decode preserves a value over 1 MiB without joined byte copies',async()=>{
 function packed(rows) {
  const raw=Buffer.from(JSON.stringify(rows)),chunks=[],parts=[];let offset=0;
  for(let start=0;start<raw.length;start+=65537){const piece=raw.subarray(start,start+65537),compressed=brotliCompressSync(piece);chunks.push(compressed);parts.push([offset,compressed.length,piece.length]);offset+=compressed.length;}
  const bytes=Buffer.concat(chunks);return {descriptor:{rows:rows.length,blocks:[{start:0,count:rows.length,parts}]},file:{slice:async(start,end)=>bytes.buffer.slice(bytes.byteOffset+start,bytes.byteOffset+end)}};
 }
 const label='José 🏛️ '.repeat(120000),data=packed([{label:[label]},null]),refs=packed([[0,0,1],Array(10000).fill(1),null]);
 const index={version:1,max_part_bytes:65537,fields:['label','missing'],observations:data.descriptor,references:refs.descriptor};
 const metrics={},cache=byteCache(1024*1024),reader=observationReader(index,data.file,refs.file,{metrics,cache});
 const full=await reader.read(0);assert.deepEqual(full,[{label:[label],missing:null},{label:[label],missing:null},null]);
 assert.equal((await reader.read(1)).length,10000);assert((await reader.read(1)).every(value=>value===null));assert.equal(await reader.read(2),null);
 assert(metrics.maxLogicalDecodedBytes>1024*1024);assert(metrics.maxDecodedPartBytes<=65537);assert.equal(metrics.joinedDecodedBytes,0);assert(cache.stats.peak<=1024*1024);
 const cloned=structuredClone(full),json=JSON.stringify(full);assert.deepEqual(JSON.parse(json),cloned);
 console.log('controlled logical decode accounting',JSON.stringify({...metrics,retainedCacheBytes:cache.stats.bytes,workerCloneEstimate:retainedBytes(cloned),fullJsonUtf16Bytes:json.length*2,fullJsonUtf8Bytes:Buffer.byteLength(json)}));
});
