import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Worker} from 'node:worker_threads';
import {execFileSync} from 'node:child_process';
import {mkdtemp,rm,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {loadRecoveries} from './recoveries.ts';
import {createHash} from 'node:crypto';

test('actual worker routes retain one catalog and serve lazy detail and complete values',async()=>{
 const folder=await mkdtemp(join(tmpdir(),'filename-worker-'));
 let worker;
 try {
  execFileSync(process.env.PYTHON||'python3',[fileURLToPath(new URL('../../../../../scripts/filename-test-fixture.py',import.meta.url)),folder],{env:{...process.env,FILENAME_FIXTURE_ROWS:'4096'}});
  const moduleUrl=new URL('./worker.ts',import.meta.url).href;
  worker=new Worker(new URL('data:text/javascript,'+encodeURIComponent(`
   import {parentPort} from 'node:worker_threads';
   import {readFile} from 'node:fs/promises';
   globalThis.self=globalThis;self.postMessage=value=>parentPort.postMessage(value);
   let pause=null,resume=()=>{};
   globalThis.fetch=async(url,options={})=>{
    if(pause)await pause;
    options.signal?.throwIfAborted();const bytes=await readFile(new URL(url));
    const range=options.headers?.Range;
    if(!range)return new Response(bytes);
    const [start,end]=range.slice(6).split('-').map(Number);
    return new Response(bytes.subarray(start,end+1),{status:206,headers:{'Content-Range':\`bytes \${start}-\${end}/\${bytes.length}\`}});
   };
   await import(${JSON.stringify(moduleUrl)});
   parentPort.on('message',data=>{
    if(data.pause){pause=new Promise(resolve=>{resume=resolve;});parentPort.postMessage({paused:true});return;}
    if(data.resume){const done=resume;pause=null;done();return;}
    self.onmessage({data});
   });parentPort.postMessage({ready:true});
  `)),{type:'module'});
  await new Promise((resolve,reject)=>{worker.once('message',resolve);worker.once('error',reject);});
  let sequence=0;
  const call=url=>new Promise((resolve,reject)=>{
   const id=++sequence;const listen=data=>{if(data.id!==id)return;worker.off('message',listen);data.error?reject(new Error(data.error)):resolve(data.result);};
   worker.on('message',listen);worker.postMessage({id,url,manifest:pathToFileURL(join(folder,'public/manifest.json')).href});
  });
  const info=await call('/api/info');assert.equal(info.catalog_id,'b'.repeat(32));
  const matched=await call('/api/match?payload='+encodeURIComponent(JSON.stringify({urls:['http://committee.test/final']})));
  assert.equal(matched.matches.length,24);assert.equal(matched.truncated,true);
  assert.equal(matched.matches[0].source_id,createHash('sha256').update('1').digest('hex'));
  const rows=await call('/api/rows?limit=1.9&page=Infinity');assert.equal(rows.page,1);assert.equal(rows.limit,1);
  const entry=await call('/api/entry/2?catalog='+info.catalog_id);assert.equal(entry.record_complete,false);
  assert.equal(entry.origin_pending,true);
  const technical=await call('/api/technical/2?catalog='+info.catalog_id);assert(!('source_occurrences' in technical));
  const full=await call('/api/full/2?catalog='+info.catalog_id);assert.equal(full.source_occurrences.length,3);
  const observations=await call('/api/observations/2?catalog='+info.catalog_id+'&limit=2');assert.deepEqual(observations.items,full.source_occurrences.slice(0,2));
  assert.equal((await call('/api/entry-origin/2?catalog='+info.catalog_id)).origin_pending,false);
  const origin=await call('/api/origin/2?catalog='+info.catalog_id);assert(origin.origin);
  await assert.rejects(call('/api/entry/2?catalog=wrong'),/different catalog snapshot/);
  await assert.rejects(call('/api/review/2?catalog='+info.catalog_id),/not configured/);
  for(const query of ['q=warm','scope=all','q=Witness&field=source_occurrences']) await call('/api/rows?'+query);
  const paused=new Promise(resolve=>{const listen=data=>{if(!data.paused)return;worker.off('message',listen);resolve();};worker.on('message',listen);});
  worker.postMessage({pause:true});await paused;
  const cancelledId=++sequence,replies=[];const listen=data=>replies.push(data);worker.on('message',listen);
  const started=performance.now();
  worker.postMessage({id:cancelledId,url:'/api/entry/'+matched.matches[0].source_id+'?catalog='+info.catalog_id,manifest:pathToFileURL(join(folder,'public/manifest.json')).href});
  worker.postMessage({cancel:cancelledId});worker.postMessage({resume:true});
  await call('/api/info');
  const latencyMs=performance.now()-started;
  await new Promise(resolve=>setTimeout(resolve,50));worker.off('message',listen);
  assert(!replies.some(item => item.id === cancelledId),'canceled worker result is suppressed');assert(latencyMs<1000);
 } finally {await worker?.terminate();await rm(folder,{recursive:true,force:true});}
});

test('recovery absence is valid and corrupt size/hash/catalog/position never falls back',async()=>{
 const info={catalog_id:'pair',rows:1,entries:1};
 assert.equal((await loadRecoveries(undefined,info,()=>{})).sources.size,0);
 const data={version:1,...info,recoveries:[{recovery_status:'recovered'}],sources:[[0,0]],groups:[[0,[0]]]};
 const attempt=async(value,alter)=>{const bytes=JSON.stringify(value);const descriptor={url:'https://data.test/recovery',bytes:Buffer.byteLength(bytes),sha256:createHash('sha256').update(bytes).digest('hex')};alter?.(descriptor);return loadRecoveries(descriptor,info,async()=>new Response(bytes));};
 await attempt(data);
 await assert.rejects(attempt(data,d=>d.bytes++),/failed verification/);
 await assert.rejects(attempt(data,d=>d.sha256='0'.repeat(64)),/failed verification/);
 await assert.rejects(attempt({...data,catalog_id:'other'}),/different catalog/);
 await assert.rejects(attempt({...data,sources:[[1,0]]}),/position/);
});
