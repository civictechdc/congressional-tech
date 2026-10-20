import { retainedBytes, sharedLoad } from './cache.mjs';
import { yieldToMessages, scanBatchRows } from './cooperative.mjs';
import { decompressBrotli } from 'hyparquet-compressors';

/** Decode only bounded blocks containing the selected source's observations. */
export function observationReader(index, data, references, {metrics = {}, cache} = {}) {
  if (index.version !== 1 || !Number.isSafeInteger(index.max_part_bytes) || index.max_part_bytes < 1 || index.max_part_bytes > 1024 * 1024) throw new Error('Unsupported observation index.');
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
  const pending = new Map();
  async function decode(file, block, signal) {
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
