import {test} from 'node:test';
import assert from 'node:assert/strict';
import {fieldTextCache} from '../../../../../../../docs/youtube-coverage/research/filename-detail-state.mjs';

test('repeated technical searches format each unchanged value once within a byte budget', () => {
  const cache = fieldTextCache(4096), format = value => JSON.stringify(value);
  const values = Array.from({length: 10}, (_, i) => ({value: 'entry-' + i}));
  for (let search = 0; search < 20; search++) values.forEach((value, i) => cache.text(String(i), value, format));
  assert.equal(cache.stats.formats, 10); assert.equal(cache.stats.hits, 190);
  assert.ok(cache.stats.bytes <= 4096);
  assert.match(cache.text('0', {value: 'replacement'}, format), /replacement/);
  cache.clear(); assert.equal(cache.stats.bytes, 0); assert.equal(cache.stats.entries, 0);
});

test('oversized technical values remain complete and searchable without retention', () => {
  const cache = fieldTextCache(1024), value = 'A'.repeat(5000) + 'end';
  assert.equal(cache.text('long', value, String), value.toLowerCase());
  assert.equal(cache.stats.entries, 0);
});
