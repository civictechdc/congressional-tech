import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {verifyLivePublication} from './verify-live-publication.mjs';
const hash=value=>createHash('sha256').update(value).digest('hex');
function fixture(withdrawn=false){
 const catalog='b'.repeat(32),source={catalog_id:catalog,files:{filenames:{sha256:'f'},documents:{sha256:'d'}}};
 const baseline={document_kind:['bill'],document_family:['legislation'],document_kind_source:['filename']};
 const data={version:1,catalog_id:catalog,review_sha256:'review',baseline:{filenames:'f',documents:'d'},files:{},rows:[{document_id:'d'.repeat(64),group:0,sources:[0],status:'candidate_applied',baseline,selected:baseline,review:{body_observation:{pages:0}},evidence:{pages:{}}}]};
 const review=JSON.stringify(data),binding=JSON.stringify({version:1,catalog_id:catalog,review_sha256:'review',rows:withdrawn?[]:[{index:0,group:0,sources:[0]}],withdrawn:withdrawn?[{index:0,document_id:'d'.repeat(64),reason:'body_changed'}]:[]});
 const manifest={version:5,info:{catalog_id:catalog,rows:1,entries:1,facets:{document_kind:[],document_family:[]}},source_manifest:source,files:{review_binding:{path:'binding.json',bytes:Buffer.byteLength(binding),sha256:hash(binding)}}};
 const pointer={version:1,catalog_id:catalog,source_manifest:source,manifest:'releases/'+'a'.repeat(32)+'/manifest.json'};
 const responses=new Map([['https://data.test/manifest.json',JSON.stringify(pointer)],['https://data.test/'+pointer.manifest,JSON.stringify(manifest)],['https://data.test/releases/'+'a'.repeat(32)+'/binding.json',binding],['https://pages.test/project/data/document-reviews/reviews.json',review],['https://pages.test/project/filenames/','<script type="module" src="/project/bootstrap.js"></script>'],['https://pages.test/project/bootstrap.js','export const runtime=5;']]);
 return {viewerUrl:'https://data.test/manifest.json',pagesUrl:'https://pages.test/project/filenames/',descriptor:{catalog_id:catalog,review_sha256:'review',bytes:Buffer.byteLength(review),sha256:hash(review)},fetcher:async url=>{assert(responses.has(String(url)),String(url));return new Response(responses.get(String(url)),{headers:{'Access-Control-Allow-Origin':'*'}});}};
}

test('live verification runs maintained review loader and pins pages assets without overstating execution',async()=>{
 const result=await verifyLivePublication(fixture());
 assert.equal(result.loader.info.reviewed_search,true);assert.equal(result.loader.rows[0].document_id,'d'.repeat(64));
 assert.equal(result.pages.runtime_execution.state,'pending');assert.equal(result.pages.assets.length,1);
 assert(result.observations.every(value=>value.sha256.length===64));
});
test('withdrawn reviews remain visible as reasons and source categories are not reinstated',async()=>{
 const result=await verifyLivePublication(fixture(true));
 assert.equal(result.loader.info.reviewed_groups,0);assert.equal(result.withdrawn[0].reason,'body_changed');
 assert.equal(result.loader.rows[0].placement.reason,'body_changed');
});
test('runtime compatibility uses explicit deployed-worker evidence and oversized controls fail',async()=>{
 const options=fixture();options.runtimeProbe=async()=>({state:'passed',method:'fixture runtime probe'});
 assert.equal((await verifyLivePublication(options)).pages.runtime_execution.state,'passed');
 options.fetcher=async()=>new Response('{}',{headers:{'Content-Length':String(16*1024*1024+1)}});
 await assert.rejects(verifyLivePublication(options),/declared byte budget/);
});

test('deployed worker proof compares catalog, review and recovery identities and closes browser',async()=>{
 const {browserRuntimeProbe}=await import('./verify-live-publication.mjs');
 let closed=0;
 const inputs={pagesUrl:'https://pages.test/project/filenames/',pointer:{catalog_id:'catalog',recovery:{sha256:'recovery'}},reviewInfo:{review_sha256:'review'}};
 const info={catalog_id:'catalog',review_sha256:'review',recovery_sha256:'recovery',reviewed_search:true};
 const chromium={launch:async()=>({version:()=> 'fixture-browser',close:async()=>closed++,newPage:async()=>({goto:async()=>{},waitForFunction:async()=>{},evaluate:async()=>info})})};
 assert.equal((await browserRuntimeProbe(inputs,chromium)).state,'passed');
 info.recovery_sha256='wrong';assert.equal((await browserRuntimeProbe(inputs,chromium)).state,'failed');
 info.catalog_id='newer';assert.equal((await browserRuntimeProbe(inputs,chromium)).state,'pending');
 assert.equal(closed,3);
});

test('decoded gzip and CORS hidden encoding normalize lengths for the maintained loaders',async()=>{
 for(const cors of [false,true]){
  const options=fixture(),original=options.fetcher;
  options.fetcher=async(url,settings)=>{
   const response=await original(url,settings);
   const bytes=await response.arrayBuffer();
   const headers=new Headers(response.headers);headers.set('Content-Length','1');
   if(!cors)headers.set('Content-Encoding','gzip');
   const decoded=new Response(bytes,{headers});
   return cors?{ok:decoded.ok,status:decoded.status,type:'cors',headers:decoded.headers,body:decoded.body}:decoded;
  };
  assert.equal((await verifyLivePublication(options)).loader.info.reviewed_search,true);
 }
});

test('declared byte-budget refusal cancels the response before consuming its body',async()=>{
 const options=fixture();let cancelled=false;
 options.fetcher=async()=>new Response(new ReadableStream({cancel(){cancelled=true;}}),{headers:{'Content-Length':String(16*1024*1024+1)}});
 await assert.rejects(verifyLivePublication(options),/declared byte budget/);
 assert.equal(cancelled,true);
});
