import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {openArchive} from '../src/components/explorer/reader/archive.ts';
import {startArchiveServer} from './archive-server.mjs';

// Run this separately with a retained, genuinely assembled public DDK fixture.
// It is not a substitute for the full archive's native qualification.
const folder=process.env.ARCHIVE_FIXTURE;
assert.ok(folder,'ARCHIVE_FIXTURE must name the retained public-catalog release');
const manifest=JSON.parse(await readFile(join(folder,'manifest.json')));
const expected=JSON.parse(await readFile(join(folder,'catalog.ddk.json')));
const requested=[];
async function localFetch(url,options={}){
  const pathname=new URL(url).pathname;requested.push(pathname);
  if(pathname==='/manifest.json')return Response.json({release_id:manifest.release_id});
  const relative=pathname.split('/').slice(3).join('/');
  const data=await readFile(join(folder,relative));
  const range=options.headers?.Range;
  if(!range)return new Response(data);
  const [start,end]=range.slice(6).split('-').map(Number);
  return new Response(data.subarray(start,end+1),{status:206,headers:{'Content-Range':`bytes ${start}-${end}/${data.length}`}});
}

test('local origin serves exact catalog companions and current reader rows',async()=>{
  const server=await startArchiveServer({release:folder});
  try{
    const reader=await openArchive(server.pointerUrl,{fetcher:fetch});
    assert.deepEqual(await reader.catalog(),expected);
    assert.ok((await reader.search({})).total>0);
    for(const item of manifest.files.filter(item=>item.name.startsWith('queries/'))){
      const response=await fetch(`${server.origin}/congressional-tech/data/archive/releases/${manifest.release_id}/${item.name}`);
      assert.equal(response.status,200);
      assert.match(response.headers.get('Content-Type'),/^text\/plain/);
      assert.equal(createHash('sha256').update(Buffer.from(await response.arrayBuffer())).digest('hex'),item.sha256);
    }
    const unlisted=await fetch(`${server.origin}/congressional-tech/data/archive/releases/${manifest.release_id}/queries/${'0'.repeat(64)}.sql`);
    assert.equal(unlisted.status,404);
  }finally{await server.close();}
});

test('browser reads admitted public definitions and rows with cached metadata',async()=>{
  assert.equal(expected.kind,'catalog');assert.equal(expected.audience,'public');
  assert.ok(!manifest.files.some(item=>item.name==='schema.json'));
  const reader=await openArchive('https://fixture.test/manifest.json',{fetcher:localFetch});
  assert.deepEqual(await reader.catalog(),expected);
  assert.deepEqual(await reader.catalog(),expected);
  assert.equal(requested.filter(name=>name.endsWith('/catalog.ddk.json')).length,1);
  assert.equal(requested.filter(name=>name.endsWith('/catalog.report.json')).length,1);
  assert.equal(requested.filter(name=>name.endsWith('/catalog.lock.json')).length,0);
  assert.equal(requested.filter(name=>name.includes('/queries/')).length,0);
  const definitions=expected.extensions['urn:ddk:catalog:assembly'].datasetDefinitions;
  for(const dataset of expected.datasets)assert.ok(definitions[dataset.alias].properties.length);
  for(const recipe of expected.recipes){
    assert.ok(Array.isArray(recipe.parameterOrder));
    const descriptor=manifest.files.find(item=>item.name===recipe.sql);
    const sql=await readFile(join(folder,recipe.sql));
    assert.equal(createHash('sha256').update(sql).digest('hex'),descriptor.sha256);
  }
  assert.ok((await reader.search({})).total>0);
  assert.ok(!requested.some(name=>name.endsWith('/schema.json')));
});

for(const [fault,message] of [
  ['nonpublic',/admitted public catalog/],
  ['failed',/metadata checking did not pass/],
  ['incomplete',/metadata checking did not pass/],
  ['companion',/companion differs/],
  ['definition',/effective field definitions/],
])test(`browser refuses genuine public fixture with ${fault} metadata`,async()=>{
  const catalog=structuredClone(expected);
  const report=JSON.parse(await readFile(join(folder,'catalog.report.json')));
  if(fault==='nonpublic')catalog.audience='local';
  else if(fault==='failed'||fault==='incomplete')report.decision=fault;
  else if(fault==='companion')catalog.files.find(item=>item.path!=='catalog.report.json').sha256='0'.repeat(64);
  else delete catalog.extensions['urn:ddk:catalog:assembly'].datasetDefinitions[catalog.datasets[0].alias];
  const reportBytes=Buffer.from(JSON.stringify(report));
  const sha=value=>createHash('sha256').update(value).digest('hex');
  catalog.files.find(item=>item.path==='catalog.report.json').sha256=sha(reportBytes);
  const changed=new Map([['catalog.ddk.json',Buffer.from(JSON.stringify(catalog))],['catalog.report.json',reportBytes]]);
  const files=manifest.files.map(item=>changed.has(item.name)?{...item,sha256:sha(changed.get(item.name)),size:changed.get(item.name).length}:item);
  const releaseId=sha(JSON.stringify([manifest.schema_version,files.map(item=>[item.name,item.sha256,item.size,item.rows])]));
  const accesses=[];
  const fetcher=async(url,options)=>{
    const path=new URL(url).pathname;accesses.push(path);
    if(path==='/manifest.json')return Response.json({release_id:releaseId});
    if(path.endsWith('/manifest.json'))return Response.json({...manifest,files,release_id:releaseId});
    const relative=path.split('/').slice(3).join('/');
    return changed.has(relative)?new Response(changed.get(relative)):localFetch(url,options);
  };
  await assert.rejects(openArchive('https://fixture.test/manifest.json',{fetcher}),message);
  assert.ok(!accesses.some(name=>name.endsWith('.parquet')),'metadata refusal must precede data reads');
});
