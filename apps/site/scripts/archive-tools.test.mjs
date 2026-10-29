import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile,mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {startArchiveServer} from './archive-server.mjs';
import {verifyArchive} from './verify-archive.mjs';
import {writeTargets,checkTargets} from './archive-targets.mjs';

test('canary refuses unsafe transport before opening a reader',async()=>{
  await assert.rejects(verifyArchive({pointerUrl:'http://public.test/manifest.json'}),/HTTPS/i);
  await assert.rejects(verifyArchive({pointerUrl:'http://user:secret@localhost/manifest.json',local:true}),/credential|public/i);
});

test('targets require both real devices and measured worker heap',async()=>{
  const folder=await mkdtemp(join(tmpdir(),'archive-targets-'));try{
    const output=join(folder,'targets.json');
    const sample={releaseId:'ab'.repeat(32),startupMs:20,searchMs:2,detailMs:3,heapBytes:40,workerHeapBytes:20};
    await assert.rejects(writeTargets({measurements:[{deviceClass:'phone-profile',samples:[sample]}],ceilings:{startupMs:25,searchMs:5,detailMs:5,heapBytes:50},output}),/real.phone|real.desktop/i);
    const measurements=['real-phone','real-desktop'].map(deviceClass=>({deviceClass,samples:[sample]}));
    await assert.rejects(writeTargets({measurements,ceilings:{startupMs:1,searchMs:5,detailMs:5,heapBytes:50},output}),/startup/i);
    await writeTargets({measurements,ceilings:{startupMs:25,searchMs:5,detailMs:5,heapBytes:50},output});
    const targets=JSON.parse(await readFile(output));assert.equal(targets.status,'owner-approved');assert.equal(targets.devices.length,2);
    assert.throws(()=>checkTargets({...sample,startupMs:26},targets),/startup/i);
    assert.throws(()=>checkTargets(sample,{status:'measured',ceilings:{}}),/target/i);
  }finally{await rm(folder,{recursive:true,force:true});}
});

test('canary checks pointer caching and one global deadline',async()=>{
  await assert.rejects(verifyArchive({pointerUrl:'https://public.test/manifest.json',fetcher:async()=>Response.json({release_id:'ab'.repeat(32)})}),/no-store/);
  await assert.rejects(verifyArchive({pointerUrl:'https://public.test/manifest.json',deadlineMs:15,fetcher:async(_url,options)=>new Promise((_,reject)=>{options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true});})}),/deadline/);
});

test('pinned candidate canaries still check live pointer cache policy',async()=>{
  await assert.rejects(verifyArchive({pointerUrl:'https://public.test/manifest.json',releaseId:'ab'.repeat(32),fetcher:async()=>Response.json({release_id:'cd'.repeat(32)})}),/no-store/);
});



test('the live canary refuses the actual old viewer pointer without reading old folders',async()=>{
  const pointer=JSON.parse(await readFile(new URL('./fixtures/old-viewer-pointer.json',import.meta.url),'utf8'));
  const pointerUrl='https://public.test/viewer-publications/manifest.json',requests=[];
  await assert.rejects(verifyArchive({pointerUrl,fetcher:async address=>{
    requests.push(String(address));return Response.json(pointer,{headers:{'Cache-Control':'no-store'}});
  }}),/Invalid live archive pointer/);
  assert.deepEqual(requests,[pointerUrl]);
});


test('an explicit candidate canary crosses the recognized old pointer without reading old assets',async()=>{
  const pointer=JSON.parse(await readFile(new URL('./fixtures/old-viewer-pointer.json',import.meta.url),'utf8'));
  for(const versions of [{version:1,publisher_version:10},{version:'1',publisher_version:'10'}]){
    const server=await startArchiveServer({release:fileURLToPath(new URL('../../../model/fixtures/archive-contract/current',import.meta.url))});
    server.state.pointerBody=JSON.stringify({...pointer,...versions});
    try{
      const result=await verifyArchive({pointerUrl:server.pointerUrl,releaseId:server.manifest.release_id,local:true,checkSaved:false});
      assert.equal(result.status,'incomplete');assert.equal(result.savedCopyChecked,false);
      assert.equal(result.releaseId,server.manifest.release_id);assert.equal(server.state.pointerReads,2);
      assert(server.state.requests.every(request=>request.path.includes('/releases/'+server.manifest.release_id+'/')));
    }finally{await server.close();}
  }
});


