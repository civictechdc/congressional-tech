import { parquetMetadataAsync, parquetReadObjects, parquetScan, parquetSchema, rowIndex, type FileMetaData, type ParquetQueryFilter } from 'hyparquet';
import { presentRecord, recordingDue, recordingVisible } from '../browse/record-presentation.ts';
import { createSearchMemo, matches, pageBounds, selectSearchRows, summarizeCoverage } from '../browse/query-utils.ts';
import { selectRelatedMaterials } from '../browse/related-materials.ts';
import type { ArtifactPart, ExplorerQuery, ExplorerReader, ExplorerRecordRef, Fetcher, PublicationHandle, QueryInfo, QueryKind, QueryRow, RelatedOptions } from './types.ts';

const rowLocation = Symbol('rowLocation');

interface RowPosition { path: string; index: number; end?: number }
interface GroupSpan { path: string; index: number; end: number; ids: number[] }
type StoredRow = QueryRow & { [rowLocation]?: RowPosition; [rowIndex]?: number };

function asQueryRow(row: StoredRow): QueryRow {
  return row;
}

export function createParquetReader(publication: PublicationHandle, fetcher: Fetcher): ExplorerReader {
  const { manifest, manifestUrl, select, readPartition } = publication;
  const parts = manifest.partitions.filter(part => part.media_type === 'application/vnd.apache.parquet');
  const metadataCache = new Map<string, FileMetaData>();
  const rowsCache = new Map<string, StoredRow[]>();
  const materialCache = new Map<string, StoredRow[]>();
  const preparedSearch = createSearchMemo();
  const positions = new Map<string, RowPosition>();
  const records = new Map<string, StoredRow>();
  const pending = new Map<string, { controller: AbortController; users: number; promise: Promise<unknown> }>();
  const ranges = new Map<string, ArrayBuffer>();
  let rangeBytes = 0;

  function shared<T>(key: string, signal: AbortSignal | undefined, load: (signal: AbortSignal) => Promise<T>): Promise<T> {
    signal?.throwIfAborted();
    let entry = pending.get(key);
    if (!entry) {
      const controller = new AbortController();
      const created = { controller, users: 0, promise: Promise.resolve().then(() => load(controller.signal)) as Promise<unknown> };
      entry = created;
      pending.set(key, created);
      const clear = () => { if (pending.get(key) === created) pending.delete(key); };
      created.promise.then(clear, clear);
    }
    const current = entry;
    current.users++;
    return new Promise((resolve, reject) => {
      let done = false;
      const finish = (ok: boolean, value: unknown) => {
        if (done) return;
        done = true;
        signal?.removeEventListener('abort', abort);
        if (--current.users === 0) {
          if (pending.get(key) === current) pending.delete(key);
          current.controller.abort();
        }
        if (ok) resolve(value as T);
        else reject(value);
      };
      const abort = () => finish(false, signal?.reason);
      signal?.addEventListener('abort', abort, { once: true });
      current.promise.then(value => finish(true, value), error => finish(false, error));
    });
  }

  let info: QueryInfo | undefined;
  function cacheRows(key: string, rows: StoredRow[]): StoredRow[] {
    const cache = key.startsWith('related-material/') ? materialCache : rowsCache;
    if (rows.length <= 100000) {
      cache.set(key, rows);
      if (cache.size > 3) {
        const oldest = cache.keys().next().value;
        if (oldest !== undefined) cache.delete(oldest);
      }
    }
    return rows;
  }

  async function getQueryInfo({ signal }: { signal?: AbortSignal } = {}): Promise<QueryInfo> {
    signal?.throwIfAborted();
    if (!info) {
      const index = await readPartition(select('index', 'committee_explorer.queries'), signal);
      if (!index || typeof index !== 'object' || (index as { storage?: unknown }).storage !== 'parquet' || !Array.isArray((index as { query_columns?: unknown }).query_columns)) {
        throw new Error('Unsupported Parquet catalog.');
      }
      const catalog = index as QueryInfo & { storage: string; query_columns: string[] };
      info = {
        ...catalog,
        supported_filters: ([['committeeLevel', 'committee_level'], ['committeeType', 'committee_types'], ['access', 'access']] as const)
          .filter(([, column]) => catalog.query_columns.includes(column)).map(([filter]) => filter),
      };
    }
    return info;
  }

  function file(part: ArtifactPart, signal?: AbortSignal) {
    return {
      byteLength: part.byte_size,
      async slice(start: number, end = part.byte_size) {
        signal?.throwIfAborted();
        const key = `${part.path}/${start}/${end}`;
        const cached = ranges.get(key);
        if (cached) return cached;
        return shared(`range/${key}`, signal, async sharedSignal => {
          const response = await fetcher(new URL(part.path, manifestUrl), { signal: sharedSignal, headers: { Range: `bytes=${start}-${end - 1}` } });
          if (response.status !== 206 || response.headers.get('Content-Range') !== `bytes ${start}-${end - 1}/${part.byte_size}`) {
            await response.body?.cancel();
            throw new Error('The data host must support HTTP byte-range requests for Parquet.');
          }
          const bytes = await response.arrayBuffer();
          if (bytes.byteLength !== end - start) throw new Error('Incomplete Parquet byte range.');
          sharedSignal.throwIfAborted();
          if (bytes.byteLength <= 64 * 1024 * 1024) {
            ranges.set(key, bytes);
            rangeBytes += bytes.byteLength;
            while (rangeBytes > 64 * 1024 * 1024) {
              const oldest = ranges.keys().next().value;
              if (oldest === undefined) break;
              rangeBytes -= ranges.get(oldest)?.byteLength || 0;
              ranges.delete(oldest);
            }
          }
          return bytes;
        });
      },
    };
  }

  async function read(kind: string, options: { columns?: readonly string[]; filter?: ParquetQueryFilter; signal?: AbortSignal; position?: RowPosition; pruningFilter?: ParquetQueryFilter } = {}): Promise<StoredRow[]> {
    const tables = parts.filter(part => part.schema_name === `committee_explorer.parquet.${kind}` && (!options.position || part.path === options.position.path));
    const rows: StoredRow[] = [];
    for (const part of tables) {
      const buffer = file(part, options.signal);
      let metadata = metadataCache.get(part.path);
      if (!metadata) {
        metadata = await parquetMetadataAsync(buffer);
        if (Number(metadata.num_rows) !== part.record_count) throw new Error('Parquet row count differs from its manifest.');
        metadataCache.set(part.path, metadata);
      }
      const available = new Set(parquetSchema(metadata).children.map(child => child.element.name));
      const selectedColumns = options.columns?.filter(column => available.has(column));
      const readOptions = {
        file: buffer,
        metadata,
        columns: selectedColumns,
        filter: options.filter,
        includeRowIndex: true as const,
        rowFormat: 'object' as const,
        ...(options.position ? { rowStart: options.position.index, rowEnd: options.position.end ?? options.position.index + 1 } : {}),
      };
      let batch: StoredRow[];
      if (options.pruningFilter) {
        const scan = await parquetScan({ file: buffer, metadata, columns: selectedColumns, pruningFilter: options.pruningFilter });
        const membershipPath = Object.keys(options.pruningFilter)[0];
        let groupStart = 0;
        const emptyGroups = metadata.row_groups.flatMap(group => {
          const start = groupStart;
          groupStart += Number(group.num_rows);
          const column = group.columns.find(item => item.meta_data?.path_in_schema.join('.') === membershipPath)?.meta_data;
          return column?.statistics?.null_count !== undefined && Number(column.statistics.null_count) === Number(column.num_values) ? [{ start, end: groupStart }] : [];
        });
        const queue = scan.ranges.filter(range => !emptyGroups.some(group => range.rowStart >= group.start && range.rowEnd <= group.end));
        batch = [];
        await Promise.all(Array.from({ length: Math.min(4, queue.length) }, async () => {
          while (queue.length) {
            const range = queue.shift();
            if (!range) break;
            batch.push(...await parquetReadObjects({ ...readOptions, rowStart: range.rowStart, rowEnd: range.rowEnd }) as StoredRow[]);
          }
        }));
      } else {
        batch = await parquetReadObjects(readOptions) as StoredRow[];
      }
      options.signal?.throwIfAborted();
      for (const row of batch) {
        const position = { path: part.path, index: Number(row[rowIndex]) };
        row[rowLocation] = position;
        if (row.id) positions.set(`${kind}/${row.id}`, position);
        if (positions.size > 100000) {
          const oldest = positions.keys().next().value;
          if (oldest !== undefined) positions.delete(oldest);
        }
        rows.push(row);
      }
    }
    options.signal?.throwIfAborted();
    return rows;
  }

  async function queryRows(query: ExplorerQuery, signal?: AbortSignal): Promise<StoredRow[]> {
    const queryInfo = await getQueryInfo({ signal });
    const kind = query.kind || 'meeting';
    if (!queryInfo.kinds.some(item => item.kind === kind)) throw new Error('Unsupported explorer query kind.');
    const congress = query.congress ?? queryInfo.default_congress;
    const key = `${kind}/${congress}`;
    const cached = rowsCache.get(key);
    if (cached) return cached;
    return shared(`query/${key}`, signal, async sharedSignal => cacheRows(key, await read(kind, {
      columns: queryInfo.query_columns ? [...queryInfo.query_columns] : undefined,
      filter: congress === 'all' ? undefined : { congress: { $eq: Number(congress) } },
      signal: sharedSignal,
    })));
  }

  async function readSelected(kind: string, ids: readonly (string | RowPosition)[], columns: string[] | undefined, signal?: AbortSignal): Promise<StoredRow[]> {
    const groups = new Map<string, GroupSpan>();
    for (const id of new Set(ids)) {
      const position = typeof id === 'object' ? id : positions.get(`${kind}/${id}`);
      if (!position) continue;
      const metadata = metadataCache.get(position.path);
      if (!metadata) continue;
      let start = 0;
      for (const group of metadata.row_groups) {
        const end = start + Number(group.num_rows);
        if (position.index < end) {
          const key = `${position.path}/${start}`;
          const selected = groups.get(key) || { path: position.path, index: position.index, end: position.index + 1, ids: [] };
          selected.index = Math.min(selected.index, position.index);
          selected.end = Math.max(selected.end, position.index + 1);
          selected.ids.push(position.index);
          groups.set(key, selected);
          break;
        }
        start = end;
      }
    }
    const result: StoredRow[] = [];
    const queue = [...groups.values()];
    await Promise.all(Array.from({ length: Math.min(4, queue.length) }, async () => {
      while (queue.length) {
        const group = queue.shift();
        if (!group) break;
        const wanted = new Set(group.ids);
        const batch = await read(kind, { columns, position: group, signal });
        result.push(...batch.filter(row => wanted.has(Number(row[rowIndex]))));
      }
    }));
    return result;
  }

  async function getRecords(refs: readonly ExplorerRecordRef[], { signal }: { signal?: AbortSignal } = {}) {
    signal?.throwIfAborted();
    const found = new Map(refs.map(ref => [`${ref.kind}/${ref.id}`, records.get(`${ref.kind}/${ref.id}`)]));
    for (const kind of new Set(refs.map(ref => ref.kind))) {
      const ids = [...new Set(refs.filter(ref => ref.kind === kind).map(ref => ref.id))].filter(id => !found.get(`${kind}/${id}`));
      if (!ids.length) continue;
      const loaded = await shared(`records/${kind}/${ids.slice().sort().join(',')}`, signal, async sharedSignal => {
        const missing = ids.filter(id => !positions.has(`${kind}/${id}`));
        if (missing.length) await read(kind, { columns: ['id'], filter: { id: { $in: missing } }, signal: sharedSignal });
        const rows = await readSelected(kind, ids, undefined, sharedSignal);
        for (const row of rows) {
          if (kind === 'source_record' && typeof row.payload === 'string') row.payload = JSON.parse(row.payload);
          records.set(`${kind}/${row.id}`, row);
          if (records.size > 2000) {
            const oldest = records.keys().next().value;
            if (oldest !== undefined) records.delete(oldest);
          }
        }
        return rows;
      });
      for (const row of loaded) found.set(`${kind}/${row.id}`, row);
    }
    signal?.throwIfAborted();
    return refs.map(ref => {
      const row = found.get(`${ref.kind}/${ref.id}`);
      return row && presentRecord(asQueryRow(row));
    });
  }

  const reader: ExplorerReader = {
    publication: manifest as ExplorerReader['publication'],
    getQueryInfo,
    getRecords,
    async getRecord(ref: ExplorerRecordRef, recordOptions?: { signal?: AbortSignal }) { return (await getRecords([ref], recordOptions))[0]; },
    async search(query: ExplorerQuery = {}, { signal }: { signal?: AbortSignal } = {}) {
      const now = new Date();
      let selected = preparedSearch.get(query, now);
      if (!selected) selected = preparedSearch.set(query, now, selectSearchRows((await queryRows(query, signal)).map(asQueryRow), query, now, { present: presentRecord, hideRecordings: true }));
      signal?.throwIfAborted();
      const { offset, limit } = pageBounds(query);
      const slice = selected.rows.slice(offset, offset + limit);
      return { rows: selected.presentPage ? slice.map(row => presentRecord(row, now)) : slice, total: selected.rows.length, offset, limit };
    },
    async getCoverage({ filters, signal }: { filters?: ExplorerQuery; signal?: AbortSignal } = {}) {
      if (!filters) throw new Error('Explorer coverage requires filters.');
      const queryInfo = await getQueryInfo({ signal });
      const now = new Date();
      const rows = (await queryRows({ ...filters, kind: 'meeting' }, signal)).map(row => presentRecord(asQueryRow(row), now)).filter(row => matches(row, filters));
      return summarizeCoverage(queryInfo, rows);
    },
    async getRelated(ref: ExplorerRecordRef, options: RelatedOptions = {}) {
      const { signal } = options;
      const { offset, limit } = pageBounds(options);
      const record = (await getRecords([ref], { signal }))[0];
      if (!record) return { records: [], total: 0, offset, limit };
      let related: QueryRow[] = [];
      const congress = record.congress ?? 'all';
      const materialParents = { meeting: 'meeting_ids', appearance: 'appearance_ids', committee_term: 'committee_ids' } as const;
      if (ref.kind === 'meeting' || ref.kind === 'appearance' || ref.kind === 'committee_term') {
        if (!options.kind || options.kind === 'material') {
          const membership = materialParents[ref.kind];
          const cacheKey = `related-material/${ref.kind}/${ref.id}`;
          const material = materialCache.get(cacheKey) || await shared(cacheKey, signal, async sharedSignal => {
            const links = await read('material', {
              columns: [membership],
              filter: { [membership]: { $in: [ref.id] } },
              pruningFilter: { [`${membership}.list.element`]: { $in: [ref.id] } },
              signal: sharedSignal,
            });
            return cacheRows(cacheKey, await readSelected('material', links.map(row => row[rowLocation]).filter((position): position is RowPosition => Boolean(position)),
              ['id', 'kind', 'title', 'meeting_ids', 'appearance_ids', 'committee_ids', 'type', 'document_type', 'category', 'date', 'scheduled_at', 'meeting_status', 'recording_url'], sharedSignal));
          });
          const now = new Date();
          related.push(...material.filter(row => recordingVisible(row, now) && (row.type !== 'recording' || recordingDue(record, now)) && row[membership]?.includes(ref.id)).map(asQueryRow));
        }
        if (ref.kind === 'meeting' && (!options.kind || options.kind === 'appearance')) {
          related.push(...(await queryRows({ kind: 'appearance', congress }, signal)).filter(row => row.meeting_id === ref.id).map(asQueryRow));
        }
        if (ref.kind === 'committee_term' && (!options.kind || options.kind === 'meeting')) {
          related.push(...(await queryRows({ kind: 'meeting', congress }, signal)).filter(row => row.committee_ids?.includes(ref.id)).map(asQueryRow));
        }
        if (ref.kind === 'committee_term' && (!options.kind || options.kind === 'committee_term')) {
          related.push(...(await queryRows({ kind: 'committee_term', congress }, signal)).filter(row => row.parent_committee_id === ref.id && row.congress === record.congress).map(asQueryRow));
        }
      } else if (ref.kind === 'material' && (!options.kind || options.kind === 'meeting')) {
        related = (await getRecords((record.meeting_ids || []).map(id => ({ kind: 'meeting', id })), { signal })).filter((row): row is QueryRow => Boolean(row));
      }
      if (options.kind) related = related.filter(row => row.kind === options.kind);
      if (!options.kind || options.kind === 'data_issue') {
        related.push(...(await read('data_issue', { columns: ['id', 'kind', 'title', 'date'], filter: { subject_kind: { $eq: ref.kind }, subject_id: { $eq: ref.id } }, signal })).map(asQueryRow));
      }
      related.sort((a, b) => a.kind.localeCompare(b.kind) || (a.kind === 'meeting' ? (b.date || '').localeCompare(a.date || '') : 0) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
      let categories;
      if (options.kind === 'material') {
        const selected = selectRelatedMaterials(related, options);
        related = selected.rows;
        categories = selected.categories;
      }
      const loaded = (await getRecords(related.slice(offset, offset + limit), { signal })).filter((row): row is QueryRow => Boolean(row));
      return { records: loaded, total: related.length, offset, limit, ...(categories ? { categories } : {}) };
    },
  };
  return Object.freeze(reader);
}
