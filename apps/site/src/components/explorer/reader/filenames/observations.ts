import { retainedBytes, sharedLoad } from './cache.ts';
import { yieldToMessages, scanBatchRows } from './cooperative.ts';
import { decompressBrotli } from 'hyparquet-compressors';

/** Decode only bounded blocks containing the selected source's observations. */
export function observationReader(index: any, data: any, references: any, {metrics = {}, cache}: {metrics?: any, cache?: any} = {}): any {
  if (index.version !== 1 || !Number.isSafeInteger(index.max_part_bytes) || index.max_part_bytes < 1 || index.max_part_bytes > 1024 * 1024) throw new Error('Unsupported observation index.');
  function locate(blocks: any[], row: number) {
    let low = 0, high = blocks.length;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (blocks[middle].start <= row) low = middle + 1; else high = middle;
    }
    const block = blocks[low - 1];
    if (!block || row >= block.start + block.count) throw new Error('Invalid observation reference.');
    return block;
  }
  const pending = new Map();
  async function decode(file: any, block: any, signal?: AbortSignal): Promise<any> {
    signal?.throwIfAborted();
    const key=`${file===references?'reference':'observation'}-block:${block.start}`;
    const retained=cache?.get(key);
    if(retained)return retained;
    return sharedLoad(pending,key,async () => {
      metrics.logicalDecodeCalls=(metrics.logicalDecodeCalls||0)+1;
      const decoder=new TextDecoder('utf-8',{fatal:true});let json='',logicalBytes=0,parts=0;
      try {
        for (const [offset,length,decoded] of block.parts) {
          if (!Number.isSafeInteger(offset) || offset<0 || !Number.isSafeInteger(length) || length<1 || !Number.isSafeInteger(decoded) || decoded<1 || decoded>index.max_part_bytes) throw new Error('Invalid observation block size.');
          const bytes=await file.slice(offset,offset+length);
          const result=decompressBrotli(new Uint8Array(bytes),decoded);
          if(result.length!==decoded)throw new Error('Incomplete observation block.');
          // Streaming UTF-8 retains split code points without a whole-block byte join.
          json+=decoder.decode(result,{stream:true});logicalBytes+=decoded;
          metrics.maxDecodedPartBytes=Math.max(metrics.maxDecodedPartBytes||0,decoded);
          if(++parts % 4===0)await yieldToMessages(undefined,metrics);
        }
        json+=decoder.decode();
        metrics.maxLogicalDecodedBytes=Math.max(metrics.maxLogicalDecodedBytes||0,logicalBytes);
        metrics.maxLogicalTextBytes=Math.max(metrics.maxLogicalTextBytes||0,json.length*2);
        metrics.joinedDecodedBytes=0;
        if(logicalBytes>16*1024*1024)metrics.oversizedLogicalDecodes=(metrics.oversizedLogicalDecodes||0)+1;
        const values=JSON.parse(json);
        if(!Array.isArray(values)||values.length!==block.count)throw new Error('Observation block count mismatch.');
        const size=retainedBytes(values);metrics.maxParsedValueBytes=Math.max(metrics.maxParsedValueBytes||0,size);
        cache?.set(key,values,size);return values;
      } catch(error) {
        if(error instanceof RangeError)throw new Error('This exact observation exceeds available browser memory. Download the source Parquet for complete values.',{cause:error});
        throw error;
      }
    },signal);
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
        if (!file.canRetain || file.canRetain(loadedThrough-start)) await file.slice(start, loadedThrough, signal);
      }
      yield {start: block.start, rows: await decode(file, block, signal)};
    }
  }
  async function observationTexts(start,rows,signal) {
    const key=`observation-search:${start}`, retained=cache?.get(key);
    if(retained)return retained;
    if(!cache)return null;
    const budget=Math.min(8*1024*1024,cache.stats.maxBytes/4), output=[];let bytes=24;
    for(let i=0;i<rows.length;i++) {
      if(i && i % scanBatchRows===0)await yieldToMessages(signal,metrics);
      const row=rows[i], restored=row===null ? null : Object.fromEntries(index.fields.map(key=>[key,row[key]??null]));
      const value=JSON.stringify(restored).toLowerCase();metrics.observationNormalizations=(metrics.observationNormalizations||0)+1;
      bytes+=24+value.length*2;if(bytes>budget)return null;
      output.push(value);
    }
    cache.set(key,output,bytes);return output;
  }
  async function* matchingSources(needle, signal) {
    const matches = new Uint8Array(index.observations.rows); let work = 0;
    // Count work across logical blocks: small blocks do not add a timer per row.
    for await (const {start, rows} of scan(data, index.observations, signal)) {
      const prepared=await observationTexts(start,rows,signal);
      for (let i=0;i<rows.length;i++) {
        if (work && work % scanBatchRows === 0) await yieldToMessages(signal, metrics);
        work++; metrics.observationScanVisits = (metrics.observationScanVisits || 0) + 1;
        let value=prepared?.[i];
        if(value===undefined) {
          const row=rows[i], restored = row === null ? null : Object.fromEntries(index.fields.map(key => [key, row[key] ?? null]));
          value=JSON.stringify(restored).toLowerCase();metrics.observationNormalizations=(metrics.observationNormalizations||0)+1;
        }
        if (value.includes(needle)) matches[start + i] = 1;
      }
    }
    for await (const {start, rows} of scan(references, index.references, signal)) {
      for (let i=0;i<rows.length;i++) {
        if (work && work % scanBatchRows === 0) await yieldToMessages(signal, metrics);
        work++; metrics.referenceScanVisits = (metrics.referenceScanVisits || 0) + 1;
        for (let j=0;j<(rows[i]?.length || 0);j++) {
          if (work && work % scanBatchRows === 0) await yieldToMessages(signal, metrics);
          work++;
          if (matches[rows[i][j]]) { yield start+i; break; }
        }
      }
    }
    signal?.throwIfAborted();
  }
  return { read, page, matchingSources };
}

