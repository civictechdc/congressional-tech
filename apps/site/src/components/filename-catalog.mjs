import { parquetMetadataAsync, parquetReadObjects } from 'hyparquet';
import { compressors } from 'hyparquet-compressors';

const filters = ['congress', 'document_family', 'document_kind', 'format'];
const sourceColumns = ['filename','source_url','source_id','body_key','format','record_role'];
const text = value => (Array.isArray(value) ? value.map(item => typeof item === 'object' ? JSON.stringify(item) : item).join(' | ') : value ?? '').toString().toLowerCase();
const normalized = value => value == null ? null : Array.isArray(value) ? value.map(normalized) : typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalized(item)])) : value;
const values = value => Array.isArray(value) ? value : value == null ? [] : [value];
const validUrl = value => { try { const url = new URL(value); return /^https?:$/.test(url.protocol) && !url.username && !url.password ? url : null; } catch { return null; } };

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
    if (basis.includes('publisher_redirect') && file_url) for (const original of values(observation.source_associated_url)) {
      if (validUrl(original) && original !== file_url && !redirects.some(row => row.original === original)) redirects.push({ original, final: file_url });
    }
    const urls = [...new Set(['source_original_page_url','source_page_url'].flatMap(key => values(observation[key])))].filter(value => validUrl(value) && value !== file_url && !recovered_urls.includes(value));
    if (!urls.length) continue;
    const page = { urls, titles: values(observation.source_page_title), link_labels: values(observation.source_link_label), link_urls: values(observation.source_link_url).filter(validUrl),
      relationship: basis.some(value => !['publisher_redirect','retained_html_link'].includes(value)) ? 'Possible source page' : JSON.stringify(observation.source_occurrence_scope) === '["anchor"]' ? 'Linked from' : 'Recorded source page' };
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

export async function createFilenameCatalog(manifestUrl, fetcher = fetch) {
  const response = await fetcher(manifestUrl);
  if (!response.ok) throw new Error('The filename catalog is not published yet.');
  const manifest = await response.json(), { info, files } = manifest;
  if (manifest.version !== 1) throw new Error('Unsupported filename catalog version.');
  const url = path => new URL(path, manifestUrl).href;
  async function binary(name) {
    const response = await fetcher(url(files[name].path));
    if (!response.ok) throw new Error('Could not load the catalog navigation index.');
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength !== files[name].bytes) throw new Error('Incomplete catalog navigation index.');
    return bytes;
  }
  const [groupBuffer, preferredBuffer, documentBuffer, flagBuffer] = await Promise.all(['groups','preferred','document_rows','flags'].map(binary));
  const groups = new Uint32Array(groupBuffer), preferred = new Uint32Array(preferredBuffer), documentRows = new Uint32Array(documentBuffer), flags = new Uint8Array(flagBuffer);
  if (groups.length !== info.rows || preferred.length !== info.entries || documentRows.length !== info.entries || flags.length !== info.entries) throw new Error('Catalog index counts disagree.');
  const first = new Int32Array(info.entries).fill(-1), next = new Int32Array(info.rows);
  for (let source = info.rows - 1; source >= 0; source--) {
    if (groups[source] >= info.entries) throw new Error('Invalid catalog group.');
    next[source] = first[groups[source]]; first[groups[source]] = source;
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
      return { start, end: offset, byteStart: Math.min(...chunks.map(column => Number(column.dictionary_page_offset ?? column.data_page_offset))),
        byteEnd: Math.max(...chunks.map(column => Number(column.dictionary_page_offset ?? column.data_page_offset) + Number(column.total_compressed_size))) };
    });
    const result = { buffer, metadata, spans }; tables.set(name, result); return result;
  }
  async function read(name, start, end, columns, signal, prefetch = false) {
    const { buffer, metadata, spans } = await table(name, signal);
    if (prefetch) for (const span of spans) if (span.end > start && span.start < end) await buffer.slice(span.byteStart, span.byteEnd, signal);
    const rows = await parquetReadObjects({ file: buffer.file(signal), metadata, compressors, columns, rowStart: start, rowEnd: end });
    signal?.throwIfAborted(); return rows.map(normalized);
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
    const mask = new Uint8Array(info.entries).fill(needle || selectedFilters.length ? 0 : 1);
    if (needle || selectedFilters.length) {
      // Nested observations can be large: stream those row groups without
      // retaining the entire million-row evidence column in memory.
      const stream = needle && field === 'source_occurrences';
      const names = [...new Set([...selectedFilters, ...(needle && !stream ? [field, ...(field === 'filename' && info.fields.includes('recovered_filename') ? ['recovered_filename'] : [])] : [])])];
      const loaded = new Map();
      for (const name of names) loaded.set(name, await column(name, signal));
      const matches = (source, searchValue) => {
        if (needle && !text(searchValue).includes(needle) && !(field === 'filename' && text(loaded.get('recovered_filename')?.[source]).includes(needle))) return false;
        return selectedFilters.every(key => values(loaded.get(key)[source]).some(value => (key === 'format' ? value.toLowerCase() : value) === query[key]));
      };
      if (stream) {
        for (const span of (await table('filenames', signal)).spans) {
          const rows = await read('filenames', span.start, span.end, [field], signal);
          for (let i = 0; i < rows.length; i++) if (matches(span.start + i, rows[i][field])) mask[groups[span.start + i]] = 1;
        }
      } else for (let source = 0; source < info.rows; source++) if (matches(source, loaded.get(field)?.[source])) mask[groups[source]] = 1;
    }
    const found = [];
    for (let group = 0; group < mask.length; group++) {
      const flag = flags[group];
      if (!mask[group] || (query.retained && !!(flag & 1) !== (query.retained === 'yes')) ||
          (!query.scope && !(flag & 2)) || (query.scope === 'capture-records' && (flag & 2)) ||
          (query.document_kind === '__null__' && !(flag & 4)) || (query.document_family === '__null__' && !(flag & 8))) continue;
      found.push(group);
    }
    const limit = Math.max(1, Math.min(100, Number(query.limit) || 50)), pages = Math.max(1, Math.ceil(found.length / limit)), page = Math.max(1, Math.min(pages, Number(query.page) || 1));
    const chosen = found.slice((page - 1) * limit, page * limit), rows = await selected('browse', chosen, undefined, signal);
    rows.forEach((row, i) => { row._row = preferred[chosen[i]]; row.api_reference = flags[chosen[i]] & 16 ? apiReference(row.source_url) : null; });
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
  async function entry(identity, catalog, signal) {
    const row = await resolve(identity, catalog, signal), group = groups[row], members = [];
    for (let source = first[group]; source !== -1; source = next[source]) members.push(source);
    const [record] = await selected('filenames', [row], undefined, signal);
    const [document] = await selected('documents', [documentRows[group]], undefined, signal);
    const sources = await selected('filenames', members, sourceColumns, signal);
    const bodies = sources.map(source => source.body_key);
    for (const source of sources) { source.retained = source.body_key != null; delete source.body_key; }
    const [canonical] = row === preferred[group] ? [record] : await selected('filenames', [preferred[group]], undefined, signal);
    return { record, document, filename: document.filename, sources, catalog_id: info.catalog_id, api_reference: apiReference(record.source_url),
      origin: sourceContext(record), document_origin: sourceContext(canonical), reading: null, saved_file_available: false, published_only: true,
      sources_share_saved_file: !!bodies[0] && bodies.every(value => value === bodies[0]) };
  }
  return { info: { ...info, downloads: { documents: url(files.documents.path), filenames: url(files.filenames.path) }, published_at: manifest.published_at }, search, entry };
}
