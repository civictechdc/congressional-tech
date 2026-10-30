/** Real built-site browser contract. Fixture expectations live before implementation. */
import {readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';
import {argumentsMap,checkTargets,readTargets,measurementProfiles} from './archive-targets.mjs';
import {startArchiveServer} from './archive-server.mjs';
import {ARCHIVE_ORIGIN,browserDependency,heapSampler,routeArchiveOrigin} from './archive-browser.mjs';
import {openArchive} from '../src/components/explorer/reader/archive.ts';
const args=argumentsMap(process.argv.slice(2));if(!args['next-release'])throw new Error('Supply --next-release for the required browser stale-tab check.');const targets=await readTargets(args.targets);
const {chromium}=browserDependency('playwright');
const server=await startArchiveServer({release:resolve(args.release),nextRelease:args['next-release']?resolve(args['next-release']):undefined,siteDist:resolve(args.dist||'dist'),bodies:args.bodies?JSON.parse(await readFile(args.bodies)):{}});
const browser=await chromium.launch({headless:true,...(args['browser-executable']?{executablePath:args['browser-executable']}:{})});
const fixtureBodyReads=[];
async function fixtureContext(options={}){
  const context=await browser.newContext(options);
  // The built artifact keeps its real raw origin. This test adapter redirects
  // only body reads to the explicit fixture store, including deliberate 404s.
  await context.route(/^https?:\/\/[^/]+\/bodies\/sha256\//,async route=>{
    if(!['GET','HEAD'].includes(route.request().method()))return route.abort();
    const url=new URL(route.request().url());
    const response=await route.fetch({url:server.rawBase+url.pathname.slice(1)+url.search});
    fixtureBodyReads.push({path:url.pathname,status:response.status()});
    await route.fulfill({response});
  });
  await routeArchiveOrigin(context,server);
  return context;
}
const results=[];
const fixtureReader=args.hand==='true'?await openArchive(server.pointerUrl):null;
const fixtureEntries=fixtureReader?await Promise.all([1,2,5,6].map(index=>fixtureReader.entry(index))):[];
const hex=value=>Buffer.from(value).toString('hex');
try{
  for(const profileKind of ['desktop','phone']){
    const profile=measurementProfiles[profileKind],viewport=profile.viewport;
    server.state.missingFile=null;server.state.flipOnMissing=null;server.state.releaseId=server.manifest.release_id;
    const context=await fixtureContext({viewport,deviceScaleFactor:profile.deviceScaleFactor,isMobile:profile.isMobile}),page=await context.newPage();page.setDefaultTimeout(60000);
    const sampler=heapSampler(browser,page,{profile:targets?.status==='provisional-emulated'?profile:undefined});
    try{
      await sampler.ready;
      const errors=[];page.on('pageerror',error=>errors.push(error.message));let started=performance.now();
      await page.goto(server.pageUrl);await page.locator('[data-archive-ready="true"]').waitFor();await page.locator('.archive-document').first().waitFor();const observedReleaseId=await page.locator('[data-archive-ready="true"]').getAttribute('data-archive-release');if(observedReleaseId!==server.manifest.release_id)throw new Error('The measured page selected a different release than its fixture.');const startupMs=performance.now()-started;
      const initialTotal=await page.locator('[data-archive-total]').innerText();
      assert(!initialTotal.startsWith('0 '),'Release must contain visible documents');
      if(args.hand==='true')assert.equal(initialTotal,'6 documents');
      const initialHeap={heapBytes:0,workerHeapBytes:0,pageHeapBytes:0};
      started=performance.now();await page.getByRole('searchbox').fill(args.hand==='true'?'record':'hearing');await page.getByRole('button',{name:'Search',exact:true}).click();await page.waitForFunction(query=>document.querySelector('[data-archive-query]')?.getAttribute('data-archive-query')===query,args.hand==='true'?'record':'hearing');const searchMs=performance.now()-started;
      if(args.hand==='true')assert.equal(await page.locator('[data-archive-total]').innerText(),'2 documents');
      await page.getByRole('searchbox').fill('');await page.getByRole('button',{name:'Search',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[data-archive-query]')?.getAttribute('data-archive-query')==='');await page.locator('.archive-document').first().waitFor();
      started=performance.now();await page.locator('.archive-document').first().click();await page.locator('[data-archive-detail]').waitFor();const detailMs=performance.now()-started;
      const measuredHeap=await sampler.stop();
      let publicKey=new URL(page.url()).searchParams.get('key');if(!publicKey){assert((await page.locator('[data-archive-detail]').innerText()).includes('No original saved copy is recorded.'));publicKey=args['link-key'];if(!publicKey)throw new Error('Supply --link-key from the real release when its first row is metadata-only.');await page.goto(server.pageUrl+'?key='+publicKey);await page.locator('[data-archive-detail]').waitFor();}assert.match(publicKey,/^[a-f0-9]{16}$/);
      assert((await page.locator('[data-archive-detail]').innerText()).includes('Sources'));
      assert((await page.locator('[data-archive-detail]').innerText()).includes('Saved copies'));
      if(args.hand==='true'){
        await page.getByRole('link',{name:'Open saved PDF',exact:true}).click();await page.getByRole('alert').filter({hasText:'Saved copy not found'}).waitFor();
        await page.getByRole('button',{name:'Transportation infrastructure hearing',exact:true}).click();await page.locator('[data-archive-total]').waitFor();assert.equal(await page.locator('[data-archive-total]').innerText(),'1 document');
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
      // Exercise the built CSS with a recorded format longer than the narrow grid cell.
      const formatLayout=await page.locator('.archive-row-format').first().evaluate(cell=>{
        const original=cell.textContent;
        try{
          cell.textContent='HTML_REQUIRES_DOCUMENT_DISCOVERY';
          const bounds=cell.getBoundingClientRect(),range=document.createRange();
          range.selectNodeContents(cell);
          const fragments=[...range.getClientRects()];
          return {contained:fragments.every(rect=>rect.left>=bounds.left-1&&rect.right<=bounds.right+1),
            fits:cell.scrollWidth<=cell.clientWidth,label:cell.textContent};
        }finally{cell.textContent=original;}
      });
      assert(formatLayout.contained&&formatLayout.fits,'Long archive formats must stay inside their cell');
      assert.equal(formatLayout.label,'HTML_REQUIRES_DOCUMENT_DISCOVERY');
      server.state.delayDetailMs=0;
      // Missing public keys have a usable error and retry, including on a phone-sized page.
      await page.goto(server.pageUrl+'?key='+'ff'.repeat(8));await page.getByRole('alert').waitFor();assert((await page.getByRole('alert').innerText()).includes('not found'));
      const finalHeap=measuredHeap,memory=finalHeap.heapBytes>initialHeap.heapBytes?finalHeap:initialHeap;
      const sample={releaseId:observedReleaseId,pageUrl:page.url(),startupMs,searchMs,detailMs,...memory};if(targets)checkTargets(sample,targets,server.manifest.origin,profileKind);
      assert.deepEqual(errors,[]);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'The phone profile must not overflow horizontally');
      if(args.screenshot)await page.screenshot({path:args.screenshot.replace(/(\.[a-z]+)$/i,`-${viewport.width}$1`),fullPage:true});
      results.push({viewport,...sample,publicKey,status:'passed'});
    }finally{try{await sampler.stop();}finally{await context.close();}}
  }
  if(server.nextManifest){
    server.state.releaseId=server.manifest.release_id;server.state.missingFile=server.manifest.files.find(file=>file.name==='detail.parquet'||file.shard==='detail').name;server.state.flipOnMissing=server.nextManifest.release_id;
    const context=await fixtureContext(),page=await context.newPage();page.setDefaultTimeout(60000);
    try{const before=server.state.pointerReads;await page.goto(server.pageUrl+'?key='+results[0].publicKey);await page.locator(`[data-archive-release="${server.nextManifest.release_id}"]`).waitFor();assert.equal(new URL(page.url()).searchParams.get('key'),results[0].publicKey);assert(server.state.pointerReads>=before+3);results.push({operation:'404-reload',status:'passed'});}finally{await context.close();}
  }
  {
    const oldPointer=await readFile(new URL('./fixtures/old-viewer-pointer.json',import.meta.url),'utf8');
    const context=await fixtureContext({viewport:{width:390,height:844}}),page=await context.newPage();
    const errors=[],dataRequests=[],legacyRequests=[];page.setDefaultTimeout(60000);
    page.on('pageerror',error=>errors.push(error.message));
    // The new pointer shares the legacy key, so only the old layout's folders count as legacy reads.
    const pointerPath='/viewer-publications/manifest.json',isPointer=url=>url.origin===ARCHIVE_ORIGIN&&url.pathname===pointerPath;
    context.on('request',request=>{const url=new URL(request.url());if(url.origin===ARCHIVE_ORIGIN&&url.pathname.startsWith('/viewer-publications/'))dataRequests.push(url.pathname);});
    await context.route(url=>/\/viewer-publications\/releases\/[a-f0-9]{32}\/|\/catalog-generations\//.test(url.pathname),route=>{legacyRequests.push(route.request().url());return route.abort();});
    await context.route(isPointer,route=>route.fulfill({status:200,contentType:'application/json',headers:{'Cache-Control':'no-store','Access-Control-Allow-Origin':'*'},body:oldPointer}));
    try{
      await page.goto(server.pageUrl);
      await page.getByRole('alert').filter({hasText:'Invalid archive release identity.'}).first().waitFor();
      assert(await page.getByRole('button',{name:'Try loading the archive again'}).isVisible());
      assert.equal(await page.locator('.archive-document').count(),0);
      assert.equal(await page.locator('[data-archive-ready="true"]').count(),0);
      assert(dataRequests.length>0);assert(dataRequests.every(path=>path===pointerPath));
      assert.deepEqual(legacyRequests,[]);assert.deepEqual(errors,[]);
      results.push({operation:'old-pointer-refusal',status:'passed',pointerRequests:dataRequests.length});
    }finally{await context.close();}
  }
  if(args.hand==='true')assert(fixtureBodyReads.some(read=>read.status===404),'Hand saved-copy checks must exercise the local missing-body store');
  const receipt={version:1,status:'passed',releaseId:server.manifest.release_id,targets:targets?.status??'owner-gated',results,fixtureBodyReads};if(args.output)await writeFile(args.output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(receipt));
}finally{await browser.close();await server.close();}
