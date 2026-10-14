import { parquetMetadataAsync, parquetReadObjects } from 'hyparquet';
import { compressors } from 'hyparquet-compressors';
import { observationReader } from './filename-observations.mjs';
import { loadPublication } from './filename-publication.mjs';
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

export function sourceContext(record) {
  const file_url = validUrl(record.source_url) ? record.source_url : null;
  const recovered_urls = values(record.recovered_source_url).filter(validUrl);
  const pages = [], redirects = [], seen = new Set();
  for (const observation of record.source_occurrences?.length ? record.source_occurrences : [record]) {
    const basis = values(observation.source_association_basis);
    if (basis.includes('publisher_redirect') && !basis.includes('linked_page') && file_url) for (const original of values(observation.source_associated_url)) {
      if (validUrl(original) && original !== file_url && !redirects.some(row => row.original === original)) redirects.push({ original, final: file_url });
    }
    const urls = [...new Set(['source_original_page_url','source_page_url'].flatMap(key => values(observation[key])))].filter(value => validUrl(value) && value !== file_url && !recovered_urls.includes(value));
    if (!urls.length) continue;
    const page = { urls, titles: values(observation.source_page_title), link_labels: values(observation.source_link_label), link_urls: values(observation.source_link_url).filter(validUrl),
      relationship: basis.some(value => !['publisher_redirect','retained_html_link','linked_page'].includes(value)) ? 'Possible source page' : basis.includes('linked_page') ? 'Linked through' : JSON.stringify(observation.source_occurrence_scope) === '["anchor"]' ? 'Linked from' : 'Recorded source page' };
    if (observation.source_page_type?.length) page.types = values(observation.source_page_type);
    if (observation.source_page_date?.length) page.dates = values(observation.source_page_date);
    const key = JSON.stringify(page);
    if (!seen.has(key)) { pages.push(page); seen.add(key); }
  }
  return { file_url, recovered_urls, pages, redirects };
}

/** Bounded compressed-byte cache; the host must return the exact requested range. */
export function rangeFile(url, byteLength, fetcher = fetch) {
  const cache = new Map(); let size = 0;
  async function slice(start, end = byteLength, signal) {
    signal?.throwIfAborted();
    for (const [key, item] of cache) if (item.start <= start && item.end >= end) {
      cache.delete(key); cache.set(key, item);
      return item.bytes.slice(start - item.start, end - item.start);
    }
    const response = await fetcher(url, { signal, headers: { Range: `bytes=${start}-${end - 1}` } });
    if (response.status !== 206 || response.headers.get('Content-Range') !== `bytes ${start}-${end - 1}/${byteLength}`) {
      await response.body?.cancel();
      throw new Error('The catalog host did not return a valid Parquet byte range. Reload and retry.');
    }
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength !== end - start) throw new Error('Incomplete Parquet byte range.');
    signal?.throwIfAborted();
    const key = `${start}/${end}`;
    if (bytes.byteLength <= 32 * 1024 * 1024 && !cache.has(key)) {
      cache.set(key, { start, end, bytes }); size += bytes.byteLength;
      while (size > 48 * 1024 * 1024) { const first = cache.keys().next().value; size -= cache.get(first).bytes.byteLength; cache.delete(first); }
    }
    return bytes;
  }
  return { slice, file: signal => ({ byteLength, slice: (start, end) => slice(start, end, signal) }) };
}

