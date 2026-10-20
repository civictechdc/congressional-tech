import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {loadReviews, reviewedMode} from './reviews.mjs';

const manifest={info:{catalog_id:'pair',entries:3,rows:4,facets:{document_kind:['amendment'],document_family:['legislation']}},source_manifest:{files:{filenames:{sha256:'source'},documents:{sha256:'documents'}}}};
const selected={document_kind:['letter'],document_family:['correspondence'],document_kind_source:['assistant_complete_body_review']};
const baseline={document_kind:['amendment'],document_family:['legislation'],document_kind_source:['filename']};
const body='evidence/'+ 'a'.repeat(64)+'.pdf',page='evidence/'+'b'.repeat(64)+'.png';
function fixture(status='candidate_applied') {
 const data={version:1,catalog_id:'pair',baseline:{filenames:'source',documents:'documents'},review_sha256:'pin',files:{[body]:{},[page]:{}},rows:[{group:1,sources:[0,1],status,baseline,selected:status==='candidate_applied'?selected:baseline,review:{body_observation:{pages:1}},evidence:{body,pages:{1:page}}}]};
 return data;
}
function args(data) {
 const bytes=JSON.stringify(data);
 return [{url:'https://viewer.test/data/reviews.json',catalog_id:'pair',review_sha256:'pin',bytes:Buffer.byteLength(bytes),sha256:createHash('sha256').update(bytes).digest('hex')},manifest,async()=>new Response(bytes)];
}
test('verified review map binds the catalog pair, all aliases, pages and selected categories',async()=>{
 const result=await loadReviews(...args(fixture()));
 assert.equal(result.info.reviewed_search,true);
 assert.equal(result.info.reviewed_groups,1);
 assert.equal(result.sources.get(0),result.sources.get(1));
 assert.equal(result.groups.get(1).evidence.pages[1],'https://viewer.test/data/'+page);
 assert.deepEqual(result.info.review_facets.document_kind,['amendment','letter']);
 assert.equal(reviewedMode({classification:'reviewed',review:'pin'},result.info),true);
 assert.throws(()=>reviewedMode({classification:'reviewed',review:'old'},result.info),/different review snapshot/);
 assert.throws(()=>reviewedMode({classification:'wrong'},result.info),/Unknown classification/);
});
test('unsupported packets remain annotations and cannot introduce searchable categories',async()=>{
 const result=await loadReviews(...args(fixture('annotation_only_unsupported_forms')));
 assert.equal(result.info.reviewed_groups,0);
 assert.deepEqual(result.info.review_facets.document_kind,['amendment']);
 const changed=fixture('annotation_only_unsupported_forms');changed.rows[0].selected=selected;
 assert.match((await loadReviews(...args(changed))).info.review_error,/Unsupported forms/);
});
test('wrong bytes, catalog pair, duplicate positions and missing pages refuse reviews while baseline stays usable',async()=>{
 const variants=[data=>data.baseline.filenames='other',data=>data.rows.push(data.rows[0]),data=>data.rows[0].sources.push(0),data=>delete data.rows[0].evidence.pages[1]];
 for(const change of variants){const data=fixture();change(data);const result=await loadReviews(...args(data));assert.equal(result.groups.size,0);assert.equal(result.info.reviewed_search,false);assert.throws(()=>reviewedMode({classification:'reviewed'},result.info));assert.equal(reviewedMode({},result.info),false);}
 const parameters=args(fixture());parameters[0].sha256='wrong';assert.match((await loadReviews(...parameters)).info.review_error,/failed verification/);
 parameters[0].catalog_id='other';assert.deepEqual((await loadReviews(...parameters)).info,{});
});
// A newer catalog version: the review file still names 'pair', the viewer
// publication supplies a binding with this version's positions.
function bound(binding,data=fixture()) {
 const reviews=JSON.stringify(data),placed=JSON.stringify(binding);
 const next={...manifest,info:{...manifest.info,catalog_id:'next'},source_manifest:{files:{filenames:{sha256:'new'},documents:{sha256:'new'}}},
  files:{review_binding:{path:'gen/viewer-v2/review-binding.json',bytes:Buffer.byteLength(placed),sha256:createHash('sha256').update(placed).digest('hex')}}};
 const bodies={'https://viewer.test/data/reviews.json':reviews,'https://data.test/releases/r/gen/viewer-v2/review-binding.json':placed};
 return [{url:'https://viewer.test/data/reviews.json',catalog_id:'pair',review_sha256:'pin',bytes:Buffer.byteLength(reviews),sha256:createHash('sha256').update(reviews).digest('hex')},
  next,async url=>new Response(bodies[url]),'https://data.test/releases/r/manifest.json'];
}
test('a review binding places reviews on a newer catalog version by stable identity',async()=>{
 const result=await loadReviews(...bound({version:1,review_sha256:'pin',catalog_id:'next',rows:[{index:0,group:2,sources:[2,3]}],withdrawn:[]}));
 assert.equal(result.info.reviewed_search,true);
 assert.equal(result.info.reviewed_groups,1);
 assert.deepEqual([...result.groups.keys()],[2]);
 assert.equal(result.sources.get(2),result.sources.get(3));
 assert.equal(result.sources.has(0),false);
});
test('a withdrawn review keeps the original categories while other reviews stay available',async()=>{
 const result=await loadReviews(...bound({version:1,review_sha256:'pin',catalog_id:'next',rows:[],withdrawn:[{index:0,document_id:'d',reason:'body_changed'}]}));
 assert.equal(result.info.reviewed_search,true);
 assert.equal(result.groups.size,0);
 assert.equal(result.info.reviewed_groups,0);
});
test('a binding for another review publication, another catalog or changed bytes refuses reviews',async()=>{
 for(const binding of [{version:1,review_sha256:'old',catalog_id:'next',rows:[]},{version:1,review_sha256:'pin',catalog_id:'pair',rows:[]}]){
  const result=await loadReviews(...bound(binding));
  assert.equal(result.info.reviewed_search,false);assert.match(result.info.review_error,/different publication/);
 }
 const parameters=bound({version:1,review_sha256:'pin',catalog_id:'next',rows:[{index:0,group:2,sources:[2,3]}]});
 parameters[1].files.review_binding.sha256='wrong';
 assert.match((await loadReviews(...parameters)).info.review_error,/binding failed verification/);
 const invalid=bound({version:1,review_sha256:'pin',catalog_id:'next',rows:[{index:0,group:9,sources:[2]}]});
 assert.match((await loadReviews(...invalid)).info.review_error,/Invalid reviewed group/);
});

