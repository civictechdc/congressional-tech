/** Conservative retained-value accounting; transient decoder/clone memory is separate. */
export function retainedBytes(value: unknown, seen = new Set<object>()): number {
  if (value == null) return 8;
  if (typeof value === 'string') return 16 + value.length * 2;
  if (typeof value !== 'object') return 8;
  if (seen.has(value)) return 0;
  seen.add(value);
  if (value instanceof ArrayBuffer) return value.byteLength;
  if (ArrayBuffer.isView(value)) return value.byteLength;
  if (Array.isArray(value)) return 24 + value.reduce((sum: number, item: unknown) => sum + 8 + retainedBytes(item, seen), 0);
  return 32 + Object.entries(value).reduce((sum, [key, item]) => sum + 16 + key.length * 2 + retainedBytes(item, seen), 0);
}

export interface ByteCache<T> {
  get(key: string): T | undefined;
  entries(): [string, T][];
  admits(size: number, key?: string): boolean;
  set(key: string, value: T, size?: number): boolean;
  readonly stats: { bytes: number; peak: number; evictions: number; entries: number; maxBytes: number; maxEntryBytes: number };
}

export function byteCache<T = unknown>(maxBytes: number, maxEntryBytes = maxBytes): ByteCache<T> {
  const entries = new Map<string, { value: T; bytes: number }>();
  let bytes = 0, peak = 0, evictions = 0;
  const cache: ByteCache<T> = {
    get(key) {
      const item = entries.get(key);
      if (item) { entries.delete(key); entries.set(key, item); }
      return item?.value;
    },
    entries() { return [...entries].map(([key, item]) => [key, item.value]); },
    admits(size, key = '') { return Number.isSafeInteger(size) && size >= 0 && size <= maxEntryBytes && size + 128 + String(key).length * 2 <= maxBytes; },
    set(key, value, size = retainedBytes(value)) {
      if (!cache.admits(size, key)) return false;
      size += 128 + String(key).length * 2;
      const previous = entries.get(key);
      if (previous) { bytes -= previous.bytes; entries.delete(key); }
      while (bytes + size > maxBytes) {
        const first = entries.keys().next().value;
        if (first === undefined) break;
        bytes -= entries.get(first)!.bytes;
        entries.delete(first);
        evictions++;
      }
      entries.set(key, { value, bytes: size });
      bytes += size;
      peak = Math.max(peak, bytes);
      return true;
    },
    get stats() { return { bytes, peak, evictions, entries: entries.size, maxBytes, maxEntryBytes }; },
  };
  return cache;
}

export function awaitShared<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise;
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => { signal.removeEventListener('abort', abort); reject(signal.reason); };
    signal.addEventListener('abort', abort, { once: true });
    promise.then(value => {
      signal.removeEventListener('abort', abort);
      if (!signal.aborted) resolve(value);
    }, error => { signal.removeEventListener('abort', abort); reject(error); });
  });
}

export function sharedLoad<T>(pending: Map<string, Promise<T>>, key: string, load: () => Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!pending.has(key)) {
    const promise = Promise.resolve().then(load).finally(() => { if (pending.get(key) === promise) pending.delete(key); });
    pending.set(key, promise);
  }
  return awaitShared(pending.get(key)!, signal);
}
