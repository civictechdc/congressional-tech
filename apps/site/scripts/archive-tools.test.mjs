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
    const targets=JSON.parse(await readFile(output));assert.equal(targets.status,'measured');assert.equal(targets.devices.length,2);
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
