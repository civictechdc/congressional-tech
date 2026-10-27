import assert from 'node:assert/strict';
import {argumentsMap} from './archive-targets.mjs';
import {browserDependency,browserHeap} from './archive-browser.mjs';
import {startArchiveServer} from './archive-server.mjs';
const args=argumentsMap(process.argv.slice(2));
const server=await startArchiveServer({release:args.release,siteDist:args.dist||'dist'}),{chromium}=browserDependency('playwright');
const browser=await chromium.launch({headless:true,executablePath:args['browser-executable']});
try{
  const context=await browser.newContext(),one=await context.newPage(),two=await context.newPage();
  await Promise.all([one,two].map(async page=>{await page.goto(server.pageUrl);await page.locator('[data-archive-ready="true"]').waitFor();}));
  const heap=await browserHeap(browser,one);assert.equal(heap.workerIsolates,1,'Only the measured page worker is attributed, even with another archive tab.');assert(heap.workerHeapBytes>0);
  console.log(JSON.stringify({status:'passed',operation:'two archive tabs, one measured worker',heap}));
}finally{await browser.close();await server.close();}
