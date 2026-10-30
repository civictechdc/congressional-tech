import {createWorkerClient} from './filenames/client.ts';
export function createArchiveClient(pointerUrl:string,rawBase:string,onReload:()=>void){
  let releaseId:string|undefined;
  const client=createWorkerClient({context:()=>({pointerUrl,rawBase,releaseId}),
    unavailableMessage:'The archive stopped loading. Try again or reload this page.',
    createWorker(){const worker=new Worker(new URL('./archive-worker.ts',import.meta.url),{type:'module'});worker.addEventListener('message',({data})=>{if(data.event==='reload')onReload();});return worker;},
    validate(_url,data){if(!/^[a-f0-9]{64}$/.test(data.releaseId))throw new Error('The archive did not identify its release.');if(releaseId&&data.releaseId!==releaseId)throw new Error('The archive release changed. Reload this page.');releaseId=data.releaseId;}});
  const request=(operation:string,args:any={},signal?:AbortSignal)=>client.request('/'+operation,signal,args);
  return {
    ...client,
    request,
    openDocument:(indexOrKey:number|string,signal?:AbortSignal)=>
      request('openDocument',typeof indexOrKey==='string'&&!/^\d+$/.test(indexOrKey)?{key:indexOrKey}:{index:Number(indexOrKey)},signal),
    getMeeting:(chamberOrEventId:any,maybeEventId?:any,signal?:AbortSignal)=>{
      const actualSignal=maybeEventId instanceof AbortSignal?maybeEventId:signal;
      const hasChamber=maybeEventId!==undefined&&!(maybeEventId instanceof AbortSignal);
      return request('meeting',hasChamber?{chamber:chamberOrEventId,eventId:maybeEventId}:{eventId:chamberOrEventId},actualSignal);
    },
    getCommittee:(committeeKey:string,options:any={},signal?:AbortSignal)=>
      request('committee',{...options,committeeKey},signal),
    getWitness:(witnessKey:string,signal?:AbortSignal)=>
      request('witness',{witnessKey},signal),
    getMember:(bioguideId:string,signal?:AbortSignal)=>
      request('member',{bioguideId},signal),
    getSubject:(subjectKey:string,signal?:AbortSignal)=>
      request('subject',{subjectKey},signal),
    getBill:(subjectKey:string,signal?:AbortSignal)=>
      request('bill',{subjectKey},signal),
    getNomination:(subjectKey:string,signal?:AbortSignal)=>
      request('nomination',{subjectKey},signal),
    listEntities:(kind:string,options:any={},signal?:AbortSignal)=>
      request('entities',{...options,kind},signal),
  };
}
