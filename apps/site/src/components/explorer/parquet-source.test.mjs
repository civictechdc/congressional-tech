import test from 'node:test';
import assert from 'node:assert/strict';
import { open, readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { openPublicationReader } from './data-source.js';
import { createParquetReader } from './parquet-source.js';
import { committeeTypeLabel } from './record-presentation.js';

// Generate real Snappy Parquet with the Python publisher; no mocked decoder.
const root = mkdtempSync(join(tmpdir(), 'explorer-parquet-'));
const repo = resolve(import.meta.dirname, '../../../../..');
const python = process.env.EXPLORER_PYTHON || process.env.COMMITTEE_PYTHON || (existsSync(join(repo, '.venv/bin/python')) ? join(repo, '.venv/bin/python') : 'python3');
execFileSync(python, ['-c', `
import sys, gzip, json
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
shared = {**row, 'eventId':'106246', 'congress':116, 'date':'2019-07-12', 'type':'Meeting', 'title':'Shared recording', 'witnesses':[]}
earlier = {**shared, 'eventId':'106247', 'date':'2019-01-01', 'title':'A January meeting', 'videos':[],
           'type':'Closed Markup',
           'committees':[{'systemCode':'hsru00', 'name':'Renamed Rules'}]}
future = {**row, 'eventId':'338793', 'congress':119, 'date':'2099-10-01T14:00:00Z', 'title':'Upcoming meeting', 'witnesses':[],
          'videos':[{'url':'https://www.senate.gov/isvp/?comm=banking&filename=banking100199'}]}
canceled = {**row, 'eventId':'338792', 'congress':119, 'meetingStatus':'Canceled', 'title':'Canceled meeting', 'witnesses':[],
            'videos':[{'url':'https://www.senate.gov/isvp/?comm=banking&filename=banking071217c'}]}
bulk = {**row, 'eventId':'338790', 'congress':117, 'date':'2021-01-01', 'title':'Many attachments', 'witnesses':[], 'relatedItems':{},
        'videos':[{'url':'https://www.youtube.com/watch?v=PRXQf-CSnoo'}],
        'meetingDocuments':[{'name':f'Attachment {i:02d}', 'documentType':'Witness Statement' if i < 30 else 'Support Document',
                             'url':f'https://example.org/attachment-{i}.pdf','format':'PDF'} for i in range(74)]}
committee_rows = [
    {'congress':congress, 'committee':{'systemCode':'hsru00', 'name':'Rules', 'chamber':'House', 'committeeTypeCode':'Standing'}}
    for congress in [115,116,117,119]
] + [
    {'congress':congress, 'committee':{'systemCode':'hsru01', 'name':'Rules subcommittee', 'chamber':'House', 'committeeTypeCode':'Subcommittee', 'parent':{'systemCode':'hsru00'}}}
    for congress in [115,116,117,119]
]
committee_path = root/'committees.jsonl.gz'
committee_path.write_bytes(gzip.compress(bytes('\\n'.join(json.dumps(item) for item in committee_rows), 'utf-8')))
export(meetings=write_meetings(root,[row,shared,earlier,future,canceled,bulk]), committees_path=committee_path, output_dir=root/'public', state_dir=root/'state', as_of=NOW, format='parquet')
import pyarrow as pa
import pyarrow.parquet as pq
pq.write_table(pa.table({'id':[f'large-{i:06}' for i in range(180000)], 'kind':['material']*180000,
                        'title':['Large catalog entry']*180000, 'congress':[119]*180000}), root/'public'/'large.parquet')
from committee_explorer.parquet import write_tables, QUERY_COLUMNS
direct = root/'public'/'direct'
direct.mkdir()
records, queries, descriptors = [], [], []
for congress in (111,112):
    for child in (False, True):
        id = ('child' if child else 'panel') + str(congress)
        records.append(dict(kind='committee_term', id=id, committee_type='subcommittee' if child else 'commission_or_caucus',
                            source_committee_type='Subcommittee' if child else 'Other',
                            parent={'id':'panel'+str(congress)} if child else None,
                            identifiers=[dict(scheme='congress.gov:committee', value='jocp01' if child else 'jocp00')]))
        queries.append(dict(kind='committee_term', id=id, title='Investigations' if child else 'Oversight Panel',
                            congress=congress, chamber='joint', committee_ids=[id]))
records.append(dict(kind='meeting',id='unrelated',meeting_type='roundtable'))
queries.append(dict(kind='meeting',id='unrelated',title='Unrelated roundtable',type='roundtable',congress=112,
                    committee_ids=[],evidence_states={aspect:'unchecked' for aspect in ('recording','transcript','documents','witnesses','captions')}))
for i in range(36):
    id = 'direct-'+str(i)
    records.extend([dict(kind='material',id=id),dict(kind='material_link',id=id+'-link',material={'kind':'material','id':id},subject={'kind':'committee_term','id':'panel112'})])
    queries.append(dict(kind='material',id=id,title='Panel document '+str(i),congress=112,committee_ids=[],
                        type='recording' if i==35 else 'document',category='transcript' if i<30 else 'supporting'))
    if i==35:
        records.extend([dict(kind='material_version',id='video-version',material={'kind':'material','id':id}),
                        dict(kind='representation',id='video-file',version={'kind':'material_version','id':'video-version'},locations=[dict(url='https://youtu.be/PRXQf-CSnoo',role='player')])])
def describe(path, role, schema, count, **kwargs):
    descriptors.append(dict(path='direct/'+path,record_count=count,schema_name=schema,byte_size=(direct/path).stat().st_size,**kwargs))
write_tables(records,[],queries,direct,describe)
(direct/'index.json').write_text(json.dumps(dict(parts=descriptors,info=dict(storage='parquet',default_congress=112,
    query_columns=QUERY_COLUMNS,kinds=[dict(kind=k) for k in ('committee_term','meeting','material')],committee_labels={}))))
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

async function directCommitteeReader() {
  const {parts,info} = JSON.parse(await readFile(join(root,'public','direct','index.json')));
  return createParquetReader({manifest:{partitions:parts},manifestUrl:new URL('https://example.org/manifest.json'),
    select:()=>({}),readPartition:async()=>info},transport().fetcher);
}

test('direct committee documents keep categories, paging and filters without creating meeting coverage', async () => {
  const reader = await directCommitteeReader();
  const committee = await reader.getRecord({kind:'committee_term',id:'panel112'});
  assert.equal(committee.committee_type,'commission_or_caucus');
  assert.equal(committee.source_committee_type,'Other');
  const documents = await reader.search({kind:'material',congress:112,committeeId:committee.id,type:'document',committeeType:'commission_or_caucus'});
  assert.equal(documents.total,35);
  const first = await reader.getRelated(committee,{kind:'material',materialType:'document',category:'Transcript',limit:25});
  const second = await reader.getRelated(committee,{kind:'material',materialType:'document',category:'Transcript',offset:25,limit:25});
  assert.equal(first.total,30);
  assert.equal(first.records.length,25);
  assert.equal(second.records.length,5);
  assert.deepEqual(first.categories,[{label:'Supporting',count:5},{label:'Transcript',count:30}]);
  assert.ok([...first.records,...second.records].every(row=>row.meeting_ids.length===0 && row.meeting_id===null));
  assert.equal((await reader.getRelated(committee,{kind:'material',materialType:'recording'})).total,1);
  assert.equal((await reader.getRelated(committee,{kind:'meeting'})).total,0);
  assert.equal((await reader.getCoverage({filters:{congress:112}})).state_breakdown.documents.denominator,1);
  assert.equal((await reader.getCoverage({filters:{congress:112,committeeId:committee.id}})).state_breakdown.documents.denominator,0);
  assert.equal((await reader.search({kind:'meeting',congress:112,type:'roundtable'})).total,1);
});

test('All Congresses groups source committee identities before paging while detail links stay in the chosen term', async () => {
  const reader = await directCommitteeReader();
  const first = await reader.search({kind:'committee_term',congress:'all',limit:1});
  const second = await reader.search({kind:'committee_term',congress:'all',limit:1,offset:1});
  assert.equal(first.total,2);
  assert.equal(second.total,2);
  const panel = [...first.rows,...second.rows].find(row=>row.id==='panel112');
  assert.deepEqual(panel.terms.map(term=>[term.id,term.congress]),[['panel112',112],['panel111',111]]);
  const single = await reader.search({kind:'committee_term',congress:112});
  assert.equal(single.total,2);
  assert.ok(single.rows.every(row=>row.terms===undefined));
  for (const term of panel.terms) {
    const record = await reader.getRecord(term);
    assert.equal(record.congress,term.congress);
    const children = await reader.getRelated(record,{kind:'committee_term'});
    assert.deepEqual(children.records.map(child=>child.id),['child'+term.congress]);
    assert.equal(children.records[0].parent_committee_id,term.id);
  }
});

test('real Parquet supports search, direct files, witnesses, coverage and on-demand source evidence', async () => {
  const { fetcher, calls } = transport();
  const reader = await openPublicationReader({ pointerUrl: 'https://example.org/CURRENT.json', fetcher });
  assert.deepEqual((await reader.getQueryInfo()).supported_filters, ['committeeLevel', 'committeeType', 'access']);
  const meetings = await reader.search({ congress: 115 });
  assert.equal(meetings.total, 1);
  assert.equal(meetings.rows[0].title, 'Rules consideration');
  assert.equal((await reader.search({ congress: 114 })).total, 0);
  const documents = await reader.search({kind:'material', congress:115, q:'Printed record'});
  assert.equal(documents.rows[0].document_type, 'Transcript');
  assert.deepEqual(documents.rows[0].source_document_groups, ['meetingDocuments']);
  assert.equal((await reader.search({kind:'material', congress:115, q:'Transcript'})).rows[0].title, 'Printed record');
  assert.ok((await reader.search({kind:'material', congress:115, q:'meetingDocuments'})).rows.some(row => row.title === 'Printed record'));
  const genericMeetings = await reader.search({congress:116, type:'meeting'});
  assert.equal(genericMeetings.total, 1);
  assert.equal(genericMeetings.rows[0].title, 'Shared recording');
  const fullCommittees = await reader.search({congress:116, committeeLevel:'full'});
  assert.equal(fullCommittees.total, 1);
  assert.equal(fullCommittees.rows[0].title, 'A January meeting');
  assert.equal(fullCommittees.rows[0].access, 'closed');
  assert.equal((await reader.search({congress:116, access:'closed'})).total, 1);
  assert.equal((await reader.search({congress:116, access:'open'})).total, 0);
  assert.equal((await reader.getCoverage({filters:{congress:116, committeeLevel:'full'}})).state_breakdown.recording.denominator, fullCommittees.total);
  assert.equal((await reader.search({kind:'appearance', congress:115, committeeLevel:'full'})).total, 0);
  assert.equal((await reader.search({kind:'committee_term', congress:115, committeeLevel:'full'})).total, 1);
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

test('official parent committee types filter committees, meetings, documents, witnesses and coverage consistently', async () => {
  const reader = await openPublicationReader({pointerUrl:'https://example.org/CURRENT.json', fetcher:transport().fetcher});
  const committees = await reader.search({kind:'committee_term', congress:115, committeeType:'standing'});
  assert.equal(committees.total, 2); // Includes the standing committee's subcommittee.
  assert.equal((await reader.search({kind:'committee_term', congress:115, committeeType:'standing', committeeLevel:'full'})).total, 1);
  const child = committees.rows.find(row => row.committee_level === 'subcommittee');
  assert.equal(child.source_committee_type, 'Subcommittee');
  assert.equal(child.committee_type, 'subcommittee');
  assert.deepEqual(child.committee_types, ['standing']);
  const childDetail = await reader.getRecord(child);
  assert.equal(committeeTypeLabel(childDetail), 'Standing (inherited from parent)');
  assert.equal(committeeTypeLabel(childDetail), committeeTypeLabel(child));
  assert.equal(childDetail.source_committee_type, 'Subcommittee');
  for (const kind of ['meeting', 'material', 'appearance']) {
    const all = await reader.search({kind, congress:115});
    assert.equal((await reader.search({kind, congress:115, committeeType:'standing'})).total, all.total);
    assert.equal((await reader.search({kind, congress:115, committeeType:'select'})).total, 0);
  }
  const filters = {congress:116, committeeType:'standing', committeeLevel:'full', access:'closed'};
  const selected = await reader.search(filters);
  assert.equal(selected.total, 1);
  assert.equal((await reader.getCoverage({filters})).state_breakdown.recording.denominator, selected.total);
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

test('related document categories count the complete meeting and filter before pagination', async () => {
  const reader = await openPublicationReader({pointerUrl:'https://example.org/CURRENT.json', fetcher:transport().fetcher});
  const meeting = (await reader.search({congress:117})).rows[0];
  const all = await reader.getRelated(meeting, {kind:'material', materialType:'document', limit:25});
  assert.equal(all.total, 74);
  assert.equal(all.records.length, 25);
  assert.deepEqual(all.categories, [{label:'Support Document', count:44}, {label:'Witness Statement', count:30}]);
  assert.ok(all.records.every(record => record.document_type === 'Support Document'));
  const first = await reader.getRelated(meeting, {kind:'material', materialType:'document', category:'Witness Statement', limit:25});
  const last = await reader.getRelated(meeting, {kind:'material', materialType:'document', category:'Witness Statement', offset:25, limit:25});
  assert.equal(first.total, 30);
  assert.equal(first.records.length, 25);
  assert.equal(last.records.length, 5);
  assert.equal(new Set([...first.records, ...last.records].map(record => record.id)).size, 30);
  assert.ok([...first.records, ...last.records].every(record => record.document_type === 'Witness Statement' && record.files.length));
  assert.deepEqual(first.categories, all.categories);
  assert.deepEqual(last.categories, all.categories);
  const recordings = await reader.getRelated(meeting, {kind:'material', materialType:'recording'});
  assert.equal(recordings.total, 1);
  assert.equal(recordings.records[0].recording_url, 'https://www.youtube.com/watch?v=PRXQf-CSnoo');
  const absent = await reader.getRelated(meeting, {kind:'material', materialType:'document', category:'Not in this meeting'});
  assert.equal(absent.total, 0);
  assert.deepEqual(absent.categories, all.categories);
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

test('all-Congress scans exceed the JavaScript argument limit without overflowing the stack', async () => {
  const bytes = await readFile(join(root, 'public', 'large.parquet'));
  const reader = createParquetReader({
    manifest: {partitions:[{path:'large.parquet', schema_name:'committee_explorer.parquet.material',
      media_type:'application/vnd.apache.parquet', byte_size:bytes.length, record_count:180000}]},
    manifestUrl: new URL('https://example.org/manifest.json'),
    select: () => ({}),
    readPartition: async () => ({storage:'parquet', default_congress:119, kinds:[{kind:'material'}],
      query_columns:['id','kind','title','congress']}),
  }, transport().fetcher);
  const result = await reader.search({kind:'material', congress:'all', offset:179975});
  assert.equal(result.total, 180000);
  assert.equal(result.rows.length, 25);
  assert.equal(result.rows[0].id, 'large-179975');
  assert.equal(result.rows.at(-1).id, 'large-179999');
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
