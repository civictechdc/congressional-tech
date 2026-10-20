import { parentCommitteeId } from '../browse/record-presentation.ts';
import { createSearchMemo, matches, orderSearchRows, pageBounds, selectSearchRows, summarizeCoverage } from '../browse/query-utils.ts';
import { selectRelatedMaterials } from '../browse/related-materials.ts';
import type { DisplayRow } from '../browse/record-presentation.ts';
import type {
  ArtifactDecoder, ArtifactPart, ExplorerDataSource, ExplorerQuery, ExplorerReader, ExplorerRecord,
  ExplorerRecordRef, ExplorerSnapshot, Fetcher, OpenReaderOptions, PublicationHandle, QueryInfo, QueryKind, QueryRow, RelatedOptions,
} from './types.ts';

export type * from './types.ts';

const supportedSchemaVersions = new Set(['0.1.0-draft.2', '0.1.0-draft.3']);

function supportedSchema(version: unknown): version is string {
  return typeof version === 'string' && supportedSchemaVersions.has(version);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function bytesBuffer(bytes: Uint8Array): ArrayBuffer {
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
}

export function decodeJson(bytes: Uint8Array): unknown {
  return JSON.parse(new TextDecoder().decode(bytes));
}

export async function decodeGzipJson(bytes: Uint8Array): Promise<unknown> {
  const stream = new Blob([bytesBuffer(bytes)]).stream().pipeThrough(new DecompressionStream('gzip'));
  return decodeJson(new Uint8Array(await new Response(stream).arrayBuffer()));
}

function identity(item: Record<string, unknown>): { kind: string; id: string } {
  if (typeof item.kind !== 'string' || !item.kind.trim() || typeof item.id !== 'string' || !item.id.trim()) {
    throw new Error('Explorer records require a kind and a nonempty string ID.');
  }
  return { kind: item.kind, id: item.id };
}

export function normalizeCatalog(document: unknown): ExplorerSnapshot {
  if (!isRecord(document) || !supportedSchema(document.schema_version)) {
    throw new Error('Unsupported explorer schema version. Refresh the application or use a compatible publication.');
  }
  if (document.scope !== 'complete' || !Array.isArray(document.records) || !Array.isArray(document.sources)) {
    throw new Error('Expected a complete explorer catalog, not a partial record file.');
  }
  const seen = new Set<string>();
  for (const [group, items] of [['records', document.records], ['sources', document.sources]] as const) {
    for (const item of items) {
      if (!isRecord(item)) throw new Error('Explorer records require a kind and a nonempty string ID.');
      const { kind, id } = identity(item);
      if ((kind === 'source_record') !== (group === 'sources')) throw new Error('Explorer source observations must be separate from domain records.');
      const key = JSON.stringify([kind, id]);
      if (seen.has(key)) throw new Error(`Duplicate explorer identity: ${key}`);
      seen.add(key);
    }
  }
  return Object.freeze({
    schemaVersion: document.schema_version,
    records: Object.freeze(document.records as ExplorerSnapshot['records']),
    sources: Object.freeze(document.sources as ExplorerSnapshot['sources']),
  });
}

async function bucketPrefix(key: string): Promise<string> {
  const digest = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(key)));
  return digest[0].toString(16).padStart(2, '0');
}

async function readBytes(fetcher: Fetcher, url: URL | string, signal?: AbortSignal): Promise<Uint8Array> {
  signal?.throwIfAborted();
  const response = await fetcher(url, { signal });
  if (!response.ok) throw new Error(`Explorer data request failed (HTTP ${response.status}).`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  signal?.throwIfAborted();
  return bytes;
}

async function checkDigest(bytes: Uint8Array, expected: unknown, label: string): Promise<void> {
  if (typeof expected !== 'string' || !/^[0-9a-f]{64}$/.test(expected)) throw new Error(`Explorer ${label} has no valid checksum.`);
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytesBuffer(bytes));
  const actual = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  if (actual !== expected) throw new Error(`Explorer ${label} checksum differs from its publication metadata.`);
}