test('an explicit candidate never makes an unknown pointer into an accepted old pointer',async()=>{
  const pointer=JSON.parse(await readFile(new URL('./fixtures/old-viewer-pointer.json',import.meta.url),'utf8'));
  for(const change of [{version:2},{publisher_version:11},{version:true},{catalog_id:''},{manifest:''},{release_id:'invalid'},{previous_release_id:null}]){
    const requests=[],pointerUrl='https://public.test/viewer-publications/manifest.json';
    await assert.rejects(verifyArchive({pointerUrl,releaseId:'a'.repeat(64),fetcher:async address=>{
      requests.push(String(address));return Response.json({...pointer,...change},{headers:{'Cache-Control':'no-store'}});
    }}),/Invalid live archive pointer/);
    assert.deepEqual(requests,[pointerUrl]);
  }
});


test('a changed old pointer during the stale probe still refuses the candidate',async()=>{
  const pointer=JSON.parse(await readFile(new URL('./fixtures/old-viewer-pointer.json',import.meta.url),'utf8'));
  const server=await startArchiveServer({release:fileURLToPath(new URL('../../../model/fixtures/archive-contract/current',import.meta.url))});
  server.state.pointerBody=JSON.stringify(pointer);
  try{
    await assert.rejects(verifyArchive({pointerUrl:server.pointerUrl,releaseId:server.manifest.release_id,local:true,checkSaved:false,
      fetcher:async(url,options)=>{const response=await fetch(url,options);if(String(url)===server.pointerUrl)server.state.pointerBody=JSON.stringify({...pointer,publisher_version:11});return response;}}),/Invalid archive release identity/);
    assert.equal(server.state.pointerReads,2);
  }finally{await server.close();}
});

for(const origin of [{kind:'seed_v5',display_only:true},{kind:'model'},{kind:'model',display_only:false}])test(`provisional targets bind five emulated runs to ${JSON.stringify(origin)} and keep each profile median`,async()=>{
  const folder=await mkdtemp(join(tmpdir(),'archive-seed-targets-'));try{
    const {measurementProfiles,readTargets}=await import('./archive-targets.mjs');
    const harnessCommit='a'.repeat(40);
    const measurements=['phone','desktop'].map((kind,index)=>({deviceClass:kind+'-profile',basis:'emulated',profile:measurementProfiles[kind],harnessCommit,origin,
      samples:[10,20,30,40,100].map(startupMs=>({releaseId:'ab'.repeat(32),startupMs:startupMs*(index?1:2),searchMs:2,detailMs:3,heapBytes:40,workerHeapBytes:20}))}));
    const output=join(folder,'targets.json');
    await assert.rejects(writeTargets({measurements:measurements.map(r=>({...r,samples:r.samples.slice(1)})),basis:'emulated',harnessCommit,output}),/five|5/i);
    await assert.rejects(writeTargets({measurements:measurements.map(r=>({...r,origin:{kind:'model',display_only:true}})),basis:'emulated',harnessCommit,output}),/origin/i);
    await writeTargets({measurements,basis:'emulated',harnessCommit,output});
    const targets=await readTargets(output);assert.equal(targets.status,'provisional-emulated');assert.equal(targets.basis,'emulated');
    assert.equal(targets.profile.phone.ceilings.startupMs,90);assert.equal(targets.profile.desktop.ceilings.startupMs,45);
    assert.equal(targets.ceilings.startupMs,90);assert.equal(targets.raw_runs.phone.length,5);assert.equal(targets.harness_commit,harnessCommit);
    const sample=measurements[1].samples[2];checkTargets(sample,targets,origin,'desktop');
    const {checkTargetRelease}=await import('./archive-targets.mjs');
    checkTargetRelease(sample.releaseId,targets,origin);
    assert.throws(()=>checkTargetRelease('cd'.repeat(32),targets,origin),/different release/);
    assert.throws(()=>checkTargetRelease(sample.releaseId,targets,{kind:'model',display_only:true}),/seed|model|origin/i);
    assert.throws(()=>checkTargets({...sample,startupMs:50},targets,origin,'desktop'),/startup/);
    for(const other of [undefined,{kind:'unknown'},{kind:'model',display_only:true},{kind:'seed_v5',display_only:false}])assert.throws(()=>checkTargets(sample,targets,other),/seed/i);
    assert.throws(()=>checkTargets(sample,{status:'measured',ceilings:targets.ceilings},origin),/target/i);
    const broken={...targets,raw_runs:{...targets.raw_runs,phone:targets.raw_runs.phone.slice(1)}};
    const invalid=join(folder,'invalid.json');await (await import('node:fs/promises')).writeFile(invalid,JSON.stringify(broken));
    await assert.rejects(readTargets(invalid),/five|5/i);
  }finally{await rm(folder,{recursive:true,force:true});}
});

