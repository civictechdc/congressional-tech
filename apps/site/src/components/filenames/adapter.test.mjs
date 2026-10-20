import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createViewerAdapter} from '../../../../../docs/youtube-coverage/research/filename-adapter.mjs';
const entry={record:{source_id:'id'},catalog_id:'pin',saved_file_available:true,reading:{version:'local'}};
test('published adapter requires its worker and published evidence URLs',async()=>{
 let calls=0;
 const adapter=createViewerAdapter({mode:'published',workerApi:()=>undefined,fetcher:()=>{calls++;throw new Error('HTTP fallback');}});
 await assert.rejects(adapter.request('/api/info'),/reader is unavailable/);assert.equal(calls,0);
 assert.throws(()=>adapter.reviewEvidence(entry,{},'body'),/verified evidence link/);
 assert.equal(adapter.savedUrl(entry),null);assert.equal(adapter.reading(entry),null);
 const worker=createViewerAdapter({mode:'published',workerApi:()=>async url=>({route:url})});
 assert.deepEqual(await worker.request('/api/info'),{route:'/api/info'});
 assert.equal(worker.reviewEvidence(entry,{evidence:{body:'https://assets.test/file.pdf'}},'body'),'https://assets.test/file.pdf');
});
test('local adapter preserves API errors, saved evidence and naming comparisons',async()=>{
 const controller=new AbortController();
 const adapter=createViewerAdapter({mode:'local',fetcher:async(url,{signal})=>{assert.equal(signal,controller.signal);return Response.json({route:url});}});
 assert.deepEqual(await adapter.request('/api/info',controller.signal),{route:'/api/info'});
 assert.equal(adapter.savedUrl(entry),'/saved/id?catalog=pin');assert.equal(adapter.reading(entry),entry.reading);
 assert.equal(adapter.reviewEvidence(entry,{},'page',2),'/review-evidence/id?catalog=pin&kind=page&page=2');
 const failed=createViewerAdapter({mode:'local',fetcher:async()=>Response.json({error:'snapshot mismatch'},{status:409})});
 await assert.rejects(failed.request('/api/info'),/snapshot mismatch/);
});
