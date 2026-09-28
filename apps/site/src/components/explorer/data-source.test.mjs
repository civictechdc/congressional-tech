import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { gzipSync } from 'node:zlib';
import test from 'node:test';
import { createCatalogSource, createPublicationSource, decodeGzipJson, normalizeCatalog, openPublicationReader } from './data-source.js';

const fixtureUrl = new URL('../../../../../docs/youtube-coverage/committee-explorer-preview.json', import.meta.url);
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

function partitioned({ wrongRecord = false, wrongBucketCount = false, relatedMaterials = [] } = {}) {
  const result = publication();
  const manifestUrl = 'https://example.test/explorer/releases/a/manifest.json';
  const manifest = JSON.parse(new TextDecoder().decode(result.resources.get(manifestUrl)));
  const meeting = fixture.records.find(r => r.kind === 'meeting');
  const source = fixture.sources[0];
  const paths = { meeting: 'details/selected.data', source: 'sources/selected.data' };
  function artifact(path, role, schemaName, value, count) {
    const bytes = encode(value);
    result.resources.set(new URL(path, manifestUrl).href, bytes);
    manifest.partitions.push({ path, role, schema_name: schemaName, schema_version: fixture.schema_version,
      media_type: 'application/json', byte_size: bytes.length, sha256: hash(bytes), record_count: count });
  }
  artifact('indexes/meetings.data', 'index', 'committee_explorer.meetings', { schema_version: fixture.schema_version, rows: [{ id: meeting.id }] }, 1);
  artifact('coverage.data', 'coverage', 'committee_explorer.coverage', { metrics: [] }, 0);
  artifact(paths.meeting, 'details', 'committee_explorer.records', { schema_version: fixture.schema_version, records: [wrongRecord ? { ...meeting, id: 'different' } : meeting, ...relatedMaterials] }, 1 + relatedMaterials.length);
  artifact(paths.source, 'sources', 'committee_explorer.sources', { schema_version: fixture.schema_version, sources: [source] }, 1);
  const buckets = {}, locations = {};
  for (const [record, path] of [[meeting, paths.meeting], ...relatedMaterials.map(record => [record, paths.meeting]), [source, paths.source]]) {
    const key = `${record.kind}/${record.id}`, bucket = hash(new TextEncoder().encode(key)).slice(0, 2);
    buckets[bucket] = `indexes/locations/${bucket}.data`;
    (locations[bucket] ||= {})[key] = path;
  }
  for (const [bucket, value] of Object.entries(locations)) artifact(buckets[bucket], 'index', 'committee_explorer.location-bucket', { schema_version: fixture.schema_version, locations: value }, Object.keys(value).length);
  artifact('indexes/locations.data', 'index', 'committee_explorer.locations', { schema_version: fixture.schema_version, key_format: '<kind>/<id>', bucket_algorithm: 'sha256-prefix-2', buckets }, wrongBucketCount ? 0 : Object.keys(buckets).length);
  const aspects = ['recording', 'transcript', 'documents', 'witnesses', 'captions'];
  const evidence = state => Object.fromEntries(aspects.map(aspect => [aspect, state]));
  const queryRows = [
    { kind: 'meeting', id: meeting.id, title: 'Infrastructure hearing', congress: 119, chamber: 'house', date: '2026-01-03', committee_ids: ['joint-a', 'joint-b'], evidence_states: evidence('reported') },
    { kind: 'meeting', id: 'other', title: 'Oversight hearing', congress: 119, chamber: 'senate', date: '2026-02-01', committee_ids: ['joint-b'], evidence_states: evidence('inferred') },
    { kind: 'meeting', id: 'older', title: 'Earlier oversight hearing', congress: 118, chamber: 'house', date: '2024-01-01', committee_ids: ['joint-a'], evidence_states: evidence('unchecked') },
  ];
  const queryParts = [119, 118].map(congress => {
    const path = `queries/${congress}.data`, rows = queryRows.filter(row => row.congress === congress);
    artifact(path, 'index', 'committee_explorer.query-rows', { schema_version: fixture.schema_version, rows }, rows.length);
    return { kind: 'meeting', congress, path, record_count: rows.length };
  });
  artifact('queries/root.data', 'index', 'committee_explorer.queries', { schema_version: fixture.schema_version, default_congress: 119, congresses: [119, 118], kinds: [{kind: 'meeting', count: 3}], committee_labels: {'joint-a': 'Committee A', 'joint-b': 'Committee B'}, partitions: queryParts }, queryParts.length);
  const relationKey = `meeting/${meeting.id}`, relationBucket = hash(new TextEncoder().encode(relationKey)).slice(0, 2);
  const relationPath = 'relations/selected.data';
  artifact(relationPath, 'index', 'committee_explorer.relation-bucket', { schema_version: fixture.schema_version, relations: {[relationKey]: [{kind: source.kind, id: source.id, relation: 'evidence'}, ...relatedMaterials.map(({kind,id}) => ({kind,id}))]} }, 1);
  artifact('relations/root.data', 'index', 'committee_explorer.relations', {schema_version: fixture.schema_version, key_format: '<kind>/<id>', bucket_algorithm: 'sha256-prefix-2', buckets: {[relationBucket]: relationPath}}, 1);
  const manifestBytes = encode(manifest);
  result.resources.set(manifestUrl, manifestBytes);
  const pointer = JSON.parse(new TextDecoder().decode(result.resources.get(pointerUrl)));
  result.resources.set(pointerUrl, encode({ ...pointer, manifest_sha256: hash(manifestBytes) }));
  return { ...result, meeting, source, paths, manifestUrl };
}

