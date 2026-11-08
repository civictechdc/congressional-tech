import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile,mkdtemp,writeFile,rm,realpath} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {openArchive} from '../src/components/explorer/reader/archive.ts';
import {startArchiveServer} from './archive-server.mjs';
import {loadArchiveFixture} from './archive-test-fixture.mjs';

// Run this separately with a retained, genuinely assembled public DDK fixture.
// It is not a substitute for the full archive's native qualification.
const fixture=await loadArchiveFixture();
const {manifest,remapRelease}=fixture;
const expected=JSON.parse(await readFile(fixture.files['catalog.ddk.json']));
const requested=[];
const localFetch=async(url,options)=>{requested.push(new URL(url).pathname);return fixture.fetcher(url,options);};

test('local origin serves exact catalog companions and current reader rows',async()=>{
  const server=await startArchiveServer({release:{...fixture.files}});
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

test('local origin serves retained exports with controls in a separate directory',async()=>{
  const files={...fixture.files},controls=await realpath(await mkdtemp(join(tmpdir(),'archive-controls-')));
  const path=join(controls,'manifest.bin');
  await writeFile(path,await readFile(files['manifest.json']));
  files['manifest.json']=path;
  const sql=manifest.files.find(file=>file.name.endsWith('.sql'));
  const queryPath=join(controls,'query.bin');
  await writeFile(queryPath,await readFile(files[sql.name]));
  files[sql.name]=queryPath;
  const server=await startArchiveServer({release:files});
  try{
    const reader=await openArchive(server.pointerUrl,{fetcher:fetch});
    assert.ok((await reader.search({})).total>0);
    const response=await fetch(`${server.origin}/congressional-tech/data/archive/releases/${manifest.release_id}/list.parquet`,{headers:{Range:'bytes=0-3'}});
    assert.equal(response.status,206);
    assert.equal(await response.text(),'PAR1');
    const base=`${server.origin}/congressional-tech/data/archive/releases/${manifest.release_id}/`;
    assert.match((await fetch(base+sql.name)).headers.get('Content-Type'),/^text\/plain/);
    assert.equal((await fetch(base+'manifest.json')).headers.get('Content-Type'),'application/json');
  }finally{await server.close();await rm(controls,{recursive:true});}
});

test('local origin refuses inventory files outside manifest membership',async()=>{
  const files={...fixture.files};
  files['unlisted.parquet']=files['list.parquet'];
  await assert.rejects(startArchiveServer({release:files}),/inventory differs/);
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
    const sql=await readFile(fixture.files[recipe.sql]);
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
  const report=JSON.parse(await readFile(fixture.files['catalog.report.json']));
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
    return changed.has(relative)?new Response(changed.get(relative)):localFetch(remapRelease(url),options);
  };
  await assert.rejects(openArchive('https://fixture.test/manifest.json',{fetcher}),message);
  assert.ok(!accesses.some(name=>name.endsWith('.parquet')),'metadata refusal must precede data reads');
});
