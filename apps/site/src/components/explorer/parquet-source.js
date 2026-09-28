import { parquetMetadataAsync, parquetReadObjects, parquetScan, rowIndex } from 'hyparquet';
import { presentRecord, recordingDue, recordingVisible } from './record-presentation.js';
import { groupCommitteeTerms, matches, pageBounds, summarizeCoverage } from './query-utils.js';
import { selectRelatedMaterials } from './related-materials.js';

const rowLocation = Symbol('rowLocation');

/** HTTP ranges remain inside the injected reader. No SQL engine or record shards. */
export function createParquetReader(publication, fetcher) {
  const { manifest, manifestUrl, select, readPartition } = publication;
  const parts = manifest.partitions.filter(p => p.media_type === 'application/vnd.apache.parquet');
  const metadataCache = new Map();
  const rowsCache = new Map();
  const positions = new Map();
  const records = new Map();
  const pending = new Map();
  const ranges = new Map();
  let rangeBytes = 0;

  // Share work while each caller retains its own cancellation. Cancel the
  // underlying request only when its last subscriber leaves.
  function shared(key, signal, load) {
    signal?.throwIfAborted();
    let entry = pending.get(key);
    if (!entry) {
      const controller = new AbortController();
      entry = { controller, users: 0, promise: Promise.resolve().then(() => load(controller.signal)) };
      pending.set(key, entry);
      const clear = () => { if (pending.get(key) === entry) pending.delete(key); };
      entry.promise.then(clear, clear);
    }
    entry.users++;
    return new Promise((resolve, reject) => {
      let done = false;
      const finish = (callback, value) => {
        if (done) return;
        done = true;
        signal?.removeEventListener('abort', abort);
        if (--entry.users === 0) {
          if (pending.get(key) === entry) pending.delete(key);
          entry.controller.abort();
        }
        callback(value);
      };
      const abort = () => finish(reject, signal.reason);
      signal?.addEventListener('abort', abort, { once: true });
      entry.promise.then(value => finish(resolve, value), error => finish(reject, error));
    });
  }
  let info;
  function cacheRows(key, rows) {
    if (rows.length <= 100000) {
      rowsCache.set(key, rows);
      if (rowsCache.size > 3) rowsCache.delete(rowsCache.keys().next().value);
    }
    return rows;
  }
  async function getQueryInfo({ signal } = {}) {
    signal?.throwIfAborted();
    if (!info) {
      const index = await readPartition(select('index', 'committee_explorer.queries'), signal);
      if (index.storage !== 'parquet' || !Array.isArray(index.query_columns)) throw new Error('Unsupported Parquet catalog.');
      info = {...index, supported_filters: [['committeeLevel', 'committee_level'], ['committeeType', 'committee_types'], ['access', 'access']]
        .filter(([, column]) => index.query_columns.includes(column)).map(([filter]) => filter)};
    }
    return info;
  }
  function file(part, signal) {
    return {
      byteLength: part.byte_size,
      async slice(start, end = part.byte_size) {
        signal?.throwIfAborted();
        const key = `${part.path}/${start}/${end}`;
        if (ranges.has(key)) return ranges.get(key);
        return shared(`range/${key}`, signal, async sharedSignal => {
          const response = await fetcher(new URL(part.path, manifestUrl), { signal: sharedSignal, headers: { Range: `bytes=${start}-${end - 1}` } });
          if (response.status !== 206 || response.headers.get('Content-Range') !== `bytes ${start}-${end - 1}/${part.byte_size}`) {
            await response.body?.cancel();
            throw new Error('The data host must support HTTP byte-range requests for Parquet.');
          }
          const bytes = await response.arrayBuffer();
          if (bytes.byteLength !== end - start) throw new Error('Incomplete Parquet byte range.');
          sharedSignal.throwIfAborted();
          // Bound retained compressed data to 64 MiB per publication reader.
          if (bytes.byteLength <= 64 * 1024 * 1024) {
            ranges.set(key, bytes);
            rangeBytes += bytes.byteLength;
            while (rangeBytes > 64 * 1024 * 1024) {
              const oldest = ranges.keys().next().value;
              rangeBytes -= ranges.get(oldest).byteLength;
              ranges.delete(oldest);
            }
          }
          return bytes;
        });
      },
    };
  }
  async function read(kind, { columns, filter, signal, position, pruningFilter } = {}) {
    const tables = parts.filter(p => p.schema_name === `committee_explorer.parquet.${kind}` && (!position || p.path === position.path));
    const rows = [];
    for (const part of tables) {
      const buffer = file(part, signal);
      let metadata = metadataCache.get(part.path);
      if (!metadata) {
        metadata = await parquetMetadataAsync(buffer);
        if (Number(metadata.num_rows) !== part.record_count) throw new Error('Parquet row count differs from its manifest.');
        metadataCache.set(part.path, metadata);
      }
      const options = { file: buffer, metadata, columns, filter, includeRowIndex: true,
        ...(position ? { rowStart: position.index, rowEnd: position.end ?? position.index + 1 } : {}) };
      let batch;
      if (pruningFilter) {
        // List membership statistics use the physical leaf path. Keep that
        // separate from the logical filter used to test assembled rows.
        const scan = await parquetScan({ file: buffer, metadata, columns, pruningFilter });
        const membershipPath = Object.keys(pruningFilter)[0];
        let groupStart = 0;
        const emptyGroups = metadata.row_groups.flatMap(group => {
          const start = groupStart;
          groupStart += Number(group.num_rows);
          const column = group.columns.find(column => column.meta_data?.path_in_schema.join('.') === membershipPath)?.meta_data;
          return column?.statistics?.null_count !== undefined && Number(column.statistics.null_count) === Number(column.num_values)
            ? [{ start, end: groupStart }] : [];
        });
        const queue = scan.ranges.filter(range => !emptyGroups.some(group => range.rowStart >= group.start && range.rowEnd <= group.end));
        batch = [];
        await Promise.all(Array.from({ length: Math.min(4, queue.length) }, async () => {
          while (queue.length) {
            const range = queue.shift();
            batch.push(...await parquetReadObjects({ ...options, rowStart: range.rowStart, rowEnd: range.rowEnd }));
          }
        }));
      } else {
        batch = await parquetReadObjects(options);
      }
      signal?.throwIfAborted();
      for (const row of batch) {
        row[rowLocation] = { path: part.path, index: row[rowIndex] };
        if (row.id) positions.set(`${kind}/${row.id}`, row[rowLocation]);
        if (positions.size > 100000) positions.delete(positions.keys().next().value);
        rows.push(row);
      }
    }
    signal?.throwIfAborted();
    return rows;
  }
  async function queryRows(query, signal, extra = []) {
    const info = await getQueryInfo({ signal });
    const kind = query.kind || 'meeting';
    if (!info.kinds.some(k => k.kind === kind)) throw new Error('Unsupported explorer query kind.');
    const congress = query.congress ?? info.default_congress;
    const key = `${kind}/${congress}/${extra.join(',')}`;
    if (rowsCache.has(key)) return rowsCache.get(key);
    return shared(`query/${key}`, signal, async sharedSignal => cacheRows(key,
      await read(kind, { columns: [...info.query_columns, ...extra],
        filter: congress === 'all' ? undefined : { congress: { $eq: Number(congress) } }, signal: sharedSignal })));
  }
  async function readSelected(kind, ids, columns, signal) {
    const groups = new Map();
    for (const id of new Set(ids)) {
      const position = typeof id === 'object' ? id : positions.get(`${kind}/${id}`);
      if (!position) continue;
      const metadata = metadataCache.get(position.path);
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
    const result = [];
    const queue = [...groups.values()];
    // Read each row group once, with bounded parallelism across groups.
    await Promise.all(Array.from({ length: Math.min(4, queue.length) }, async () => {
      while (queue.length) {
        const group = queue.shift();
        const wanted = new Set(group.ids);
        const batch = await read(kind, { columns, position: group, signal });
        result.push(...batch.filter(row => wanted.has(row[rowIndex])));
      }
    }));
    return result;
  }
  async function getRecords(refs, { signal } = {}) {
    signal?.throwIfAborted();
    const found = new Map(refs.map(ref => [`${ref.kind}/${ref.id}`, records.get(`${ref.kind}/${ref.id}`)]));
    for (const kind of new Set(refs.map(r => r.kind))) {
      const ids = [...new Set(refs.filter(r => r.kind === kind).map(r => r.id))].filter(id => !found.get(`${kind}/${id}`));
      if (!ids.length) continue;
      const loaded = await shared(`records/${kind}/${ids.slice().sort().join(',')}`, signal, async sharedSignal => {
        const missing = ids.filter(id => !positions.has(`${kind}/${id}`));
        if (missing.length) await read(kind, { columns: ['id'], filter: { id: { $in: missing } }, signal: sharedSignal });
        const rows = await readSelected(kind, ids, undefined, sharedSignal);
        for (const row of rows) {
          if (kind === 'source_record' && row.payload) row.payload = JSON.parse(row.payload);
          records.set(`${kind}/${row.id}`, row);
          if (records.size > 2000) records.delete(records.keys().next().value);
        }
        return rows;
      });
      for (const row of loaded) found.set(`${kind}/${row.id}`, row);
    }
    signal?.throwIfAborted();
    return refs.map(ref => {
      const row = found.get(`${ref.kind}/${ref.id}`);
      return row && presentRecord(row);
    });
  }
  return Object.freeze({
    publication: manifest,
    getQueryInfo, getRecords,
    async getRecord(ref, options) { return (await getRecords([ref], options))[0]; },
    async search(query = {}, { signal } = {}) {
      const rows = groupCommitteeTerms((await queryRows(query, signal)).map(row => presentRecord(row)).filter(row => recordingVisible(row) && matches(row, query)), query);
      rows.sort((a, b) => (b.date || '').localeCompare(a.date || '') || a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
      const { offset, limit } = pageBounds(query);
      return { rows: rows.slice(offset, offset + limit), total: rows.length, offset, limit };
    },
    async getCoverage({ filters = {}, signal } = {}) {
      const info = await getQueryInfo({ signal });
      const rows = (await queryRows({ ...filters, kind: 'meeting' }, signal)).map(row => presentRecord(row)).filter(row => matches(row, filters));
      return summarizeCoverage(info, rows);
    },
    async getRelated(ref, options = {}) {
      const { signal } = options;
      const { offset, limit } = pageBounds(options);
      const record = (await getRecords([ref], { signal }))[0];
      if (!record) return { records: [], total: 0, offset, limit };
      let related = [];
      const congress = record.congress ?? 'all';
      if (['meeting', 'appearance', 'committee_term'].includes(ref.kind)) {
        if (!options.kind || options.kind === 'material') {
          const membership = {meeting: 'meeting_ids', appearance: 'appearance_ids', committee_term: 'committee_ids'}[ref.kind];
          const cacheKey = `related-material/${ref.kind}/${ref.id}`;
          const material = rowsCache.get(cacheKey) || await shared(cacheKey, signal, async sharedSignal => {
            // Discover links using only IDs and membership, then read display
            // columns from the row groups that actually contain matching items.
            const links = await read('material', { columns: [membership],
              filter: { [membership]: { $in: [ref.id] } },
              pruningFilter: { [`${membership}.list.element`]: { $in: [ref.id] } }, signal: sharedSignal });
            return cacheRows(cacheKey, await readSelected('material', links.map(row => row[rowLocation]),
              ['id', 'kind', 'title', 'meeting_ids', 'appearance_ids', 'committee_ids', 'type', 'document_type', 'category', 'date', 'scheduled_at', 'meeting_status', 'recording_url'], sharedSignal));
          });
          related.push(...material.filter(r => recordingVisible(r) && (r.type !== 'recording' || recordingDue(record))
            && r[membership]?.includes(ref.id)));
        }
        if (ref.kind === 'meeting' && (!options.kind || options.kind === 'appearance')) {
          related.push(...(await queryRows({ kind: 'appearance', congress }, signal)).filter(r => r.meeting_id === ref.id));
        }
        if (ref.kind === 'committee_term' && (!options.kind || options.kind === 'meeting')) {
          related.push(...(await queryRows({ kind: 'meeting', congress }, signal)).filter(r => r.committee_ids?.includes(ref.id)));
        }
        if (ref.kind === 'committee_term' && (!options.kind || options.kind === 'committee_term')) {
          related.push(...(await queryRows({ kind: 'committee_term', congress }, signal)).filter(r => r.parent_committee_id === ref.id && r.congress === record.congress));
        }
      } else if (ref.kind === 'material' && (!options.kind || options.kind === 'meeting')) {
        related = (await getRecords((record.meeting_ids || []).map(id => ({ kind: 'meeting', id })), { signal })).filter(Boolean);
      }
      if (options.kind) related = related.filter(r => r.kind === options.kind);
      if (!options.kind || options.kind === 'data_issue') {
        related.push(...await read('data_issue', { columns: ['id', 'kind', 'title', 'date'],
          filter: { subject_kind: { $eq: ref.kind }, subject_id: { $eq: ref.id } }, signal }));
      }
      related.sort((a, b) => a.kind.localeCompare(b.kind) || (a.kind === 'meeting' ? (b.date || '').localeCompare(a.date || '') : 0) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id));
      let categories;
      if (options.kind === 'material') {
        const selected = selectRelatedMaterials(related, options);
        related = selected.rows;
        categories = selected.categories;
      }
      const records = (await getRecords(related.slice(offset, offset + limit), { signal })).filter(Boolean);
      return { records, total: related.length, offset, limit, ...(categories ? { categories } : {}) };
    },
  });
}
