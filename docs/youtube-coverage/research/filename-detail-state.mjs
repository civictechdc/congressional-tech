/** Per-detail formatting reuse. Oversized values remain searchable, not cached. */
export function fieldTextCache(maxBytes = 2 * 1024 * 1024) {
  const entries = new Map(); let bytes = 0, formats = 0, hits = 0;
  return {
    text(key, value, format) {
      const cached = entries.get(key);
      if (cached && cached.value === value) { hits++; return cached.text; }
      if (cached) { bytes -= cached.bytes; entries.delete(key); }
      const text = String(format(value)).toLowerCase(); formats++;
      const size = 128 + 2 * (key.length + text.length);
      if (size <= maxBytes) {
        while (bytes + size > maxBytes) { const first = entries.keys().next().value; bytes -= entries.get(first).bytes; entries.delete(first); }
        entries.set(key, {value, text, bytes: size}); bytes += size;
      }
      return text;
    },
    clear() { entries.clear(); bytes = 0; },
    get stats() { return {bytes, entries: entries.size, formats, hits}; },
  };
}