test('optional review startup settles hung and oversized responses under explicit limits',async()=>{
 const parameters=args(fixture());let signal;
 parameters[2]=(_url,options)=>{signal=options.signal;return new Promise(()=>{});};
 const hung=await loadReviews(...parameters,undefined,{deadlineMs:10});
 assert.equal(hung.info.reviewed_search,false);assert.match(hung.info.review_error,/deadline/);assert.equal(signal.aborted,true);
 const oversized=args(fixture());oversized[2]=async()=>new Response(new ReadableStream({start(controller){controller.enqueue(new Uint8Array(oversized[0].bytes+1));controller.close();}}));
 assert.match((await loadReviews(...oversized)).info.review_error,/expected response length/);
 const bounded=args(fixture());
 assert.match((await loadReviews(...bounded,undefined,{maxBytes:1})).info.review_error,/byte limit/);
 const headers=args(fixture());headers[2]=async()=>new Response('{}',{headers:{'Content-Length':'2'}});
 assert.match((await loadReviews(...headers)).info.review_error,/unexpected response length/);
});


test('decoded gzip and CORS responses verify actual bytes rather than encoded Content-Length',async()=>{
 for(const cors of [false,true]) {
  const parameters=args(fixture());const body=JSON.stringify(fixture());
  parameters[2]=async()=>{
   const response=new Response(body,{headers:{'Content-Length':'12',...(!cors?{'Content-Encoding':'gzip'}:{})}});
   if(!cors)return response;
   return {type:'cors',ok:response.ok,headers:response.headers,body:response.body};
  };
  assert.equal((await loadReviews(...parameters)).info.reviewed_search,true);
 }
});

test('shared startup reader retains optional failure behavior and cleans stalled streams', async () => {
 const parameters=args(fixture()); let cancels=0,signal;
 const response=new Response(new ReadableStream({cancel(){cancels++;return new Promise(()=>{});}}));
 parameters[2]=(_url,options)=>{signal=options.signal;return response;};
 const result=await loadReviews(...parameters,undefined,{deadlineMs:15});
 assert.equal(result.groups.size,0);assert.equal(result.info.reviewed_search,false);
 assert.match(result.info.review_error,/startup deadline/);assert.equal(signal.aborted,true);
 assert.equal(cancels,1);assert.equal(response.body.locked,false);
});

test('review binding and publication share one total deadline', async () => {
 const parameters=bound({version:1,review_sha256:'pin',catalog_id:'next',rows:[]});
 const fetcher=parameters[2];let requests=0;
 parameters[2]=async(...args)=>{requests++;if(requests===1)return fetcher(...args);return new Promise(()=>{});};
 const result=await loadReviews(...parameters,{deadlineMs:15});
 assert.equal(requests,2);assert.equal(result.info.reviewed_search,false);assert.match(result.info.review_error,/startup deadline/);
});
