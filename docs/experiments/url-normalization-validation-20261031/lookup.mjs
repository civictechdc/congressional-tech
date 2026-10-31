import {createReadStream,createWriteStream} from 'node:fs';
import {readFile,writeFile} from 'node:fs/promises';
import {createInterface} from 'node:readline';
import {createHash} from 'node:crypto';
import {once} from 'node:events';
import {lookupUrl,openArchive} from '../../../apps/site/src/components/explorer/reader/archive.ts';
import {startArchiveServer} from '../../../apps/site/scripts/archive-server.mjs';
const out=(await readFile(new URL('./scratch-path.txt',import.meta.url),'utf8')).trim();
const root='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/codex-impl/cx_model_design';
const sink=createWriteStream(out+'/lookup-results.jsonl');const examples=new Map();let count=0;
async function emit(kind,list_row,original,url){
 let row={kind,list_row};if(kind!=='exact')Object.assign(row,{original,url});
 try{row.lookup_key=createHash('sha256').update('lookup:'+lookupUrl(url)).digest('hex').slice(0,16);}catch(e){row.error=e.message;}
 if(!sink.write(JSON.stringify(row)+'\n'))await once(sink,'drain');
 if(kind!=='exact'&&!examples.has(kind))examples.set(kind,{original,url,list_row});
}
for await(const line of createInterface({input:createReadStream(out+'/lookup-sources.jsonl'),crlfDelay:Infinity})){
 const {url,list_row}=JSON.parse(line);await emit('exact',list_row,url,url);count++;
 const variants=[];
 if(url.includes(' '))variants.push(['browser_spaces',new URL(url).href]);
 if(/%[0-9A-F]*[A-F]/.test(url))variants.push(['lowercase_hex',url.replace(/%[0-9A-Fa-f]{2}/g,x=>x.toLowerCase())]);
 if(/&download=1$/.test(url))variants.push(['repaired_download',url.replace(/&download=1$/,'?download=1')]);
 if(/congress\.gov\/.*[?&]q=/.test(url)){
  const [path,query]=url.split('?');const kept=query.split('&').filter(p=>!p.startsWith('q='));variants.push(['strip_congress_q',path+(kept.length?'?'+kept.join('&'):'')]);
 }
 if(/[?&]utm_/.test(url)){
  const [path,query]=url.split('?');const kept=query.split('&').filter(p=>!p.startsWith('utm_'));variants.push(['strip_tracker',path+(kept.length?'?'+kept.join('&'):'')]);
 }
 const m=/^https?:\/\/web\.archive\.org\/web\/\d{14}(?:[a-z]+_)?\/(https?:\/\/.+)$/i.exec(url);if(m)variants.push(['unwrapped_wayback',m[1]]);
 for(const [kind,value] of variants)if(value!==url)await emit(kind,list_row,url,value);
}
sink.end();await once(sink,'finish');
const server=await startArchiveServer({release:root+'/publish_v20/release',bodies:{}});
const journeys=[];
try{
 const reader=await openArchive(server.pointerUrl,{heapBytes:768*1024*1024});
 for(const [kind,row] of examples){
  const exact=await reader.lookup(row.original),variant=await reader.lookup(row.url);
  journeys.push({kind,...row,exact_rows:exact.map(x=>x.list_row),variant_rows:variant.map(x=>x.list_row)});
 }
}finally{await server.close();}
await writeFile(out+'/lookup-journeys.json',JSON.stringify({source_rows:count,journeys},null,2)+'\n');
console.log(JSON.stringify({source_rows:count,journeys},null,2));
