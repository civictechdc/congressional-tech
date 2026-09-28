import test from 'node:test';
import assert from 'node:assert/strict';
import { open, readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { openPublicationReader } from './data-source.js';

// Generate real Snappy Parquet with the Python publisher; no mocked decoder.
const root = mkdtempSync(join(tmpdir(), 'explorer-parquet-'));
const repo = resolve(import.meta.dirname, '../../../../..');
const python = process.env.EXPLORER_PYTHON || process.env.COMMITTEE_PYTHON || (existsSync(join(repo, '.venv/bin/python')) ? join(repo, '.venv/bin/python') : 'python3');
execFileSync(python, ['-c', `
import sys
from pathlib import Path
sys.path.insert(0, 'tests')
from test_explorer_export import native, write_meetings, NOW
from committee_explorer.export import export
root = Path(sys.argv[1])
row = native()
row['witnesses'] += [{'name':f'Witness {i}'} for i in range(30)]
row['meetingDocuments'].append({'name':'Printed record','documentType':'Transcript','format':'PDF','url':'https://example.org/record.pdf'})
row['videos'] = [{'url':'https://www.congress.gov/event/115th-congress/house-event/106245'},
                 {'url':'https://www.senate.gov/isvp/?comm=banking&filename=banking071217'}]
shared = {**row, 'eventId':'106246', 'congress':116, 'date':'2019-07-12', 'title':'Shared recording', 'witnesses':[]}
earlier = {**shared, 'eventId':'106247', 'date':'2019-01-01', 'title':'A January meeting', 'videos':[],
           'committees':[{'systemCode':'hsru00', 'name':'Renamed Rules'}]}
future = {**row, 'eventId':'338793', 'congress':119, 'date':'2099-10-01T14:00:00Z', 'title':'Upcoming meeting', 'witnesses':[],
          'videos':[{'url':'https://www.senate.gov/isvp/?comm=banking&filename=banking100199'}]}
canceled = {**row, 'eventId':'338792', 'congress':119, 'meetingStatus':'Canceled', 'title':'Canceled meeting', 'witnesses':[],
            'videos':[{'url':'https://www.senate.gov/isvp/?comm=banking&filename=banking071217c'}]}
export(meetings=write_meetings(root,[row,shared,earlier,future,canceled]), output_dir=root/'public', state_dir=root/'state', as_of=NOW, format='parquet')
`, root], { cwd: repo });
test.after(() => rmSync(root, { recursive: true }));

function transport(mode) {
  const calls = [];
  const fetcher = async (url, options = {}) => {
    options.signal?.throwIfAborted();
    const path = join(root, 'public', new URL(url).pathname);
    const range = options.headers?.Range;
    calls.push({ path, range });
    if (!range) return new Response(await readFile(path));
    const [, first, last] = /bytes=(\d+)-(\d+)/.exec(range);
    const start = Number(first), end = Number(last) + 1;
    const handle = await open(path);
    try {
      const size = (await handle.stat()).size;
      const bytes = Buffer.alloc(end - start);
      await handle.read(bytes, 0, bytes.length, start);
      return new Response(bytes, { status: mode === 'no-ranges' ? 200 : 206,
        headers: { 'Content-Range': `bytes ${start}-${end - 1}/${mode === 'bad-range' ? size + 1 : size}` } });
    } finally { await handle.close(); }
  };
  return { fetcher, calls };
}

test('real Parquet supports search, direct files, witnesses, coverage and on-demand source evidence', async () => {
  const { fetcher, calls } = transport();
  const reader = await openPublicationReader({ pointerUrl: 'https://example.org/CURRENT.json', fetcher });
  const meetings = await reader.search({ congress: 115 });
  assert.equal(meetings.total, 1);
  assert.equal(meetings.rows[0].title, 'Rules consideration');
  assert.equal((await reader.search({ congress: 114 })).total, 0);
  assert.equal((await reader.search({ congress: 'all', q: 'Alex Smith' })).total, 1);
  const meeting = await reader.getRecord(meetings.rows[0]);
  const related = await reader.getRelated(meeting, {limit:100});
  assert.ok(related.records.some(r => r.kind === 'appearance' && r.title === 'Alex Smith'));
  assert.ok(related.records.some(r => r.files?.some(f => f.url === 'https://example.org/record.pdf')));
  const coverage = await reader.getCoverage({ filters: { congress: 115 } });
  assert.equal(coverage.state_breakdown.documents.denominator, 1);
  assert.ok(!calls.some(c => c.path.includes('sources.parquet')));
  assert.ok(calls.filter(c => c.path.endsWith('.parquet')).every(c => c.range));
  const sources = await reader.getRecords(meeting.source_ids.map(id => ({kind: 'source_record', id})));
  assert.ok(sources.some(source => source.payload.eventId === '106245'));
  assert.equal((await reader.getRecord({ kind: 'meeting', id: 'missing' })), undefined);
});

test('shared recordings remain reachable across Congress filters; event pages and future streams stay hidden', async () => {
  const reader = await openPublicationReader({ pointerUrl: 'https://example.org/CURRENT.json', fetcher: transport().fetcher });
  for (const congress of [115, 116]) {
    const meeting = (await reader.search({congress})).rows[0];
    assert.equal(meeting.status, 'past');
    assert.equal(meeting.source_status, 'scheduled');
    const related = await reader.getRelated(meeting, {kind:'material'});
    const videos = related.records.filter(r => r.type === 'recording');
    assert.equal(videos.length, 1);
    assert.equal(videos[0].congress, null); // Explicitly shared across two Congresses.
    assert.equal(videos[0].recording_url, 'https://www.senate.gov/isvp/?comm=banking&filename=banking071217');
    assert.ok(!related.records.flatMap(r => r.files || []).some(f => f.url.includes('congress.gov/event/')));
  }
  assert.equal((await reader.search({kind:'material', congress:119, type:'recording'})).total, 0);
  for (const meeting of (await reader.search({congress:119})).rows) {
    assert.ok(['upcoming', 'canceled'].includes(meeting.status));
    assert.equal(meeting.evidence_states.recording, 'not_applicable');
    assert.ok(!(await reader.getRelated(meeting)).records.some(r => r.type === 'recording'));
  }
});

test('documents and witnesses page independently so neither hides the other', async () => {
  const {fetcher, calls} = transport();
  const reader = await openPublicationReader({pointerUrl:'https://example.org/CURRENT.json', fetcher});
  const meeting = (await reader.search({congress:115})).rows[0];
  const witnesses = await reader.getRelated(meeting, {kind:'appearance',limit:25});
  assert.equal(witnesses.total, 31);
  assert.equal(witnesses.records.length, 25);
  assert.ok(witnesses.records.every(r => r.kind === 'appearance'));
  assert.ok(!calls.some(c => c.path.includes('materials.parquet')));
  const documents = await reader.getRelated(meeting, {kind:'material',limit:25});
  assert.ok(documents.records.some(r => r.files.some(f => f.url === 'https://example.org/record.pdf')));
  assert.ok(documents.records.every(r => r.kind === 'material'));
});

test('committee meetings are chronological, witnesses searchable by organization, and issues have usable subjects', async () => {
  const {fetcher, calls} = transport();
  const reader = await openPublicationReader({pointerUrl:'https://example.org/CURRENT.json', fetcher});
  const witnesses = await reader.search({kind:'appearance', congress:115, q:'First office'});
  assert.equal(witnesses.total, 1);
  assert.equal(witnesses.rows[0].title, 'Alex Smith');
  assert.equal(witnesses.rows[0].organization, 'First office');
  const committees = await reader.search({kind:'committee_term', congress:116});
  const committee = committees.rows.find(r => r.issue_count > 0);
  assert.ok(committee);
  const before = calls.length;
  const issues = await reader.getRelated(committee, {kind:'data_issue'});
  assert.ok(issues.records.some(r => r.facts.some(f => f.label === 'Alternative 1')));
  assert.ok(!calls.slice(before).some(c => c.path.includes('meetings.parquet')));
  const meetings = await reader.getRelated(committee, {kind:'meeting'});
  assert.deepEqual(meetings.records.map(r => r.date), ['2019-07-12','2019-01-01']);
  const affected = await reader.getRecord({kind:issues.records[0].subject_kind, id:issues.records[0].subject_id});
  assert.equal(affected.id, committee.id);
});

test('reject unsupported range serving, malformed responses and canceled reads', async () => {
  for (const mode of ['no-ranges', 'bad-range']) {
    const reader = await openPublicationReader({ pointerUrl: 'https://example.org/CURRENT.json', fetcher: transport(mode).fetcher });
    await assert.rejects(reader.search({ congress: 115 }), /byte-range/);
  }
  const { fetcher, calls } = transport();
  const reader = await openPublicationReader({ pointerUrl: 'https://example.org/CURRENT.json', fetcher });
  const controller = new AbortController(); controller.abort();
  const count = calls.length;
  await assert.rejects(reader.search({}, { signal: controller.signal }), { name: 'AbortError' });
  assert.equal(calls.length, count);
  assert.equal((await reader.search({ congress: 115 })).total, 1);
});
