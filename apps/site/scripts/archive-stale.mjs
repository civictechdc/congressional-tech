/** Fault injection stays in the harness; the shipped reader has no test branch. */
import {createHash} from 'node:crypto';
import {openArchive} from '../src/components/explorer/reader/archive.ts';
const {pointerUrl,releaseId,heapBytes,missingFile,timeout,legacyPointerSha256}=JSON.parse(process.argv[2]);
let reads=0,reloaded,pointerStatus,legacyReread=false;
const pointerPath=new URL(pointerUrl).pathname;
const reader=await openArchive(pointerUrl,{releaseId,heapBytes,signal:AbortSignal.timeout(timeout),reload:id=>{reloaded=id;},fetcher:async(url,options)=>{
  if(new URL(url).pathname===pointerPath){reads++;const response=await fetch(url,options);pointerStatus=response.status;if(!(response.headers.get('Cache-Control')||'').includes('no-store'))throw new Error('Archive pointer must be no-store.');if(legacyPointerSha256!==undefined&&response.ok){const bytes=new Uint8Array(await response.arrayBuffer());legacyReread=createHash('sha256').update(bytes).digest('hex')===legacyPointerSha256;return new Response(bytes,{status:response.status,headers:response.headers});}return response;}
  if(new URL(url).pathname.endsWith('/'+missingFile))return new Response(null,{status:404});return fetch(url,options);
}});
const expectedRefusal=error=>/not found|reload/i.test(String(error))||(pointerStatus===404&&/Could not read the archive pointer/i.test(String(error)))||(legacyReread&&error.message==='Invalid archive release identity.');
let failed=false;try{await reader.entry(0);}catch(error){if(!expectedRefusal(error))throw error;failed=true;}
if(!failed||reads!==1)throw new Error('Stale release did not reread the pointer exactly once.');
try{await reader.entry(0);}catch(error){if(!expectedRefusal(error))throw error;}
if(reads!==1)throw new Error('Repeated stale reads reread the pointer.');
console.log(JSON.stringify({status:'passed',pointerReads:reads,reloaded:reloaded??null}));
