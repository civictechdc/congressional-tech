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
const teardownHooks=Symbol('teardownHooks');
function onTeardown(emitter,mark){
  if(!emitter)return ()=>{};
  let hooks=emitter[teardownHooks];
  if(!hooks){
    hooks=new Set();
    emitter[teardownHooks]=hooks;
    const notify=()=>{for(const fn of [...hooks])fn();hooks.clear();};
    emitter.once?.('close',notify);
    emitter.once?.('disconnected',notify);
    if(typeof emitter.close==='function'){
      const originalClose=emitter.close;
      emitter.close=function(...args){notify();return originalClose.apply(this,args);};
    }
  }
  hooks.add(mark);
  return ()=>hooks.delete(mark);
}
/** Route `matcher` on a page or context. A handler can still be running when
 * its page, context or browser begins closing (for example while the archive
 * worker prefetches); Playwright disposes in-flight fetch responses before its
 * client close event arrives, and worker requests have a null `frame()`. Only
 * that teardown race is ignored: a failure while open is rethrown. */
export async function routeWhileOpen(target,matcher,handler){
  let closed=false;
  const context=typeof target.context==='function'?target.context():target;
  const browser=typeof context?.browser==='function'?context.browser():null;
  const closingPages=new WeakSet();
  let sawPage=false;
  const trackPage=page=>{
    sawPage=true;
    onTeardown(page,()=>{closingPages.add(page);});
  };
  if(context===target&&typeof context?.pages==='function'){
    for(const page of context.pages())trackPage(page);
    context.on?.('page',trackPage);
  }
  const cleanups=[];
  const mark=()=>{
    closed=true;
    if(context===target)context?.off?.('page',trackPage);
    while(cleanups.length)cleanups.pop()();
  };
  onTeardown(target,mark);
  if(context&&context!==target)cleanups.push(onTeardown(context,mark));
  if(browser)cleanups.push(onTeardown(browser,mark));
  const tornDown=route=>{
    if(closed)return true;
    if(typeof target.isClosed==='function'&&target.isClosed())return true;
    if(browser&&typeof browser.isConnected==='function'&&!browser.isConnected())return true;
    try{
      const frame=route.request().frame();
      if(frame){
        const page=frame.page();
        return page.isClosed()||closingPages.has(page);
      }
      if(context===target&&sawPage&&typeof context.pages==='function'){
        return context.pages().every(page=>page.isClosed()||closingPages.has(page));
      }
    }catch{}
    return false;
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
