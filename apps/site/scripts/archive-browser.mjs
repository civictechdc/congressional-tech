import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
/** Load a browser library lazily from the site's own lock (one pin for CI and
 * local runs; `npm ci` in apps/site installs it). */
export function browserDependency(name){
  try{return require(name);}catch(error){
    if(error.code!=='MODULE_NOT_FOUND')throw error;
    throw new Error(`Missing ${name}. Run npm ci in apps/site; package.json pins it.`);
  }
}
/** The built site reads the public archive origin (pointer, then its release
 * files). Local harnesses keep that real artifact and redirect only those reads
 * to the fixture server, which serves the same layout under /data/archive/. */
export const ARCHIVE_ORIGIN='https://congressional-data.spicygov.ai';
const archivePath=/^\/viewer-publications\/(manifest\.json|releases\/[a-f0-9]{64}\/[a-z_0-9.-]+)$/;
/** Route `matcher` on a page or context. A handler can still be running when
 * its page or context closes (a harness finishing while the worker prefetches);
 * Playwright then disposes the fetched response and fulfill rejects ("Fetch
 * response has been disposed"). Only that teardown race is ignored: a failure
 * while the owner is still open is rethrown. */
export async function routeWhileOpen(target,matcher,handler){
  let closed=false;target.once('close',()=>{closed=true;});
  const tornDown=route=>{
    if(closed)return true;
    try{return route.request().frame().page().isClosed();}catch{return false;}
  };
  await target.route(matcher,async route=>{
    try{await handler(route);}catch(error){if(!tornDown(route))throw error;}
  });
}
export async function routeArchiveOrigin(target,server){
  await routeWhileOpen(target,url=>url.origin===ARCHIVE_ORIGIN&&archivePath.test(url.pathname),async route=>{
    const url=new URL(route.request().url());
    const fixture=server.origin+'/congressional-tech/data/archive/'+archivePath.exec(url.pathname)[1]+url.search;
    await route.fulfill({response:await route.fetch({url:fixture})});
  });
}
const heap=value=>value.usedSize+(value.backingStorageSize||0)+(value.embedderHeapUsedSize||0);
const networkParameters=network=>({offline:false,latency:network.latency,downloadThroughput:network.downloadThroughput,uploadThroughput:network.uploadThroughput,connectionType:'cellular4g'});
/** One page session owns policy and samples. Chromium 148 resets global page
 * throttling when ANY page session detaches, so never detach between samples. */
async function heapSession(page,profile){
  const main=await page.context().newCDPSession(page),workers=new Map();let sequence=0;
  function workerCommand(sessionId,method,params={}){
    const id=++sequence;
    return new Promise((resolve,reject)=>{
      const cleanup=()=>{clearTimeout(timeout);main.off('Target.receivedMessageFromTarget',receive);};
      const timeout=setTimeout(()=>{cleanup();reject(new Error('Worker measurement command timed out.'));},30000);
      function receive(event){if(event.sessionId!==sessionId)return;const message=JSON.parse(event.message);if(message.id!==id)return;cleanup();message.error?reject(new Error(message.error.message)):resolve(message.result);}
      main.on('Target.receivedMessageFromTarget',receive);
      main.send('Target.sendMessageToTarget',{sessionId,message:JSON.stringify({id,method,params})}).catch(error=>{cleanup();reject(error);});
    });
  }
  function attached(event){
    const {sessionId,targetInfo,waitingForDebugger}=event;
    const ready=(async()=>{
      if(waitingForDebugger)await workerCommand(sessionId,'Runtime.runIfWaitingForDebugger');
    })();ready.catch(()=>{});
    workers.set(sessionId,{archive:targetInfo.type==='worker'&&targetInfo.url.includes('archive-worker'),ready});
  }
  const detached=event=>workers.delete(event.sessionId);
  main.on('Target.attachedToTarget',attached);main.on('Target.detachedFromTarget',detached);
  try{
    if(profile){await main.send('Emulation.setCPUThrottlingRate',{rate:profile.cpuSlowdown});if(profile.network){await main.send('Network.enable');await main.send('Network.emulateNetworkConditions',networkParameters(profile.network));}}
    await main.send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:Boolean(profile),flatten:false});
    return {
      async read({requireWorker=true}={}){
        const pageHeap=heap(await main.send('Runtime.getHeapUsage'));let workerHeap=0,workerIsolates=0;
        for(const [sessionId,worker] of workers){await worker.ready;if(worker.archive){workerHeap+=heap(await workerCommand(sessionId,'Runtime.getHeapUsage'));workerIsolates++;}}
        if(requireWorker&&!workerHeap)throw new Error('The archive worker heap was not sampled.');
        return {heapBytes:pageHeap+workerHeap,workerHeapBytes:workerHeap,pageHeapBytes:pageHeap,workerIsolates};
      },
      async close(){main.off('Target.attachedToTarget',attached);main.off('Target.detachedFromTarget',detached);await main.detach();},
    };
  }catch(error){await main.detach();throw error;}
}
/** Runtime.getHeapUsage includes worker isolates and external backing storage. */
export async function browserHeap(browser,page,{requireWorker=true}={}){
  const session=await heapSession(page);try{return await session.read({requireWorker});}finally{await session.close();}
}
export function heapSampler(browser,page,{profile}={}){
  let stopped=false,latest={heapBytes:0,workerHeapBytes:0,pageHeapBytes:0},samples=0;
  const ready=heapSession(page,profile);
  const running=(async()=>{const session=await ready;while(!stopped){const value=await session.read({requireWorker:false});samples++;if(value.heapBytes>latest.heapBytes)latest=value;await new Promise(resolve=>setTimeout(resolve,50));}})();
  running.catch(()=>{});
  let result;return {ready,stop(){return result??=(async()=>{
    stopped=true;const session=await ready;
    try{await running;const final=await session.read();if(final.heapBytes>latest.heapBytes)latest=final;return {...latest,heapSamples:samples+1};}
    finally{await session.close();}
  })();}};
}
