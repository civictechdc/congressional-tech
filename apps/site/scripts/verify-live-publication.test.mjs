import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {verifyLivePublication,requireNativeWorker} from './verify-live-publication.mjs';
import {canonicalJson} from '../src/components/explorer/reader/filenames/startup.ts';
const hash=value=>createHash('sha256').update(value).digest('hex');
function fixture(withdrawn=false,version=5){
 const catalog='b'.repeat(32),source={catalog_id:catalog,files:{filenames:{sha256:'f'},documents:{sha256:'d'}}};
 const baseline={document_kind:['bill'],document_family:['legislation'],document_kind_source:['filename']};
 const data={version:1,catalog_id:catalog,review_sha256:'review',baseline:{filenames:'f',documents:'d'},files:{},rows:[{document_id:'d'.repeat(64),group:0,sources:[0],status:'candidate_applied',baseline,selected:baseline,review:{body_observation:{pages:0}},evidence:{pages:{}}}]};
 const review=JSON.stringify(data),binding=JSON.stringify({version:1,catalog_id:catalog,review_sha256:'review',rows:withdrawn?[]:[{index:0,group:0,sources:[0]}],withdrawn:withdrawn?[{index:0,document_id:'d'.repeat(64),reason:'body_changed'}]:[]});
 const manifest={version,info:{catalog_id:catalog,rows:1,entries:1,facets:{document_kind:[],document_family:[]}},source_manifest:source,files:{review_binding:{path:'binding.json',bytes:Buffer.byteLength(binding),sha256:hash(binding)}}};
 const pointer={version:1,catalog_id:catalog,source_manifest:source,manifest:'releases/'+'a'.repeat(32)+'/manifest.json'};
 const responses=new Map([['https://data.test/manifest.json',JSON.stringify(pointer)],['https://data.test/'+pointer.manifest,JSON.stringify(manifest)],['https://data.test/releases/'+'a'.repeat(32)+'/binding.json',binding],['https://pages.test/project/data/document-reviews/reviews.json',review],['https://pages.test/project/dashboard/','<script type="module" src="/project/bootstrap.js"></script>'],['https://pages.test/project/bootstrap.js','export const runtime=5;']]);
 return {viewerUrl:'https://data.test/manifest.json',pagesUrl:'https://pages.test/project/dashboard/',descriptor:{catalog_id:catalog,review_sha256:'review',bytes:Buffer.byteLength(review),sha256:hash(review)},fetcher:async url=>{assert(responses.has(String(url)),String(url));return new Response(responses.get(String(url)),{headers:{'Access-Control-Allow-Origin':'*'}});}};
}

