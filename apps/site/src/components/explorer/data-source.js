import { groupCommitteeTerms, matches, pageBounds, summarizeCoverage } from './query-utils.js';
import { selectRelatedMaterials } from './related-materials.js';
/**
 * The frontend's data boundary contains no UI or chart logic. Its consumers do
 * not need storage paths or decoding libraries. See data-source.d.ts for the
 * injected interfaces.
 */
const SCHEMA_VERSION = '0.1.0-draft.2';
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);

export function decodeJson(bytes) {
  return JSON.parse(new TextDecoder().decode(bytes));
}

export async function decodeGzipJson(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return decodeJson(new Uint8Array(await new Response(stream).arrayBuffer()));
}

export function normalizeCatalog(document) {
  if (!isObject(document) || document.schema_version !== SCHEMA_VERSION) {
    throw new Error('Unsupported explorer schema version. Refresh the application or use a compatible publication.');
  }
  if (document.scope !== 'complete' || !Array.isArray(document.records) || !Array.isArray(document.sources)) {
    throw new Error('Expected a complete explorer catalog, not a partial record file.');
  }
  const seen = new Set();
  for (const [group, items] of [['records', document.records], ['sources', document.sources]]) {
    for (const item of items) {
      if (!isObject(item) || typeof item.kind !== 'string' || !item.kind.trim()
        || typeof item.id !== 'string' || !item.id.trim()) {
        throw new Error('Explorer records require a kind and a nonempty string ID.');
      }
      if ((item.kind === 'source_record') !== (group === 'sources')) {
        throw new Error('Explorer source observations must be separate from domain records.');
      }
      const key = JSON.stringify([item.kind, item.id]);
      if (seen.has(key)) throw new Error(`Duplicate explorer identity: ${key}`);
      seen.add(key);
    }
  }
  // Full domain and relationship validation happens in the Python exporter.
  // These boundary checks prevent partial or incompatible bytes reaching the UI.
  return Object.freeze({
    schemaVersion: document.schema_version,
    records: Object.freeze(document.records),
    sources: Object.freeze(document.sources),
  });
}

