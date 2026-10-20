import {test} from 'node:test';
import assert from 'node:assert/strict';
import {byteCache,retainedBytes,sharedLoad} from './cache.ts';
import {rangeFile} from './catalog.ts';

test('wide decoded values never enter a cache beyond its aggregate byte budget',()=>{
 const cache=byteCache(1024);
 assert.equal(cache.set('wide',['x'.repeat(1024)]),false);
 for(let i=0;i<100;i++){cache.set(i,['x'.repeat(100)]);assert(cache.stats.bytes<=1024);}
 assert(cache.stats.evictions>0);assert(cache.stats.peak<=1024);
 assert(retainedBytes({wide:'x'.repeat(1024)})>=2048);
});
test('shared range loads survive one cancellation and obey one cross-file compressed budget',async()=>{
 const cache=byteCache(300,12);let calls=0,release;
 const blocked=new Promise(resolve=>release=resolve);
 const fetcher=async(url,options)=>{calls++;await blocked;const [a,b]=options.headers.Range.slice(6).split('-').map(Number);return new Response(new Uint8Array(b-a+1),{status:206,headers:{'Content-Range':`bytes ${a}-${b}/12`}});};
 const file=rangeFile('https://data.test/a',12,fetcher,cache),controller=new AbortController();
 const first=file.slice(0,8,controller.signal),rejected=assert.rejects(first,{name:'AbortError'});
 const second=file.slice(0,8);controller.abort();release();await rejected;assert.equal((await second).byteLength,8);assert.equal(calls,1);
 const other=rangeFile('https://data.test/b',12,fetcher,cache);await other.slice(0,8);assert(cache.stats.bytes<=300);assert.equal(cache.stats.evictions,1);
 await assert.rejects(file.slice(-1,5),/Invalid/);await assert.rejects(file.slice(0,13),/Invalid/);
});
test('failed shared work evicts and retries without retaining rejected promises',async()=>{
 const pending=new Map();let calls=0;
 const load=()=>{calls++;if(calls===1)throw new Error('failed');return 'ok';};
 await assert.rejects(sharedLoad(pending,'same',load),/failed/);assert.equal(pending.size,0);
 assert.equal(await sharedLoad(pending,'same',load),'ok');assert.equal(calls,2);assert.equal(pending.size,0);
});