/** Read [offset, offset + limit) slices directly from flat occurrences.parquet via HTTP 206 Range requests. */
export function parquetObservationReader(descriptor: any, readRows: any, { metrics = {} }: any = {}): any {
  const rawFields = descriptor.fields || [];
  const fields = rawFields
    .map((f: any) => (typeof f === 'string' ? f : f?.name))
    .filter((name: any): name is string => Boolean(name && !['owner_id', 'occurrence_order', 'occurrence_is_null'].includes(name)));
  const rowSlices = Array.isArray(descriptor.row_slices) ? descriptor.row_slices : null;
  const browseRanges = (descriptor.browse_ranges || []).map((r: any) => ({
    rowGroup: r.row_group ?? 0,
    startRow: r.start_row ?? r.row_offset ?? 0,
    numRows: r.num_rows ?? r.rows ?? 0,
    minOwner: r.min_values?.owner_id ?? (r.column === 'owner_id' ? r.min : undefined),
    maxOwner: r.max_values?.owner_id ?? (r.column === 'owner_id' ? r.max : undefined),
  }));
  const ownerSliceCache = new Map();

  async function resolveSliceByOwnerId(ownerId: any, signal?: AbortSignal) {
    const key = String(ownerId);
    if (ownerSliceCache.has(key)) return ownerSliceCache.get(key);
    const candidates = browseRanges.length
      ? browseRanges.filter((r: any) => (!r.minOwner || r.minOwner <= key) && (!r.maxOwner || key <= r.maxOwner))
      : descriptor.rows > 0
        ? [{ rowGroup: 0, startRow: 0, numRows: descriptor.rows, minOwner: undefined, maxOwner: undefined }]
        : [];
    if (!candidates.length) {
      const empty = [0, 0];
      ownerSliceCache.set(key, empty);
      return empty;
    }
    const firstRg = candidates[0];
    const lastRg = candidates[candidates.length - 1];
    let firstRow = null;
    let firstRgOwners = null;
    if (firstRg.minOwner === key && firstRg.maxOwner === key) {
      firstRow = firstRg.startRow;
    } else {
      firstRgOwners = await readRows(
        descriptor,
        firstRg.startRow,
        firstRg.startRow + firstRg.numRows,
        ['owner_id'],
        signal
      );
      const localFirst = firstRgOwners.findIndex(r => r.owner_id === key);
      if (localFirst >= 0) {
        firstRow = firstRg.startRow + localFirst;
      }
    }
    if (firstRow === null) {
      for (let i = 1; i < candidates.length; i++) {
        const rg = candidates[i];
        if (rg.minOwner === key && rg.maxOwner === key) {
          firstRow = rg.startRow;
          break;
        }
        const rows = await readRows(descriptor, rg.startRow, rg.startRow + rg.numRows, ['owner_id'], signal);
        const idx = rows.findIndex(r => r.owner_id === key);
        if (idx >= 0) {
          firstRow = rg.startRow + idx;
          if (i === candidates.length - 1) firstRgOwners = rows;
          break;
        }
      }
    }
    if (firstRow === null) {
      const empty = [0, 0];
      ownerSliceCache.set(key, empty);
      return empty;
    }
    let lastRowExclusive = null;
    if (lastRg.minOwner === key && lastRg.maxOwner === key) {
      lastRowExclusive = lastRg.startRow + lastRg.numRows;
    } else {
      const lastRgOwners =
        lastRg === firstRg && firstRgOwners
          ? firstRgOwners
          : await readRows(
              descriptor,
              lastRg.startRow,
              lastRg.startRow + lastRg.numRows,
              ['owner_id'],
              signal
            );
      let localLast = -1;
      for (let i = lastRgOwners.length - 1; i >= 0; i--) {
        if (lastRgOwners[i].owner_id === key) {
          localLast = i;
          break;
        }
      }
      if (localLast >= 0) {
        lastRowExclusive = lastRg.startRow + localLast + 1;
      }
    }
    if (lastRowExclusive === null) {
      lastRowExclusive = firstRow + 1;
    }
    const resolved = [firstRow, Math.max(0, lastRowExclusive - firstRow)];
    ownerSliceCache.set(key, resolved);
    return resolved;
  }

  async function resolveSlice(row: any, ownerId: any, signal?: AbortSignal) {
    if (rowSlices && typeof row === 'number' && row >= 0 && row < rowSlices.length) {
      return rowSlices[row];
    }
    const targetOwner = ownerId ?? (typeof row === 'string' ? row : null);
    if (targetOwner != null) {
      return resolveSliceByOwnerId(targetOwner, signal);
    }
    throw new Error('Invalid observation row reference.');
  }

  async function page(row: any, { offset = 0, limit = 20, columns = fields, ownerId }: any = {}, signal?: AbortSignal) {
    signal?.throwIfAborted();
    const slice = await resolveSlice(row, ownerId, signal);
    if (!slice) throw new Error('Invalid observation row reference.');
    const [startOffset, rawCount] = slice;
    if (rawCount < 0) {
      return { items: [], total: 0, offset, next: null, is_null: true };
    }
    if (rawCount === 0) {
      return { items: [], total: 0, offset, next: null, is_null: false };
    }
    const total = rawCount;
    const clampedStart = Math.min(offset, total);
    const clampedEnd = Math.min(Number.isFinite(limit) ? offset + limit : total, total);
    const rowStart = startOffset + clampedStart;
    const rowEnd = startOffset + clampedEnd;
    const physicalCols = ['occurrence_is_null', ...columns.filter((name: string) => fields.includes(name))];
    const rows = rowStart < rowEnd ? await readRows(descriptor, rowStart, rowEnd, physicalCols, signal) : [];
    metrics.parquetOccurrenceRowsRead = (metrics.parquetOccurrenceRowsRead || 0) + rows.length;
    const items = rows.map((item: any) =>
      item.occurrence_is_null
        ? null
        : Object.fromEntries(columns.map((key: string) => [key, item[key] ?? null]))
    );
    return {
      items,
      total,
      offset,
      next: offset + items.length < total ? offset + items.length : null,
      is_null: false,
    };
  }

  async function read(row: any, signal?: AbortSignal, { ownerId }: any = {}) {
    const result = await page(row, { offset: 0, limit: Infinity, ownerId }, signal);
    return result.is_null ? null : result.items;
  }

  async function* matchingSources(needle: any, signal?: AbortSignal) {
    const lowerNeedle = String(needle || '').toLowerCase();
    if (rowSlices) {
      for (let parentRow = 0; parentRow < rowSlices.length; parentRow++) {
        const [startOffset, rawCount] = rowSlices[parentRow];
        if (rawCount <= 0) continue;
        for (let cursor = 0; cursor < rawCount; cursor += 2048) {
          const take = Math.min(2048, rawCount - cursor);
          const batch = await readRows(
            descriptor,
            startOffset + cursor,
            startOffset + cursor + take,
            ['occurrence_is_null', ...fields],
            signal
          );
          let matched = false;
          for (const item of batch) {
            const restored = item.occurrence_is_null
              ? null
              : Object.fromEntries(fields.map(key => [key, item[key] ?? null]));
            if (JSON.stringify(restored).toLowerCase().includes(lowerNeedle)) {
              matched = true;
              break;
            }
          }
          if (matched) {
            yield parentRow;
            break;
          }
        }
      }
    }
    signal?.throwIfAborted();
  }

  return { read, page, matchingSources };
}