test('live verification runs maintained review loader and pins pages assets without overstating execution',async()=>{
 const result=await verifyLivePublication(fixture());
 assert.equal(result.loader.info.reviewed_search,true);assert.equal(result.loader.rows[0].document_id,'d'.repeat(64));
 assert.equal(result.pages.runtime_execution.state,'pending');assert.equal(result.pages.assets.length,1);
 assert(result.observations.every(value=>value.sha256.length===64));
});
test('historical version 2 remains readable through its original verification route',async()=>{
 const result=await verifyLivePublication(fixture(false,2));
 assert.equal(result.manifest.version,2);assert.equal(result.loader.info.reviewed_search,true);
});
test('deployment gate requires native data, executed worker proof and the built-site selection',()=>{
 const result={manifest:{version:6},pointer:{catalog_id:'selected',recovery:{sha256:'saved'}},pages:{runtime_execution:{state:'passed'}}};
 requireNativeWorker(result,structuredClone(result));
 for(const version of [2,5]) assert.throws(()=>requireNativeWorker({...result,manifest:{version}}),/native v6/);
 for(const state of ['pending','failed']) assert.throws(()=>requireNativeWorker({...result,pages:{runtime_execution:{state}}}),/did not pass/);
 const earlier=structuredClone(result);earlier.pointer.recovery.sha256='old';
 assert.throws(()=>requireNativeWorker(result,earlier),/changed after built-site/);
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
 const inputs={pagesUrl:'https://pages.test/project/dashboard/',pointer:{catalog_id:'catalog',recovery:{sha256:'recovery'}},reviewInfo:{review_sha256:'review'}};
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

function nativeFixture(damage,accepted=[],acceptedHash=hash('[]')) {
 const options=fixture(),responses=new Map(),catalog=options.descriptor.catalog_id;
 const node=value=>{
  const bytes=canonicalJson(value),sha256=hash(bytes),path=`releases/${sha256.slice(0,32)}/${sha256.slice(32)}/viewer-v2/page.json`;
  responses.set('https://data.test/'+path,bytes);return {path,bytes:Buffer.byteLength(bytes),sha256};
 };
 const selected={counts:{source_rows:1,document_rows:1},dependency:{source_root:{sha256:'1'.repeat(64)}},components:{sha256:'2'.repeat(64)}};
 if(damage==='native-root')selected.dependency.source_root.sha256='0'.repeat(64);
 if(damage==='counts')selected.counts.source_rows=2;
 const sourceSelection=node(selected),source={version:2,selection:{key:'selected.json',bytes:sourceSelection.bytes,sha256:sourceSelection.sha256}};
 const identity={selected_ref:source.selection,selector_sha256:hash(canonicalJson(source))};
 const roots={sources:{native_sha256:'1'.repeat(64),stats:{rows:1}},components:{native_sha256:'2'.repeat(64),stats:{entries:1,source_rows:1}},browse:{rows:1}};
 const bindingValue={version:2,catalog_id:catalog,review_sha256:'review',rows:[{index:0,document_id:'d'.repeat(64),source_ids:['e'.repeat(64)]}],withdrawn:[]};
 if(damage==='review')bindingValue.review_sha256='other';
 if(damage==='withdrawn'){bindingValue.rows=[];bindingValue.withdrawn=[{index:0,document_id:'d'.repeat(64),reason:'body_changed',source_ids:['e'.repeat(64)]}];}
 const binding=node(bindingValue);
 const manifest={version:6,info:{catalog_id:catalog,rows:1,entries:1,facets:{document_kind:[],document_family:[]}},source_manifest:source,source_identity:identity,source_selection:sourceSelection,roots,requirements:{renderer:'native-viewer-v2'},files:{review_binding:binding}};
 manifest.proof=node({version:1,kind:'viewer-proof',publication:structuredClone(manifest)});
 const recovery={version:2,catalog_id:catalog,source_identity:identity,rows:1,entries:1,accepted,recoveries:[],sources:[],groups:[]};
 if(damage==='recovery')recovery.source_identity={...identity,selector_sha256:'0'.repeat(64)};
 const recoveryBytes=canonicalJson(recovery),recoveryHash=hash(recoveryBytes);
 const pointer={version:1,catalog_id:catalog,source_manifest:source,source_identity:identity,manifest:`releases/${'a'.repeat(32)}/manifest.json`,recovery:{path:`releases/${recoveryHash.slice(0,32)}/${recoveryHash.slice(32)}/viewer-v2/recovery-status.json`,sha256:recoveryHash,bytes:Buffer.byteLength(recoveryBytes)}};
 pointer.recovery_inputs={version:2,source_identity:identity,roots,raw_manifest_sha256:identity.selector_sha256,
  viewer_manifest_sha256:hash(JSON.stringify(manifest)),accepted:{present:true,sha256:acceptedHash}};
 if(damage==='accepted')pointer.recovery_inputs.accepted.sha256='0'.repeat(64);
 if(damage==='viewer-manifest')pointer.recovery_inputs.viewer_manifest_sha256='0'.repeat(64);
 if(damage==='pointer')pointer.source_identity={...identity,selector_sha256:'0'.repeat(64)};
 if(damage==='roots')manifest.roots.sources.native_sha256='0'.repeat(64);
 responses.set(options.viewerUrl,JSON.stringify(pointer));responses.set('https://data.test/'+pointer.manifest,JSON.stringify(manifest));
 responses.set('https://data.test/'+pointer.recovery.path,recoveryBytes);
 if(damage==='binding')responses.set('https://data.test/'+binding.path,'{}');
 const legacy=options.fetcher;
 options.fetcher=async(url,settings)=>responses.has(String(url))?new Response(responses.get(String(url)),{headers:{'Access-Control-Allow-Origin':'*'}}):legacy(url,settings);
 return options;
}

test('native live observation uses maintained stable root, recovery and review checks',async()=>{
 const result=await verifyLivePublication(nativeFixture());
 assert.equal(result.manifest.version,6);assert.equal(result.loader.info.reviewed_search,true);
 assert.equal(result.loader.rows[0].document_id,'d'.repeat(64));assert.equal(result.pages.runtime_execution.state,'pending');
});
for(const [damage,message] of [['pointer',/different native snapshot/],['roots',/different selected snapshot/],['native-root',/selected native root/],['counts',/counts disagree/],['recovery',/different selected snapshot/],['binding',/unexpected response length/],['review',/different publication/],['accepted',/recovery inputs differ/],['viewer-manifest',/recovery inputs differ/]])test(`native live observation refuses mixed or stale ${damage}`,async()=>{
 await assert.rejects(verifyLivePublication(nativeFixture(damage)),message);
});

test('native withdrawals retain the explicit reason and leave original categories intact',async()=>{
 const result=await verifyLivePublication(nativeFixture('withdrawn'));
 assert.equal(result.loader.info.reviewed_groups,0);
 assert.equal(result.withdrawn[0].reason,'body_changed');
 assert.equal(result.loader.rows[0].placement.reason,'body_changed');
 assert.deepEqual(result.loader.rows[0].baseline.document_kind,['bill']);
});

test('deployed native worker must match the exact selected generation even when catalog ID is unchanged',async()=>{
 const {browserRuntimeProbe}=await import('./verify-live-publication.mjs');
 const pointer={catalog_id:'catalog',source_identity:{selected_ref:{sha256:'a'.repeat(64)}},recovery:{sha256:'recovery'}};
 const info={catalog_id:'catalog',generation:'a'.repeat(32),review_sha256:'review',recovery_sha256:'recovery',reviewed_search:true};
 const chromium={launch:async()=>({version:()=> 'fixture-browser',close:async()=>{},newPage:async()=>({goto:async()=>{},waitForFunction:async()=>{},evaluate:async()=>info})})};
 const input={pagesUrl:'https://pages.test/',pointer,reviewInfo:{review_sha256:'review'}};
 assert.equal((await browserRuntimeProbe(input,chromium)).state,'passed');
 info.generation='b'.repeat(32);assert.equal((await browserRuntimeProbe(input,chromium)).state,'failed');
});

test('native accepted mapping digest matches Python ASCII JSON for Unicode URLs',async()=>{
 const accepted=[{original_url:'https://example.gov/café/🏛',recovered_url:'https://archive.test/café/🏛',body_key:'raw/files/a.gz',kind:'pdf',recovery_basis:'web_archive',recovery_status:'recovered'}];
 // Independent hashlib/json.dumps(sort_keys=True, separators=(',', ':')) receipt.
 const expected='3dd1a8b2bd6c2759ac4ce8614c8f1799787ea56a25b7ecea7c5b99256af13341';
 const result=await verifyLivePublication(nativeFixture(undefined,accepted,expected));
 assert.equal(result.recovery_identity.accepted_sha256,expected);
});
