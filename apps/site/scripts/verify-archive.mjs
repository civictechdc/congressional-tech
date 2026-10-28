/** The site's exact reader checks a pinned candidate before the pointer flip. */
import {readFile,writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {performance} from 'node:perf_hooks';
import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';
import {openArchive} from '../src/components/explorer/reader/archive.ts';
import {argumentsMap,checkTargets,readTargets} from './archive-targets.mjs';
const hex=value=>typeof value==='string'?value:Buffer.from(value).toString('hex');
function legacyPointer(value){
  return value&&typeof value==='object'&&!Array.isArray(value)
    &&(value.version===1||value.version==='1')&&(value.publisher_version===10||value.publisher_version==='10')
    &&typeof value.catalog_id==='string'&&value.catalog_id.length>0
    &&typeof value.manifest==='string'&&value.manifest.length>0
    &&!('release_id' in value)&&!('previous_release_id' in value);
}
function safeUrl(value,local){
  const url=new URL(value);
  if(url.username||url.password)throw new Error('Use a public URL without credentials.');
  if(url.protocol!=='https:'&&!(local&&url.protocol==='http:'&&['localhost','127.0.0.1','[::1]'].includes(url.hostname)))throw new Error('Archive verification requires HTTPS (or explicit loopback local mode).');
  return url;
}
export async function verifyArchive({pointerUrl,releaseId,rawBase,local=false,fetcher=fetch,targets,savedRow,deadlineMs=59000,heapBytes=256*1024*1024,checkSaved=true}){
  if(!checkSaved&&!local)throw new Error('The production canary must open a saved copy.');
  const pointer=safeUrl(pointerUrl,local);if(rawBase)safeUrl(rawBase,local);
  if(!Number.isFinite(deadlineMs)||deadlineMs<=0||deadlineMs>=60000)throw new Error('The canary deadline must be below one minute.');
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(new Error('Archive canary exceeded its deadline.')),deadlineMs);
  const started=performance.now(),operations={},headers=[];let peak=0;
  const sample=()=>{const memory=process.memoryUsage();peak=Math.max(peak,memory.heapUsed+memory.external);return memory;};
  const sampler=setInterval(sample,5);sample();
  const bounded=async(url,options={})=>{
    safeUrl(url,local);const response=await fetcher(url,{...options,signal:options.signal?AbortSignal.any([options.signal,controller.signal]):controller.signal});
    const path=new URL(url).pathname,cache=response.headers.get('Cache-Control')||'';
    if(path===pointer.pathname&&!cache.includes('no-store')){await response.body?.cancel();throw new Error('Archive pointer must be no-store.');}
    if(response.ok&&path.includes('/releases/')){
      if(!cache.includes('immutable')){await response.body?.cancel();throw new Error('Archive release files must be immutable.');}
      if(options.headers?.Range&&response.headers.get('Accept-Ranges')!=='bytes'){await response.body?.cancel();throw new Error('Archive host must advertise byte ranges.');}
      if(response.headers.get('Access-Control-Allow-Origin')!=='*'){await response.body?.cancel();throw new Error('Archive release CORS must allow any origin.');}
    }
    headers.push({status:response.status,range:Boolean(options.headers?.Range),cache});return response;
  };
  const timed=async(name,run)=>{const begin=performance.now(),value=await run();operations[name]=performance.now()-begin;if(name!=='stale')sample();return value;};
  try{
    let legacyPointerSha256;
    const livePointer=await bounded(pointer.href,{cache:'no-store'});if(livePointer.ok){
      const bytes=new Uint8Array(await livePointer.arrayBuffer()),value=JSON.parse(new TextDecoder().decode(bytes));
      if(!/^[a-f0-9]{64}$/.test(value?.release_id)){
        if(!/^[a-f0-9]{64}$/.test(releaseId)||!legacyPointer(value))throw new Error('Invalid live archive pointer.');
        legacyPointerSha256=createHash('sha256').update(bytes).digest('hex');
      }
    }else{await livePointer.body?.cancel();if(livePointer.status!==404||!releaseId)throw new Error('Could not read the archive pointer.');}
    const reader=await timed('startup',()=>openArchive(pointer.href,{fetcher:bounded,releaseId,rawBase,heapBytes,signal:controller.signal}));
    const initial=await timed('listScan',()=>reader.search({limit:30},controller.signal));
    if(!initial.total)throw new Error('Archive candidate has no visible documents.');
    const facets=await timed('facets',()=>reader.facets({},controller.signal));
    for(const entry of reader.manifest.facet_counts??[])if(facets[entry.facet]?.[String(entry.value)]!==Number(entry.count))throw new Error('Archive facet counts differ from its manifest.');
    const indexes=[0,reader.count-1,parseInt(reader.releaseId.slice(0,8),16)%reader.count];
    const entries=[];for(let i=0;i<indexes.length;i++)entries.push(await timed('detail'+i,()=>reader.entry(indexes[i],controller.signal)));
    const searchable=entries.map(entry=>entry.document).concat(initial.rows).find(row=>!row.hidden&&String(row.filename||row.title||'').trim());if(!searchable)throw new Error('Archive candidate has no searchable document label.');
    const term=String(searchable.filename||searchable.title).slice(0,24);if(!(await timed('search',()=>reader.search({text:term,limit:30},controller.signal))).total)throw new Error('Archive search did not find its own document label.');
    const linked=entries.find(entry=>entry.detail.link_key);if(!linked)throw new Error('Archive candidate did not exercise a public link.');
    if(await timed('link',()=>reader.resolve(hex(linked.detail.link_key)))===null)throw new Error('Archive link did not resolve to its document.');
    const sourceEntry=entries.find(entry=>entry.sources.length)??await reader.entry(initial.rows[0].list_row,controller.signal);
    if(!sourceEntry.sources.length)throw new Error('Archive candidate did not exercise a source range.');
    operations.sources=sourceEntry.sources.length;
    const recoveryCount=reader.manifest.files.find(file=>file.name==='recoveries.parquet').rows;
    const [probe]=await timed('recoveryRange',()=>reader.recoveryRange(0,Math.min(1,recoveryCount),controller.signal));
    let recovery;
    if(probe){recovery=await timed('recoveryAttachment',()=>reader.entry(probe.list_row,controller.signal));if(!recovery.recoveries.some(item=>item.ordinal===probe.ordinal))throw new Error('Archive recovery range is not attached to its document.');}
    operations.recoveryRows=recovery?.recoveries.length??0;
    await timed('urlState',()=>reader.urlState());
    if(checkSaved){
      let saved=savedRow!==undefined?await reader.entry(Number(savedRow),controller.signal):entries.find(entry=>entry.detail.saved_body);
      if(!saved?.detail.saved_body)throw new Error('A recorded saved file is required for the canary.');
      const opened=await timed('saved',()=>reader.openSaved(saved.detail));
      if(opened.compressedDownload)throw new Error('Select a saved file under the unpacking limit for the canary.');
      if(!opened.blob){const response=await bounded(opened.url);if(!response.ok)throw new Error('Saved copy not found.');const body=await response.arrayBuffer();if(!body.byteLength)throw new Error('Saved copy is empty.');}
      else if(!opened.blob.size)throw new Error('Saved copy is empty.');
    }
    // The stale probe gets its own heap: the phone holds one decoded list, not two.
    const memory=sample();clearInterval(sampler);
    const missingFile=reader.manifest.files.find(file=>file.name==='detail.parquet'||file.shard==='detail').name;
    const remaining=Math.floor(deadlineMs-(performance.now()-started));
    const stale=await timed('stale',()=>promisify(execFile)(process.execPath,[fileURLToPath(new URL('./archive-stale.mjs',import.meta.url)),JSON.stringify({pointerUrl:pointer.href,releaseId:reader.releaseId,heapBytes,missingFile,timeout:remaining,legacyPointerSha256})],{timeout:remaining,maxBuffer:1024*1024,signal:controller.signal}));
    const staleResult=JSON.parse(stale.stdout);if(staleResult.status!=='passed')throw new Error('Stale release probe failed.');
    const metrics={releaseId:reader.releaseId,startupMs:operations.startup,searchMs:operations.search,detailMs:Math.max(...[0,1,2].map(i=>operations['detail'+i])),heapBytes:peak,workerHeapBytes:0};
    if(targets)checkTargets(metrics,targets);
    const elapsedMs=performance.now()-started;if(elapsedMs>=deadlineMs)throw new Error('Archive canary exceeded its deadline.');
    return {version:1,status:checkSaved?'passed':'incomplete',targets:targets?'measured':'owner-gated',savedCopyChecked:checkSaved,elapsedMs,...metrics,operations,estimatedListBytes:reader.metrics.decodedBytes,estimatedListPeakBytes:reader.metrics.decodedPeak,memory,transport:{requests:headers.length,ranges:headers.filter(item=>item.range).length}};
  }catch(error){error.message+=` (elapsed ${Math.round(performance.now()-started)}ms; operations ${JSON.stringify(operations)})`;throw error;}finally{clearTimeout(timer);clearInterval(sampler);controller.abort();}
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  const args=argumentsMap(process.argv.slice(2));
  const result=await verifyArchive({pointerUrl:args.pointer,releaseId:args.release,rawBase:args.raw,local:args.local==='true',targets:await readTargets(args.targets),savedRow:args['saved-row'],heapBytes:args['heap-bytes']?Number(args['heap-bytes']):undefined,checkSaved:args['check-saved']!=='false'});
  if(args.output)await writeFile(args.output,JSON.stringify(result,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(result));
}
