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
  const main=await page.context().newCDPSession(page),root=await browser.newBrowserCDPSession();
  const heap=value=>value.usedSize+(value.backingStorageSize||0)+(value.embedderHeapUsedSize||0);
  try{
    const pageHeap=heap(await main.send('Runtime.getHeapUsage'));
    const {targetInfos}=await root.send('Target.getTargets');let workerHeap=0,sequence=0;
    for(const target of targetInfos.filter(item=>item.type==='worker'&&item.url.includes('archive-worker'))){
      const {sessionId}=await root.send('Target.attachToTarget',{targetId:target.targetId,flatten:false}),id=++sequence;
      const response=new Promise((resolve,reject)=>{
        const timeout=setTimeout(()=>{root.off('Target.receivedMessageFromTarget',receive);reject(new Error('Worker heap sampling timed out.'));},30000);
        function receive(event){if(event.sessionId!==sessionId)return;const message=JSON.parse(event.message);if(message.id!==id)return;clearTimeout(timeout);root.off('Target.receivedMessageFromTarget',receive);message.error?reject(new Error(message.error.message)):resolve(message.result);}
        root.on('Target.receivedMessageFromTarget',receive);
      });
      await root.send('Target.sendMessageToTarget',{sessionId,message:JSON.stringify({id,method:'Runtime.getHeapUsage',params:{}})});
      workerHeap+=heap(await response);await root.send('Target.detachFromTarget',{sessionId});
    }
    if(requireWorker&&!workerHeap)throw new Error('The archive worker heap was not sampled.');
    return {heapBytes:pageHeap+workerHeap,workerHeapBytes:workerHeap,pageHeapBytes:pageHeap};
  }finally{await main.detach();await root.detach();}
}

export function heapSampler(browser,page){
  let stopped=false,latest={heapBytes:0,workerHeapBytes:0,pageHeapBytes:0},samples=0;
  const running=(async()=>{while(!stopped){const value=await browserHeap(browser,page,{requireWorker:false});samples++;if(value.heapBytes>latest.heapBytes)latest=value;await new Promise(resolve=>setTimeout(resolve,50));}})();
  // Observe a sampling error immediately; stop() still propagates it to the caller.
  running.catch(()=>{});
  return {async stop(){stopped=true;await running;const final=await browserHeap(browser,page);if(final.heapBytes>latest.heapBytes)latest=final;return {...latest,heapSamples:samples+1};}};
}
