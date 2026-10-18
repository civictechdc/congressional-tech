import { sourceContext } from '../../../../docs/youtube-coverage/research/filename-provenance.mjs';
export { sourceContext };
import { yieldToMessages, scanBatchRows } from './filename-cooperative.mjs';
import { byteCache, retainedBytes, sharedLoad } from './filename-cache.mjs';
import { positiveInteger } from '../../../../docs/youtube-coverage/research/filename-rules.mjs';
import { parquetMetadataAsync, parquetReadObjects, parquetRead } from 'hyparquet';
import { compressors } from 'hyparquet-compressors';
import { observationReader } from './filename-observations.mjs';
import { loadPublication } from './filename-publication.mjs';
import { loadReviews, reviewedMode } from './filename-reviews.mjs';
import { loadRecoveries } from './filename-recoveries.mjs';

const filters = ['congress', 'document_family', 'document_kind', 'format'];
const sourceColumns = ['filename','source_url','source_id','body_key','format','record_role'];
const text = value => (Array.isArray(value) ? value.map(item => typeof item === 'object' ? JSON.stringify(item) : item).join(' | ') : value ?? '').toString().toLowerCase();
const normalized = value => value == null ? null : value instanceof Date ? value.toISOString() : Array.isArray(value) ? value.map(normalized) : typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalized(item)])) : value;
const values = value => Array.isArray(value) ? value : value == null ? [] : [value];
const validUrl = value => { try { const url = new URL(value); return /^https?:$/.test(url.protocol) && !url.username && !url.password ? url : null; } catch { return null; } };

export function savedCopyUrl(record, groupRecovery, manifestUrl) {
  const recovery = record.recovery || groupRecovery;
  const key = recovery?.recovery_status === 'recovered' ? recovery.body_key : record.body_key;
  const match = /^bodies\/sha256\/([a-f0-9]{2})\/([a-f0-9]{64})\.gz$/.exec(key || '');
  if (!match || match[1] !== match[2].slice(0, 2) || !validUrl(manifestUrl)) return null;
  return new URL(`/saved/${match[2]}/${encodeURIComponent(record.filename || 'saved-copy')}`, manifestUrl).href;
}

export function apiReference(value) {
  const url = validUrl(value);
  if (url?.hostname !== 'api.congress.gov' || !url.pathname.startsWith('/v3/')) return null;
  const parts = url.pathname.slice(4).split('/').filter(Boolean);
  if (!parts.length) return null;
  const title = parts.length >= 4 && /^\d+$/.test(parts[1]) && ['house','senate'].includes(parts[2])
    ? `${parts[2]} ${parts[0].replaceAll('-', ' ')} ${parts[3]} · Congress ${parts[1]}${parts.length > 4 ? ' · ' + parts.slice(4).join(' / ') : ''}`
    : parts[0].replaceAll('-', ' ') + (parts.length > 1 ? ' · ' + parts.slice(1).join(' / ') : '');
  return { title: title.replace(/^./, value => value.toUpperCase()), evidence: 'Congress.gov API endpoint URL' };
}

export function videoReference(value) {
  const url = validUrl(value);
  if (!url) return null;
  const host = url.hostname.replace(/^www\./, '');
  const parts = url.pathname.replace(/^\/+|\/+$/g, '').split('/');
  const id = host === 'youtu.be' ? parts[0]
    : ['youtube.com', 'youtube-nocookie.com'].includes(host)
      ? url.pathname === '/watch' ? url.searchParams.get('v')
        : parts.length === 2 && ['live', 'embed', 'shorts', 'v'].includes(parts[0]) ? parts[1] : null
      : null;
  return /^[A-Za-z0-9_-]{11}$/.test(id || '') ? {provider: 'YouTube', id} : null;
}

