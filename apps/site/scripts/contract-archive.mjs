/** Real built-site browser contract. Fixture expectations live before implementation. */
import {readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {argumentsMap,checkTargets,readTargets,measurementProfiles} from './archive-targets.mjs';
import {startArchiveServer} from './archive-server.mjs';
import {ARCHIVE_ORIGIN,browserDependency,heapSampler,routeArchiveOrigin,routeWhileOpen} from './archive-browser.mjs';
import {openArchive} from '../src/components/explorer/reader/archive.ts';
const args=argumentsMap(process.argv.slice(2));if(!args['next-release'])throw new Error('Supply --next-release for the required browser stale-tab check.');const targets=await readTargets(args.targets);const targetsStatus=args.targets?JSON.parse(await readFile(args.targets)).status:undefined;
const {chromium}=browserDependency('playwright');
const server=await startArchiveServer({release:resolve(args.release),nextRelease:args['next-release']?resolve(args['next-release']):undefined,siteDist:resolve(args.dist||'dist'),bodies:args.bodies?JSON.parse(await readFile(args.bodies)):{}});
const browser=await chromium.launch({headless:true,...(args['browser-executable']?{executablePath:args['browser-executable']}:{})});
const fixtureBodyReads=[];
async function fixtureContext(options={}){
  const context=await browser.newContext(options);
  // The built artifact keeps its real raw origin. This test adapter redirects
  // only body reads to the explicit fixture store, including deliberate 404s.
  await routeWhileOpen(context,/^https?:\/\/[^/]+\/bodies\/sha256\//,async route=>{
    if(!['GET','HEAD'].includes(route.request().method()))return route.abort();
    const url=new URL(route.request().url());
    const response=await route.fetch({url:server.rawBase+url.pathname.slice(1)+url.search});
    fixtureBodyReads.push({path:url.pathname,status:response.status()});
    await route.fulfill({response});
  });
  await routeArchiveOrigin(context,server);
  return context;
}
async function checkSiteCutover(eventId){
  const context=await fixtureContext(),page=await context.newPage();
  page.setDefaultTimeout(15000);
  const base=server.origin+'/congressional-tech/';
  const oldId='d6c7189d-ab25-4785-bc4e-fc7284b70fd6';
  const legacyRequests=[];
  context.on('request',request=>{
    const path=new URL(request.url()).pathname;
    if(path.includes('/data/explorer/'))legacyRequests.push(path);
  });
  try{
    await page.goto(base);
    const explorer=page.getByRole('navigation',{name:'Main',exact:true}).getByRole('link',{name:'Congress Explorer',exact:true});
    assert.equal(await explorer.getAttribute('href'),'/congressional-tech/archive/');
    await explorer.click();
    const release=page.locator(`[data-archive-release="${server.manifest.release_id}"]`);
    await release.waitFor();
    assert.equal(await page.locator('a[href*="/dashboard/"]').count(),0);
    for(const bookmark of ['?meeting='+eventId,'?hearing='+eventId,'?event_id='+eventId]){
      await page.goto(base+'dashboard/'+bookmark);
      await page.waitForURL(server.pageUrl+'?tab=hearings&hearing='+eventId);
      await release.waitFor();
      await page.getByRole('region',{name:'Hearing details'}).getByRole('heading',{name:'Transportation infrastructure hearing'}).waitFor();
    }
    await page.goto(base+'dashboard/?view=materials&q=record&congress=118');
    await page.waitForURL(server.pageUrl+'?q=record&congress=118');
    await release.waitFor();
    await page.goto(base+'dashboard/?view=coverage');
    await page.getByText('The former Coverage and Gaps views have closed.',{exact:false}).waitFor();
    assert.equal(await page.getByRole('link',{name:'Open Congress Explorer',exact:true}).getAttribute('href'),server.pageUrl+'?tab=hearings');
    for(const bookmark of ['?kind=meeting&id='+oldId,'?kind=witness&id='+oldId,'?id='+oldId,'?kind=meeting&id=unknown']){
      await page.goto(base+'dashboard/'+bookmark);
      await page.getByText('This old Committee Explorer record link has been removed.',{exact:false}).waitFor();
      assert.equal(new URL(page.url()).pathname,'/congressional-tech/dashboard/');
      assert.equal(await page.getByRole('link',{name:'Open Congress Explorer',exact:true}).getAttribute('href'),server.pageUrl+'?tab=hearings');
    }
    await page.getByRole('link',{name:'Open Congress Explorer',exact:true}).click();
    await page.waitForURL(server.pageUrl+'?tab=hearings');
    await release.waitFor();
    await page.goto(base+'youtube-coverage/');
    await page.getByRole('heading',{name:'Committee YouTube coverage',exact:true}).waitFor();
    await page.locator('astro-island').scrollIntoViewIfNeeded();
    await page.getByRole('form',{name:'Filter the report'}).waitFor();
    await page.getByRole('heading',{name:'Committee leaderboard',exact:true}).waitFor();
    assert.deepEqual(legacyRequests,[],'Retired bookmarks must never read the old publication or event map.');
    return {operation:'shared-explorer-entry',status:'passed',eventId,legacyMapRequests:legacyRequests.length,youtubeCoverage:'passed'};
  }finally{await context.close();}
}
// Use the same browser and release server for the typed candidate and its older schema.
async function checkRecordingAssociations(eventId){
  for(const [releaseId,scoped] of [[server.manifest.release_id,true],[server.nextManifest.release_id,false]]){
    server.state.releaseId=releaseId;
    const context=await fixtureContext(),page=await context.newPage();page.setDefaultTimeout(15000);
    try{
      await page.goto(server.origin+'/congressional-tech/dashboard/?hearing='+encodeURIComponent(eventId));
      await page.waitForURL(server.pageUrl+'?tab=hearings&hearing='+encodeURIComponent(eventId));
      await page.locator(`[data-archive-release="${releaseId}"]`).waitFor();
      const hearing=page.getByRole('region',{name:'Hearing details'});
      await hearing.getByRole('heading',{name:'Video Recordings'}).waitFor();
      const evidence=hearing.getByRole('heading',{name:'Recording evidence'});
      await evidence.waitFor();
      const link=(name)=>hearing.getByRole('link',{name,exact:true}).filter({hasText:name});
      if(scoped){
        const contextLink=link('Related package recording evidence');
        assert.equal(await contextLink.getAttribute('href'),'https://example.test/watch');
        assert.equal(await hearing.locator('a[href="https://example.test/watch"]').count(),2,
          'Distinct event and package observations sharing a locator must remain visible.');
        await hearing.getByRole('link',{name:'CHRG-118hhrg55555',exact:true}).waitFor();
      }else{
        await hearing.getByText('Recording associations · This release does not include this information.').waitFor();
        await link('Original recording observation').first().waitFor();
        const packageEvidence=hearing.locator('details').filter({hasText:'Original package observations for CHRG-118hhrg55555'});
        await packageEvidence.locator('summary').click();
        assert.equal(await packageEvidence.getByRole('link',{name:'Original recording observation',exact:true}).getAttribute('href'),
          'https://example.test/watch');
        assert.equal(await link('Related package recording evidence').count(),0);
      }
    }finally{await context.close();}
  }
  return {operation:'scoped-recording-associations',status:'passed'};
}

