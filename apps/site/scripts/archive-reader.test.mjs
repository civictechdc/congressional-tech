import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {openArchive, lookupUrl, savedCopy, dateLabels, recoveryLabel} from '../src/components/explorer/reader/archive.ts';

const folder = process.env.ARCHIVE_FIXTURE;
const manifest = JSON.parse(await readFile(join(folder, 'manifest.json')));
const releaseId = manifest.release_id;
const requests = [];
async function localFetch(url, options={}) {
  const path = new URL(url).pathname;
  requests.push({path, range: options.headers?.Range});
  if (path === '/manifest.json') return Response.json({release_id: releaseId, previous_release_id:null});
  const bytes = await readFile(join(folder, path.split('/').at(-1)));
  const range = options.headers?.Range;
  if (!range) return new Response(bytes);
  const [start,end] = range.slice(6).split('-').map(Number);
  return new Response(bytes.subarray(start,end+1), {status:206,
    headers:{'Content-Range':`bytes ${start}-${end}/${bytes.length}`}});
}

test('one reader opens native releases, searches arrays and resolves indexed keys', async()=>{
  const reader = await openArchive('https://fixture.test/manifest.json', {fetcher: localFetch, heapBytes:64*1024*1024});
  assert.equal(reader.releaseId, releaseId);
  const all = await reader.search({});
  assert.equal(all.total,6);
  assert.equal(all.rows[0].filename,'Agenda.pdf');
  assert.equal((await reader.search({text:'record'})).total,2);
  assert.equal((await reader.search({meeting_keys:['118001']})).total,1);
  assert.equal((await reader.search({saved_kind:['recovery']})).total,3);
  assert.equal((await reader.search({includeHidden:true})).total,7);
  const key = '11'.repeat(8);
  assert.equal(await reader.resolve(key),0);
  assert.equal(await reader.resolve('ff'.repeat(8)),null);
  const entry = await reader.entry(0);
  assert.equal(entry.detail.alternates[0].format,'xml');
  assert.equal(entry.sources.length,1);
  assert.equal(entry.sources[0].url,'https://fixture.test/agenda.pdf');
  assert.equal((await reader.meetings())[0].title,'Transportation infrastructure hearing');
  assert.equal((await reader.versions(3)).length,2);
  assert.deepEqual((await reader.lookup('http://www.FIXTURE.test:80/record.pdf/#fragment')).map(row=>row.list_row),[3,4]);
  assert.equal((await reader.entry(1)).recoveries[0].kind,'requested_content_in_official_hearing');
  const before = requests.length;
  await reader.entry(0);
  assert.equal(requests.length,before,'byte cache reuses metadata, offset indexes and dictionaries');
  assert.equal((await reader.urlState()).length,0);
});

test('fixed URL spelling, physical saved copies and public labels',()=>{
  assert.equal(lookupUrl('https://www.EXAMPLE.test:443/path/?x=1/#a'),'example.test/path?x=1/');
  assert.equal(lookupUrl('https://example.test/?x=/'),'example.test?x=/');
  const detail={saved_body:new Uint8Array(32).fill(17),saved_suffix:'.gz',saved_bytes:101*1024*1024,saved_media_type:'application/pdf'};
  const saved=savedCopy(detail,'https://raw.test/');
  assert.equal(saved.url,`https://raw.test/bodies/sha256/11/${'11'.repeat(32)}.gz`);
  assert.equal(saved.compressedDownload,true);
  assert.equal(dateLabels({date_kind:'unknown'},{}).capture,'Capture date not recorded');
  assert.equal(dateLabels({date_kind:'import_day'},{in_archive_since:'2020-01-02'}).capture,'In our archive since 2020-01-02 (original capture date not recorded)');
  assert.equal(recoveryLabel('requested_content_in_official_hearing'),'Requested content in an official hearing');
  assert.equal(recoveryLabel('official_substitute'),'Official substitute');
});