/** Bounded compressed-byte cache; the host must return the exact requested range. */
export function rangeFile(url, byteLength, fetcher = fetch, cache = byteCache(48 * 1024 * 1024, 32 * 1024 * 1024), metrics = {}) {
  const pending = new Map();
  async function slice(start, end = byteLength, signal) {
    signal?.throwIfAborted();
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end <= start || end > byteLength) throw new Error('Invalid catalog byte range.');
    for (const [key, item] of cache.entries()) if (item.url === url && item.start <= start && item.end >= end) {
      cache.get(key); metrics.rangeHits = (metrics.rangeHits || 0) + 1;
      return item.bytes.slice(start - item.start, end - item.start);
    }
    const key = `${url}:${start}/${end}`;
    const bytes = await sharedLoad(pending, key, async () => {
      const response = await fetcher(url, { headers: { Range: `bytes=${start}-${end - 1}` } });
      if (response.status !== 206 || response.headers.get('Content-Range') !== `bytes ${start}-${end - 1}/${byteLength}`) {
        await response.body?.cancel();
        throw new Error('The catalog host did not return a valid Parquet byte range. Reload and retry.');
      }
      const bytes = await response.arrayBuffer();
      metrics.rangeRequests = (metrics.rangeRequests || 0) + 1;
      metrics.rangeBytes = (metrics.rangeBytes || 0) + bytes.byteLength;
      if (bytes.byteLength !== end - start) throw new Error('Incomplete Parquet byte range.');
      cache.set(key, {url, start, end, bytes}, bytes.byteLength);
      return bytes;
    }, signal);
    signal?.throwIfAborted(); return bytes;
  }
  return { slice, canRetain: size => cache.admits(size,`${url}:${byteLength}/${byteLength}`), cacheBudget: cache.stats.maxBytes,
    file: signal => ({ byteLength, slice: (start, end) => slice(start, end, signal) }) };
}

