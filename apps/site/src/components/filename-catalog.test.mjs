import assert from 'node:assert/strict';
import { test } from 'node:test';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, open, stat, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { createFilenameCatalog, rangeFile, sourceContext, savedCopyUrl } from './filename-catalog.mjs';
import { observationReader } from './filename-observations.mjs';
import { brotliCompressSync } from 'node:zlib';
import { createHash } from 'node:crypto';

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

async function localFetch(url, options = {}) {
  options.signal?.throwIfAborted();
  if (!options.headers?.Range) return new Response(await readFile(new URL(url)));
  const [start, end] = options.headers.Range.slice(6).split('-').map(Number);
  const handle = await open(new URL(url));
  try {
    const data = Buffer.alloc(end - start + 1); await handle.read(data, 0, data.length, start);
    return new Response(data, { status: 206, headers: { 'Content-Range': `bytes ${start}-${end}/${(await stat(new URL(url))).size}` } });
  } finally { await handle.close(); }
}

test('static Parquet queries match the Python catalog and preserve complete source records', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'filename-catalog-'));
  try {
    execFileSync(process.env.PYTHON || 'python3', [fileURLToPath(new URL('../../scripts/filename-test-fixture.py', import.meta.url)), folder]);
    const requests = [];
    const reader = await createFilenameCatalog(pathToFileURL(join(folder,'public/manifest.json')), (url, options) => {
      requests.push(new URL(url).pathname);
      return localFetch(url, options);
    });
    assert.equal(requests.length, 1, 'catalog information only loads the manifest');
    await reader.search({});
    await reader.search({scope:'all', retained:'no'});
    assert.ok(!requests.some(path => /(?:groups|document_rows)\.bin$/.test(path)), 'browsing defers search and detail indexes');
    await reader.search({q:'alias'});
    assert.equal(requests.filter(path => path.endsWith('/groups.bin')).length, 1);
    assert.ok(!requests.some(path => path.endsWith('/document_rows.bin')), 'search does not load detail navigation');
    await reader.entry('0');
    assert.equal(requests.filter(path => path.endsWith('/document_rows.bin')).length, 1);

    const expected = JSON.parse(await readFile(join(folder,'expected.json')));
    for (const { query, result } of expected) {
      for (const row of result.rows) { delete row.source_id; delete row.document_id; }
      assert.deepEqual(await reader.search(query), result, JSON.stringify(query));
    }
    const sources = JSON.parse(await readFile(join(folder,'source-records.json')));
    for (const source of sources) {
      const detail = await reader.entry(source.source_id, 'b'.repeat(32));
      assert.deepEqual(detail.record, source);
      assert.equal(detail.saved_file_available, false);
      assert.equal(detail.published_only, true);
    }
    assert.equal((await reader.entry('0')).sources.length, 2);
    assert.deepEqual((await reader.entry('2')).origin.pages[0].titles, ['Hearing page']);
    await assert.rejects(reader.entry('0', 'stale'), /different catalog snapshot/);
    await assert.rejects(reader.entry('unknown'), /not present/);
    await assert.rejects(reader.search({field:'missing'}), /Unknown search field/);
    const controller = new AbortController(); controller.abort();
    await assert.rejects(reader.search({q:'anything'}, controller.signal), {name:'AbortError'});

    let release, started;
    const pending = new Promise(resolve => { release = resolve; });
    const loading = new Promise(resolve => { started = resolve; });
    let groupLoads = 0;
    const concurrent = await createFilenameCatalog(pathToFileURL(join(folder,'public/manifest.json')), async (url, options) => {
      if (new URL(url).pathname.endsWith('/groups.bin')) { groupLoads++; started(); await pending; }
      return localFetch(url, options);
    });
    const cancelled = new AbortController();
    const first = concurrent.search({q:'alias'}, cancelled.signal);
    const rejected = assert.rejects(first, {name:'AbortError'});
    await loading;
    const second = concurrent.search({q:'alias'});
    cancelled.abort(); release();
    await rejected;
    assert.equal((await second).total, 1, 'a cancelled query does not cancel a shared index load');
    assert.equal(groupLoads, 1);
    let attempts = 0;
    const retrying = await createFilenameCatalog(pathToFileURL(join(folder,'public/manifest.json')), (url, options) => {
      if (new URL(url).pathname.endsWith('/groups.bin') && attempts++ === 0) return new Response('', {status:503});
      return localFetch(url, options);
    });
    await assert.rejects(retrying.search({q:'alias'}), /navigation index/);
    assert.equal((await retrying.search({q:'alias'})).total, 1, 'failed lazy loads can retry');
    assert.equal(attempts, 2);
  } finally { await rm(folder, { recursive: true, force: true }); }
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

