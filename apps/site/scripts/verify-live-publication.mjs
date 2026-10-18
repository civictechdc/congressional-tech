#!/usr/bin/env node
/** Read-only verification with the maintained review loader and bounded HTTP. */
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {delimiter,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {loadPublication} from '../src/components/filename-publication.mjs';
import {loadRecoveries} from '../src/components/filename-recoveries.mjs';
import {loadReviews} from '../src/components/filename-reviews.mjs';

const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
export async function verifyLivePublication({viewerUrl,pagesUrl,descriptor,fetcher=fetch,runtimeProbe}) {
  let requests=0,total=0;
  const observations=[];
  const bounded=async(url,options={})=>{
    const target=new URL(url);
    if(!['http:','https:'].includes(target.protocol)||target.username||target.password)throw new Error('Unsupported public verification URL');
    if(++requests>32)throw new Error('Public verification request budget exceeded');
    const response=await fetcher(url,{...options,cache:'no-store',signal:AbortSignal.any([...(options.signal?[options.signal]:[]),AbortSignal.timeout(20_000)])});
    if(!response.ok){await response.body?.cancel().catch(()=>{});throw new Error(`Public verification HTTP ${response.status}`);}
    const declared=response.headers.get('Content-Length'),limit=16*1024*1024;
    if(declared!==null&&(!Number.isSafeInteger(Number(declared))||Number(declared)<0||Number(declared)>limit)){await response.body?.cancel().catch(()=>{});throw new Error('Public response exceeds declared byte budget');}
    const encoding=response.headers.get('Content-Encoding');
    const identityLength=response.type!=='cors'&&(!encoding||encoding.toLowerCase()==='identity');
    const reader=response.body.getReader(),chunks=[];let count=0;
    try {while(true){const {done,value}=await reader.read();if(done)break;count+=value.byteLength;total+=value.byteLength;if(count>limit||total>32*1024*1024)throw new Error('Public verification byte budget exceeded');chunks.push(value);}}
    catch(error){await reader.cancel().catch(()=>{});throw error;}finally{reader.releaseLock();}
    if(identityLength&&declared!==null&&Number(declared)!==count)throw new Error('Incomplete public verification response');
    const bytes=Buffer.concat(chunks);
    observations.push({url:String(url),bytes:count,sha256:hash(bytes),cors:response.headers.get('Access-Control-Allow-Origin')});
    // Fetch already decoded the body. Downstream maintained loaders receive
    // accurate normalized headers, including when CORS hid Content-Encoding.
    const headers=new Headers(response.headers);headers.set('Content-Length',String(count));headers.delete('Content-Encoding');
    return new Response(bytes,{status:response.status,headers});
  };
  const pointerResponse=await bounded(viewerUrl),pointer=await pointerResponse.json();
  // Pin the pointer just observed; do not permit a second mutable read to select
  // a different release inside this verification invocation.
  const publication=await loadPublication(viewerUrl,(url,opts)=>String(url)===String(viewerUrl)?Promise.resolve(Response.json(pointer)):bounded(url,opts));
  const {manifest,url:manifestUrl}=publication;
  if(![2,5].includes(manifest.version))throw new Error('Maintained loader does not support selected manifest version');
  const reviewDescriptor={...descriptor,url:new URL('data/document-reviews/reviews.json',new URL('../',pagesUrl)).href};
  await loadRecoveries(publication.recovery,manifest.info,bounded);
  const reviews=await loadReviews(reviewDescriptor,manifest,bounded,manifestUrl);
  if(reviews.info.review_error)throw new Error(reviews.info.review_error);
  let binding=null;
  if(manifest.files?.review_binding){
    const item=manifest.files.review_binding,response=await bounded(new URL(item.path,manifestUrl));
    const bytes=new Uint8Array(await response.arrayBuffer());
    if(bytes.byteLength!==item.bytes||hash(bytes)!==item.sha256)throw new Error('Review binding readback differs');
    binding=JSON.parse(new TextDecoder().decode(bytes));
  }
  const reviewResponse=await bounded(reviewDescriptor.url),reviewBytes=new Uint8Array(await reviewResponse.arrayBuffer());
  if(reviewBytes.byteLength!==descriptor.bytes||hash(reviewBytes)!==descriptor.sha256)throw new Error('Review publication readback differs');
  const reviewData=JSON.parse(new TextDecoder().decode(reviewBytes));
  if(!Array.isArray(reviewData.rows)||reviewData.rows.length>4096||reviewData.rows.some(row=>!/^([a-f0-9]{64})$/.test(row.document_id))||new Set(reviewData.rows.map(row=>row.document_id)).size!==reviewData.rows.length)throw new Error('Review document identity inventory is invalid or excessive');
  const pagesResponse=await bounded(pagesUrl),pages=await pagesResponse.text();
  const moduleUrls=[...pages.matchAll(/<script\b[^>]*\bsrc=["']([^"']+)["'][^>]*>/gi)].map(match=>new URL(match[1],pagesUrl).href);
  const assets=[];
  for(const url of moduleUrls.slice(0,8)){const response=await bounded(url);assets.push({url,sha256:hash(new Uint8Array(await response.arrayBuffer()))});}
  const runtime=runtimeProbe?await runtimeProbe({pagesUrl,pointer,reviewInfo:reviews.info}):{state:'pending',reason:'Deployed Pages worker was not executed'};
  const loaderHashes=Object.fromEntries(await Promise.all(['filename-publication.mjs','filename-reviews.mjs','filename-recoveries.mjs'].map(async name=>[name,hash(await readFile(new URL('../src/components/'+name,import.meta.url)))])));
  return {version:1,runtime:{node:process.version,platform:process.platform,loader_hashes:loaderHashes},status:'observed',observed_at:new Date().toISOString(),pointer,manifest,manifest_url:manifestUrl,
    pages:{url:pagesUrl,assets,runtime_execution:runtime},
    loader:{source:'maintained filename-reviews.mjs',info:reviews.info,
      rows:reviewData.rows.map((row,index)=>({document_id:row.document_id,status:row.status,baseline:row.baseline,selected:row.selected,
        placement:binding?.withdrawn?.find(item=>item.index===index)||{state:'bound'},index}))},
    withdrawn:binding?.withdrawn||[],requests,bytes:total,observations};
}

export async function browserRuntimeProbe({pagesUrl,pointer,reviewInfo},chromium,executablePath) {
  const browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{})});
  try {
    const page=await browser.newPage();
    await page.goto(pagesUrl,{waitUntil:'domcontentloaded',timeout:30_000});
    await page.waitForFunction(()=>typeof window.filenameViewerApi==='function',null,{timeout:30_000});
    const info=await page.evaluate(()=>Promise.race([window.filenameViewerApi('/api/info'),new Promise((_,reject)=>setTimeout(()=>reject(new Error('Live reader exceeded30second verification deadline')),30_000))]));
    const observed={catalog_id:info.catalog_id,review_sha256:info.review_sha256,recovery_sha256:info.recovery_sha256,
      reviewed_search:info.reviewed_search,reviewed_groups:info.reviewed_groups,review_error:info.review_error};
    return {state:info.catalog_id!==pointer.catalog_id?'pending':info.review_error||info.review_sha256!==reviewInfo.review_sha256||info.recovery_sha256!==pointer.recovery?.sha256||!info.reviewed_search?'failed':'passed',
      observed,expected:{catalog_id:pointer.catalog_id,review_sha256:reviewInfo.review_sha256,recovery_sha256:pointer.recovery?.sha256},browser:browser.version(),
      method:'fresh Chromium executing deployed Pages bootstrap and worker; no UI mutation'};
  } finally {await browser.close();}
}

