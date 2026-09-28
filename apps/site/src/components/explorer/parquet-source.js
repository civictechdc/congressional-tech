import { parquetMetadataAsync, parquetReadObjects, rowIndex } from 'hyparquet';
import { presentRecord, recordingDue, recordingVisible } from './record-presentation.js';
import { groupCommitteeTerms, matches, pageBounds, summarizeCoverage } from './query-utils.js';
import { selectRelatedMaterials } from './related-materials.js';

/** HTTP ranges remain inside the injected reader. No SQL engine or record shards. */
export function createParquetReader(publication, fetcher) {
  const { manifest, manifestUrl, select, readPartition } = publication;
  const parts = manifest.partitions.filter(p => p.media_type === 'application/vnd.apache.parquet');
  const metadataCache = new Map();
  const rowsCache = new Map();
  const positions = new Map();
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
        const response = await fetcher(new URL(part.path, manifestUrl), { signal, headers: { Range: `bytes=${start}-${end - 1}` } });
        if (response.status !== 206 || response.headers.get('Content-Range') !== `bytes ${start}-${end - 1}/${part.byte_size}`) {
          await response.body?.cancel();
          throw new Error('The data host must support HTTP byte-range requests for Parquet.');
        }
        const bytes = await response.arrayBuffer();
        if (bytes.byteLength !== end - start) throw new Error('Incomplete Parquet byte range.');
        return bytes;
      },
    };
  }
  async function read(kind, { columns, filter, signal, position } = {}) {
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
      const batch = await parquetReadObjects({ file: buffer, metadata, columns, filter, includeRowIndex: true,
        ...(position ? { rowStart: position.index, rowEnd: position.index + 1 } : {}) });
      signal?.throwIfAborted();
      for (const row of batch) {
        positions.set(`${kind}/${row.id}`, { path: part.path, index: row[rowIndex] });
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
    const rows = await read(kind, { columns: [...info.query_columns, ...extra],
      filter: congress === 'all' ? undefined : { congress: { $eq: Number(congress) } }, signal });
    return cacheRows(key, rows);
  }
  async function getRecords(refs, { signal } = {}) {
    const found = new Map();
    for (const kind of new Set(refs.map(r => r.kind))) {
      const ids = refs.filter(r => r.kind === kind).map(r => r.id);
      const missing = ids.filter(id => !positions.has(`${kind}/${id}`));
      if (missing.length) await read(kind, { columns: ['id'], filter: { id: { $in: missing } }, signal });
      for (const id of ids) {
        const position = positions.get(`${kind}/${id}`);
        if (!position) continue;
        const [row] = await read(kind, { position, signal });
        if (!row || row.id !== id) throw new Error('Parquet row lookup changed within a release.');
        if (kind === 'source_record' && row.payload) row.payload = JSON.parse(row.payload);
        found.set(`${kind}/${row.id}`, presentRecord(row));
      }
    }
    return refs.map(ref => found.get(`${ref.kind}/${ref.id}`));
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
          const material = rowsCache.get(cacheKey) || cacheRows(cacheKey, await read('material', {
            columns: ['id', 'kind', 'title', 'meeting_ids', 'appearance_ids', 'committee_ids', 'type', 'document_type', 'category', 'date', 'scheduled_at', 'meeting_status', 'recording_url'],
            filter: { [membership]: { $in: [ref.id] } }, signal }));
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
