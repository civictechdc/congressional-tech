import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { gzipSync } from 'node:zlib';
import test from 'node:test';
import { createCatalogSource, createPublicationSource, decodeGzipJson, normalizeCatalog, openPublicationReader } from './data-source.ts';

const fixtureUrl = new URL('./__fixtures__/committee-explorer-preview.json', import.meta.url);
const fixture = JSON.parse(await readFile(fixtureUrl, 'utf8'));
const encode = value => new TextEncoder().encode(JSON.stringify(value));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const pointerUrl = 'https://example.test/explorer/CURRENT.json';

function publication({ mediaType = 'application/json', bytes = encode(fixture), catalogPatch = {}, manifestPatch = {} } = {}) {
  const manifest = {
    schema_version: fixture.schema_version, publication_id: 'release-a',
    partitions: [{ role: 'download', schema_name: 'committee_meeting.Catalog', schema_version: fixture.schema_version,
      media_type: mediaType, path: 'catalog.data', byte_size: bytes.length, sha256: hash(bytes), record_count: fixture.records.length, ...catalogPatch }],
    ...manifestPatch,
  };
  const manifestBytes = encode(manifest);
  const pointer = { schema_version: fixture.schema_version, publication_id: 'release-a', manifest_path: 'releases/a/manifest.json', manifest_sha256: hash(manifestBytes), media_type: 'application/json' };
  const resources = new Map([
    [pointerUrl, encode(pointer)],
    ['https://example.test/explorer/releases/a/manifest.json', manifestBytes],
    ['https://example.test/explorer/releases/a/catalog.data', bytes],
  ]);
  const requests = [];
  const fetcher = async (url, options) => {
    requests.push({ url: String(url), signal: options.signal });
    return new Response(resources.get(String(url)), { status: resources.has(String(url)) ? 200 : 404 });
  };
  return { resources, requests, fetcher };
}

test('JSON source normalizes the actual model fixture without changing IDs or date precision', async () => {
  const source = createCatalogSource({ url: 'fixture', fetcher: async () => new Response(encode(fixture)) });
  const loaded = await source.load();
  assert.equal(loaded.schemaVersion, fixture.schema_version);
  assert.deepEqual(loaded.records, fixture.records);
  assert.deepEqual(loaded.sources, fixture.sources);
  assert.ok(Object.isFrozen(loaded.records));
});

test('publication adapter discovers relative paths and verifies manifest and catalog before returning records', async () => {
  const { fetcher, requests } = publication();
  const signal = new AbortController().signal;
  const loaded = await createPublicationSource({ pointerUrl, fetcher }).load({ signal });
  assert.equal(loaded.publication.publication_id, 'release-a');
  assert.equal(loaded.records.length, fixture.records.length);
  assert.equal(requests.length, 3);
  assert.ok(requests.every(request => request.signal === signal));
});

test('a different encoding can produce the same snapshot through an injected decoder', async () => {
  const bytes = new Uint8Array([80, 65, 82, 49]);
  const { fetcher } = publication({ mediaType: 'application/vnd.apache.parquet', bytes });
  let decoded = 0;
  const source = createPublicationSource({ pointerUrl, fetcher, decoders: {
    'application/vnd.apache.parquet': async input => { assert.deepEqual(input, bytes); decoded++; return fixture; },
  } });
  assert.deepEqual((await source.load()).records, fixture.records);
  assert.equal(decoded, 1);
  // This tests the seam, not an actual Parquet decoder.
});

test('unconfigured encodings fail explicitly before requesting a catalog', async () => {
  const { fetcher, requests } = publication({ mediaType: 'application/vnd.apache.parquet' });
  await assert.rejects(createPublicationSource({ pointerUrl, fetcher }).load(), /No explorer decoder/);
  assert.equal(requests.length, 2);
});

test('rejects changed bytes, descriptor counts, and mixed releases', async () => {
  for (const options of [
    { catalogPatch: { sha256: '0'.repeat(64) } },
    { catalogPatch: { byte_size: 1 } },
    { catalogPatch: { record_count: 1 } },
    { manifestPatch: { publication_id: 'different-release' } },
  ]) {
    const { fetcher } = publication(options);
    await assert.rejects(createPublicationSource({ pointerUrl, fetcher }).load(), /differs|different publications/);
  }
  const corrupt = publication();
  corrupt.resources.set('https://example.test/explorer/releases/a/manifest.json', encode({ schema_version: fixture.schema_version }));
  await assert.rejects(createPublicationSource({ pointerUrl, fetcher: corrupt.fetcher }).load(), /manifest checksum/);
});

test('rejects partial catalogs, incompatible versions, and duplicate identity', () => {
  assert.throws(() => normalizeCatalog({ ...fixture, scope: 'selection' }), /complete explorer catalog/);
  assert.throws(() => normalizeCatalog({ ...fixture, schema_version: 'future' }), /Unsupported explorer schema/);
  assert.throws(() => normalizeCatalog({ ...fixture, records: [...fixture.records, fixture.records[0]] }), /Duplicate explorer identity/);
  assert.throws(() => normalizeCatalog({ ...fixture, records: [{ kind: 'meeting', id: 123 }] }), /string ID/);
});

test('an aborted request neither fetches nor returns a stale snapshot', async () => {
  const controller = new AbortController();
  controller.abort();
  let called = false;
  const source = createCatalogSource({ url: 'fixture', fetcher: async () => { called = true; return new Response(encode(fixture)); } });
  await assert.rejects(source.load({ signal: controller.signal }), error => error.name === 'AbortError');
  assert.equal(called, false);
  const duringDecode = new AbortController();
  const delayed = createCatalogSource({ url: 'fixture', fetcher: async () => new Response(encode(fixture)), decode: () => { duringDecode.abort(); return fixture; } });
  await assert.rejects(delayed.load({ signal: duringDecode.signal }), error => error.name === 'AbortError');
});

test('HTTP failure is preserved instead of becoming an empty result', async () => {
  const source = createCatalogSource({ url: 'fixture', fetcher: async () => new Response('', { status: 503 }) });
  await assert.rejects(source.load(), /HTTP 503/);
});

test('explicit gzip decoder preserves domain values without a UI format switch', async () => {
  const bytes = gzipSync(encode(fixture));
  assert.deepEqual(await decodeGzipJson(bytes), fixture);
  const files = publication({mediaType: 'application/vnd.committee-explorer+json+gzip', bytes});
  const loaded = await createPublicationSource({pointerUrl, fetcher: files.fetcher}).load();
  assert.deepEqual(loaded.records, fixture.records);
});

test('openPublicationReader rejects retired legacy sharded JSON publications and requires Parquet partitions', async () => {
  const { fetcher } = publication();
  await assert.rejects(
    openPublicationReader({ pointerUrl, fetcher }),
    /Explorer publication requires Parquet partitions; legacy sharded JSON \(\.data\) has been retired/,
  );
});
