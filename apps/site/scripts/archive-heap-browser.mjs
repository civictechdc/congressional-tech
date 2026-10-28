import assert from 'node:assert/strict';
import {argumentsMap,measurementProfiles} from './archive-targets.mjs';
import {browserDependency,browserHeap,heapSampler,routeArchiveOrigin} from './archive-browser.mjs';
import {startArchiveServer} from './archive-server.mjs';
const args=argumentsMap(process.argv.slice(2));
const server=await startArchiveServer({release:args.release,siteDist:args.dist||'dist'}),{chromium}=browserDependency('playwright');
const browser=await chromium.launch({headless:true,executablePath:args['browser-executable']});
try{
  const context=await browser.newContext();await routeArchiveOrigin(context,server);const one=await context.newPage(),two=await context.newPage();
  await Promise.all([one,two].map(async page=>{await page.goto(server.pageUrl);await page.locator('[data-archive-ready="true"]').waitFor();}));
  const heap=await browserHeap(browser,one);assert.equal(heap.workerIsolates,1,'Only the measured page worker is attributed, even with another archive tab.');assert(heap.workerHeapBytes>0);
  const sampler=heapSampler(browser,one,{profile:measurementProfiles.phone});await sampler.ready;
  await one.waitForTimeout(250);
  const networkMs=await one.evaluate(async url=>{const start=performance.now();const response=await fetch(url+'?policy-proof=1',{cache:'no-store'});await response.arrayBuffer();return performance.now()-start;},server.pageUrl);
  const workerNetworkMs=await one.workers().find(worker=>worker.url().includes('archive-worker')).evaluate(async url=>{const start=performance.now();const response=await fetch(url+'?worker-policy-proof=1',{cache:'no-store'});await response.arrayBuffer();return performance.now()-start;},server.pageUrl);
  const sampled=await sampler.stop();assert.equal(sampled.workerIsolates,1);assert(sampled.heapSamples>2);
  assert(networkMs>=100,'Heap sampling must retain the applied 150ms network latency.');
  assert(workerNetworkMs>=100,'The archive worker must retain the applied 150ms network latency.');
  console.log(JSON.stringify({status:'passed',operation:'two archive tabs, one measured worker, persistent throttling through samples',heap,sampled,networkMs,workerNetworkMs}));
}finally{await browser.close();await server.close();}
