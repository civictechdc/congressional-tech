import {openArchive} from './archive.ts';
import {awaitShared} from './filenames/cache.ts';

let session:Promise<Awaited<ReturnType<typeof openArchive>>>|undefined;
const pending=new Map<number,AbortController>();
async function displayedDates(reader:any,rows:any[],signal:AbortSignal){
  for(let i=0;i<rows.length;i+=4)await Promise.all(rows.slice(i,i+4).filter(row=>row.date_kind==='import_day').map(async row=>{row.in_archive_since=(await reader.entry(row.list_row,signal)).detail.in_archive_since;}));
  return rows;
}
self.onmessage=async({data})=>{
  if(data.cancel){pending.get(data.cancel)?.abort();return;}
  const {id,url,pointerUrl,rawBase,releaseId}=data;if(!id||!url||!pointerUrl)return;
  const controller=new AbortController();pending.set(id,controller);
  try{
    session??=openArchive(pointerUrl,{rawBase,releaseId,reload:releaseId=>self.postMessage({event:'reload',releaseId})}).catch(error=>{session=undefined;throw error;});
    const reader=await awaitShared(session,controller.signal),request=new URL(url,'https://archive.invalid/');
    const args=JSON.parse(request.searchParams.get('args')||'{}');let result;
    switch(request.pathname){
      case '/info':result={releaseId:reader.releaseId,count:reader.count,facets:reader.manifest.facet_counts};break;
      case '/search':{
        result=await reader.search(args,controller.signal);
        // Only visible import-day rows need detail reads for the date absent from list.
        await displayedDates(reader,result.rows,controller.signal);
        break;
      }
      case '/lookup':result=await displayedDates(reader,await reader.lookup(args.url),controller.signal);break;
      case '/entry':{
        const index=args.key?await reader.resolve(args.key):args.index;
        if(index===null)throw new Error('This document was not found in the archive.');
        const entry=await reader.entry(index,controller.signal);
        const [meetings,versions]=await Promise.all([reader.meetings(),reader.versions(index,controller.signal)]);
        result={entry,meetings,versions:await displayedDates(reader,versions,controller.signal)};break;
      }
      case '/saved':result=await reader.openSaved(args);break;
      default:throw new Error('Unknown archive request.');
    }
    controller.signal.throwIfAborted();self.postMessage({id,result,releaseId:reader.releaseId});
  }catch(error){if(!controller.signal.aborted)self.postMessage({id,error:error instanceof Error?error.message:String(error)});}
  finally{controller.abort();pending.delete(id);}
};