test('partition reader retrieves index, selected records and evidence without requesting the Catalog download', async () => {
  const files = partitioned();
  const reader = await openPublicationReader({ pointerUrl, fetcher: files.fetcher });
  assert.equal((await reader.getMeetingIndex())[0].id, files.meeting.id);
  const requested = [files.meeting, files.source, files.meeting].map(({ kind, id }) => ({ kind, id }));
  assert.deepEqual(await reader.getRecords(requested), [files.meeting, files.source, files.meeting]);
  assert.deepEqual(await reader.getCoverage(), { metrics: [] });
  const fetched = files.requests.length;
  assert.deepEqual(await reader.getRecords(requested), [files.meeting, files.source, files.meeting]);
  assert.equal(files.requests.length, fetched);
  assert.ok(!files.requests.some(r => r.url.endsWith('/catalog.data')));
  assert.equal(await reader.getRecord({ kind: 'meeting', id: 'not-in-release' }), undefined);
});

test('a published locator that does not match the chunk fails instead of declaring a record absent', async () => {
  const files = partitioned({ wrongRecord: true });
  const reader = await openPublicationReader({ pointerUrl, fetcher: files.fetcher });
  await assert.rejects(reader.getRecord(files.meeting), /lookup and detail contents disagree/);
  const missingBuckets = partitioned({ wrongBucketCount: true });
  const invalid = await openPublicationReader({ pointerUrl, fetcher: missingBuckets.fetcher });
  await assert.rejects(invalid.getRecord(files.meeting), /lookup bucket count differs/);
});

test('reader pins one release, rejects corrupted chunks and permits retry without a poisoned cache', async () => {
  const files = partitioned();
  const reader = await openPublicationReader({ pointerUrl, fetcher: files.fetcher });
  files.resources.set(pointerUrl, encode({ publication_id: 'changed-after-open' }));
  const path = new URL(files.paths.meeting, files.manifestUrl).href;
  const valid = files.resources.get(path);
  files.resources.set(path, new Uint8Array(valid.length));
  await assert.rejects(reader.getRecord(files.meeting), /checksum differs/);
  files.resources.set(path, valid);
  assert.deepEqual(await reader.getRecord(files.meeting), files.meeting);
  assert.equal(files.requests.filter(r => r.url === pointerUrl).length, 1);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(reader.getRecord(files.meeting, { signal: controller.signal }), error => error.name === 'AbortError');
});

