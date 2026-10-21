import {test} from 'node:test';
import assert from 'node:assert/strict';
import {byteCache, retainedBytes} from './cache.ts';
import {fieldLabel, readableValue} from '../../browse/filename-presentation.ts';

test('repeated technical values stay within a bounded byte budget', () => {
  const cache = byteCache(4096);
  const values = Array.from({length: 10}, (_, i) => ({value: 'entry-' + i}));
  let formats = 0, hits = 0;
  for (let search = 0; search < 20; search++) {
    values.forEach((value, i) => {
      const key = String(i);
      const existing = cache.get(key);
      if (existing !== undefined) {
        hits++;
      } else {
        formats++;
        const formatted = `${fieldLabel(key)} ${readableValue(value)}`.toLowerCase();
        cache.set(key, formatted, retainedBytes(formatted));
      }
    });
  }
  assert.equal(formats, 10);
  assert.equal(hits, 190);
  assert.ok(cache.stats.bytes <= 4096);
});

test('oversized technical values remain readable without exceeding cache admission limits', () => {
  const cache = byteCache(1024, 512);
  const value = 'A'.repeat(5000) + 'end';
  assert.equal(readableValue(value).toLowerCase(), value.toLowerCase());
  assert.equal(cache.admits(retainedBytes(value), 'long'), false);
  cache.set('long', value, retainedBytes(value));
  assert.equal(cache.stats.entries, 0);
});