export async function createFilenameCatalog(manifestUrl, fetcher = fetch, catalogId, reviewPublication, options = {}) {
  const publication = await loadPublication(manifestUrl, fetcher, catalogId);
  manifestUrl = publication.url;
  const manifest = publication.manifest, { info, files } = manifest;
  if (![2, 5].includes(manifest.version)) throw new Error('Unsupported filename catalog version.');
  const recovery = await loadRecoveries(publication.recovery, info, fetcher);
  const reviews = await loadReviews(reviewPublication, manifest, fetcher, manifestUrl);
  Object.assign(info, reviews.info);
  const url = path => new URL(path, manifestUrl).href;
  const metrics = {sourceScanVisits: 0, groupScanVisits: 0, columnLoads: 0, tableLoads: 0, observationStoreLoads: 0, decodedRows: 0, normalizationValues: 0};
  const compressedCache = byteCache(options.compressedBytes ?? 48 * 1024 * 1024, options.rangeEntryBytes ?? 32 * 1024 * 1024);
  const decodedCache = byteCache(options.decodedBytes ?? 64 * 1024 * 1024);
  const loads = new Map();
  const ranged = part => rangeFile(url(part.path), part.bytes, fetcher, compressedCache, metrics);
  const cached = (key, load, signal) => {
    signal?.throwIfAborted();
    const value = decodedCache.get(key);
    return value ? Promise.resolve(value) : sharedLoad(loads, key, async () => { const value = await load(); decodedCache.set(key,value); return value; }, signal);
  };
  async function binary(name) {
    const response = await fetcher(url(files[name].path));
    if (!response.ok) throw new Error('Could not load the catalog navigation index.');
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength !== files[name].bytes) throw new Error('Incomplete catalog navigation index.');
    return bytes;
  }
  // Shared index loads outlive individual queries; cancellation is checked by
  // each caller so typing cannot cancel an index another request is using.
  const indexes = new Map();
  function index(name) {
    if (!indexes.has(name)) indexes.set(name, binary(name).then(buffer => {
      const array = name === 'flags' ? new Uint8Array(buffer) : new Uint32Array(buffer);
      if (array.length !== (name === 'groups' ? info.rows : info.entries)) throw new Error('Catalog index counts disagree.');
      if (name === 'groups' && array.some(group => group >= info.entries)) throw new Error('Invalid catalog group.');
      return array;
    }).catch(error => { indexes.delete(name); throw error; }));
    return indexes.get(name);
  }
  let membership;
  async function membersOf(group) {
    if (!membership) {
      const groups = await index('groups');
      if (!membership) {
        const first = new Int32Array(info.entries).fill(-1), next = new Int32Array(info.rows);
        for (let source = info.rows - 1; source >= 0; source--) {
          next[source] = first[groups[source]]; first[groups[source]] = source;
        }
        membership = { first, next };
      }
    }
    const members = [];
    for (let source = membership.first[group]; source !== -1; source = membership.next[source]) members.push(source);
    return members;
  }
  const navigationFiles = new Map();
  function navigationFile(name, length) {
    const part = files[name];
    if (!part || part.bytes !== length) throw new Error('Invalid detail navigation index.');
    if (!navigationFiles.has(name)) navigationFiles.set(name, ranged(part));
    return navigationFiles.get(name);
  }
  async function navigation(row, signal) {
    if (!files.detail_navigation && !files.detail_members) {
      const [groups, preferred] = await Promise.all(['groups', 'preferred'].map(index));
      const group = groups[row];
      return {group, preferred: preferred[group], members: await membersOf(group)};
    }
    const bytes = await navigationFile('detail_navigation', info.rows * 16).slice(row * 16, (row + 1) * 16, signal);
    const view = new DataView(bytes);
    const group = view.getUint32(0, true), preferred = view.getUint32(4, true);
    const offset = view.getUint32(8, true), count = view.getUint32(12, true);
    if (group >= info.entries || preferred >= info.rows || !count || offset + count > info.rows) throw new Error('Invalid detail navigation record.');
    const packed = await navigationFile('detail_members', info.rows * 4).slice(offset * 4, (offset + count) * 4, signal);
    const data = new DataView(packed), members = Array.from({length: count}, (_, i) => data.getUint32(i * 4, true));
    if (!members.includes(row) || !members.includes(preferred) || members.some((member, i) => member >= info.rows || (i && member <= members[i - 1]))) throw new Error('Invalid detail group membership.');
    return {group, preferred, members};
  }
  function table(name, signal) {
    return cached(`table:${name}`, async () => {
    metrics.tableLoads++;
    const part = files[name], buffer = ranged(part);
    const metadata = await parquetMetadataAsync(buffer.file());
    if (Number(metadata.num_rows) !== part.rows) throw new Error('Parquet rows disagree with the publication.');
    let offset = 0;
    const spans = metadata.row_groups.map(group => {
      const start = offset; offset += Number(group.num_rows);
      const chunks = group.columns.map(column => column.meta_data);
      return { start, end: offset, chunks };
    });
    return { buffer, metadata, spans };
    }, signal);
  }
  async function prefetchColumns(name, start, end, columns, signal) {
    if (options.prefetch === false) return;
    const { buffer, spans } = await table(name, signal);
    const ranges = [];
    for (const span of spans) if (span.end > start && span.start < end) {
      for (const chunk of span.chunks) if (!columns || columns.includes(chunk.path_in_schema[0])) {
        const start = Number(chunk.dictionary_page_offset ?? chunk.data_page_offset);
        ranges.push([start, start + Number(chunk.total_compressed_size)]);
      }
    }
    ranges.sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const range of ranges) {
      const last = merged.at(-1);
      if (last && range[0] <= last[1] + 1024) last[1] = Math.max(last[1], range[1]);
      else merged.push([...range]);
    }
    // Unadmitted prefetch transfers would be downloaded again by the decoder.
    if (merged.reduce((sum,[start,end])=>sum+end-start+512,0) > buffer.cacheBudget || merged.some(([start,end])=>!buffer.canRetain(end-start))) {
      metrics.skippedPrefetches = (metrics.skippedPrefetches || 0) + 1;
      return;
    }
    for (const [start, end] of merged) await buffer.slice(start, end, signal);
  }
  async function read(name, start, end, columns, signal, prefetch = false) {
    const { buffer, metadata } = await table(name, signal);
    if (prefetch) await prefetchColumns(name, start, end, columns, signal);
    const rows = await parquetReadObjects({ file: buffer.file(signal), metadata, compressors, columns, rowStart: start, rowEnd: end });
    signal?.throwIfAborted(); metrics.decodedRows += rows.length; metrics.normalizationValues += rows.length * (columns?.length ?? metadata.schema.length); return rows.map(normalized);
  }
  const originColumns = ['source_association_basis','source_associated_url','source_original_page_url','source_page_url','source_page_title','source_link_label','source_link_url','source_occurrence_scope','source_page_type','source_page_date'];
  function observationStore(signal) {
    return cached('observation-store', async () => {
      metrics.observationStoreLoads++;
      const response = await fetcher(url(files.observation_index.path));
      if (!response.ok) throw new Error('Could not load the observation index.');
      const descriptor = await response.json();
      if (descriptor.references.rows !== info.rows) throw new Error('Observation rows disagree with the publication.');
      const store = observationReader(descriptor, ranged(files.observations), ranged(files.observation_rows), {metrics, cache: decodedCache});
      return {...store, descriptor};
    }, signal);
  }
  async function scalarRecord(row, signal) {
    const columns = info.fields.filter(name => name !== 'source_occurrences');
    await prefetchColumns('filenames', row, row + 1, columns, signal);
    const record = {};
    // Wide reads allocate every physical column at once, even for one row.
    // Small batches bound that work without changing the downloadable schema.
    for (let start = 0; start < columns.length; start += 8) {
      Object.assign(record, (await read('filenames', row, row + 1, columns.slice(start, start + 8), signal))[0]);
    }
    metrics.maxScalarRecordBytes = Math.max(metrics.maxScalarRecordBytes || 0,retainedBytes(record));
    return record;
  }
  async function sourceRecord(row, signal) {
    const record = await scalarRecord(row, signal);
    record.source_occurrences = await (await observationStore(signal)).read(row, signal);
    // Keep the original field order for copied JSON and technical metadata.
    const output = Object.fromEntries(info.fields.map(name => [name, record[name]]));
    metrics.maxFullRecordBytes = Math.max(metrics.maxFullRecordBytes || 0,retainedBytes(output));
    return output;
  }
  async function selected(name, positions, columns, signal) {
    const {buffer, metadata, spans} = await table(name, signal), result = new Map();
    const ordered = [...new Set(positions)].sort((a,b)=>a-b); let cursor = 0;
    for (const span of spans) {
      const wanted = [];
      while (cursor < ordered.length && ordered[cursor] < span.end) {
        const position = ordered[cursor++];
        if (position < span.start) throw new Error('Invalid catalog row position.');
        wanted.push(position); result.set(position, {});
      }
      if (!wanted.length) continue;
      await prefetchColumns(name, span.start, span.end, columns, signal);
      // Let the maintained reader assemble columns, then construct only selected
      // row objects. Physical column chunks still decode at row-group granularity.
      await parquetRead({file: buffer.file(signal), metadata, compressors, columns,
        rowStart: span.start, rowEnd: span.end, rowFormat: 'object', onChunk({columnName,columnData,rowStart,rowEnd}) {
          metrics.physicalColumnValues = (metrics.physicalColumnValues || 0) + columnData.length;
          for (const position of wanted) if (position >= rowStart && position < rowEnd) {
            result.get(position)[columnName] = normalized(columnData[position-rowStart]);
            metrics.normalizationValues++;
          }
        }});
      signal?.throwIfAborted(); metrics.decodedRows += wanted.length;
    }
    if (cursor !== ordered.length) throw new Error('Invalid catalog row position.');
    return positions.map(position => result.get(position));
  }
  function column(name, signal) {
    return cached(`column:${name}`, async () => {
      metrics.columnLoads++;
      const {spans} = await table('filenames'), output = new Array(info.rows);
      let nextSpan = 0;
      await Promise.all(Array.from({length: Math.min(6,spans.length)}, async () => {
        while (nextSpan < spans.length) {
          const span = spans[nextSpan++], rows = await read('filenames',span.start,span.end,[name]);
          for (let i=0;i<rows.length;i++) output[span.start+i] = rows[i][name];
        }
      }));
      return output;
    }, signal);
  }
  function searchTexts(name, source, signal) {
    const key = `search:${name}`, retained = decodedCache.get(key);
    if (retained) return Promise.resolve(retained);
    const budget = Math.min(options.searchNormalizationBytes ?? 8 * 1024 * 1024, decodedCache.stats.maxBytes / 4);
    if (retainedBytes(source) > budget) return Promise.resolve(null);
    return sharedLoad(loads,key,async () => {
      const output = []; let bytes = 24;
      for (let i=0;i<source.length;i++) {
        if (i && i % scanBatchRows === 0) await yieldToMessages(undefined,metrics);
        const value = text(source[i]); metrics.searchNormalizations = (metrics.searchNormalizations || 0) + 1;
        bytes += 24 + value.length*2;
        if (bytes > budget) return null;
        output.push(value);
      }
      decodedCache.set(key,output,bytes);return output;
    },signal);
  }
  async function search(query, signal) {
    signal?.throwIfAborted();
    const reviewed = reviewedMode(query, info);
    const limit = positiveInteger(query.limit,50,100), requestedPage = positiveInteger(query.page);
    const firstWanted = (requestedPage-1)*limit;
    const field = query.field || 'filename', needle = (query.q || '').slice(0, 2000).toLowerCase();
    if (!info.fields.includes(field)) throw new Error('Unknown search field.');
    if (!['','yes','no'].includes(query.retained || '') || !['','all','capture-records'].includes(query.scope || '')) throw new Error('Unknown catalog filter.');
    const selectedFilters = filters.filter(key => query[key] && query[key] !== '__null__');
    for (const key of selectedFilters) if (!(info.review_facets?.[key] || info.facets[key]).includes(query[key])) throw new Error(`Unknown ${key} filter.`);
    const [preferred, flags] = await Promise.all(['preferred', 'flags'].map(index));
    signal?.throwIfAborted();
    const mask = new Uint8Array(info.entries).fill(needle || selectedFilters.length ? 0 : 1);
    if (needle || selectedFilters.length) {
      const groups = await index('groups');
      signal?.throwIfAborted();
      // Search each unique observation once, then map matches to source groups.
      const stream = needle && field === 'source_occurrences';
      const names = [...new Set([...selectedFilters, ...(needle && !stream ? [field, ...(field === 'filename' && info.fields.includes('recovered_filename') ? ['recovered_filename'] : [])] : [])])];
      const loaded = new Map();
      for (const name of names) loaded.set(name, await column(name, signal));
      const sourceValue = (source, field) => {
        const review = reviewed && reviews.sources.get(source);
        return review?.status === 'candidate_applied' && field in review.selected ? review.selected[field] : loaded.get(field)?.[source];
      };
      const preparedText = needle && !stream ? await searchTexts(field,loaded.get(field),signal) : null;
      const recoveredText = needle && field === 'filename' && loaded.has('recovered_filename') ? await searchTexts('recovered_filename',loaded.get('recovered_filename'),signal) : null;
      const normalizeText = value => {metrics.searchNormalizations = (metrics.searchNormalizations || 0) + 1;return text(value);};
      const matches = (source, searchValue) => {
        const review = reviewed && reviews.sources.get(source);
        const changed = review?.status === 'candidate_applied' && field in review.selected;
        if (needle && !(changed ? normalizeText(searchValue) : preparedText?.[source] ?? normalizeText(searchValue)).includes(needle) &&
            !(field === 'filename' && (recoveredText?.[source] ?? normalizeText(loaded.get('recovered_filename')?.[source])).includes(needle))) return false;
        return selectedFilters.every(key => values(sourceValue(source, key)).some(value => (key === 'format' ? value.toLowerCase() : value) === query[key]));
      };
      if (stream) {
        for await (const source of (await observationStore(signal)).matchingSources(needle, signal)) {
          if (selectedFilters.every(key => values(sourceValue(source, key)).some(value => (key === 'format' ? value.toLowerCase() : value) === query[key]))) mask[groups[source]] = 1;
        }
      } else for (let source = 0; source < info.rows; source++) {
        if (source && source % scanBatchRows === 0) await yieldToMessages(signal, metrics);
        metrics.sourceScanVisits++;
        if (matches(source, sourceValue(source, field))) mask[groups[source]] = 1;
      }
    }
    let total=0, chosen=[], last=[];
    for (let group = 0; group < mask.length; group++) {
      if (group && group % scanBatchRows === 0) await yieldToMessages(signal, metrics);
      metrics.groupScanVisits++;
      let flag = flags[group] | (recovery.groups.has(group) ? 1 : 0);
      const review = reviewed && reviews.groups.get(group);
      if (review?.status === 'candidate_applied') {
        flag = (flag & ~12) | (review.selected.document_kind?.length ? 0 : 4) | (review.selected.document_family?.length ? 0 : 8);
      }
      if (!mask[group] || (query.retained && !!(flag & 1) !== (query.retained === 'yes')) ||
          (!query.scope && !(flag & 2)) || (query.scope === 'capture-records' && (flag & 2)) ||
          (query.document_kind === '__null__' && !(flag & 4)) || (query.document_family === '__null__' && !(flag & 8))) continue;
      if (total % limit === 0) last=[];
      last.push(group);
      if (total >= firstWanted && total < firstWanted+limit) chosen.push(group);
      total++;
      metrics.maxMatchedGroupsRetained = Math.max(metrics.maxMatchedGroupsRetained || 0,chosen.length+last.length);
    }
    const pages=Math.max(1,Math.ceil(total/limit)), page=Math.min(requestedPage,pages);
    if (page !== requestedPage) chosen=last;
    const rows = await selected('browse', chosen, undefined, signal);
    rows.forEach((row, i) => { row._row = preferred[chosen[i]]; row.api_reference = flags[chosen[i]] & 16 ? apiReference(row.source_url) : null; row.video_reference = flags[chosen[i]] & 32 ? videoReference(row.source_url) : null; });
    rows.forEach((row, i) => {
      if (recovery.groups.has(chosen[i])) Object.assign(row, {retained: true, recovery: recovery.groups.get(chosen[i])[0], recoveries: recovery.groups.get(chosen[i])});
    });
    if (reviewed) rows.forEach((row, i) => {
      const review = reviews.groups.get(chosen[i]);
      if (!review) return;
      row._review_status = review.status;
      if (review.status === 'candidate_applied') {
        row.catalog_document_kind = row.document_kind;
        Object.assign(row, structuredClone(review.selected));
      }
    });
    signal?.throwIfAborted();
    return { rows, total, page, pages, limit };
  }
  const resolved = new Map();
  async function resolve(identity, catalog, signal) {
    signal?.throwIfAborted();
    if (catalog && catalog !== info.catalog_id) throw new Error('This link belongs to a different catalog snapshot. Close this panel and select the document in the current results.');
    if (/^\d{1,11}$/.test(identity) && Number(identity) < info.rows) return Number(identity);
    if (!/^[a-f0-9]{64}$/.test(identity)) throw new Error('Source record is not present in this catalog.');
    if (resolved.has(identity)) return resolved.get(identity);
    const prefix = identity.slice(0, 2);
    const buffer = await cached(`ids:${prefix}`, async () => {
      const response = await fetcher(url(manifest.ids + prefix + '.bin'));
      if (!response.ok) throw new Error('Could not resolve the source record.');
      const buffer = await response.arrayBuffer(), view = new DataView(buffer);
      if (buffer.byteLength % 36) throw new Error('Incomplete source ID index.');
      for (let offset=0;offset<buffer.byteLength;offset+=36) if (view.getUint32(offset+32,true)>=info.rows) throw new Error('Invalid source ID index.');
      return buffer;
    }, signal);
    const bytes = new Uint8Array(buffer), view = new DataView(buffer);
    if (bytes.length % 36) throw new Error('Incomplete source ID index.');
    const wanted = identity.match(/../g).map(value => parseInt(value, 16));
    for (let offset = 0; offset < bytes.length; offset += 36) if (wanted.every((value, i) => value === bytes[offset + i])) {
      const row = view.getUint32(offset + 32, true);
      if (row >= info.rows) throw new Error('Invalid source ID index.');
      if (resolved.size >= 256) resolved.delete(resolved.keys().next().value);
      resolved.set(identity, row);
      return row;
    }
    throw new Error('Source record is not present in this catalog.');
  }
  async function detailRecord(row, signal) {
    if (!files.details) {
      // Old immutable publications remain readable without eager nested evidence.
      const record = await scalarRecord(row, signal);
      return {record, facts: null};
    }
    const [data] = await read('details', row, row + 1, undefined, signal, true);
    const {filename_readings, fact_alternatives, filename_field_count, ...record} = data;
    const facts = {};
    for (const name of ['http_status','response_usable','response_body_complete','record_role','state_checked_at','state_retrieved_at']) {
      if (!(name in record)) continue;
      facts[name] = record[name];
      record[name] = record[name] == null ? null : [String(record[name])];
    }
    for (const item of fact_alternatives || []) record[item.field] = item.values;
    for (const item of filename_readings || []) record[item.field] = item.values;
    facts.completeness_conflict = new Set(record.response_body_complete || []).size > 1;
    return {record, facts, filename_field_count};
  }
  async function observationPage(identity, catalog, options = {}, signal) {
    const row = await resolve(identity, catalog, signal);
    const offset = positiveInteger(options.offset, 0);
    const limit = positiveInteger(options.limit, 20, 100);
    return (await observationStore(signal)).page(row, {offset, limit, ...(options.origin ? {columns: originColumns} : {})}, signal);
  }
  async function technical(identity, catalog, signal, full = false) {
    const row = await resolve(identity, catalog, signal);
    const record = full ? await sourceRecord(row, signal) : await scalarRecord(row, signal);
    if (recovery.sources.has(row)) record.recovery = recovery.sources.get(row);
    return record;
  }
  async function technicalOrigin(identity, catalog, signal) {
    const row = await resolve(identity, catalog, signal);
    return (await read(files.details ? 'details' : 'filenames', row, row + 1,
      ['source_url','recovered_source_url', ...originColumns].filter(name => info.fields.includes(name)), signal, true))[0];
  }
  async function entry(identity, catalog, signal, options = {}) {
    const row = await resolve(identity, catalog, signal);
    const {group, preferred, members} = await navigation(row, signal);
    const {record, facts, filename_field_count} = await detailRecord(row, signal);
    if (recovery.sources.has(row)) record.recovery = recovery.sources.get(row);
    const [document] = files.document_summaries
      ? await selected('document_summaries', [(await index('document_rows'))[group]], undefined, signal)
      : await selected('browse', [group], ['filename','document_kind','document_kind_source'], signal);
    const sources = await selected(files.details ? 'details' : 'filenames', members, files.details ? [...sourceColumns, 'fact_alternatives'] : sourceColumns, signal);
    if (files.details) for (const source of sources) {
      source.record_role = source.fact_alternatives?.find(item => item.field === 'record_role')?.values ?? (source.record_role == null ? null : [source.record_role]);
      delete source.fact_alternatives;
    }
    const bodies = sources.map(source => source.body_key);
    for (const source of sources) { source.retained = source.body_key != null; delete source.body_key; }
    sources.forEach((source, i) => { if (recovery.sources.has(members[i])) Object.assign(source, {retained: true, recovery: recovery.sources.get(members[i])}); });
    document.source_id = sources[members.indexOf(preferred)].source_id;
    const recovered = recovery.groups.get(group);
    if (recovered) Object.assign(document, {recovery: recovered[0], recoveries: recovered});
    const context = options.deferOrigin ? {origin_pending: true, origin: sourceContext(record), document_origin: {redirects: []}}
      : await entryOrigin(identity, catalog, signal, {row, preferred, record, canonicalSource: sources[members.indexOf(preferred)]});
    return {record, document, facts, filename_field_count, filename: document.filename, sources, catalog_id: info.catalog_id,
      api_reference: apiReference(record.source_url), video_reference: videoReference(record.source_url), ...(recovered ? {recovery: recovered[0], recoveries: recovered} : {}),
      ...context, record_complete: false,
      reading: null, saved_file_available: false, saved_file_url: savedCopyUrl(record, recovered?.[0], manifestUrl), published_only: true,
      sources_share_saved_file: !!bodies[0] && bodies.every(value => value === bodies[0])};
  }
  async function entryOrigin(identity, catalog, signal, known) {
    const row = known?.row ?? await resolve(identity, catalog, signal);
    const preferred = known?.preferred ?? (await navigation(row, signal)).preferred;
    const record = known?.record ?? await technicalOrigin(String(row), catalog, signal);
    const store = await observationStore(signal);
    const evidence = await store.page(row, {limit: 20, columns: originColumns}, signal);
    const origin = sourceContext({...record, source_occurrences: evidence.items.filter(Boolean)});
    let documentOrigin = origin;
    if (row !== preferred) {
      const canonical = known?.canonicalSource ?? await technicalOrigin(String(preferred), catalog, signal);
      const canonicalEvidence = await store.page(preferred, {limit: 20, columns: originColumns}, signal);
      documentOrigin = sourceContext({...canonical, source_occurrences: canonicalEvidence.items.filter(Boolean)});
    }
    return {origin_pending: false, origin, document_origin: {redirects: documentOrigin.redirects}, observation_count: evidence.total, origin_next: evidence.next};
  }
  async function review(identity, catalog, signal, withdrawn = false) {
    if (info.review_error) throw new Error(info.review_error);
    if (!info.complete_body_reviews) throw new Error('Document reviews are not configured.');
    const row = await resolve(identity, catalog, signal);
    const value = reviews.sources.get(row);
    if (!value) return {status: 'no_review'};
    return structuredClone({...value, status: withdrawn ? 'withdrawn' : value.status, selected: withdrawn ? value.baseline : value.selected});
  }
  return { diagnostics: () => ({...metrics, compressed: compressedCache.stats, decoded: decodedCache.stats}), review, info: { ...info, recovery_sha256: publication.recovery?.sha256, downloads: { documents: url(files.documents.path), filenames: url(files.filenames.path), recoveries: publication.recovery?.url }, published_at: manifest.published_at }, search, entry, entryOrigin, technical, technicalOrigin, observationPage, sourceContext };
}