test('measurement argument errors refuse before opening a release or browser',async()=>{
  const {measureArchive}=await import('./measure-archive.mjs');
  await assert.rejects(measureArchive({release:'/missing/not-opened',dist:'/missing/not-opened'}),/harness.commit/i);
  await assert.rejects(measureArchive({release:'/missing/not-opened',repeats:'0','harness-commit':'a'.repeat(40)}),/repetitions/i);
});

test('provisional targets refuse a different seed identity and CLI validation reuses the shared policy',async()=>{
  const {measurementProfiles,validateTargetFile}=await import('./archive-targets.mjs');
  const folder=await mkdtemp(join(tmpdir(),'archive-target-identity-'));try{
    const origin={kind:'seed_v5',display_only:true},harnessCommit='b'.repeat(40),releaseId='cd'.repeat(32);
    const sample={releaseId,startupMs:10,searchMs:2,detailMs:3,heapBytes:40,workerHeapBytes:20};
    const measurements=['phone','desktop'].map(kind=>({deviceClass:kind+'-profile',basis:'emulated',profile:measurementProfiles[kind],harnessCommit,origin,samples:Array.from({length:5},()=>({...sample}))}));
    const output=join(folder,'targets.json'),targets=await writeTargets({measurements,basis:'emulated',harnessCommit,output});
    assert.throws(()=>checkTargets({...sample,releaseId:'ab'.repeat(32)},targets,origin),/release|identity/i);
    assert.deepEqual(await validateTargetFile(output,origin),{status:'provisional-emulated',basis:'emulated',measured_release_id:releaseId});
    await assert.rejects(validateTargetFile(output,{kind:'model',display_only:true}),/seed|model|origin/i);
  }finally{await rm(folder,{recursive:true,force:true});}
});


test('Node canary keeps its decoded budget without applying browser runtime ceilings',async()=>{
  const server=await startArchiveServer({release:fileURLToPath(new URL('../../../model/fixtures/archive-contract/current',import.meta.url))});
  const targets={version:1,status:'owner-approved',basis:'real-device',ceilings:{startupMs:1,searchMs:1,detailMs:1,heapBytes:1}};
  try{
    const options={pointerUrl:server.pointerUrl,releaseId:server.manifest.release_id,local:true,checkSaved:false,targets};
    const receipt=await verifyArchive(options);
    assert.equal(receipt.status,'incomplete');assert.equal(receipt.savedCopyChecked,false);
    assert(receipt.estimatedListPeakBytes>targets.ceilings.heapBytes);
    assert.throws(()=>checkTargets({releaseId:server.manifest.release_id,startupMs:2,searchMs:2,detailMs:2,heapBytes:2},targets,server.manifest.origin),/startupMs/);
    await assert.rejects(verifyArchive({...options,heapBytes:1}),/budget|allowance|limit|bytes/i);
  }finally{await server.close();}
});


for(const origin of [{kind:'model'},{kind:'model',display_only:false}])test('raw model target validation derives actual identity and refuses mixed candidates',async()=>{
  const {measurementProfiles,validateTargetFile,checkTargetRelease}=await import('./archive-targets.mjs');
  const folder=await mkdtemp(join(tmpdir(),'archive-model-targets-'));try{
    const releaseId='de'.repeat(32),harnessCommit='c'.repeat(40);
    const sample={releaseId,startupMs:10,searchMs:2,detailMs:3,heapBytes:40,workerHeapBytes:20};
    const measurements=['phone','desktop'].map(kind=>({deviceClass:kind+'-profile',basis:'emulated',profile:measurementProfiles[kind],harnessCommit,origin,samples:Array.from({length:5},()=>({...sample}))}));
    const output=join(folder,'targets.json');
    const mixed=measurements.map((receipt,index)=>({...receipt,samples:receipt.samples.map(sample=>({...sample,releaseId:index?'ef'.repeat(32):releaseId}))}));
    await assert.rejects(writeTargets({measurements:mixed,basis:'emulated',harnessCommit,output}),/same release/);
    const targets=await writeTargets({measurements,basis:'emulated',harnessCommit,output});
    assert.equal(targets.ceilings.startupMs,15);assert.equal(targets.profile.phone.ceilings.heapBytes,60);
    assert.deepEqual(await validateTargetFile(output,origin),{status:'provisional-emulated',basis:'emulated',measured_release_id:releaseId});
    assert.throws(()=>checkTargetRelease('ef'.repeat(32),targets,origin),/different release/);
    assert.throws(()=>checkTargets({...sample,heapBytes:61},targets,origin,'phone'),/heapBytes/);
    assert.equal(Object.hasOwn(targets,'measured_release_id'),false);
  }finally{await rm(folder,{recursive:true,force:true});}
});
