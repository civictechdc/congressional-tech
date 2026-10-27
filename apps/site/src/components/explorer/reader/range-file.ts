import {byteCache, sharedLoad} from './filenames/cache.ts';

/** Bounded compressed-byte cache; the host must return the exact requested range. */
export function rangeFile(url, byteLength, fetcher = fetch, cache = byteCache(48 * 1024 * 1024, 32 * 1024 * 1024), metrics = {}, retained = {entries:new Map(),bytes:0,maxBytes:32*1024*1024}) {
  const pending = new Map();
  let protectedRanges:number[][]=[];
  const put=(start:number,end:number,bytes:ArrayBuffer)=>{
    const key=`${url}:${start}/${end}`;if(retained.entries.has(key))return;
    const cost=bytes.byteLength+128+key.length*2;
    if(retained.bytes+cost>retained.maxBytes)throw new Error('Archive index and dictionary cache exceeds its budget.');
    retained.entries.set(key,{url,start,end,bytes});retained.bytes+=cost;
  };
  const protect=(start:number,end:number,bytes:ArrayBuffer)=>{
    for(const [left,right] of protectedRanges){const first=Math.max(left,start),last=Math.min(right,end);if(first<last)put(first,last,bytes.slice(first-start,last-start));}
  };
  const retain=(ranges:number[][])=>{
    ranges.sort((a,b)=>a[0]-b[0]);protectedRanges=[];
    for(const [start,end] of ranges){
      if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start<0||end<=start||end>byteLength)throw new Error('Invalid archive index range.');
      const previous=protectedRanges.at(-1);if(previous&&start<=previous[1])previous[1]=Math.max(previous[1],end);else protectedRanges.push([start,end]);
    }
    for(const [,item] of cache.entries())if(item.url===url)protect(item.start,item.end,item.bytes);
  };
  async function slice(start, end = byteLength, signal) {
    signal?.throwIfAborted();
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end <= start || end > byteLength) throw new Error('Invalid catalog byte range.');
    for(const item of retained.entries.values())if(item.url===url&&item.start<=start&&item.end>=end){metrics.rangeHits=(metrics.rangeHits||0)+1;return item.bytes.slice(start-item.start,end-item.start);}
    const pieces=[...retained.entries.values()].filter(item=>item.url===url&&item.end>start&&item.start<end).sort((a,b)=>a.start-b.start);
    if(pieces.length){let cursor=start;for(const item of pieces){if(item.start>cursor)break;cursor=Math.max(cursor,item.end);}if(cursor>=end){const result=new Uint8Array(end-start);cursor=start;for(const item of pieces){if(item.start>cursor||cursor>=end)break;const last=Math.min(item.end,end);if(last>cursor){result.set(new Uint8Array(item.bytes,cursor-item.start,last-cursor),cursor-start);cursor=last;}}metrics.rangeHits=(metrics.rangeHits||0)+1;return result.buffer;}}
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
      protect(start,end,bytes);
      cache.set(key, {url, start, end, bytes}, bytes.byteLength);
      return bytes;
    }, signal);
    signal?.throwIfAborted(); return bytes;
  }
  return { slice, retain, canRetain: size => cache.admits(size,`${url}:${byteLength}/${byteLength}`), cacheBudget: cache.stats.maxBytes,
    file: signal => ({ byteLength, slice: (start, end) => slice(start, end, signal) }) };
}

