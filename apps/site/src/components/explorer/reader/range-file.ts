import {byteCache, sharedLoad} from './filenames/cache.ts';

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