export function createCatalogSource(options: { url: string | URL; fetcher?: Fetcher; decode?: ArtifactDecoder }): ExplorerDataSource {
  const fetcher = options.fetcher || globalThis.fetch;
  const decode = options.decode || decodeJson;
  return {
    async load({ signal } = {}) {
      const document = await decode(await readBytes(fetcher, options.url, signal));
      signal?.throwIfAborted();
      return normalizeCatalog(document);
    },
  };
}

async function openVerifiedPublication(options: OpenReaderOptions): Promise<PublicationHandle> {
  const fetcher = options.fetcher || globalThis.fetch;
  const { signal } = options;
  const available: Record<string, ArtifactDecoder> = {
    'application/json': decodeJson,
    'application/vnd.committee-explorer+json+gzip': decodeGzipJson,
    ...options.decoders,
  };
  const pointerLocation = new URL(options.pointerUrl, globalThis.location?.href);
  const pointer = decodeJson(await readBytes(fetcher, pointerLocation, signal));
  if (!isRecord(pointer) || !supportedSchema(pointer.schema_version) || typeof pointer.manifest_path !== 'string' || typeof pointer.publication_id !== 'string') {
    throw new Error('The explorer release pointer does not identify a manifest.');
  }
  const manifestUrl = new URL(pointer.manifest_path, pointerLocation);
  const manifestBytes = await readBytes(fetcher, manifestUrl, signal);
  await checkDigest(manifestBytes, pointer.manifest_sha256, 'manifest');
  const manifest = decodeJson(manifestBytes);
  if (!isRecord(manifest) || !supportedSchema(manifest.schema_version) || !Array.isArray(manifest.partitions)) {
    throw new Error('Unsupported explorer publication manifest.');
  }
  if (pointer.publication_id !== manifest.publication_id) throw new Error('Explorer release pointer and manifest identify different publications.');
  const partitions = manifest.partitions as ArtifactPart[];
  function select(role: string, schemaName: string): ArtifactPart {
    const candidates = partitions.filter(part => part.role === role && part.schema_name === schemaName);
    if (candidates.length !== 1) throw new Error(`Expected one ${schemaName} artifact in this explorer publication.`);
    const [chosen] = candidates;
    if (!chosen) throw new Error(`Expected one ${schemaName} artifact in this explorer publication.`);
    return chosen;
  }
  async function readPartition(part: ArtifactPart, readSignal?: AbortSignal): Promise<unknown> {
    const mediaType = part.media_type || 'application/json';
    const decode = Object.hasOwn(available, mediaType) ? available[mediaType] : undefined;
    if (typeof decode !== 'function') throw new Error(`No explorer decoder is configured for ${mediaType}.`);
    if (!supportedSchema(part.schema_version) || !Number.isSafeInteger(part.byte_size) || part.byte_size < 0
      || !Number.isSafeInteger(part.record_count) || part.record_count < 0 || !/^[0-9a-f]{64}$/.test(part.sha256 || '')) {
      throw new Error('The explorer artifact descriptor is incomplete or incompatible.');
    }
    const bytes = await readBytes(fetcher, new URL(part.path, manifestUrl), readSignal);
    if (bytes.byteLength !== part.byte_size) throw new Error('Explorer artifact size differs from its publication manifest.');
    await checkDigest(bytes, part.sha256, 'artifact');
    const document = await decode(bytes, { schemaName: part.schema_name, schemaVersion: part.schema_version });
    readSignal?.throwIfAborted();
    return document;
  }
  signal?.throwIfAborted();
  return { manifest: Object.freeze(manifest) as PublicationHandle['manifest'], manifestUrl, select, readPartition };
}

