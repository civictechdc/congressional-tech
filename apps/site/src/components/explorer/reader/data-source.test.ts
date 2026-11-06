import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { gzipSync } from 'node:zlib';
import test from 'node:test';
import { decodeGzipJson, openPublicationReader } from './data-source.ts';

const schemaVersion = '0.1.0-draft.3';
const queryInfo = {
  storage: 'parquet', query_columns: ['id', 'title'], default_congress: 119,
  kinds: [{ kind: 'meeting' }], congresses: [119],
};
const encode = value => new TextEncoder().encode(JSON.stringify(value));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const pointerUrl = 'https://example.test/explorer/CURRENT.json';
const manifestUrl = 'https://example.test/explorer/releases/a/manifest.json';
const indexUrl = 'https://example.test/explorer/releases/a/queries.json';

function publication({ mediaType = 'application/json', bytes = encode(queryInfo), indexPatch = {},
  tablePatch = {}, manifestPatch = {}, pointerPatch = {} } = {}) {
  const manifest = {
    schema_version: schemaVersion, publication_id: 'release-a',
    partitions: [
      { role: 'index', schema_name: 'committee_explorer.queries', schema_version: schemaVersion,
        media_type: mediaType, path: 'queries.json', byte_size: bytes.length,
        sha256: hash(bytes), record_count: 1, ...indexPatch },
      // Metadata-only tests never read this table. Actual Parquet decoding,
      // row counts and ranges are exercised in parquet-source.test.ts.
      { role: 'index', schema_name: 'committee_explorer.parquet.meeting', schema_version: schemaVersion,
        media_type: 'application/vnd.apache.parquet', path: 'meetings.parquet',
        byte_size: 8, sha256: 'a'.repeat(64), record_count: 0, ...tablePatch },
    ],
    ...manifestPatch,
  };
  const manifestBytes = encode(manifest);
  const pointer = { schema_version: schemaVersion, publication_id: 'release-a',
    manifest_path: 'releases/a/manifest.json', manifest_sha256: hash(manifestBytes), ...pointerPatch };
  const resources = new Map([[pointerUrl, encode(pointer)], [manifestUrl, manifestBytes], [indexUrl, bytes]]);
  const requests = [];
  const fetcher = async (url, options) => {
    requests.push({ url: String(url), signal: options.signal });
    return new Response(resources.get(String(url)), { status: resources.has(String(url)) ? 200 : 404 });
  };
  return { resources, requests, fetcher };
}

test('current reader verifies relative manifest and metadata without eagerly loading tables', async () => {
  const { fetcher, requests } = publication();
  const signal = new AbortController().signal;
  const reader = await openPublicationReader({ pointerUrl, fetcher, signal });
  assert.equal(requests.length, 2);
  const info = await reader.getQueryInfo({ signal });
  assert.equal(info.storage, 'parquet');
  assert.deepEqual(info.query_columns, queryInfo.query_columns);
  assert.deepEqual(requests.map(request => request.url), [pointerUrl, manifestUrl, indexUrl]);
  assert.ok(requests.every(request => request.signal === signal));
});

test('query metadata encoding uses the declared decoder and schema context', async () => {
  const bytes = new Uint8Array([1, 2, 3]);
  const mediaType = 'application/vnd.example.query-index';
  const { fetcher } = publication({ mediaType, bytes });
  let decoded = 0;
  const reader = await openPublicationReader({ pointerUrl, fetcher, decoders: {
    [mediaType]: async (input, context) => {
      assert.deepEqual(input, bytes);
      assert.deepEqual(context, { schemaName: 'committee_explorer.queries', schemaVersion });
      decoded++;
      return queryInfo;
    },
  } });
  assert.deepEqual((await reader.getQueryInfo()).query_columns, queryInfo.query_columns);
  assert.equal(decoded, 1);
});

test('unconfigured metadata encodings fail before requesting the artifact', async () => {
  const { fetcher, requests } = publication({ mediaType: 'application/vnd.example.query-index' });
  const reader = await openPublicationReader({ pointerUrl, fetcher });
  await assert.rejects(reader.getQueryInfo(), /No explorer decoder/);
  assert.equal(requests.length, 2);
});

test('rejects changed metadata bytes and invalid descriptors', async () => {
  for (const indexPatch of [{ sha256: '0'.repeat(64) }, { byte_size: 1 }, { record_count: -1 }]) {
    const { fetcher } = publication({ indexPatch });
    const reader = await openPublicationReader({ pointerUrl, fetcher });
    await assert.rejects(reader.getQueryInfo(), /differs|incomplete or incompatible/);
  }
});

test('rejects mixed releases and a manifest that no longer matches its pointer', async () => {
  const mixed = publication({ manifestPatch: { publication_id: 'different-release' } });
  await assert.rejects(openPublicationReader({ pointerUrl, fetcher: mixed.fetcher }), /different publications/);
  const corrupt = publication();
  corrupt.resources.set(manifestUrl, encode({ schema_version: schemaVersion }));
  await assert.rejects(openPublicationReader({ pointerUrl, fetcher: corrupt.fetcher }), /manifest checksum/);
});

test('refuses retired and unknown schema versions in pointers, manifests and every partition', async () => {
  for (const version of ['0.1.0-draft.2', 'future']) {
    for (const options of [
      { pointerPatch: { schema_version: version } },
      { manifestPatch: { schema_version: version } },
      { indexPatch: { schema_version: version } },
      { tablePatch: { schema_version: version } },
    ]) {
      const { fetcher } = publication(options);
      await assert.rejects(openPublicationReader({ pointerUrl, fetcher }), /pointer|manifest|incompatible/);
    }
  }
});

test('an aborted open never fetches and aborting metadata decoding never returns stale data', async () => {
  const beforeFetch = new AbortController();
  beforeFetch.abort();
  const files = publication();
  await assert.rejects(openPublicationReader({ pointerUrl, fetcher: files.fetcher, signal: beforeFetch.signal }),
    error => error.name === 'AbortError');
  assert.equal(files.requests.length, 0);
  const duringDecode = new AbortController();
  const reader = await openPublicationReader({ pointerUrl, fetcher: files.fetcher, decoders: {
    'application/json': () => { duringDecode.abort(); return queryInfo; },
  } });
  await assert.rejects(reader.getQueryInfo({ signal: duringDecode.signal }), error => error.name === 'AbortError');
});

test('HTTP failure is preserved instead of becoming an empty reader', async () => {
  await assert.rejects(openPublicationReader({ pointerUrl, fetcher: async () => new Response('', { status: 503 }) }), /HTTP 503/);
});

test('gzip query metadata preserves values without changing the table reader', async () => {
  const bytes = gzipSync(encode(queryInfo));
  assert.deepEqual(await decodeGzipJson(bytes), queryInfo);
  const { fetcher } = publication({ mediaType: 'application/vnd.committee-explorer+json+gzip', bytes });
  const reader = await openPublicationReader({ pointerUrl, fetcher });
  assert.deepEqual((await reader.getQueryInfo()).query_columns, queryInfo.query_columns);
});

test('rejects retired whole-JSON and sharded JSON publications', async () => {
  const { fetcher } = publication({ manifestPatch: { partitions: [{
    role: 'download', schema_name: 'committee_meeting.Catalog', schema_version: schemaVersion,
    media_type: 'application/json', path: 'catalog.data',
  }] } });
  await assert.rejects(openPublicationReader({ pointerUrl, fetcher }), /Explorer publication requires Parquet partitions/);
});
