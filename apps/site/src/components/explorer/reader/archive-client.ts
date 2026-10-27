import {createWorkerClient} from './filenames/client.ts';
export function createArchiveClient(pointerUrl:string,rawBase:string,onReload:()=>void){
  let releaseId:string|undefined;
  const client=createWorkerClient({context:()=>({pointerUrl,rawBase,releaseId}),
    unavailableMessage:'The archive stopped loading. Try again or reload this page.',
    createWorker(){const worker=new Worker(new URL('./archive-worker.ts',import.meta.url),{type:'module'});worker.addEventListener('message',({data})=>{if(data.event==='reload')onReload();});return worker;},
    validate(_url,data){if(!/^[a-f0-9]{64}$/.test(data.releaseId))throw new Error('The archive did not identify its release.');if(releaseId&&data.releaseId!==releaseId)throw new Error('The archive release changed. Reload this page.');releaseId=data.releaseId;}});
  return {...client,request:(operation:string,args:any={},signal?:AbortSignal)=>client.request('/'+operation,signal,args)};
}
