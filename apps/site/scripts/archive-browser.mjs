import {createRequire} from 'node:module';
import {delimiter,join,resolve} from 'node:path';
const require=createRequire(import.meta.url);
export function browserDependency(name){
  for(const load of [require,...(process.env.VIEWER_BENCHMARK_MODULES||'').split(delimiter).filter(Boolean).map(path=>createRequire(join(resolve(path),'__archive__.mjs')))]){
    try{return load(name);}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}
  }
  throw new Error(`Missing ${name}. Set VIEWER_BENCHMARK_MODULES to its maintained node_modules folder.`);
}
/** Runtime.getHeapUsage includes worker isolates and their external backing storage. */
export async function browserHeap(browser,page,{requireWorker=true}={}){
  const main=await page.context().newCDPSession(page);
  const heap=value=>value.usedSize+(value.backingStorageSize||0)+(value.embedderHeapUsedSize||0);
  try{
    const pageHeap=heap(await main.send('Runtime.getHeapUsage'));
    const attached=[];
    main.on('Target.attachedToTarget',event=>{if(event.targetInfo.type==='worker'&&event.targetInfo.url.includes('archive-worker'))attached.push(event);});
    // A page session auto-attaches only its related targets, never another open tab.
    await main.send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:false});
    let workerHeap=0,sequence=0,workerIsolates=0;
    for(const {sessionId} of attached){
      const id=++sequence;
      let cleanup=()=>{};
      const response=new Promise((resolve,reject)=>{
        const timeout=setTimeout(()=>{cleanup();reject(new Error('Worker heap sampling timed out.'));},30000);
        cleanup=()=>{clearTimeout(timeout);main.off('Target.receivedMessageFromTarget',receive);};
        function receive(event){if(event.sessionId!==sessionId)return;const message=JSON.parse(event.message);if(message.id!==id)return;clearTimeout(timeout);main.off('Target.receivedMessageFromTarget',receive);message.error?reject(new Error(message.error.message)):resolve(message.result);}
        main.on('Target.receivedMessageFromTarget',receive);
      });
      response.catch(()=>{});
      try{await main.send('Target.sendMessageToTarget',{sessionId,message:JSON.stringify({id,method:'Runtime.getHeapUsage',params:{}})});workerHeap+=heap(await response);workerIsolates++;}finally{cleanup();}
    }
    if(requireWorker&&!workerHeap)throw new Error('The archive worker heap was not sampled.');
    return {heapBytes:pageHeap+workerHeap,workerHeapBytes:workerHeap,pageHeapBytes:pageHeap,workerIsolates};
  }finally{await main.detach();}
}

export function heapSampler(browser,page){
  let stopped=false,latest={heapBytes:0,workerHeapBytes:0,pageHeapBytes:0},samples=0;
  const running=(async()=>{while(!stopped){const value=await browserHeap(browser,page,{requireWorker:false});samples++;if(value.heapBytes>latest.heapBytes)latest=value;await new Promise(resolve=>setTimeout(resolve,50));}})();
  // Observe a sampling error immediately; stop() still propagates it to the caller.
  running.catch(()=>{});
  let result;return {stop(){return result??=(async()=>{stopped=true;await running;const final=await browserHeap(browser,page);if(final.heapBytes>latest.heapBytes)latest=final;return {...latest,heapSamples:samples+1};})();}};
}

/** Apply the recorded page CDP policy before navigation; detach after the run. */
export async function applyMeasurementProfile(page,profile){
  const session=await page.context().newCDPSession(page);
  try{
    await session.send('Emulation.setCPUThrottlingRate',{rate:profile.cpuSlowdown});
    if(profile.network){await session.send('Network.enable');await session.send('Network.emulateNetworkConditions',{offline:false,latency:profile.network.latency,downloadThroughput:profile.network.downloadThroughput,uploadThroughput:profile.network.uploadThroughput,connectionType:'cellular4g'});}
    return session;
  }catch(error){await session.detach();throw error;}
}
