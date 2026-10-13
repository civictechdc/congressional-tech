import assert from 'node:assert/strict';
import { test } from 'node:test';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, open, stat, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { createFilenameCatalog, rangeFile, sourceContext } from './filename-catalog.mjs';

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
    const reader = await createFilenameCatalog(pathToFileURL(join(folder,'public/manifest.json')), localFetch);
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
  } finally { await rm(folder, { recursive: true, force: true }); }
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
