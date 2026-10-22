import type {
  ArtifactDecoder, ArtifactPart, ExplorerDataSource, ExplorerReader,
  ExplorerSnapshot, Fetcher, OpenReaderOptions, PublicationHandle,
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

export async function openPublicationReader(options: OpenReaderOptions): Promise<ExplorerReader> {
  const publication = await openVerifiedPublication(options);
  if (!publication.manifest.partitions.some(part => part.media_type === 'application/vnd.apache.parquet')) {
    throw new Error('Explorer publication requires Parquet partitions; legacy sharded JSON (.data) has been retired.');
  }
  const { createParquetReader } = await import('./parquet-source.ts');
  return createParquetReader(publication, options.fetcher || globalThis.fetch);
}
