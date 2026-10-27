import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile,mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
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