async function checkPublisherPage(datedKey, markedKey) {
  const context = await fixtureContext(), page = await context.newPage();
  page.setDefaultTimeout(15000);
  const open = async key => {
    await page.goto(server.pageUrl + '?key=' + key);
    await page.locator('[data-archive-detail]').waitFor();
    return page.locator('[data-archive-ready]').getAttribute('data-archive-release');
  };
  const bytesRead = () => server.state.requests
    .filter(r => r.path.includes('/detail.') && r.status === 206)
    .reduce((sum, r) => sum + r.end - r.start + 1, 0);
  try {
    const releaseId = await open(datedKey);
    assert.equal(releaseId, server.manifest.release_id);
    const panel = page.locator('[data-archive-detail]');
    assert.match(await panel.innerText(), /Page published 2017-09-13/);
    assert.match(await panel.innerText(), /Page updated 2025-04-01/);
    const declaration = panel.getByText(/2025-04-01T15:01:50[+]00:00/);
    assert.equal(await declaration.count(), 0, 'Publisher evidence stays out of the closed disclosure');
    await page.getByText('Publisher declarations and evidence', {exact: true}).click();
    await page.getByRole('link', {name: 'Open original saved page'}).waitFor();
    assert.match(await panel.innerText(), /HTML reading version [a-f0-9]{64}/);
    await declaration.first().waitFor();

    assert.equal(await open(markedKey), releaseId);
    await page.getByText('Publisher declarations and evidence', {exact: true}).click();
    const citation = (await panel.getByText(/^Selected text SHA-256/).innerText()).split(' ').at(-1);
    assert.match(citation, /^[a-f0-9]{64}$/);
    const before = bytesRead();
    await page.getByRole('button', {name: 'Read selected text'}).click();
    const markedPrefix = args['html-marked-prefix'] || 'Chairman Miller, Ranking Member Michaud and Committee Members:';
    const text = panel.getByText(new RegExp('^' + markedPrefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    await text.waitFor();
    assert.equal(createHash('sha256').update(await text.textContent()).digest('hex'), citation);
    const selectedTextRangeBytes = bytesRead() - before;

    const older = JSON.parse(await readFile(resolve(args['next-release'], 'manifest.json')));
    server.state.releaseId = older.release_id;
    assert.equal(await open(datedKey), older.release_id);
    assert.equal(await page.getByRole('heading', {name: 'Publisher page'}).count(), 0);
    return {operation: 'publisher-page', releaseId, olderReleaseId: older.release_id, selectedTextRangeBytes, status: 'passed'};
  } finally {
    await context.close();
  }
}

const results=[];
const fixtureReader=args.hand==='true'?await openArchive(server.pointerUrl):null;
const fixtureEntries=fixtureReader?await Promise.all([1,2,5,6].map(index=>fixtureReader.entry(index))):[];
const hex=value=>Buffer.from(value).toString('hex');
try{
  if(args['html-dated-key'] && args['html-marked-key']){
    results.push(await checkPublisherPage(args['html-dated-key'],args['html-marked-key']));
  }else if(args['recording-event']){
    results.push(await checkRecordingAssociations(args['recording-event']));
  }else{
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
      // Recovery-only documents present their provenance in the recovery section.
      await page.locator('[data-archive-detail]').getByRole('heading',{name:/^(Sources|Recovered and related files)$/}).first().waitFor();
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
  if(args.hand==='true'){
    results.push(await checkSiteCutover(String((await fixtureReader.meetings())[0].event_id)));
    const context=await fixtureContext(),page=await context.newPage();page.setDefaultTimeout(15000);
    server.state.missingFile='committees.parquet';
    try{
      await page.goto(server.pageUrl+'?key='+results[0].publicKey);
      const detail=page.locator('[data-archive-detail]');
      await detail.getByText('Committee details · This information could not be loaded.').waitFor();
      await detail.getByRole('link',{name:'Open saved PDF'}).waitFor();
      await page.goto(server.pageUrl+'?tab=hearings&hearing='+String((await fixtureReader.meetings())[0].event_id));
      const hearing=page.getByRole('region',{name:'Hearing details'});
      await hearing.getByRole('heading',{name:'Transportation infrastructure hearing'}).waitFor();
      await hearing.getByText('Committee details · This information could not be loaded.').waitFor();
      await hearing.getByText('Witnesses · This release does not include this information.').waitFor();
      results.push({operation:'optional-relation-failure',status:'passed'});

      server.state.missingFile='meetings.parquet';
      await page.goto(server.pageUrl+'?key='+results[0].publicKey);
      await detail.getByText('Hearing details · This information could not be loaded.').waitFor();
      await detail.getByRole('link',{name:'Open saved PDF'}).waitFor();
      await page.goto(server.pageUrl+'?tab=hearings&hearing='+String((await fixtureReader.meetings())[0].event_id));
      await page.getByRole('alert').filter({hasText:'Archive file not found'}).waitFor();
      await page.getByRole('button',{name:'Try loading this hearing again'}).waitFor();
      assert.equal(await page.getByText('No matching hearing found.').count(),0);
      results.push({operation:'core-hearing-failure',status:'passed'});
    }finally{server.state.missingFile=null;await context.close();}
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
  }
  if(server.manifest.files.some(file=>file.name==='search_index.sqlite')){
    const indexRequests=server.state.requests.filter(request=>request.path.endsWith('/search_index.sqlite'));
    assert.deepEqual(indexRequests,[],'The browser must leave the server-only text index on the archive.');
    results.push({operation:'server-only-text-index',status:'passed',releaseId:server.manifest.release_id,indexRequests:indexRequests.length});
  }
  const receipt={version:1,status:'passed',releaseId:server.manifest.release_id,targets:targets?.status??targetsStatus??'owner-gated',results,fixtureBodyReads};if(args.output)await writeFile(args.output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(receipt));
}finally{await browser.close();await server.close();}
