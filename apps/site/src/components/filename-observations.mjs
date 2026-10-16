import { decompressBrotli } from 'hyparquet-compressors';

/** Decode only bounded blocks containing the selected source's observations. */
export function observationReader(index, data, references) {
  if (index.version !== 1 || index.max_part_bytes > 1024 * 1024) throw new Error('Unsupported observation index.');
  function locate(blocks, row) {
    let low = 0, high = blocks.length;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (blocks[middle].start <= row) low = middle + 1; else high = middle;
    }
    const block = blocks[low - 1];
    if (!block || row >= block.start + block.count) throw new Error('Invalid observation reference.');
    return block;
  }
  async function decode(file, block, signal) {
    const pieces = [];
    for (const [offset, length, decoded] of block.parts) {
      signal?.throwIfAborted();
      if (!Number.isSafeInteger(decoded) || decoded < 1 || decoded > index.max_part_bytes) throw new Error('Invalid observation block size.');
      const bytes = await file.slice(offset, offset + length, signal);
      const result = decompressBrotli(new Uint8Array(bytes), decoded);
      if (result.length !== decoded) throw new Error('Incomplete observation block.');
      pieces.push(result);
    }
    // Parts can split a UTF-8 character. Decode only after joining the bytes.
    const bytes = new Uint8Array(pieces.reduce((sum, piece) => sum + piece.length, 0));
    let offset = 0;
    for (const piece of pieces) { bytes.set(piece, offset); offset += piece.length; }
    const values = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    if (!Array.isArray(values) || values.length !== block.count) throw new Error('Observation block count mismatch.');
    signal?.throwIfAborted();
    return values;
  }
  async function refsFor(row, signal) {
    const block = locate(index.references.blocks, row);
    const refs = (await decode(references, block, signal))[row - block.start];
    if (refs !== null && !Array.isArray(refs)) throw new Error('Invalid source observation list.');
    return refs;
  }
  async function page(row, {offset = 0, limit = 20, columns = index.fields} = {}, signal) {
    const refs = await refsFor(row, signal);
    const chosen = refs?.slice(offset, offset + limit) || [];
    const wanted = new Map(), values = new Map();
    for (const ref of chosen) {
      if (!Number.isSafeInteger(ref) || ref < 0) throw new Error('Invalid observation reference.');
      const block = locate(index.observations.blocks, ref);
      if (!wanted.has(block)) wanted.set(block, new Set());
      wanted.get(block).add(ref);
    }
    // Release each unrelated block before decoding the next; restore null
    // fields only on observations belonging to this source record.
    for (const [block, selected] of wanted) {
      const rows = await decode(data, block, signal);
      for (const ref of selected) {
        const value = rows[ref - block.start];
        values.set(ref, value === null ? null : Object.fromEntries(columns.map(key => [key, value[key] ?? null])));
      }
    }
    const total = refs?.length ?? 0;
    return {items: chosen.map(ref => values.get(ref)), total, offset, next: offset + chosen.length < total ? offset + chosen.length : null, is_null: refs === null};
  }
  async function read(row, signal) {
    const result = await page(row, {limit: Infinity}, signal);
    return result.is_null ? null : result.items;
  }
  async function* scan(file, descriptor, signal) {
    const last = descriptor.blocks.at(-1)?.parts.at(-1);
    const end = last ? last[0] + last[1] : 0;
    let loadedThrough = 0;
    for (const block of descriptor.blocks) {
      const tail = block.parts.at(-1);
      if (tail[0] + tail[1] > loadedThrough) {
        const start = block.parts[0][0];
        loadedThrough = Math.min(start + 4 * 1024 * 1024, end);
        await file.slice(start, loadedThrough, signal);
      }
      yield {start: block.start, rows: await decode(file, block, signal)};
    }
  }
  async function* matchingSources(needle, signal) {
    const matches = new Uint8Array(index.observations.rows);
    // Scan each unique observation once, without decoding nested source row groups.
    for await (const {start, rows} of scan(data, index.observations, signal)) {
      rows.forEach((row, i) => {
        const restored = row === null ? null : Object.fromEntries(index.fields.map(key => [key, row[key] ?? null]));
        if (JSON.stringify(restored).toLowerCase().includes(needle)) matches[start + i] = 1;
      });
    }
    for await (const {start, rows} of scan(references, index.references, signal)) {
      for (let i = 0; i < rows.length; i++) if (rows[i]?.some(ref => matches[ref])) yield start + i;
    }
  }
  return { read, page, matchingSources };
}