async function readBytes(fetcher, url, signal) {
  signal?.throwIfAborted();
  const response = await fetcher(url, { signal });
  if (!response.ok) throw new Error(`Explorer data request failed (HTTP ${response.status}).`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  signal?.throwIfAborted();
  return bytes;
}

async function checkDigest(bytes, expected, label) {
  if (!/^[0-9a-f]{64}$/.test(expected || '')) throw new Error(`Explorer ${label} has no valid checksum.`);
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  const actual = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
  if (actual !== expected) throw new Error(`Explorer ${label} checksum differs from its publication metadata.`);
}

/** A bounded complete-catalog source; the caller supplies its location/decoder. */
export function createCatalogSource({ url, fetcher = globalThis.fetch, decode = decodeJson }) {
  return {
    async load({ signal } = {}) {
      const document = await decode(await readBytes(fetcher, url, signal));
      signal?.throwIfAborted();
      return normalizeCatalog(document);
    },
  };
}

/**
 * Discover the selected release through CURRENT and its manifest. The manifest's
 * media_type selects a decoder; a .json/.parquet suffix never does.
 * Extra decoders are injected only by the application's composition code.
 */
async function openVerifiedPublication({ pointerUrl, fetcher = globalThis.fetch, decoders = {}, signal }) {
  const available = { 'application/json': decodeJson, 'application/vnd.committee-explorer+json+gzip': decodeGzipJson, ...decoders };
  const pointerLocation = new URL(pointerUrl, globalThis.location?.href);
  const pointer = decodeJson(await readBytes(fetcher, pointerLocation, signal));
  if (!isObject(pointer) || pointer.schema_version !== SCHEMA_VERSION || typeof pointer.manifest_path !== 'string'
    || typeof pointer.publication_id !== 'string') {
    throw new Error('The explorer release pointer does not identify a manifest.');
  }
  const manifestUrl = new URL(pointer.manifest_path, pointerLocation);
  const manifestBytes = await readBytes(fetcher, manifestUrl, signal);
  await checkDigest(manifestBytes, pointer.manifest_sha256, 'manifest');
  const manifest = decodeJson(manifestBytes);
  if (!isObject(manifest) || manifest.schema_version !== SCHEMA_VERSION || !Array.isArray(manifest.partitions)) {
    throw new Error('Unsupported explorer publication manifest.');
  }
  if (pointer.publication_id !== manifest.publication_id) {
    throw new Error('Explorer release pointer and manifest identify different publications.');
  }
  function select(role, schemaName) {
    const candidates = manifest.partitions.filter(p => p.role === role && p.schema_name === schemaName);
    if (candidates.length !== 1) throw new Error(`Expected one ${schemaName} artifact in this explorer publication.`);
    return candidates[0];
  }
  async function readPartition(part, signal) {
    const mediaType = part.media_type || 'application/json'; // draft.2 predates explicit media_type
    const decode = Object.hasOwn(available, mediaType) ? available[mediaType] : undefined;
    if (typeof decode !== 'function') throw new Error(`No explorer decoder is configured for ${mediaType}.`);
    if (typeof part.path !== 'string' || part.schema_version !== SCHEMA_VERSION
      || !Number.isSafeInteger(part.byte_size) || part.byte_size < 0
      || !Number.isSafeInteger(part.record_count) || part.record_count < 0
      || !/^[0-9a-f]{64}$/.test(part.sha256 || '')) {
      throw new Error('The explorer artifact descriptor is incomplete or incompatible.');
    }
    const bytes = await readBytes(fetcher, new URL(part.path, manifestUrl), signal);
    if (bytes.byteLength !== part.byte_size) throw new Error('Explorer artifact size differs from its publication manifest.');
    await checkDigest(bytes, part.sha256, 'artifact');
    const document = await decode(bytes, { schemaName: part.schema_name, schemaVersion: part.schema_version });
    signal?.throwIfAborted();
    return document;
  }
  signal?.throwIfAborted();
  return { manifest: Object.freeze(manifest), manifestUrl, select, readPartition };
}

export function createPublicationSource(options) {
  return {
    async load({ signal } = {}) {
      const publication = await openVerifiedPublication({ ...options, signal });
      const part = publication.select('download', 'committee_meeting.Catalog');
      const snapshot = normalizeCatalog(await publication.readPartition(part, signal));
      if (snapshot.records.length !== part.record_count) throw new Error('Explorer record count differs from its publication manifest.');
      signal?.throwIfAborted();
      return Object.freeze({ ...snapshot, publication: publication.manifest });
    },
  };
}

/** Open one immutable release for index-first browsing and selected-record reads. */
export async function openPublicationReader(options) {
  const publication = await openVerifiedPublication(options);
  if (publication.manifest.partitions.some(part => part.media_type === 'application/vnd.apache.parquet')) {
    const { createParquetReader } = await import('./parquet-source.js');
    return createParquetReader(publication, options.fetcher || globalThis.fetch);
  }
  const descriptors = new Map(publication.manifest.partitions.map(part => [part.path, part]));
  const cache = new Map();
  const queryCache = new Map();
  async function read(part, signal) {
    signal?.throwIfAborted();
    if (cache.has(part.path)) {
      const value = cache.get(part.path);
      cache.delete(part.path);
      cache.set(part.path, value);
      return value;
    }
    const value = await publication.readPartition(part, signal);
    // Cache a few completed chunks only. A canceled request cannot poison the cache.
    cache.set(part.path, value);
    if (cache.size > 8) cache.delete(cache.keys().next().value);
    return value;
  }
  function described(path, schemaName) {
    const part = descriptors.get(path);
    if (!part || part.schema_name !== schemaName) throw new Error('Explorer lookup points to an unadvertised artifact.');
    return part;
  }
  async function checked(part, signal) {
    const value = await read(part, signal);
    if (!isObject(value) || value.schema_version !== SCHEMA_VERSION) throw new Error('Unsupported explorer index or detail schema.');
    return value;
  }
  async function getQueryInfo({ signal } = {}) {
    const part = publication.select('index', 'committee_explorer.queries');
    const info = await checked(part, signal);
    if (!Array.isArray(info.partitions) || info.partitions.length !== part.record_count || !Array.isArray(info.congresses)
      || !Number.isInteger(info.default_congress) || !Array.isArray(info.kinds)) {
      throw new Error('The explorer query index is incomplete.');
    }
    return info;
  }
  async function queryRows(query, signal) {
    const info = await getQueryInfo({ signal });
    const congress = query.congress ?? info.default_congress;
    const kind = query.kind || 'meeting';
    if (!info.kinds.some(entry => entry.kind === kind)) throw new Error('Unsupported explorer query kind.');
    if (congress !== 'all' && !info.congresses.includes(Number(congress))) return [];
    const key = `${kind}/${congress}`;
    if (queryCache.has(key)) return queryCache.get(key);
    const parts = info.partitions.filter(part => part.kind === kind && (congress === 'all' || part.congress === Number(congress)));
    const rows = [];
    // Bound concurrent transfers and keep deterministic published order.
    for (let offset = 0; offset < parts.length; offset += 4) {
      const batches = await Promise.all(parts.slice(offset, offset + 4).map(async entry => {
        const part = described(entry.path, 'committee_explorer.query-rows');
        const document = await checked(part, signal);
        if (!Array.isArray(document.rows) || document.rows.length !== part.record_count
          || document.rows.some(row => row.kind !== kind || typeof row.id !== 'string' || typeof row.title !== 'string')) {
          throw new Error('Explorer query rows disagree with their manifest.');
        }
        return document.rows;
      }));
      for (const batch of batches) for (const row of batch) rows.push(row);
    }
    signal?.throwIfAborted();
    // Large archive-wide scans remain uncached; ordinary Congress views stay responsive.
    if (rows.length <= 50000) {
      queryCache.set(key, rows);
      if (queryCache.size > 2) queryCache.delete(queryCache.keys().next().value);
    }
    return rows;
  }
  async function search(query = {}, { signal } = {}) {
    const rows = groupCommitteeTerms((await queryRows(query, signal)).filter(row => matches(row, query)), query);
    rows.sort((a, b) => (b.date || '').localeCompare(a.date || '') || a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
    const { offset, limit } = pageBounds(query);
    signal?.throwIfAborted();
    return { rows: rows.slice(offset, offset + limit), total: rows.length, offset, limit };
  }
  async function filteredCoverage(filters, signal) {
    const info = await getQueryInfo({ signal });
    const rows = (await queryRows({ ...filters, kind: 'meeting' }, signal)).filter(row => matches(row, filters));
    return summarizeCoverage(info, rows);
  }

  async function getRecords(refs, { signal } = {}) {
    const locatorPart = publication.select('index', 'committee_explorer.locations');
    const locator = await checked(locatorPart, signal);
    if (locator.key_format !== '<kind>/<id>' || locator.bucket_algorithm !== 'sha256-prefix-2' || !isObject(locator.buckets)) {
      throw new Error('Unsupported explorer record lookup format.');
    }
    if (Object.keys(locator.buckets).length !== locatorPart.record_count) throw new Error('Explorer lookup bucket count differs from its manifest.');
    const keys = refs.map(ref => {
      if (typeof ref.kind !== 'string' || !ref.kind || typeof ref.id !== 'string' || !ref.id) throw new Error('A record lookup requires kind and ID.');
      return `${ref.kind}/${ref.id}`;
    });
    const hashes = await Promise.all(keys.map(async key => {
      const digest = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(key)));
      return digest[0].toString(16).padStart(2, '0');
    }));
    const locations = new Map();
    for (const bucket of new Set(hashes)) {
      const path = locator.buckets[bucket];
      if (!path) continue;
      const part = described(path, 'committee_explorer.location-bucket');
      const document = await checked(part, signal);
      if (!isObject(document.locations) || Object.keys(document.locations).length !== part.record_count) throw new Error('Explorer record lookup count differs from its manifest.');
      for (const key of keys) if (Object.hasOwn(document.locations, key)) locations.set(key, document.locations[key]);
    }
    const found = new Map();
    // Read each requested chunk once, even when several requested records share it.
    for (const path of new Set(locations.values())) {
      const part = descriptors.get(path);
      const field = part?.schema_name === 'committee_explorer.sources' ? 'sources' : part?.schema_name === 'committee_explorer.records' ? 'records' : null;
      if (!field) throw new Error('Explorer record lookup does not identify a detail or source artifact.');
      const document = await checked(part, signal);
      if (!Array.isArray(document[field]) || document[field].length !== part.record_count) throw new Error('Explorer detail count differs from its manifest.');
      for (const record of document[field]) {
        if (!isObject(record) || typeof record.kind !== 'string' || typeof record.id !== 'string') throw new Error('Explorer detail has no stable identity.');
        const key = `${record.kind}/${record.id}`;
        if (locations.get(key) === path) {
          if (found.has(key)) throw new Error('Explorer detail contains a duplicate identity.');
          found.set(key, record);
        }
      }
    }
    if (keys.some(key => locations.has(key) && !found.has(key))) throw new Error('Explorer record lookup and detail contents disagree.');
    const committees = [...found.values()].filter(record => record.kind === 'committee_term');
    if (committees.length && (await getQueryInfo({signal})).kinds.some(entry => entry.kind === 'committee_term')) {
      for (const congress of new Set(committees.map(record => record.congress))) {
        const metadata = new Map((await queryRows({kind:'committee_term', congress}, signal)).map(row => [row.id, row]));
        for (const record of committees.filter(record => record.congress === congress)) {
          const row = metadata.get(record.id);
          if (row) found.set(`committee_term/${record.id}`, {...record, committee_types:row.committee_types,
            committee_level:row.committee_level, parent_committee_id:row.parent_committee_id});
        }
      }
    }
    signal?.throwIfAborted();
    return keys.map(key => found.get(key));
  }
  return Object.freeze({
    publication: publication.manifest,
    getQueryInfo,
    search,
    async getRelated(ref, options = {}) {
      const { signal } = options;
      const { offset, limit } = pageBounds(options);
      const part = publication.select('index', 'committee_explorer.relations');
      const root = await checked(part, signal);
      if (root.key_format !== '<kind>/<id>' || root.bucket_algorithm !== 'sha256-prefix-2' || !isObject(root.buckets)
        || Object.keys(root.buckets).length !== part.record_count) throw new Error('Unsupported explorer relationship index.');
      const key = `${ref.kind}/${ref.id}`;
      const digest = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(key)));
      const path = root.buckets[digest[0].toString(16).padStart(2, '0')];
      if (!path) return { records: [], total: 0, offset, limit };
      const bucketPart = described(path, 'committee_explorer.relation-bucket');
      const bucket = await checked(bucketPart, signal);
      if (!isObject(bucket.relations) || Object.keys(bucket.relations).length !== bucketPart.record_count) throw new Error('Explorer relationship count differs from its manifest.');
      const allRefs = bucket.relations[key] || [];
      if (!Array.isArray(allRefs)) throw new Error('Explorer relationships are invalid.');
      const refs = options.kind ? allRefs.filter(r => r.kind === options.kind) : allRefs;
      if (ref.kind === 'committee_term' && options.kind === 'committee_term') {
        const [parent] = await getRecords([ref], { signal });
        const candidates = await getRecords(refs, { signal });
        if (candidates.some(record => !record)) throw new Error('Explorer relationship points to a missing record.');
        const children = candidates.filter(record => (record.parent_committee_id || record.parent?.id) === ref.id && record.congress === parent?.congress);
        return { records: children.slice(offset, offset + limit), total: children.length, offset, limit };
      }
      if (options.kind === 'material') {
        const materials = await getRecords(refs, { signal });
        if (materials.some(record => !record)) throw new Error('Explorer relationship points to a missing record.');
        const selected = selectRelatedMaterials(materials, options);
        return { records: selected.rows.slice(offset, offset + limit), total: selected.rows.length, offset, limit, categories: selected.categories };
      }
      const records = await getRecords(refs.slice(offset, offset + limit), { signal });
      if (records.some(record => !record)) throw new Error('Explorer relationship points to a missing record.');
      return { records, total: refs.length, offset, limit };
    },
    async getMeetingIndex({ signal } = {}) {
      const part = publication.select('index', 'committee_explorer.meetings');
      const document = await checked(part, signal);
      if (!Array.isArray(document.rows) || document.rows.length !== part.record_count) throw new Error('Explorer meeting index count differs from its manifest.');
      return document.rows;
    },
    async getCoverage({ signal, filters } = {}) {
      if (filters) return filteredCoverage(filters, signal);
      const part = publication.select('coverage', 'committee_explorer.coverage');
      const document = await read(part, signal);
      if (!isObject(document) || !Array.isArray(document.metrics) || document.metrics.length !== part.record_count) throw new Error('Explorer coverage count differs from its manifest.');
      return document;
    },
    getRecords,
    async getRecord(ref, options) { return (await getRecords([ref], options))[0]; },
  });
}