export async function createFilenameCatalog(manifestUrl, fetcher = fetch, catalogId) {
  const publication = await loadPublication(manifestUrl, fetcher, catalogId);
  manifestUrl = publication.url;
  const manifest = publication.manifest, { info, files } = manifest;
  if (![2, 5].includes(manifest.version)) throw new Error('Unsupported filename catalog version.');
  const recovery = await loadRecoveries(publication.recovery, info, fetcher);
  const url = path => new URL(path, manifestUrl).href;
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
  const tables = new Map(), columnCache = new Map();
  async function table(name, signal) {
    if (tables.has(name)) return tables.get(name);
    const part = files[name], buffer = rangeFile(url(part.path), part.bytes, fetcher);
    const metadata = await parquetMetadataAsync(buffer.file(signal));
    if (Number(metadata.num_rows) !== part.rows) throw new Error('Parquet rows disagree with the publication.');
    let offset = 0;
    const spans = metadata.row_groups.map(group => {
      const start = offset; offset += Number(group.num_rows);
      const chunks = group.columns.map(column => column.meta_data);
      return { start, end: offset, chunks };
    });
    const result = { buffer, metadata, spans }; tables.set(name, result); return result;
  }
  async function prefetchColumns(name, start, end, columns, signal) {
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
    for (const [start, end] of merged) await buffer.slice(start, end, signal);
  }
  async function read(name, start, end, columns, signal, prefetch = false) {
    const { buffer, metadata } = await table(name, signal);
    if (prefetch) await prefetchColumns(name, start, end, columns, signal);
    const rows = await parquetReadObjects({ file: buffer.file(signal), metadata, compressors, columns, rowStart: start, rowEnd: end });
    signal?.throwIfAborted(); return rows.map(normalized);
  }
  let observations;
  const originColumns = ['source_association_basis','source_associated_url','source_original_page_url','source_page_url','source_page_title','source_link_label','source_link_url','source_occurrence_scope','source_page_type','source_page_date'];
  async function observationStore(signal) {
    if (!observations) {
      const response = await fetcher(url(files.observation_index.path), {signal});
      if (!response.ok) throw new Error('Could not load the observation index.');
      const descriptor = await response.json();
      if (descriptor.references.rows !== info.rows) throw new Error('Observation rows disagree with the publication.');
      observations = observationReader(descriptor,
        rangeFile(url(files.observations.path), files.observations.bytes, fetcher),
        rangeFile(url(files.observation_rows.path), files.observation_rows.bytes, fetcher));
    }
    return observations;
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
    return record;
  }
  async function sourceRecord(row, signal) {
    const record = await scalarRecord(row, signal);
    record.source_occurrences = await (await observationStore(signal)).read(row, signal);
    // Keep the original field order for copied JSON and technical metadata.
    return Object.fromEntries(info.fields.map(name => [name, record[name]]));
  }
  async function selected(name, positions, columns, signal) {
    const { spans } = await table(name, signal), result = new Map();
    for (const span of spans) {
      const wanted = positions.filter(position => position >= span.start && position < span.end);
      if (!wanted.length) continue;
      const start = Math.min(...wanted), end = Math.max(...wanted) + 1;
      const rows = await read(name, start, end, columns, signal, true);
      for (const position of wanted) result.set(position, rows[position - start]);
    }
    return positions.map(position => result.get(position));
  }
  async function column(name, signal) {
    if (columnCache.has(name)) { const value = columnCache.get(name); columnCache.delete(name); columnCache.set(name, value); return value; }
    const { spans } = await table('filenames', signal), output = new Array(info.rows), queue = [...spans];
    await Promise.all(Array.from({ length: 6 }, async () => {
      while (queue.length) {
        const span = queue.shift(), rows = await read('filenames', span.start, span.end, [name], signal);
        for (let i = 0; i < rows.length; i++) output[span.start + i] = rows[i][name];
      }
    }));
    signal?.throwIfAborted(); columnCache.set(name, output);
    while (columnCache.size > 4) columnCache.delete(columnCache.keys().next().value);
    return output;
  }
  async function search(query, signal) {
    signal?.throwIfAborted();
    const field = query.field || 'filename', needle = (query.q || '').slice(0, 2000).toLowerCase();
    if (!info.fields.includes(field)) throw new Error('Unknown search field.');
    if (!['','yes','no'].includes(query.retained || '') || !['','all','capture-records'].includes(query.scope || '')) throw new Error('Unknown catalog filter.');
    const selectedFilters = filters.filter(key => query[key] && query[key] !== '__null__');
    for (const key of selectedFilters) if (!info.facets[key].includes(query[key])) throw new Error(`Unknown ${key} filter.`);
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
      const matches = (source, searchValue) => {
        if (needle && !text(searchValue).includes(needle) && !(field === 'filename' && text(loaded.get('recovered_filename')?.[source]).includes(needle))) return false;
        return selectedFilters.every(key => values(loaded.get(key)[source]).some(value => (key === 'format' ? value.toLowerCase() : value) === query[key]));
      };
      if (stream) {
        for await (const source of (await observationStore(signal)).matchingSources(needle, signal)) {
          if (selectedFilters.every(key => values(loaded.get(key)[source]).some(value => (key === 'format' ? value.toLowerCase() : value) === query[key]))) mask[groups[source]] = 1;
        }
      } else for (let source = 0; source < info.rows; source++) if (matches(source, loaded.get(field)?.[source])) mask[groups[source]] = 1;
    }
    const found = [];
    for (let group = 0; group < mask.length; group++) {
      const flag = flags[group] | (recovery.groups.has(group) ? 1 : 0);
      if (!mask[group] || (query.retained && !!(flag & 1) !== (query.retained === 'yes')) ||
          (!query.scope && !(flag & 2)) || (query.scope === 'capture-records' && (flag & 2)) ||
          (query.document_kind === '__null__' && !(flag & 4)) || (query.document_family === '__null__' && !(flag & 8))) continue;
      found.push(group);
    }
    const limit = Math.max(1, Math.min(100, Number(query.limit) || 50)), pages = Math.max(1, Math.ceil(found.length / limit)), page = Math.max(1, Math.min(pages, Number(query.page) || 1));
    const chosen = found.slice((page - 1) * limit, page * limit), rows = await selected('browse', chosen, undefined, signal);
    rows.forEach((row, i) => { row._row = preferred[chosen[i]]; row.api_reference = flags[chosen[i]] & 16 ? apiReference(row.source_url) : null; });
    rows.forEach((row, i) => {
      if (recovery.groups.has(chosen[i])) Object.assign(row, {retained: true, recovery: recovery.groups.get(chosen[i])[0], recoveries: recovery.groups.get(chosen[i])});
    });
    signal?.throwIfAborted();
    return { rows, total: found.length, page, pages, limit };
  }
  async function resolve(identity, catalog, signal) {
    if (catalog && catalog !== info.catalog_id) throw new Error('This link belongs to a different catalog snapshot. Close this panel and select the document in the current results.');
    if (/^\d{1,11}$/.test(identity) && Number(identity) < info.rows) return Number(identity);
    if (!/^[a-f0-9]{64}$/.test(identity)) throw new Error('Source record is not present in this catalog.');
    const response = await fetcher(url(manifest.ids + identity.slice(0, 2) + '.bin'), { signal });
    if (!response.ok) throw new Error('Could not resolve the source record.');
    const buffer = await response.arrayBuffer(), bytes = new Uint8Array(buffer), view = new DataView(buffer);
    if (bytes.length % 36) throw new Error('Incomplete source ID index.');
    const wanted = identity.match(/../g).map(value => parseInt(value, 16));
    for (let offset = 0; offset < bytes.length; offset += 36) if (wanted.every((value, i) => value === bytes[offset + i])) {
      const row = view.getUint32(offset + 32, true);
      if (row >= info.rows) throw new Error('Invalid source ID index.');
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
    const offset = Math.max(0, Math.trunc(Number(options.offset) || 0));
    const limit = Math.max(1, Math.min(100, Math.trunc(Number(options.limit) || 20)));
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
      ['source_url','recovered_source_url'].filter(name => info.fields.includes(name)), signal, true))[0];
  }
  async function entry(identity, catalog, signal) {
    const row = await resolve(identity, catalog, signal);
    const [groups, preferred] = await Promise.all(['groups', 'preferred'].map(index));
    const group = groups[row], members = await membersOf(group);
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
    document.source_id = sources[members.indexOf(preferred[group])].source_id;
    const recovered = recovery.groups.get(group);
    if (recovered) Object.assign(document, {recovery: recovered[0], recoveries: recovered});
    const evidence = await (await observationStore(signal)).page(row, {limit: 20, columns: originColumns}, signal);
    const origin = sourceContext({...record, source_occurrences: evidence.items.filter(Boolean)});
    const canonicalEvidence = row === preferred[group] ? evidence : await (await observationStore(signal)).page(preferred[group], {limit: 20, columns: originColumns}, signal);
    const canonicalSource = sources[members.indexOf(preferred[group])];
    const documentOrigin = row === preferred[group] ? origin : sourceContext({...canonicalSource, source_occurrences: canonicalEvidence.items.filter(Boolean)});
    return {record, document, facts, filename_field_count, filename: document.filename, sources, catalog_id: info.catalog_id,
      api_reference: apiReference(record.source_url), ...(recovered ? {recovery: recovered[0], recoveries: recovered} : {}),
      origin, document_origin: {redirects: documentOrigin.redirects}, observation_count: evidence.total, origin_next: evidence.next, record_complete: false,
      reading: null, saved_file_available: false, saved_file_url: savedCopyUrl(record, recovered?.[0], manifestUrl), published_only: true,
      sources_share_saved_file: !!bodies[0] && bodies.every(value => value === bodies[0])};
  }
  return { info: { ...info, recovery_sha256: publication.recovery?.sha256, downloads: { documents: url(files.documents.path), filenames: url(files.filenames.path), recoveries: publication.recovery?.url }, published_at: manifest.published_at }, search, entry, technical, technicalOrigin, observationPage, sourceContext };
}
