/** Real built-site browser contract. Fixture expectations live before implementation. */
import {readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';
import {argumentsMap,checkTargets,readTargets} from './archive-targets.mjs';
import {startArchiveServer} from './archive-server.mjs';
import {browserDependency,browserHeap,heapSampler} from './archive-browser.mjs';
import {openArchive} from '../src/components/explorer/reader/archive.ts';
const args=argumentsMap(process.argv.slice(2)),targets=await readTargets(args.targets);
const {chromium}=browserDependency('playwright');
const server=await startArchiveServer({release:resolve(args.release),nextRelease:args['next-release']?resolve(args['next-release']):undefined,siteDist:resolve(args.dist||'dist'),bodies:args.bodies?JSON.parse(await readFile(args.bodies)):{}});
const browser=await chromium.launch({headless:true,...(args['browser-executable']?{executablePath:args['browser-executable']}:{})});
const results=[];
const fixtureReader=args.hand==='true'?await openArchive(server.pointerUrl):null;
const fixtureEntries=fixtureReader?await Promise.all([1,2,5,6].map(index=>fixtureReader.entry(index))):[];
const hex=value=>Buffer.from(value).toString('hex');
try{
  for(const viewport of [{width:1440,height:1000},{width:390,height:844}]){
    server.state.missingFile=null;server.state.flipOnMissing=null;server.state.releaseId=server.manifest.release_id;
    const context=await browser.newContext({viewport}),page=await context.newPage();page.setDefaultTimeout(60000);
    try{
      const sampler=heapSampler(browser,page);const errors=[];page.on('pageerror',error=>errors.push(error.message));let started=performance.now();
      await page.goto(server.pageUrl);await page.locator('[data-archive-ready="true"]').waitFor();await page.locator('.archive-document').first().waitFor();const startupMs=performance.now()-started;
      const initialTotal=await page.locator('[data-archive-total]').innerText();
      assert(!initialTotal.startsWith('0 '),'Release must contain visible documents');
      if(args.hand==='true')assert.equal(initialTotal,'6 documents');
      const initialHeap={heapBytes:0,workerHeapBytes:0,pageHeapBytes:0};
      started=performance.now();await page.getByRole('searchbox').fill(args.hand==='true'?'record':'hearing');await page.getByRole('button',{name:'Search',exact:true}).click();await page.locator('[data-archive-total]').waitFor();const searchMs=performance.now()-started;
      if(args.hand==='true')assert.equal(await page.locator('[data-archive-total]').innerText(),'2 documents');
      await page.getByRole('searchbox').fill('');await page.getByRole('button',{name:'Search',exact:true}).click();await page.locator('.archive-document').first().waitFor();
      started=performance.now();await page.locator('.archive-document').first().click();await page.locator('[data-archive-detail]').waitFor();const detailMs=performance.now()-started;
      const measuredHeap=await sampler.stop();
      let publicKey=new URL(page.url()).searchParams.get('key');if(!publicKey){assert((await page.locator('[data-archive-detail]').innerText()).includes('No original saved copy is recorded.'));publicKey=args['link-key'];if(!publicKey)throw new Error('Supply --link-key from the real release when its first row is metadata-only.');await page.goto(server.pageUrl+'?key='+publicKey);await page.locator('[data-archive-detail]').waitFor();}assert.match(publicKey,/^[a-f0-9]{16}$/);
      assert((await page.locator('[data-archive-detail]').innerText()).includes('Sources'));
      assert((await page.locator('[data-archive-detail]').innerText()).includes('Saved copies'));
      if(args.hand==='true'){
        await page.getByRole('link',{name:'Open saved PDF',exact:true}).click();await page.getByRole('alert').filter({hasText:'Saved copy not found'}).waitFor();
        await page.getByRole('button',{name:'Transportation infrastructure hearing',exact:true}).click();await page.locator('[data-archive-total]').waitFor();assert.equal(await page.locator('[data-archive-total]').innerText(),'1 documents');
        for(const [key,label] of [[hex(fixtureEntries[0].detail.link_key),'Requested content in an official hearing'],[hex(fixtureEntries[2].detail.link_key),'Recovered document'],[hex(fixtureEntries[3].detail.link_key),'Official substitute']]){
          await page.goto(server.pageUrl+'?key='+key);await page.locator('[data-archive-detail]').waitFor();assert((await page.locator('[data-archive-detail]').innerText()).includes(label));
        }
        await page.goto(server.pageUrl+'?key='+hex(fixtureEntries[1].detail.link_key));await page.getByRole('heading',{name:'Removed by review'}).waitFor();assert((await page.locator('[data-archive-detail]').innerText()).includes('Superseded by the complete record'));
        await page.goto(server.pageUrl+'?q='+encodeURIComponent('http://www.fixture.test:80/record.pdf/#old'));await page.locator('[data-archive-total]').waitFor();assert.equal(await page.locator('[data-archive-total]').innerText(),'2 documents');
        await page.locator('.archive-document').first().click();await page.getByRole('heading',{name:'Other versions'}).waitFor();
      }
      server.state.delayDetailMs=150;
      await page.goto(server.pageUrl);await page.locator('.archive-document').first().waitFor();
      await page.locator('.archive-document').first().click();await page.goBack();
      await page.locator('[data-archive-total]').waitFor();await page.waitForTimeout(250);
      assert.equal(await page.locator('[data-archive-detail]').count(),0,'Back cancels an internal row selection');
      server.state.delayDetailMs=0;
      // Missing public keys have a usable error and retry, including on a phone-sized page.
      await page.goto(server.pageUrl+'?key='+'ff'.repeat(8));await page.getByRole('alert').waitFor();assert((await page.getByRole('alert').innerText()).includes('not found'));
      const finalHeap=measuredHeap,memory=finalHeap.heapBytes>initialHeap.heapBytes?finalHeap:initialHeap;
      const sample={releaseId:server.manifest.release_id,startupMs,searchMs,detailMs,...memory};if(targets)checkTargets(sample,targets);
      assert.deepEqual(errors,[]);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'The phone profile must not overflow horizontally');
      if(args.screenshot)await page.screenshot({path:args.screenshot.replace(/(\.[a-z]+)$/i,`-${viewport.width}$1`),fullPage:true});
      results.push({viewport,...sample,publicKey,status:'passed'});
    }finally{await context.close();}
  }
  if(server.nextManifest){
    server.state.releaseId=server.manifest.release_id;server.state.missingFile=server.manifest.files.find(file=>file.name==='detail.parquet'||file.shard==='detail').name;server.state.flipOnMissing=server.nextManifest.release_id;
    const context=await browser.newContext(),page=await context.newPage();page.setDefaultTimeout(60000);
    try{const before=server.state.pointerReads;await page.goto(server.pageUrl+'?key='+results[0].publicKey);await page.locator(`[data-archive-release="${server.nextManifest.release_id}"]`).waitFor();assert.equal(new URL(page.url()).searchParams.get('key'),results[0].publicKey);assert(server.state.pointerReads>=before+3);results.push({operation:'404-reload',status:'passed'});}finally{await context.close();}
  }
  const receipt={version:1,status:'passed',releaseId:server.manifest.release_id,targets:targets?'measured':'owner-gated',results};if(args.output)await writeFile(args.output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(receipt));
}finally{await browser.close();await server.close();}