test('query reader scopes by Congress, filters before paging, and fetches related records', async () => {
  const files = partitioned();
  const reader = await openPublicationReader({ pointerUrl, fetcher: files.fetcher });
  const latest = await reader.search({limit: 1});
  assert.equal(latest.total, 2);
  assert.equal(latest.rows.length, 1);
  assert.ok(!files.requests.some(r => r.url.endsWith('/queries/118.data')));
  const older = await reader.search({congress: 'all', q: 'oversight', dateTo: '2024-12-31'});
  assert.equal(older.total, 1);
  assert.equal(older.rows[0].id, 'older');
  const byState = await reader.search({aspect: 'recording', evidence: 'inferred'});
  assert.equal(byState.total, 1);
  assert.equal(byState.rows[0].chamber, 'senate');
  assert.deepEqual((await reader.getRelated(files.meeting)).records, [files.source]);
  assert.equal((await reader.getRelated(files.meeting, {offset: 1})).total, 1);
  assert.equal((await reader.getRelated(files.meeting, {offset: 1})).records.length, 0);
});

test('legacy related-material queries count every category before filtering and paging', async () => {
  const relatedMaterials = Array.from({length:36}, (_, index) => ({kind:'material', id:`material-${index}`, title:`Attachment ${index}`,
    details:index === 35 ? {type:'recording'} : {type:'document', category:index < 30 ? 'statement' : 'supporting'}}));
  const files = partitioned({relatedMaterials});
  const reader = await openPublicationReader({pointerUrl, fetcher:files.fetcher});
  const page = await reader.getRelated(files.meeting, {kind:'material', materialType:'document', category:'Statement', offset:25, limit:25});
  assert.equal(page.total, 30);
  assert.equal(page.records.length, 5);
  assert.ok(page.records.every(record => record.details.category === 'statement'));
  assert.deepEqual(page.categories, [{label:'Statement',count:30},{label:'Supporting',count:5}]);
  assert.equal((await reader.getRelated(files.meeting, {kind:'material', materialType:'recording'})).total, 1);
});

test('filtered coverage uses published states and reconciles shared committee denominators', async () => {
  const files = partitioned();
  const reader = await openPublicationReader({ pointerUrl, fetcher: files.fetcher });
  const coverage = await reader.getCoverage({filters: {congress: 119}});
  assert.equal(coverage.state_breakdown.recording.denominator, 2);
  assert.equal(coverage.state_breakdown.recording.states.reported, 1);
  assert.equal(coverage.state_breakdown.recording.states.inferred, 1);
  assert.equal(coverage.groups.committee.find(g => g.key === 'joint-b').denominator, 2);
  assert.equal(coverage.groups.committee.find(g => g.key === 'joint-a').denominator, 1);
  const filtered = await reader.getCoverage({filters: {chamber: 'house', q: 'infrastructure'}});
  assert.equal(filtered.state_breakdown.transcript.denominator, 1);
  const empty = await reader.getCoverage({filters: {q: 'not a meeting'}});
  assert.equal(empty.state_breakdown.transcript.denominator, 0);
  assert.equal(empty.groups.month.length, 0);
});

test('explicit gzip decoder preserves domain values without a UI format switch', async () => {
  const bytes = gzipSync(encode(fixture));
  assert.deepEqual(await decodeGzipJson(bytes), fixture);
  const files = publication({mediaType: 'application/vnd.committee-explorer+json+gzip', bytes});
  const loaded = await createPublicationSource({pointerUrl, fetcher: files.fetcher}).load();
  assert.deepEqual(loaded.records, fixture.records);
});