test('release identity and immutable bytes are verified before use',async()=>{
  const wrong = async(url,options)=>String(url).endsWith('/manifest.json') && String(url).includes('/releases/')
    ? Response.json({...manifest,release_id:'0'.repeat(64)}) : localFetch(url,options);
  await assert.rejects(openArchive('https://fixture.test/manifest.json',{fetcher:wrong}),/identity/);
  const bad = async(url,options)=>String(url).endsWith('/list.parquet')
    ? new Response(new Uint8Array(manifest.files.find(f=>f.name==='list.parquet').size)) : localFetch(url,options);
  await assert.rejects(openArchive('https://fixture.test/manifest.json',{fetcher:bad}),/verification/i);
});

test('a missing immutable file rereads the pointer exactly once',async()=>{
  let pointerReads=0;
  const missing=async(url,options)=>{
    if(new URL(url).pathname==='/manifest.json')pointerReads++;
    if(String(url).endsWith('/detail.parquet'))return new Response('',{status:404});
    return localFetch(url,options);
  };
  const reader=await openArchive('https://fixture.test/manifest.json',{fetcher:missing});
  await assert.rejects(reader.entry(0),/not found/i);
  assert.equal(pointerReads,2);
});


test('candidate selection is explicit and scans support facets, dates and cancellation',async()=>{
  const live='ee'.repeat(32);
  const otherPointer=async(url,options)=>new URL(url).pathname==='/manifest.json'
    ? Response.json({release_id:live,previous_release_id:null}) : localFetch(url,options);
  const reader=await openArchive('https://fixture.test/manifest.json',{fetcher:otherPointer,releaseId});
  assert.equal(reader.releaseId,releaseId);
  assert.equal(reader.count,7);
  assert.equal((await reader.facets()).saved_kind.recovery,3);
  assert.deepEqual((await reader.versions(3)).map(row=>row.list_row),[4,3]);
  const signal=AbortSignal.abort();
  await assert.rejects(reader.search({},signal));
  await assert.rejects(reader.entry(0,signal));
  assert.equal((await reader.entry(2)).document.hidden,true);
});

test('a changed pointer requests one reload and retries are not poisoned',async()=>{
  let reads=0,reloaded;
  const next='ab'.repeat(32);
  const fetcher=async(url,options)=>{
    if(new URL(url).pathname==='/manifest.json')return Response.json({release_id:++reads===1?releaseId:next});
    if(String(url).endsWith('/detail.parquet'))return new Response('',{status:404});
    return localFetch(url,options);
  };
  const reader=await openArchive('https://fixture.test/manifest.json',{fetcher,reload:id=>{reloaded=id;}});
  await assert.rejects(reader.entry(0),/reload/i);
  assert.equal(reloaded,next);assert.equal(reads,2);
  await assert.rejects(reader.entry(0),/reload|not found/i);
  assert.equal(reads,2);
});

test('shard descriptors use half-open absolute ranges and keep the same document links',async()=>{
  const files=manifest.files.map(file=>file.name==='detail.parquet'?{...file,name:'detail-00000.parquet',shard:'detail',row_range:[0,file.rows]}:file);
  const id=createHash('sha256').update(JSON.stringify([manifest.schema_version,files.map(f=>[f.name,f.sha256,f.size,f.rows])])).digest('hex');
  const sharded={...manifest,files,release_id:id};
  const fetcher=async(url,options)=>{
    if(new URL(url).pathname==='/manifest.json')return Response.json({release_id:id});
    if(String(url).endsWith('/manifest.json'))return Response.json(sharded);
    if(String(url).endsWith('/detail-00000.parquet'))return localFetch(String(url).replace('detail-00000.parquet','detail.parquet'),options);
    return localFetch(url,options);
  };
  const reader=await openArchive('https://fixture.test/manifest.json',{fetcher});
  assert.equal((await reader.entry(4)).document.filename,'Record.pdf');
  assert.equal(await reader.resolve('11'.repeat(8)),0);
});

