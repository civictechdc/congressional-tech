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
  async function read(row, signal) {
    const block = locate(index.references.blocks, row);
    const refs = (await decode(references, block, signal))[row - block.start];
    if (refs === null) return null;
    if (!Array.isArray(refs)) throw new Error('Invalid source observation list.');
    const wanted = new Map(), values = new Map();
    for (const ref of refs) {
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
        values.set(ref, value === null ? null : Object.fromEntries(index.fields.map(key => [key, value[key] ?? null])));
      }
    }
    return refs.map(ref => values.get(ref));
  }
  return { read };
}
