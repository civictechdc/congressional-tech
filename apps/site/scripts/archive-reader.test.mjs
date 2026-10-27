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