test('accepted recoveries update saved filtering and summaries without changing original source values', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'filename-recovery-'));
  try {
    execFileSync(process.env.PYTHON || 'python3', [fileURLToPath(new URL('../../scripts/filename-test-fixture.py', import.meta.url)), folder]);
    const root = pathToFileURL(join(folder,'public/manifest.json')).href;
    const manifest = JSON.parse(await readFile(new URL(root)));
    const groupBytes = await readFile(new URL(manifest.files.groups.path, root));
    const originals = JSON.parse(await readFile(join(folder,'source-records.json')));
    const positions = [0,2,5];
    const recoveries = positions.map(row => ({original_url: originals[row].source_url, recovered_url:`http://archive.test/${row}.pdf`,
      body_key:`bodies/sha256/aa/${'a'.repeat(64)}.gz`, kind:'pdf', recovery_status:'recovered', recovery_basis:'user_accepted_url_variant'}));
    const data = {version:1,catalog_id:manifest.info.catalog_id,rows:manifest.info.rows,entries:manifest.info.entries,recoveries,
      sources: positions.map((row,i)=>[row,i]), groups:positions.map((row,i)=>[groupBytes.readUInt32LE(row*4),[i]])};
    const bytes = Buffer.from(JSON.stringify(data));
    const sha256 = createHash('sha256').update(bytes).digest('hex');
    const statusPath = hash => `releases/${hash.slice(0,32)}/${hash.slice(32)}/viewer-v2/recovery-status.json`;
    const descriptor = {path:statusPath(sha256),bytes:bytes.length,sha256};
    const pointer = {version:1,catalog_id:manifest.info.catalog_id,manifest:`releases/${'c'.repeat(32)}/manifest.json`,recovery:descriptor};
    // Keep fixture payload paths at their original location while exercising the real pointer/sidecar path.
    const remote = structuredClone(manifest);
    for(const item of Object.values(remote.files)) item.path = new URL(item.path,root).href;
    remote.ids = new URL(remote.ids,root).href;
    const fetcher = (url,options) => String(url)===root ? Promise.resolve(Response.json(pointer))
      : String(url).endsWith('/recovery-status.json') ? Promise.resolve(new Response(bytes))
      : String(url).includes('/releases/') ? Promise.resolve(Response.json(remote)) : localFetch(url,options);
    const reader = await createFilenameCatalog(root, fetcher);
    assert.equal((await reader.search({q:'unfetched',retained:'no'})).total,0);
    const results = await reader.search({q:'unfetched',retained:'yes'});
    assert.equal(results.total,2);
    assert.ok(results.rows.every(row=>row.retained && row.recovery.recovery_status==='recovered'));
    for(const position of positions) {
      const detail=await reader.entry(String(position));
      assert.deepEqual(detail.record,{...originals[position],recovery:recoveries[positions.indexOf(position)]});
      assert.equal(detail.recovery.recovery_status,'recovered');
      assert.equal(detail.document.recovery.recovery_status,'recovered');
      assert.equal(detail.sources.find(source=>source.source_id===originals[position].source_id).retained,true);
      assert.equal(detail.saved_file_available,false,'status does not claim a public body download exists');
    }
    const canonical=await reader.entry('1');
    assert.deepEqual(canonical.record,originals[1]);
    assert.equal(canonical.recovery.original_url,originals[0].source_url);
    const damaged = async (url,options) => String(url).endsWith('/recovery-status.json') ? new Response(Buffer.from('{}')) : fetcher(url,options);
    await assert.rejects(createFilenameCatalog(root,damaged),/failed verification/);
    const wrong = {...data,catalog_id:'d'.repeat(32)};
    const wrongBytes=Buffer.from(JSON.stringify(wrong));
    const wrongHash=createHash('sha256').update(wrongBytes).digest('hex');
    await assert.rejects(createFilenameCatalog(root,(url,options)=>String(url)===root
      ? Promise.resolve(Response.json({...pointer,recovery:{path:statusPath(wrongHash),bytes:wrongBytes.length,sha256:wrongHash}}))
      : String(url).endsWith('/recovery-status.json') ? Promise.resolve(new Response(wrongBytes)) : fetcher(url,options)),/different catalog/);
  } finally { await rm(folder,{recursive:true,force:true}); }
});