test('a transient meeting failure can be retried within the same reader session',async()=>{
  let failed=false;
  const fetcher=async(url,options)=>{if(String(url).endsWith('/meetings.parquet')&&!failed){failed=true;return new Response(null,{status:503});}return localFetch(url,options);};
  const reader=await openArchive('https://fixture.test/manifest.json',{fetcher});
  await assert.rejects(reader.meetings());assert.equal((await reader.meetings())[0].event_id,118001n);
});

test('pasted-address versions apply hearing and format filters with capture paging',async()=>{
  const reader=await openArchive('https://fixture.test/manifest.json',{fetcher:localFetch});
  const url='https://fixture.test/record.pdf';
  assert.deepEqual((await reader.lookupRows(url,{limit:1})).rows.map(row=>row.list_row),[4]);
  assert.deepEqual((await reader.lookupRows(url,{limit:1,offset:1})).rows.map(row=>row.list_row),[3]);
  assert.equal((await reader.lookupRows(url,{meeting_keys:['118001']})).total,0);
  assert.equal((await reader.lookupRows(url,{format:['xml']})).total,0);
});

test('mandatory release files cannot be omitted as empty optional entities',async()=>{
  for(const omitted of ['url_state.parquet','recoveries.parquet','schema.json','capture_scope.json']){
    const files=manifest.files.filter(item=>item.name!==omitted),id=createHash('sha256').update(JSON.stringify([manifest.schema_version,files.map(f=>[f.name,f.sha256,f.size,f.rows])])).digest('hex');
    const fetcher=async(url,options)=>new URL(url).pathname==='/manifest.json'?Response.json({release_id:id}):String(url).endsWith('/manifest.json')?Response.json({...manifest,files,release_id:id}):localFetch(url,options);
    await assert.rejects(openArchive('https://fixture.test/manifest.json',{fetcher}),/required|missing/i);
  }
  const reader=await openArchive('https://fixture.test/manifest.json',{fetcher:localFetch});assert.equal((await reader.recoveryRange(0,1)).length,1);
});

