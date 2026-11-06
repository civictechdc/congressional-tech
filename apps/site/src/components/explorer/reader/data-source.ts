import type {
  ArtifactDecoder, ArtifactPart, ExplorerReader, Fetcher, OpenReaderOptions, PublicationHandle,
} from './types.ts';

export type * from './types.ts';

function supportedSchema(version: unknown): version is string {
  return version === '0.1.0-draft.3';
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
  if (manifest.partitions.some(part => !isRecord(part) || !supportedSchema(part.schema_version))) {
    throw new Error('The explorer artifact descriptor is incomplete or incompatible.');
  }
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

export async function openPublicationReader(options: OpenReaderOptions): Promise<ExplorerReader> {
  const publication = await openVerifiedPublication(options);
  if (!publication.manifest.partitions.some(part => part.media_type === 'application/vnd.apache.parquet')) {
    throw new Error('Explorer publication requires Parquet partitions; legacy sharded JSON (.data) has been retired.');
  }
  const { createParquetReader } = await import('./parquet-source.ts');
  return createParquetReader(publication, options.fetcher || globalThis.fetch);
}
