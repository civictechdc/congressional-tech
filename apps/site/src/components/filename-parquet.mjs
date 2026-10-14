import init, {ParquetFile} from 'parquet-wasm/esm';
import {tableFromIPC} from 'apache-arrow';
import {parquetMetadataAsync} from 'hyparquet';

let runtime;
function initialize(wasmUrl) {
  return runtime ||= init(wasmUrl ? {module_or_path: wasmUrl} : undefined)
    .catch(error => { runtime = null; throw error; });
}

// Parquet-Wasm reads Blob slices. Reuse the catalog's bounded range cache and
// response validation rather than downloading the whole file into a Blob.
class RangeBlob extends Blob {
  constructor(file, start = 0, end = file.byteLength) {
    super(); this.file = file; this.start = start; this.end = end;
  }
  get size() { return this.end - this.start; }
  slice(start = 0, end = this.size) {
    const offset = value => value < 0 ? Math.max(this.size + value, 0) : Math.min(value, this.size);
    const first = offset(start), last = Math.max(first, offset(end));
    return new RangeBlob(this.file, this.start + first, this.start + last);
  }
  arrayBuffer() { return this.file.slice(this.start, this.end); }
}

function plain(value) {
  if (value == null) return null;
  if (typeof value.toJSON === 'function') return plain(value.toJSON());
  if (Array.isArray(value)) return value.map(plain);
  if (typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, plain(item)]));
  return value;
}

export async function readParquetRows(file, options, wasmUrl, metadata) {
  metadata ||= await parquetMetadataAsync(file);
  // The library's async Blob reader traps on rejected I/O. Complete validated,
  // cancellable fetches first, then decode only these in-memory file ranges.
  const ranges = [[file.byteLength - metadata.metadata_length - 8, file.byteLength]];
  let position = 0;
  for (const group of metadata.row_groups) {
    const start = position; position += Number(group.num_rows);
    if (position <= (options.offset || 0) || start >= (options.offset || 0) + (options.limit ?? Infinity)) continue;
    for (const column of group.columns) {
      const chunk = column.meta_data;
      if (!options.columns || options.columns.includes(chunk.path_in_schema[0])) {
        const offset = Number(chunk.dictionary_page_offset ?? chunk.data_page_offset);
        ranges.push([offset, offset + Number(chunk.total_compressed_size)]);
      }
    }
  }
  // Page indexes, when present, are inspected while opening the Parquet file.
  for (const group of metadata.row_groups) for (const column of group.columns) {
    for (const kind of ['column_index', 'offset_index']) if (column[kind + '_length']) {
      ranges.push([Number(column[kind + '_offset']), Number(column[kind + '_offset']) + column[kind + '_length']]);
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const range of ranges) {
    const last = merged.at(-1);
    if (last && range[0] <= last[1] + 1024) last[1] = Math.max(last[1], range[1]);
    else merged.push(range);
  }
  const parts = [];
  for (const [start, end] of merged) parts.push({start, end, bytes: await file.slice(start, end)});
  await initialize(wasmUrl);
  const local = {byteLength: file.byteLength, slice(start, end) {
    const part = parts.find(part => part.start <= start && part.end >= end);
    if (!part) throw new Error('Parquet requested bytes outside the selected row groups.');
    return Promise.resolve(part.bytes.slice(start - part.start, end - part.start));
  }};
  const parquet = await ParquetFile.fromFile(new RangeBlob(local));
  try {
    const table = await parquet.read(options);
    // intoIPCStream transfers ownership and releases the Wasm table.
    return tableFromIPC(table.intoIPCStream()).toArray().map(plain);
  } finally { parquet.free(); }
}
