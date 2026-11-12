import {openArchive} from './archive.ts';
import {ArchiveReleaseChangedError,awaitShared} from './cache.ts';

let session:Promise<Awaited<ReturnType<typeof openArchive>>>|undefined;
const pending=new Map<number,AbortController>();
async function displayedDates(reader:any,rows:any[],signal:AbortSignal){
  const needsEntry=(row:any)=>row.date_kind==='import_day'||(!row.title&&!row.filename);
  for(let i=0;i<rows.length;i+=4)await Promise.all(rows.slice(i,i+4).filter(needsEntry).map(async row=>{
    try {
      const entry=await reader.entry(row.list_row,signal);
      row.in_archive_since=entry.detail.in_archive_since;
      row.removed_on=entry.detail.removed_on;
      row.source_url=entry.sources[0]?.url||entry.recoveries[0]?.recovered_url||null;
    } catch (error) {
      signal.throwIfAborted();
      if (error instanceof ArchiveReleaseChangedError) throw error;
      // Keep the list row when its optional display details cannot be read.
    }
  }));
  return rows;
}
self.onmessage=async({data})=>{
  if(data.cancel){pending.get(data.cancel)?.abort();return;}
  const {id,url,pointerUrl,rawBase,releaseId}=data;if(!id||!url||!pointerUrl)return;
  const controller=new AbortController();pending.set(id,controller);
  try{
    session??=openArchive(pointerUrl,{rawBase,releaseId,reload:releaseId=>self.postMessage({event:'reload',releaseId})}).catch(error=>{session=undefined;throw error;});
    const reader=await awaitShared(session,controller.signal),request=new URL(url,'https://archive.invalid/');
    const args=data.payload??{};let result;
    switch(request.pathname){
      case '/info':{
        const [committees,kindSynonyms]=await Promise.all([reader.committees().catch(()=>[]),reader.kindSynonyms()]);
        const entityCounts:Record<string,number>={};
        for(const f of reader.manifest.files??[]){
          if(typeof f?.name==='string'&&f.name.endsWith('.parquet')&&Number.isSafeInteger(f.rows)){
            entityCounts[f.name.slice(0,-8)]=f.rows;
          }
        }
        result={releaseId:reader.releaseId,count:reader.count,facets:reader.manifest.facet_counts,kindSynonyms,committees,entityCounts,files:reader.manifest.files};
        break;
      }
      case '/search':{
        result=await reader.search(args,controller.signal);
        // Only visible import-day rows need detail reads for the date absent from list.
        await displayedDates(reader,result.rows,controller.signal);
        if(!args.offset&&!args.text)void reader.meetings().catch(()=>{});
        break;
      }
      case '/facets':result=await reader.facets(args,controller.signal);break;
      case '/lookup':result=await reader.lookupRows(args.url,args.query,controller.signal);await displayedDates(reader,result.rows,controller.signal);break;
      case '/entry':
      case '/openDocument':{
        let index=args.index,redirectedFrom:string|null=null;
        if(args.key){
          const found=await reader.locate(args.key);
          if(!found)throw new Error('This document was not found in the archive.');
          if('removed' in found){result={removed:found.removed};break;}
          ({index,redirectedFrom}=found);
        }
        const opened=await reader.openDocument(index,controller.signal);
        const entry={document:opened.document,detail:opened.detail,sources:opened.sources,recoveries:opened.recoveries,releaseId:reader.releaseId};
        const versions=await displayedDates(reader,opened.versions,controller.signal);
        result={
          ...opened,
          entry,
          meetingDetails:opened.meetings,
          versions,
          redirectedFrom,
        };
        break;
      }
      case '/meeting':{
        const hasChamber=args.chamber!=null&&args.chamber!=='';
        const eventId=args.eventId??args.event_id??args.key;
        result=hasChamber
          ?await reader.getMeeting(args.chamber,eventId,controller.signal)
          :await reader.getMeeting(eventId,controller.signal);
        break;
      }
      case '/committee':result=await reader.getCommittee(args.committeeKey??args.committee_key??args.key,args,controller.signal);break;
      case '/witness':result=await reader.getWitness(args.witnessKey??args.witness_key??args.key,controller.signal);break;
      case '/person':result=await reader.getPerson(args.personKey??args.person_key??args.key,controller.signal);break;
      case '/member':result=await reader.getMember(args.bioguideId??args.bioguide_id??args.key,controller.signal);break;
      case '/subject':result=await reader.getSubject(args.subjectKey??args.subject_key??args.key,controller.signal);break;
      case '/bill':result=await reader.getBill(args.subjectKey??args.subject_key??args.bill_id??args.key,controller.signal);break;
      case '/nomination':result=await reader.getNomination(args.subjectKey??args.subject_key??args.nomination_id??args.key,controller.signal);break;
      case '/entities':result=await reader.listEntities(args.kind,args,controller.signal);break;
      case '/pageMetadata':result=await reader.pageMetadata(args.index,controller.signal);break;
      case '/selectedText':result=await reader.selectedText(args.index,controller.signal);break;
      case '/saved':result=await reader.openSaved(args);break;
      default:throw new Error('Unknown archive request.');
    }
    controller.signal.throwIfAborted();self.postMessage({id,result,releaseId:reader.releaseId});
  }catch(error){if(!controller.signal.aborted)self.postMessage({id,error:error instanceof Error?error.message:String(error)});}
  finally{controller.abort();pending.delete(id);}
};