function browserProbe(executablePath) {
  const require=createRequire(import.meta.url);
  const loaders=[require,...(process.env.PUBLICATION_BROWSER_MODULES||'').split(delimiter).filter(Boolean).map(path=>createRequire(join(path,'__verification__.cjs')))];
  for(const load of loaders){try{const {chromium}=load('playwright');return inputs=>browserRuntimeProbe(inputs,chromium,executablePath);}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}}
  return async()=>({state:'pending',reason:'Playwright unavailable; set PUBLICATION_BROWSER_MODULES to an existing pinned node_modules directory'});
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  const args={};for(let i=2;i<process.argv.length;i+=2){if(!process.argv[i].startsWith('--')||!process.argv[i+1])throw new Error('Use --name value arguments');args[process.argv[i].slice(2)]=process.argv[i+1];}
  for(const name of ['viewer-url','pages-url','review-descriptor','output'])if(!args[name])throw new Error('Missing --'+name);
  const descriptorRaw=await readFile(args['review-descriptor']);if(descriptorRaw.length>16*1024)throw new Error('Review descriptor exceeds16KiB');
  const result=await verifyLivePublication({viewerUrl:args['viewer-url'],pagesUrl:args['pages-url'],descriptor:JSON.parse(descriptorRaw),runtimeProbe:browserProbe(args['browser-executable'])});
  await writeFile(args.output,JSON.stringify(result,null,2)+'\n');
}
