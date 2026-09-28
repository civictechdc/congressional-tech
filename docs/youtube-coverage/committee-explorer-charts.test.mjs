import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { evidenceState, meetingWeek, renderCoverage, summarize } from './committee-explorer-charts.js';

const { records } = JSON.parse(await readFile(new URL('./committee-explorer-preview.json', import.meta.url), 'utf8'));
const meetings = records.filter(r => r.kind === 'meeting');

test('each measure reconciles its disjoint populations without counting formats or sittings as meetings', () => {
  assert.deepEqual(summarize(meetings, 'transcript', records), { listed: 2, not_found: 1, unknown: 3, total: 6 });
  assert.deepEqual(summarize(meetings, 'recording', records), { listed: 0, not_found: 0, unknown: 6, total: 6 });
  assert.deepEqual(summarize(meetings, 'witnesses', records), { listed: 1, not_found: 0, unknown: 5, total: 6 });
  assert.deepEqual(summarize(meetings.filter(m => m.chamber === 'senate'), 'transcript', records), { listed: 0, not_found: 1, unknown: 1, total: 2 });
  assert.equal(meetingWeek(meetings.find(m => m.id === 'hearing'), records), '2026-08-31');
});

test('failed checks, undated negatives, and inferred associations do not become supported findings', () => {
  const oversight = meetings.find(m => m.id === 'oversight');
  for (const patch of [{ status: 'error' }, { observed_at: null }]) {
    assert.equal(evidenceState(oversight, 'transcript', records.map(r => r.id === 'oversight-text-check' ? { ...r, ...patch } : r)), 'unknown');
  }
  const inferred = records.map(r => r.kind === 'material_link' ? { ...r, provenance: { basis: 'inferred' } } : r);
  assert.equal(evidenceState(meetings.find(m => m.id === 'hearing'), 'transcript', inferred), 'unknown');
});

test('empty populations have no percentage; zero-count weeks remain visible inside the observed range', () => {
  const options = { records, measure: 'transcript', route: p => '?' + new URLSearchParams(p) };
  assert.match(renderCoverage({ ...options, meetings: [] }), /empty population has no coverage percentage/);
  const html = renderCoverage({ ...options, meetings });
  assert.ok(!html.includes('NaN'));
  assert.match(html, /Sep 21/);
  assert.match(html, /period=2026-09-07/);
  assert.match(html, /committee=term-a/);
});