test('Phase-2 entity Parquet files load lazily, support cross-filtering, and resolve rich entity details',async()=>{
  const phase2Dir = new URL('./fixtures/phase2-entities/', import.meta.url);
  const phase2Manifest = JSON.parse(await readFile(new URL('manifest.json', phase2Dir), 'utf8'));
  const phase2ReleaseId = phase2Manifest.release_id;
  const fetchedFiles = [];
  const phase2Fetch = async (url, options = {}) => {
    const pathname = new URL(url).pathname;
    if (pathname === '/manifest.json') {
      return Response.json({release_id: phase2ReleaseId, previous_release_id: null});
    }
    const name = pathname.split('/').at(-1);
    fetchedFiles.push(name);
    let bytes;
    try {
      bytes = await readFile(new URL(name, phase2Dir));
    } catch {
      bytes = await readFile(join(folder, name));
    }
    const range = options.headers?.Range;
    if (!range) return new Response(bytes);
    const [start, end] = range.slice(6).split('-').map(Number);
    return new Response(bytes.subarray(start, end + 1), {
      status: 206,
      headers: {'Content-Range': `bytes ${start}-${end}/${bytes.length}`},
    });
  };

  const reader = await openArchive('https://fixture.test/manifest.json', {
    fetcher: phase2Fetch,
    heapBytes: 64 * 1024 * 1024,
  });

  // Startup only loads manifest.json and list.parquet, not optional Phase-2 entity tables
  assert(!fetchedFiles.includes('witnesses.parquet'));
  assert(!fetchedFiles.includes('bills.parquet'));

  // Filter documents by witness_key, bioguide_id, event_id, subject_key, and committee_key
  assert.equal((await reader.search({witness_key: 'smith_jane'})).total, 2);
  assert.equal((await reader.search({bioguide_id: 'S000510'})).total, 1);
  assert.equal((await reader.search({event_id: '118001'})).total, 2);
  assert.equal((await reader.search({subject_key: '118-hr-1234'})).total, 1);
  assert.equal((await reader.search({subject_key: '118-pn-730-2'})).total, 1);
  assert.equal((await reader.search({committee_key: 'hspw00'})).total, 2);

  // Rich Meeting lookup with joined recordings, committees, subjects, witnesses, and documents
  const meeting = await reader.getMeeting('house', 118001);
  assert(meeting);
  assert.equal(meeting.title, 'Transportation infrastructure hearing');
  assert.equal(meeting.status, 'held');
  assert.equal(meeting.sittings[0].building, 'Rayburn');
  assert.equal(meeting.recordings.length, 1);
  assert.equal(meeting.recordings[0].duration_s, 5420);
  assert.equal(meeting.recordings[0].tracks[0].label, 'English captions');
  assert.equal(meeting.witnesses.length, 2);
  assert.equal(meeting.witnesses[0].name, 'Dr. Jane Smith');
  assert.equal(meeting.witnesses[0].documents.length, 2);
  assert.equal(meeting.subjects.length, 2);
  assert.equal(meeting.documents.length, 2);

  // Rich Committee lookup with historical name intervals, subcommittees, and roster
  const committeeCurrent = await reader.getCommittee('hspw00', {congress: 118});
  assert(committeeCurrent);
  assert.equal(committeeCurrent.resolved_name, 'House Committee on Transportation and Infrastructure');
  assert.equal(committeeCurrent.subcommittees.length, 1);
  assert.equal(committeeCurrent.roster.length, 2);
  assert.equal(committeeCurrent.roster[0].name, 'Sam Graves');
  assert.equal(committeeCurrent.hearings.length, 1);

  const committeeHistorical = await reader.getCommittee('hspw00', {date: '1985-06-01'});
  assert.equal(committeeHistorical.resolved_name, 'House Committee on Public Works and Transportation');

  // Rich Witness lookup
  const witness = await reader.getWitness('smith_jane');
  assert(witness);
  assert.equal(witness.name, 'Dr. Jane Smith');
  assert.deepEqual(witness.organizations, ['National Transit Institute']);
  assert.equal(witness.appearances.length, 1);
  assert.equal(witness.documents.length, 2);

  // Rich Member lookup
  const member = await reader.getMember('S000510');
  assert(member);
  assert.equal(member.name, 'Adam Smith');
  assert.equal(member.party, 'D');
  assert.equal(member.roster_entries.length, 1);
  assert.equal(member.sponsored_bills.length, 1);
  assert.equal(member.hearings.length, 1);
  assert.equal(member.documents.length, 1);

  // Rich Bill & Nomination lookups via getSubject / getBill / getNomination
  const bill = await reader.getSubject('118-hr-1234');
  assert(bill);
  assert.equal(bill.kind, 'bill');
  assert.equal(bill.short_title, 'Surface Transportation Modernization Act');
  assert.equal(bill.cbo_estimates.length, 1);
  assert.equal(bill.votes.length, 1);
  assert.equal(bill.amendment_count, 1);
  assert.equal(bill.hearings.length, 1);
  assert.equal(bill.documents.length, 1);

  const nom = await reader.getSubject('118-pn-730-2');
  assert(nom);
  assert.equal(nom.kind, 'nomination');
  assert.equal(nom.citation, 'PN730-2');
  assert.equal(nom.nominees[0].name, 'Jane Doe');
  assert.equal(nom.votes.length, 1);
  assert.equal(nom.hearings.length, 1);

  // openDocument returns document entry plus joined Phase-2 entities
  const opened = await reader.openDocument(0);
  assert.equal(opened.document.filename, 'Agenda.pdf');
  assert.equal(opened.meetings.length, 1);
  assert.equal(opened.committees.length, 2);
  assert.equal(opened.subjects.length, 2);
  assert.equal(opened.witnesses.length, 2);
  assert.equal(opened.members.length, 1);

  // listEntities supports listing and filtering
  assert.equal((await reader.listEntities('witnesses', {text: 'transit'})).total, 1);
  assert.equal((await reader.listEntities('subjects', {congress: 118})).total, 2);
});