export function createPublicationSource(options: OpenReaderOptions): ExplorerDataSource {
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

function asRows(value: unknown, kind: string, count: number): QueryRow[] {
  if (!Array.isArray(value) || value.length !== count || value.some(row => !isRecord(row) || row.kind !== kind || typeof row.id !== 'string' || typeof row.title !== 'string')) {
    throw new Error('Explorer query rows disagree with their manifest.');
  }
  return value as QueryRow[];
}

export async function openPublicationReader(options: OpenReaderOptions): Promise<ExplorerReader> {
  const publication = await openVerifiedPublication(options);
  if (publication.manifest.partitions.some(part => part.media_type === 'application/vnd.apache.parquet')) {
    const { createParquetReader } = await import('./parquet-source.ts');
    return createParquetReader(publication, options.fetcher || globalThis.fetch);
  }
  const descriptors = new Map(publication.manifest.partitions.map(part => [part.path, part]));
  const cache = new Map<string, unknown>();
  const queryCache = new Map<string, QueryRow[]>();
  const materialCache = new Map<string, ExplorerRecord[]>();
  const preparedSearch = createSearchMemo();

  async function read(part: ArtifactPart, signal?: AbortSignal): Promise<unknown> {
    signal?.throwIfAborted();
    if (cache.has(part.path)) {
      const cached = cache.get(part.path);
      cache.delete(part.path);
      cache.set(part.path, cached);
      return cached;
    }
    const value = await publication.readPartition(part, signal);
    cache.set(part.path, value);
    if (cache.size > 8) {
      const oldest = cache.keys().next().value;
      if (oldest !== undefined) cache.delete(oldest);
    }
    return value;
  }

  function described(path: string, schemaName: string): ArtifactPart {
    const part = descriptors.get(path);
    if (!part || part.schema_name !== schemaName) throw new Error('Explorer lookup points to an unadvertised artifact.');
    return part;
  }

  async function checked(part: ArtifactPart, signal?: AbortSignal): Promise<Record<string, unknown>> {
    const value = await read(part, signal);
    if (!isRecord(value) || !supportedSchema(value.schema_version)) throw new Error('Unsupported explorer index or detail schema.');
    return value;
  }

  async function getQueryInfo({ signal }: { signal?: AbortSignal } = {}): Promise<QueryInfo> {
    const part = publication.select('index', 'committee_explorer.queries');
    const info = await checked(part, signal);
    if (!Array.isArray(info.partitions) || info.partitions.length !== part.record_count || !Array.isArray(info.congresses)
      || !Number.isInteger(info.default_congress) || !Array.isArray(info.kinds)) {
      throw new Error('The explorer query index is incomplete.');
    }
    return info as unknown as QueryInfo;
  }

  async function queryRows(query: ExplorerQuery, signal?: AbortSignal): Promise<QueryRow[]> {
    const info = await getQueryInfo({ signal });
    const congress = query.congress ?? info.default_congress;
    const kind: QueryKind | string = query.kind || 'meeting';
    if (!info.kinds.some(entry => entry.kind === kind)) throw new Error('Unsupported explorer query kind.');
    if (congress !== 'all' && !info.congresses.includes(Number(congress))) return [];
    const key = `${kind}/${congress}`;
    const cached = queryCache.get(key);
    if (cached) return cached;
    const parts = (info.partitions || []).filter(part => part.kind === kind && (congress === 'all' || part.congress === Number(congress)));
    const rows: QueryRow[] = [];
    for (let offset = 0; offset < parts.length; offset += 4) {
      const batches = await Promise.all(parts.slice(offset, offset + 4).map(async entry => {
        const part = described(entry.path, 'committee_explorer.query-rows');
        const document = await checked(part, signal);
        return asRows(document.rows, kind, part.record_count);
      }));
      for (const batch of batches) rows.push(...batch);
    }
    signal?.throwIfAborted();
    if (rows.length <= 50000) {
      queryCache.set(key, rows);
      if (queryCache.size > 2) {
        const oldest = queryCache.keys().next().value;
        if (oldest !== undefined) queryCache.delete(oldest);
      }
    }
    return rows;
  }

  async function search(query: ExplorerQuery = {}, { signal }: { signal?: AbortSignal } = {}) {
    const now = new Date();
    let selected = preparedSearch.get(query, now);
    if (!selected) selected = preparedSearch.set(query, now, selectSearchRows(await queryRows(query, signal), query, now));
    signal?.throwIfAborted();
    const { offset, limit } = pageBounds(query);
    const ordered = orderSearchRows(selected.rows, query.sort, query.direction);
    return { rows: ordered.slice(offset, offset + limit), total: ordered.length, offset, limit };
  }

  async function getRecords(refs: readonly ExplorerRecordRef[], { signal }: { signal?: AbortSignal } = {}): Promise<(ExplorerRecord | undefined)[]> {
    const locatorPart = publication.select('index', 'committee_explorer.locations');
    const locator = await checked(locatorPart, signal);
    if (locator.key_format !== '<kind>/<id>' || locator.bucket_algorithm !== 'sha256-prefix-2' || !isRecord(locator.buckets)) {
      throw new Error('Unsupported explorer record lookup format.');
    }
    if (Object.keys(locator.buckets).length !== locatorPart.record_count) throw new Error('Explorer lookup bucket count differs from its manifest.');
    const keys = refs.map(ref => {
      if (typeof ref.kind !== 'string' || !ref.kind || typeof ref.id !== 'string' || !ref.id) throw new Error('A record lookup requires kind and ID.');
      return `${ref.kind}/${ref.id}`;
    });
    const hashes = await Promise.all(keys.map(bucketPrefix));
    const locations = new Map<string, string>();
    const buckets = locator.buckets;
    for (const bucket of new Set(hashes)) {
      const path = buckets[bucket];
      if (typeof path !== 'string') continue;
      const part = described(path, 'committee_explorer.location-bucket');
      const document = await checked(part, signal);
      if (!isRecord(document.locations) || Object.keys(document.locations).length !== part.record_count) throw new Error('Explorer record lookup count differs from its manifest.');
      for (const key of keys) if (Object.hasOwn(document.locations, key) && typeof document.locations[key] === 'string') locations.set(key, document.locations[key]);
    }
    const found = new Map<string, ExplorerRecord>();
    for (const path of new Set(locations.values())) {
      const part = descriptors.get(path);
      const field = part?.schema_name === 'committee_explorer.sources' ? 'sources' : part?.schema_name === 'committee_explorer.records' ? 'records' : null;
      if (!part || !field) throw new Error('Explorer record lookup does not identify a detail or source artifact.');
      const document = await checked(part, signal);
      const items = document[field];
      if (!Array.isArray(items) || items.length !== part.record_count) throw new Error('Explorer detail count differs from its manifest.');
      for (const item of items) {
        if (!isRecord(item)) throw new Error('Explorer detail has no stable identity.');
        const { kind, id } = identity(item);
        const key = `${kind}/${id}`;
        if (locations.get(key) === path) {
          if (found.has(key)) throw new Error('Explorer detail contains a duplicate identity.');
          found.set(key, item as unknown as ExplorerRecord);
        }
      }
    }
    if (keys.some(key => locations.has(key) && !found.has(key))) throw new Error('Explorer record lookup and detail contents disagree.');
    const committees = [...found.values()].filter(record => record.kind === 'committee_term');
    if (committees.length && (await getQueryInfo({ signal })).kinds.some(entry => entry.kind === 'committee_term')) {
      for (const congress of new Set(committees.map(record => (record as DisplayRow).congress))) {
        const metadata = new Map((await queryRows({ kind: 'committee_term', congress: typeof congress === 'number' ? congress : undefined }, signal)).map(row => [row.id, row]));
        for (const record of committees.filter(item => (item as DisplayRow).congress === congress)) {
          const row = metadata.get(record.id);
          if (row) found.set(`committee_term/${record.id}`, { ...record, committee_types: row.committee_types, committee_level: row.committee_level, parent_committee_id: row.parent_committee_id } as ExplorerRecord);
        }
      }
    }
    signal?.throwIfAborted();
    return keys.map(key => found.get(key));
  }

  const reader: ExplorerReader = {
    publication: publication.manifest as ExplorerReader['publication'],
    getQueryInfo,
    search,
    async getRelated(ref: ExplorerRecordRef, options: RelatedOptions = {}) {
      const { signal } = options;
      const { offset, limit } = pageBounds(options);
      const part = publication.select('index', 'committee_explorer.relations');
      const root = await checked(part, signal);
      if (root.key_format !== '<kind>/<id>' || root.bucket_algorithm !== 'sha256-prefix-2' || !isRecord(root.buckets) || Object.keys(root.buckets).length !== part.record_count) {
        throw new Error('Unsupported explorer relationship index.');
      }
      const key = `${ref.kind}/${ref.id}`;
      const path = root.buckets[await bucketPrefix(key)];
      if (typeof path !== 'string') return { records: [], total: 0, offset, limit };
      const bucket = await checked(described(path, 'committee_explorer.relation-bucket'), signal);
      if (!isRecord(bucket.relations) || Object.keys(bucket.relations).length !== described(path, 'committee_explorer.relation-bucket').record_count) {
        throw new Error('Explorer relationship count differs from its manifest.');
      }
      const listed = bucket.relations[key] ?? [];
      if (!Array.isArray(listed)) throw new Error('Explorer relationships are invalid.');
      const refs = (options.kind ? listed.filter(item => (item as { kind?: string }).kind === options.kind) : listed) as ExplorerRecordRef[];
      if (ref.kind === 'committee_term' && options.kind === 'committee_term') {
        const [parent] = await getRecords([ref], { signal });
        const candidates = await getRecords(refs, { signal });
        if (candidates.some(record => !record)) throw new Error('Explorer relationship points to a missing record.');
        const present = candidates.filter((record): record is ExplorerRecord => Boolean(record));
        const children = present.filter(record => parentCommitteeId(record as DisplayRow) === ref.id && (record as DisplayRow).congress === (parent as DisplayRow | undefined)?.congress);
        return { records: children.slice(offset, offset + limit), total: children.length, offset, limit };
      }
      if (options.kind === 'material') {
        let materials = materialCache.get(key);
        if (!materials) {
          const loaded = await getRecords(refs, { signal });
          if (loaded.some(record => !record)) throw new Error('Explorer relationship points to a missing record.');
          signal?.throwIfAborted();
          materials = loaded.filter((record): record is ExplorerRecord => Boolean(record));
          materialCache.set(key, materials);
          if (materialCache.size > 3) {
            const oldest = materialCache.keys().next().value;
            if (oldest !== undefined) materialCache.delete(oldest);
          }
        }
        const selected = selectRelatedMaterials(materials, options);
        return { records: selected.rows.slice(offset, offset + limit), total: selected.rows.length, offset, limit, categories: selected.categories };
      }
      const pageRefs = refs.slice(offset, offset + limit);
      const records = await getRecords(pageRefs, { signal });
      if (records.some(record => !record)) throw new Error('Explorer relationship points to a missing record.');
      return { records: records.filter((record): record is ExplorerRecord => Boolean(record)), total: refs.length, offset, limit };
    },
    async getCoverage({ filters, signal }: { filters?: ExplorerQuery; signal?: AbortSignal } = {}) {
      if (!filters) throw new Error('Explorer coverage requires filters.');
      const info = await getQueryInfo({ signal });
      const rows = (await queryRows({ ...filters, kind: 'meeting' }, signal)).filter(row => matches(row, filters));
      return summarizeCoverage(info, rows);
    },
    getRecords,
    async listWitnesses(meetingIds: readonly string[], { signal }: { signal?: AbortSignal } = {}) {
      const ids = new Set(meetingIds.map(id => id.trim()).filter(Boolean));
      if (!ids.size) return [];
      const rows = await queryRows({ kind: 'appearance', congress: 'all' }, signal);
      return rows.flatMap(row => row.meeting_id && ids.has(row.meeting_id) && row.title ? [{ meeting_id: row.meeting_id, title: row.title }] : []);
    },
    async getRecord(ref: ExplorerRecordRef, recordOptions?: { signal?: AbortSignal }) { return (await getRecords([ref], recordOptions))[0]; },
  };
  return Object.freeze(reader);
}
